"""Post-training Gaussian pruning using COLMAP multi-view geometry."""

from __future__ import annotations

import argparse
import json
import random
from argparse import Namespace
from pathlib import Path

import torch
from fused_ssim import fused_ssim as fast_ssim

from arguments import ModelParams, OptimizationParams, PipelineParams, get_combined_args
from gaussian_renderer import render_fastgs
from scene import GaussianModel, Scene
from scripts.colmap_model_io import read_cameras_binary, read_images_binary, read_points3d_binary
from utils.general_utils import safe_state
from utils.geometric_pruning import (
    build_geometric_prune_decision,
    build_observation_indices,
    camera_intrinsics,
    collect_geometric_support,
    compute_render_importance,
    knn_isolation_mask,
    project_points,
    qvec2rotmat,
    screen_overlap_loser_mask,
    select_evaluation_cameras,
)
from utils.loss_utils import l1_loss


def build_output_paths(model_path: Path, iteration: int, output_name: str):
    root = model_path / output_name
    return {
        "root": root,
        "ply": root / "point_cloud" / ("iteration_%d" % iteration) / "point_cloud.ply",
        "checkpoint": root / ("chkpnt_geometric_pruned_%d.pth" % iteration),
        "stats": root / "prune_stats.json",
        "cfg_args": root / "cfg_args",
    }


def distribution(values):
    values = values.detach().float().cpu()
    return {
        "min": float(values.min()),
        "q02": float(torch.quantile(values, 0.02)),
        "q05": float(torch.quantile(values, 0.05)),
        "median": float(torch.quantile(values, 0.5)),
        "q95": float(torch.quantile(values, 0.95)),
        "q99": float(torch.quantile(values, 0.99)),
        "max": float(values.max()),
    }


@torch.no_grad()
def collect_render_stats(scene, gaussians, pipeline, background, mult):
    count = gaussians.get_xyz.shape[0]
    visibility = torch.zeros(count, dtype=torch.int32, device="cuda")
    max_radius = torch.zeros(count, dtype=torch.float32, device="cuda")
    for camera in scene.getTrainCameras():
        package = render_fastgs(camera, gaussians, pipeline, background, mult)
        radii = package["radii"]
        visible = radii > 0
        visibility += visible.to(torch.int32)
        max_radius = torch.maximum(max_radius, torch.where(visible, radii, torch.zeros_like(radii)))
    return visibility, max_radius


@torch.no_grad()
def collect_screen_overlap_counts(scene, gaussians, pipeline, background, mult, cameras, images, importance, args):
    count = gaussians.get_xyz.shape[0]
    overlap_counts = torch.zeros(count, dtype=torch.int32)
    points = gaussians.get_xyz.detach().float().cpu()
    image_by_name = {Path(image.name).stem: image for image in images.values()}
    low_importance = importance <= torch.quantile(importance, args.importance_quantile)
    camera_count = 0

    for render_camera in scene.getTrainCameras():
        image = image_by_name.get(render_camera.image_name)
        if image is None:
            continue
        camera = cameras[image.camera_id]
        fx, fy, cx, cy = camera_intrinsics(camera)
        rotation = torch.from_numpy(qvec2rotmat(image.qvec)).float()
        translation = torch.from_numpy(image.tvec).float()
        uv, depth, valid = project_points(
            points, rotation, translation, fx, fy, cx, cy, camera.width, camera.height,
        )
        radii = render_fastgs(render_camera, gaussians, pipeline, background, mult)["radii"].detach().float().cpu()
        radii[~valid] = 0
        losers = screen_overlap_loser_mask(
            uv, depth, radii, importance,
            args.screen_overlap_depth_absolute_tolerance,
            args.screen_overlap_depth_relative_tolerance,
            args.screen_overlap_dominance_ratio,
            args.screen_overlap_max_neighbors,
            candidate_mask=low_importance,
        )
        overlap_counts += losers.to(torch.int32)
        camera_count += 1
    return overlap_counts.to(device=gaussians.get_xyz.device), camera_count


