from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from compare_colmap_pipelines import (
    Pipeline,
    build_convert_command,
    parse_points3d_metrics,
    parse_registered_images,
)


def test_pipeline_commands_keep_cpu_and_gpu_variants_explicit():
    base = dict(job_dir=Path('/tmp/job'), fastgs_dir=Path('/home/liangjiahua/FastGS'))
    legacy = Pipeline('legacy_cpu', '/usr/bin/colmap', False, False, False)
    new_cpu = Pipeline('new_cpu', '/home/liangjiahua/colmap-cuda-ceres/bin/colmap', True, False, False)
    new_gpu = Pipeline('new_gpu', '/home/liangjiahua/colmap-cuda-ceres/bin/colmap', True, True, True)

    legacy_cmd = build_convert_command(**base, pipeline=legacy, intrinsics=Path('/tmp/intrinsics.yaml'))
    cpu_cmd = build_convert_command(**base, pipeline=new_cpu, intrinsics=Path('/tmp/intrinsics.yaml'))
    gpu_cmd = build_convert_command(**base, pipeline=new_gpu, intrinsics=Path('/tmp/intrinsics.yaml'))

    assert '--no_gpu' in legacy_cmd
    assert '--no_gpu' in cpu_cmd
    assert '--no_gpu' not in gpu_cmd
    assert '--colmap_new_api' not in legacy_cmd
    assert '--colmap_new_api' in cpu_cmd
    assert '--mapper_use_gpu' in gpu_cmd


def test_hybrid_pipeline_uses_cpu_features_and_gpu_matching_and_ba():
    hybrid = Pipeline('new_hybrid', '/home/liangjiahua/colmap-cuda-ceres/bin/colmap', True, False, True)

    command = build_convert_command(
        job_dir=Path('/tmp/job'),
        fastgs_dir=Path('/home/liangjiahua/FastGS'),
        pipeline=hybrid,
    )

    assert '--no_gpu' in command
    assert '--matching_gpu' in command
    assert '--mapper_use_gpu' in command


def test_parse_points3d_metrics_counts_tracks_and_error(tmp_path):
    points = tmp_path / 'points3D.txt'
    points.write_text(
        '# header\n'
        '1 1 2 3 255 0 0 0.5 10 2 11 3\n'
        '2 4 5 6 0 255 0 1.5 12 4\n',
        encoding='utf-8',
    )

    metrics = parse_points3d_metrics(points)

    assert metrics == {
        'points3d_count': 2,
        'mean_reprojection_error': 1.0,
        'mean_track_length': 1.5,
    }


def test_parse_registered_images_counts_image_records_not_observation_lines(tmp_path):
    images = tmp_path / 'images.txt'
    images.write_text(
        '# header\n'
        '1 1 0 0 0 0 0 0 1 frame_000001.jpg\n'
        '12.0 4.0 7 9.0 3.0 -1\n'
        '2 1 0 0 0 0 0 0 1 frame_000002.jpg\n'
        '\n',
        encoding='utf-8',
    )

    assert parse_registered_images(images) == 2
