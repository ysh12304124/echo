# Gravity-Aligned Gaussian Output Design

## Goal

Add optional gravity alignment to the FastGS reconstruction worker. The worker
continues to receive an image set in `job_dir/input/`; an optional manifest
associates one camera-frame acceleration vector with each image. When gravity
is reliable, the worker rotates the Gaussian point cloud, C2W poses, and anchor
into one gravity-aligned world where +Y points downward. When it is not
reliable, the existing COLMAP world is preserved.

## Scope

This change is limited to `/home/liangjiahua/FastGS`. The upstream 130 service
is out of scope and is assumed to stage images and `imu_manifest.json` in the
200 worker job directory. The worker must not generate `alignment.json`.

## Components

### `scripts/gravity_alignment.py`

Pure post-processing helpers using NumPy and `plyfile`:

- load and validate the optional manifest;
- estimate a robust gravity direction in COLMAP world coordinates;
- construct the minimum-angle rotation to `[0, 1, 0]`;
- transform Gaussian PLY positions and `wxyz` rotations;
- transform row-major C2W pose matrices;
- write the coordinate-system field in `anchor.json`.

### `scripts/reconstruct_images.py`

Keeps orchestration and existing COLMAP/FastGS commands. After training it
writes the original poses and anchor, applies optional gravity alignment to
the trained PLY and poses, then rewrites the anchor from the transformed
outputs. `result.json` records the alignment method and residual angle.

## Manifest Contract

The optional file is `job_dir/imu_manifest.json`:

```json
{
  "version": 1,
  "acceleration_frame": "camera",
  "acceleration_type": "gravity",
  "frames": [
    {
      "image": "frame_000000.jpg",
      "timestamp_ms": 0,
      "acceleration": [0.0, 0.0, 9.81]
    }
  ]
}
```

Rules:

- `version` must be `1`.
- `acceleration_frame` must be `camera`.
- `acceleration_type` must be `gravity` or `specific_force`.
- `image` must match an image filename exactly.
- `timestamp_ms` is retained for diagnostics and is not used for matching.
- Invalid or duplicate entries are ignored with a diagnostic reason.
- A missing manifest preserves current image-only behavior.

## Gravity Estimation

For every valid manifest entry with a matching registered pose:

```text
g_camera = normalize(acceleration)
g_colmap = R_c2w @ g_camera
```

For `specific_force`, the camera vector is negated before normalization. A
vector is valid only when it is finite, non-zero, and its magnitude is within
`[0.5, 20.0]` in the manifest's acceleration units. The normalized world
vectors are combined using a component-wise median followed by a normalized
mean of samples within 20 degrees of that median. Alignment requires at least
three valid samples, at least half of the manifest entries to be valid, and a
median inlier angle no greater than 20 degrees.

Failure returns an identity transform and `colmap_world` metadata. No
correction is fabricated.

## Coordinate Transform

Let `g` be the estimated downward gravity direction and `u = [0, 1, 0]`.
The minimum-angle proper rotation satisfies:

```text
R_align @ g = u
```

Already aligned vectors use identity. Opposite vectors use a deterministic
180-degree rotation around the X axis. General vectors use Rodrigues'
formula from the cross product and dot product. This does not determine yaw;
the minimum-angle choice leaves the horizontal orientation otherwise
unchanged.

For each Gaussian:

```text
p_new = R_align @ p_old
Q_new = R_align @ Q_old
```

FastGS stores `rot_0..rot_3` as normalized `wxyz`. The result is converted
back to `wxyz` and normalized. `nx/ny/nz`, SH coefficients, opacity, scale,
unknown scalar attributes, property order, property types, and vertex count
are preserved. SH rotation is intentionally out of scope; the current
viewer/training contract treats these coefficients as appearance data.

For every row-major C2W pose:

```text
R_new = R_align @ R_old
t_new = R_align @ t_old
```

The transformed PLY and transformed poses are used to recalculate the anchor.
Successful output uses `coordinate_system: gravity_aligned_world`; fallback
output uses `coordinate_system: colmap_world`.

## Output Metadata

Existing output names remain unchanged:

- `point_cloud.ply`
- `poses.txt`
- `anchor.json`
- `result.json`

`result.json` adds:

```json
{
  "alignment_method": "gravity_aligned_world",
  "gravity_colmap": [0.0, 1.0, 0.0],
  "alignment_residual_degrees": 0.0
}
```

Fallback uses `alignment_method: colmap_world` and null gravity/residual
fields. `anchor.json` retains its existing `method`, `coordinate_system`, and
`position` fields.

## Failure Handling

Alignment is optional and must not make ordinary image reconstruction fail.
Missing manifest, malformed manifest, unmatched images, invalid acceleration,
insufficient samples, unstable gravity, malformed PLY, or malformed poses
causes a logged fallback to the original COLMAP world. Existing reconstruction
validation errors still fail the job as before.

Writes use temporary files in the same directory followed by replacement so a
partially transformed PLY or pose file is never published as the final output.

## Verification

`scripts/tests/test_gravity_alignment.py` covers manifest validation, specific
force sign, robust gravity estimation, outlier rejection, insufficient-data
fallback, identity and 60-degree rotations, opposite vectors, C2W transforms,
Gaussian quaternion transforms, PLY attribute preservation, and metadata.

Existing pose, anchor, CUDA-command, and reconstruction-worker tests remain
green. A small synthetic binary PLY integration test verifies that the final
PLY, poses, and anchor share the same transform without running COLMAP or
FastGS training.