@torch.no_grad()
def evaluation_psnr(scene, gaussians, pipeline, background, mult):
    cameras, split = select_evaluation_cameras(scene.getTrainCameras(), scene.getTestCameras())
    if not cameras:
        raise ValueError("PSNR evaluation requires at least one camera")
    values = []
    for camera in cameras:
        image = render_fastgs(camera, gaussians, pipeline, background, mult)["render"]
        target = camera.original_image.cuda()
        mse = (image - target).square().mean()
        values.append(20.0 * torch.log10(1.0 / torch.sqrt(mse.clamp_min(1e-12))))
    return float(torch.stack(values).mean().item()), split


def finetune(scene, gaussians, pipeline, background, mult, iterations, geometry_scale, appearance_scale):
    if iterations <= 0:
        return
    for group in gaussians.optimizer.param_groups:
        group["lr"] *= geometry_scale if group["name"] in {"xyz", "scaling", "rotation"} else appearance_scale
    for group in gaussians.shoptimizer.param_groups:
        group["lr"] *= appearance_scale

    cameras = scene.getTrainCameras()
    for _ in range(iterations):
        camera = cameras[random.randrange(len(cameras))]
        image = render_fastgs(camera, gaussians, pipeline, background, mult)["render"]
        target = camera.original_image.cuda()
        loss = 0.8 * l1_loss(image, target) + 0.2 * (1.0 - fast_ssim(image.unsqueeze(0), target.unsqueeze(0)))
        loss.backward()
        gaussians.optimizer.step()
        gaussians.optimizer.zero_grad(set_to_none=True)
        gaussians.shoptimizer.step()
        gaussians.shoptimizer.zero_grad(set_to_none=True)


def validate_finetune_iterations(iterations, dry_run=False):
    if iterations < 0:
        raise ValueError("--finetune_iterations must not be negative")
    if not dry_run and iterations == 0:
        raise ValueError(
            "--finetune_iterations must be positive for a normal prune run; "
            "use --dry_run for statistics-only execution"
        )
    return iterations


