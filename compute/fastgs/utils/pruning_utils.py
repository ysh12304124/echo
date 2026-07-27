import torch


def online_prune_mask(
    xyz,
    scaling,
    opacity,
    camera_centers,
    scene_extent,
    min_opacity,
    margin,
    max_scale_ratio,
):
    """Return a mask for Gaussians outside the observed scene or too weak/large."""
    if camera_centers.numel() == 0:
        raise ValueError("online pruning requires at least one camera center")
    if scene_extent <= 0:
        raise ValueError("scene_extent must be positive")

    chunk_size = 32768
    nearest_camera_distance = torch.empty(xyz.shape[0], device=xyz.device, dtype=xyz.dtype)
    for start in range(0, xyz.shape[0], chunk_size):
        stop = min(start + chunk_size, xyz.shape[0])
        nearest_camera_distance[start:stop] = torch.cdist(
            xyz[start:stop], camera_centers
        ).amin(dim=1)
    outside_observed_scene = nearest_camera_distance > margin * scene_extent
    oversized = scaling.amax(dim=1) > max_scale_ratio * scene_extent
    low_opacity = opacity.squeeze(-1) < min_opacity
    return low_opacity | oversized | outside_observed_scene