def make_stats(decision, visibility, max_radius, opacity, support, conflicts, isolated, kth, knn_threshold, before, camera_count, point3d_count, overlap_camera_count):
    mask = decision["prune_mask"]
    return {
        "gaussians_before": int(before),
        "gaussians_after": int(before - mask.sum().item()),
        "pruned_count": int(mask.sum().item()),
        "pruned_ratio": float(mask.float().mean().item()),
        "redundant_candidates": int(decision["redundant"].sum().item()),
        "screen_overlap_redundant_candidates": int(decision["overlap_redundant"].sum().item()),
        "floater_candidates": int(decision["floater"].sum().item()),
        "pruned_redundant": int((mask & decision["redundant"]).sum().item()),
        "pruned_floater": int((mask & decision["floater"]).sum().item()),
        "isolated_count": int(isolated.sum().item()),
        "colmap_registered_images": int(camera_count),
        "colmap_points3d": int(point3d_count),
        "screen_overlap_cameras": int(overlap_camera_count),
        "visibility_count": distribution(visibility.float()),
        "max_screen_radius": distribution(max_radius),
        "opacity_before": distribution(opacity),
        "opacity_after": distribution(opacity[~mask]),
        "importance_before": distribution(decision["importance"]),
        "importance_after": distribution(decision["importance"][~mask]),
        "geometric_support_count": distribution(support.float()),
        "depth_conflict_count": distribution(conflicts.float()),
        "screen_overlap_loser_views": distribution(decision["screen_overlap_count"].float()),
        "scale_normalized_kth_neighbor_distance": distribution(kth),
        "knn_isolation_threshold": float(knn_threshold),
        "importance_threshold": float(decision["importance_threshold"].item()),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    model = ModelParams(parser, sentinel=True)
    optimization = OptimizationParams(parser)
    pipeline = PipelineParams(parser)
    parser.add_argument("--iteration", type=int, default=-1)
    parser.add_argument("--output_name", default="geometric_pruned")
    parser.add_argument("--max_prune_ratio", type=float, default=0.03)
    parser.add_argument("--importance_quantile", type=float, default=0.05)
    parser.add_argument("--knn_k", type=int, default=8)
    parser.add_argument("--knn_mad_factor", type=float, default=4.0)
    parser.add_argument("--support_pixel_radius", type=float, default=3.0)
    parser.add_argument("--depth_absolute_tolerance", type=float, default=0.05)
    parser.add_argument("--depth_relative_tolerance", type=float, default=0.05)
    parser.add_argument("--screen_overlap_min_views", type=int, default=3)
    parser.add_argument("--screen_overlap_depth_absolute_tolerance", type=float, default=0.05)
    parser.add_argument("--screen_overlap_depth_relative_tolerance", type=float, default=0.02)
    parser.add_argument("--screen_overlap_dominance_ratio", type=float, default=1.5)
    parser.add_argument("--screen_overlap_max_neighbors", type=int, default=8)
    parser.add_argument("--voxel_size_ratio", type=float, default=0.05)
    parser.add_argument("--max_voxel_prune_ratio", type=float, default=0.20)
    parser.add_argument("--finetune_iterations", type=int, default=800)
    parser.add_argument("--finetune_geometry_lr_scale", type=float, default=0.01)
    parser.add_argument("--finetune_appearance_lr_scale", type=float, default=0.01)
    parser.add_argument("--evaluate_psnr", action="store_true")
    parser.add_argument("--max_psnr_drop", type=float, default=0.05)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = get_combined_args(parser)
    try:
        validate_finetune_iterations(args.finetune_iterations, args.dry_run)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.source_path or not args.model_path:
        parser.error("both -s/--source_path and -m/--model_path are required")
    if not 0.0 <= args.max_prune_ratio <= 0.03:
        parser.error("--max_prune_ratio must be in [0, 0.03]")
    if args.screen_overlap_min_views < 1 or args.screen_overlap_max_neighbors < 1:
        parser.error("screen overlap view and neighbor limits must be positive")
    if args.screen_overlap_dominance_ratio <= 1.0:
        parser.error("--screen_overlap_dominance_ratio must be greater than 1")
    if args.voxel_size_ratio <= 0.0 or not 0.0 < args.max_voxel_prune_ratio <= 1.0:
        parser.error("voxel ratios must be in (0, 1]")
    return args, model, optimization, pipeline


def main():
    args, model_params, optimization_params, pipeline_params = parse_args()
    safe_state(args.quiet)
    dataset = model_params.extract(args)
    optimization = optimization_params.extract(args)
    pipeline = pipeline_params.extract(args)

    gaussians = GaussianModel(dataset.sh_degree, optimizer_type="default")
    scene = Scene(dataset, gaussians, load_iteration=args.iteration, shuffle=False)
    iteration = scene.loaded_iter
    paths = build_output_paths(Path(dataset.model_path), iteration, args.output_name)
    if paths["root"].exists() and not args.overwrite:
        raise FileExistsError("output exists; use --overwrite or --output_name: %s" % paths["root"])

    gaussians.spatial_lr_scale = scene.cameras_extent
    gaussians.training_setup(optimization)
    gaussians.max_radii2D = torch.zeros(gaussians.get_xyz.shape[0], device="cuda")
    gaussians.tmp_radii = None
    background = torch.tensor([1, 1, 1] if dataset.white_background else [0, 0, 0], dtype=torch.float32, device="cuda")

    colmap_dir = Path(dataset.source_path) / "sparse" / "0"
    cameras = read_cameras_binary(colmap_dir / "cameras.bin")
    images = read_images_binary(colmap_dir / "images.bin")
    points3d = read_points3d_binary(colmap_dir / "points3D.bin")
    observation_indices = build_observation_indices(cameras, images, points3d)

    psnr_before, psnr_split = evaluation_psnr(scene, gaussians, pipeline, background, args.mult) if args.evaluate_psnr else (None, None)
    visibility, max_radius = collect_render_stats(scene, gaussians, pipeline, background, args.mult)
    opacity = gaussians.get_opacity.detach().squeeze(1)
    importance = compute_render_importance(opacity, visibility, max_radius)
    isolated, kth, knn_threshold = knn_isolation_mask(
        gaussians.get_xyz, args.knn_k, args.knn_mad_factor, gaussians.get_scaling,
    )
    support, conflicts = collect_geometric_support(
        gaussians.get_xyz,
        cameras,
        images,
        observation_indices,
        args.support_pixel_radius,
        args.depth_absolute_tolerance,
        args.depth_relative_tolerance,
    )
    overlap_counts, overlap_camera_count = collect_screen_overlap_counts(
        scene, gaussians, pipeline, background, args.mult, cameras, images, importance, args,
    )
    decision = build_geometric_prune_decision(
        importance, visibility, support, conflicts, isolated,
        args.max_prune_ratio, args.importance_quantile,
        screen_overlap_count=overlap_counts,
        min_overlap_views=args.screen_overlap_min_views,
        xyz=gaussians.get_xyz,
        voxel_size=scene.cameras_extent * args.voxel_size_ratio,
        max_voxel_prune_ratio=args.max_voxel_prune_ratio,
    )
    stats = make_stats(
        decision, visibility, max_radius, opacity, support, conflicts,
        isolated, kth, knn_threshold, gaussians.get_xyz.shape[0],
        len(images), len(points3d), overlap_camera_count,
    )
    stats["parameters"] = {key: getattr(args, key) for key in (
        "max_prune_ratio", "importance_quantile", "knn_k", "knn_mad_factor",
        "support_pixel_radius", "depth_absolute_tolerance", "depth_relative_tolerance",
        "screen_overlap_min_views", "screen_overlap_depth_absolute_tolerance",
        "screen_overlap_depth_relative_tolerance", "screen_overlap_dominance_ratio",
        "screen_overlap_max_neighbors", "voxel_size_ratio", "max_voxel_prune_ratio",
        "finetune_iterations", "finetune_geometry_lr_scale", "finetune_appearance_lr_scale",
    )}

    if args.dry_run:
        print(json.dumps(stats, indent=2))
        return 0

    gaussians.prune_points(decision["prune_mask"])
    finetune(
        scene, gaussians, pipeline, background, args.mult,
        args.finetune_iterations, args.finetune_geometry_lr_scale,
        args.finetune_appearance_lr_scale,
    )
    if args.evaluate_psnr:
        psnr_after, after_split = evaluation_psnr(scene, gaussians, pipeline, background, args.mult)
        if after_split != psnr_split:
            raise RuntimeError("PSNR camera split changed during pruning")
        stats["psnr_split"] = psnr_split
        stats["psnr_before"] = psnr_before
        stats["psnr_after"] = psnr_after
        stats["psnr_delta"] = psnr_after - psnr_before
        if stats["psnr_delta"] < -args.max_psnr_drop:
            raise RuntimeError("PSNR drop %.6f exceeds %.6f dB; output was not published" % (-stats["psnr_delta"], args.max_psnr_drop))

    paths["ply"].parent.mkdir(parents=True, exist_ok=True)
    paths["root"].mkdir(parents=True, exist_ok=True)
    gaussians.save_ply(str(paths["ply"]))
    torch.save((gaussians.capture("default"), iteration), str(paths["checkpoint"]))
    exported_args = vars(args).copy()
    exported_args["model_path"] = str(paths["root"])
    paths["cfg_args"].write_text(str(Namespace(**exported_args)))
    paths["stats"].write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    print("Saved PLY:", paths["ply"])
    print("Saved checkpoint:", paths["checkpoint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
