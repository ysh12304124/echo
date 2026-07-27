# Gravity-Aligned Gaussian Output Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with a review checkpoint after each task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not create a git commit unless the user explicitly authorizes it.

**Goal:** Add optional IMU-based gravity alignment to the FastGS worker so the final Gaussian PLY, C2W poses, and anchor share a world where +Y points downward, while preserving the existing COLMAP fallback.

**Architecture:** Add a NumPy/`plyfile` post-processing module at `scripts/gravity_alignment.py`. It reads `job_dir/imu_manifest.json`, estimates gravity from image-associated camera-frame accelerations and registered C2W poses, transforms Gaussian geometry and poses, and returns explicit alignment metadata. `scripts/reconstruct_images.py` remains the workflow owner and invokes the module after training and pose export, then writes the anchor from the transformed outputs.

**Tech Stack:** Python 3.7+; NumPy; `plyfile`; existing FastGS `pytest` tests; existing COLMAP and FastGS command orchestration.

## Global Constraints

- This change is limited to `/home/liangjiahua/FastGS`; the upstream 130 service is out of scope.
- Input images are `job_dir/input/*.jpg` or `*.jpeg`.
- Optional manifest is `job_dir/imu_manifest.json`.
- `poses.txt` stores row-major C2W 4x4 matrices.
- FastGS Gaussian rotations are `rot_0..rot_3` in normalized `wxyz` order.
- Successful target gravity is `[0, 1, 0]`; successful anchor coordinate system is `gravity_aligned_world`.
- Fallback coordinate system is `colmap_world`; fallback must not fabricate a correction.
- Preserve PLY vertex count, property names/order/types, normals, SH coefficients, opacity, scale, unknown scalar fields, and existing artifact names.
- Do not generate `alignment.json`.
- Do not add a runtime dependency; `numpy` and `plyfile` are already in the FastGS environments.
- Do not commit changes without explicit user approval.

## File Map

- Create `/home/liangjiahua/FastGS/scripts/gravity_alignment.py`: manifest parsing, gravity estimation, rotation math, PLY transforms, pose transforms, and alignment result metadata.
- Create `/home/liangjiahua/FastGS/scripts/tests/test_gravity_alignment.py`: focused unit and binary PLY tests for the new module.
- Modify `/home/liangjiahua/FastGS/scripts/reconstruct_images.py`: call the module after training, pass the optional manifest, write transformed outputs, and expose metadata in `result.json` and events.
- Modify `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images_anchor.py`: assert configurable coordinate-system output while preserving existing default behavior.
- Modify `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images_poses.py`: retain existing C2W export coverage and add transformed-pose integration coverage only where the workflow API requires it.

---

### Task 1: Define and Implement Manifest/Gravity Math

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_gravity_alignment.py`
- Create: `/home/liangjiahua/FastGS/scripts/gravity_alignment.py`

**Interfaces:**
- Produces `load_manifest(path: Path) -> Manifest`; missing or structurally invalid files raise `ManifestError` for the integration layer to convert into fallback.
- Produces `estimate_gravity(manifest: Manifest, poses_by_image: Dict[str, np.ndarray], image_names: List[str]) -> AlignmentResult`.
- Produces `rotation_to_target(source: np.ndarray, target: np.ndarray) -> np.ndarray`.
- `AlignmentResult` exposes `method: str`, `coordinate_system: str`, `rotation: np.ndarray`, `gravity_colmap: Optional[np.ndarray]`, `residual_degrees: Optional[float]`, and `valid_sample_count: int`.

- [ ] **Step 1: Write manifest and gravity tests first.**

```python
def test_load_manifest_associates_acceleration_by_image(tmp_path):
    path = tmp_path / "imu_manifest.json"
    path.write_text(json.dumps({
        "version": 1,
        "acceleration_frame": "camera",
        "acceleration_type": "gravity",
        "frames": [{
            "image": "frame_000000.jpg",
            "timestamp_ms": 123,
            "acceleration": [0.0, 0.0, 9.81],
        }],
    }))

    manifest = load_manifest(path)

    assert manifest.acceleration_type == "gravity"
    assert manifest.frames["frame_000000.jpg"].acceleration == (0.0, 0.0, 9.81)


def test_rotation_to_target_maps_sixty_degree_tilt_to_positive_y():
    source = np.array([0.0, np.sqrt(3.0) / 2.0, 0.5])

    rotation = rotation_to_target(source, np.array([0.0, 1.0, 0.0]))

    np.testing.assert_allclose(rotation @ source, [0.0, 1.0, 0.0], atol=1e-7)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-7)
    assert np.linalg.det(rotation) == pytest.approx(1.0)


def test_estimate_gravity_rejects_unstable_or_insufficient_samples():
    manifest = manifest_with_frames([
        ("a.jpg", [0.0, 0.0, 9.81]),
        ("b.jpg", [0.0, 9.81, 0.0]),
    ])
    poses = {name: np.eye(4) for name in ("a.jpg", "b.jpg")}

    result = estimate_gravity(manifest, poses, ["a.jpg", "b.jpg"])

    assert result.method == "colmap_world"
    np.testing.assert_allclose(result.rotation, np.eye(3))


def test_specific_force_is_inverted_before_world_estimation():
    manifest = manifest_with_frames(
        [("a.jpg", [0.0, 0.0, -9.81]),
         ("b.jpg", [0.0, 0.0, -9.81]),
         ("c.jpg", [0.0, 0.0, -9.81])],
        acceleration_type="specific_force",
    )
    poses = {name: np.eye(4) for name in ("a.jpg", "b.jpg", "c.jpg")}

    result = estimate_gravity(manifest, poses, list(poses))

    assert result.method == "gravity_aligned_world"
    np.testing.assert_allclose(result.gravity_colmap, [0.0, 0.0, 1.0], atol=1e-7)
```

The test file must also cover duplicate/invalid entries, missing manifest handling at the caller boundary, opposite vectors, finite-value checks, acceleration magnitude `[0.5, 20.0]`, three-sample minimum, 50% valid ratio, 20-degree inlier threshold, and an outlier that is excluded from the final direction.

- [ ] **Step 2: Run the focused tests and verify the intended red failure.**

Run from `/home/liangjiahua/FastGS`:

```bash
python -m pytest scripts/tests/test_gravity_alignment.py -q
```

Expected: collection or test failure because `scripts/gravity_alignment.py` and its public interfaces do not yet exist. If the command is unavailable, run the same command through the FastGS conda environment and record the exact interpreter used.

- [ ] **Step 3: Implement the minimal manifest and gravity module.**

Implement these concrete behaviors:

```python
@dataclass(frozen=True)
class ManifestFrame:
    image: str
    timestamp_ms: int
    acceleration: Tuple[float, float, float]


@dataclass(frozen=True)
class Manifest:
    acceleration_type: str
    frames: Dict[str, ManifestFrame]


@dataclass(frozen=True)
class AlignmentResult:
    method: str
    coordinate_system: str
    rotation: np.ndarray
    gravity_colmap: Optional[np.ndarray]
    residual_degrees: Optional[float]
    valid_sample_count: int
```

`load_manifest` must parse the JSON, require version `1`, require camera frame, accept only `gravity` and `specific_force`, ignore invalid or duplicate frame entries, and raise `ManifestError` for a missing or structurally invalid file. `estimate_gravity` must transform each normalized camera vector with `pose[:3, :3]`, invert specific force, use component-wise median plus a 20-degree inlier pass, require the minimum count and valid ratio, then return either identity/`colmap_world` or a gravity alignment result. `rotation_to_target` must use identity for parallel vectors, deterministic X-axis 180 degrees for antiparallel vectors, and Rodrigues rotation otherwise.

- [ ] **Step 4: Run focused tests and inspect numerical output.**

```bash
python -m pytest scripts/tests/test_gravity_alignment.py -q
```

Expected: all manifest, direction, sign, outlier, and rotation tests pass. Also run a one-line numerical check that `np.linalg.norm(result.rotation.T @ result.rotation - np.eye(3)) < 1e-7` for the 60-degree fixture.

---

### Task 2: Transform Gaussian PLY and C2W Poses

**Files:**
- Modify: `/home/liangjiahua/FastGS/scripts/gravity_alignment.py`
- Modify: `/home/liangjiahua/FastGS/scripts/tests/test_gravity_alignment.py`

**Interfaces:**
- Produces `transform_poses(poses_by_image: Dict[str, np.ndarray], rotation: np.ndarray) -> Dict[str, np.ndarray]`.
- Produces `transform_pose_text(text: str, rotation: np.ndarray) -> str`.
- Produces `transform_gaussian_ply(path: Path, rotation: np.ndarray) -> None`.
- Produces `apply_gravity_alignment(manifest_path: Path, poses_path: Path, ply_path: Path, image_names: List[str]) -> AlignmentResult`.

- [ ] **Step 1: Write failing pose/quaternion/PLY preservation tests.**

```python
def test_transform_poses_rotates_c2w_rotation_and_translation():
    poses = {"frame.jpg": np.array([
        [1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0, 2.0],
        [0.0, 0.0, 1.0, 3.0],
        [0.0, 0.0, 0.0, 1.0],
    ])}
    rotation = rotation_to_target(np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]))

    transformed = transform_poses(poses, rotation)

    np.testing.assert_allclose(transformed["frame.jpg"][:3, :3], rotation)
    np.testing.assert_allclose(transformed["frame.jpg"][:3, 3], rotation @ [1.0, 2.0, 3.0])


def test_transform_gaussian_ply_changes_only_position_and_wxyz_rotation(tmp_path):
    ply_path = write_synthetic_gaussian_ply(tmp_path / "point_cloud.ply")
    before = read_vertex_arrays(ply_path)
    rotation = rotation_to_target(np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]))

    transform_gaussian_ply(ply_path, rotation)

    after = read_vertex_arrays(ply_path)
    before_positions = np.column_stack([before[name] for name in ("x", "y", "z")])
    expected_positions = (rotation @ before_positions.T).T
    np.testing.assert_allclose(after["x"], expected_positions[:, 0])
    np.testing.assert_allclose(after["y"], expected_positions[:, 1])
    np.testing.assert_allclose(after["z"], expected_positions[:, 2])
    for name in before.dtype.names:
        if name not in {"x", "y", "z", "rot_0", "rot_1", "rot_2", "rot_3"}:
            np.testing.assert_array_equal(after[name], before[name])
    assert len(after) == len(before)
```

The synthetic PLY must contain the real FastGS fields `x/y/z`, `nx/ny/nz`, `f_dc_0..2`, at least one `f_rest_*`, `opacity`, `scale_0..2`, and `rot_0..3`, written as binary little-endian float properties. Add a test that identity rotation preserves the complete byte-level semantic values and a test that the quaternion remains normalized and represents `R_align @ R_old`.

- [ ] **Step 2: Run the focused transform tests and verify red failure.**

```bash
python -m pytest scripts/tests/test_gravity_alignment.py -q
```

Expected: the new transform tests fail because the transform functions are not implemented.

- [ ] **Step 3: Implement pose text and PLY transforms.**

Use `plyfile.PlyData.read` and `PlyData.write` while retaining the vertex structured array and property definitions. Update only `x`, `y`, `z`, and `rot_0..rot_3`; parse FastGS quaternions as `wxyz`, convert each to a 3x3 matrix using the same equations as `utils.general_utils.build_rotation`, left-multiply by `rotation`, convert back to normalized `wxyz`, and write through a same-directory temporary path followed by `os.replace`.

For pose text, parse every non-empty line as exactly 16 floats, reshape row-major, apply `R_new = R_align @ R_old` and `t_new = R_align @ t_old`, and serialize 16 values with the existing `%.15f` precision. Reject malformed rows rather than silently producing a shifted artifact.

- [ ] **Step 4: Run transform tests and the existing pose/anchor tests.**

```bash
python -m pytest scripts/tests/test_gravity_alignment.py scripts/tests/test_reconstruct_images_poses.py scripts/tests/test_reconstruct_images_anchor.py -q
```

Expected: all focused tests pass and the pre-existing tests remain green.

---

### Task 3: Integrate Alignment Into the Reconstruction Worker

**Files:**
- Modify: `/home/liangjiahua/FastGS/scripts/reconstruct_images.py`
- Modify: `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images_anchor.py`
- Modify: `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images_poses.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images.py`

**Interfaces:**
- `write_anchor(job_dir, poses_path, ply_path, coordinate_system="colmap_world") -> tuple[Path, str]` remains backward compatible.
- `write_result(...)` accepts optional `alignment_method`, `gravity_colmap`, and `alignment_residual_degrees` values and serializes them at the existing result top level.
- `run_job` discovers `job_dir/imu_manifest.json` without changing required CLI arguments.

- [ ] **Step 1: Write failing integration tests.**

Add tests that patch `run_command`, `write_colmap_poses`, and the existing output paths so no COLMAP or GPU training runs. The fixture must create an input image set, a trained Gaussian PLY, `poses.txt`, and a manifest. Assert:

```python
assert json.loads((job_dir / "anchor.json").read_text())["coordinate_system"] == "gravity_aligned_world"
assert json.loads((job_dir / "result.json").read_text())["alignment_method"] == "gravity_aligned_world"
assert not (job_dir / "alignment.json").exists()
```

Add a second integration test with no manifest and assert `coordinate_system == "colmap_world"`, `alignment_method == "colmap_world"`, and unchanged PLY/pose semantic values.

- [ ] **Step 2: Run the integration tests and verify red failure.**

```bash
python -m pytest scripts/tests/test_reconstruct_images.py -q
```

Expected: the success-path test fails because `run_job` currently never reads a manifest or invokes alignment, while the pre-existing worker tests continue to show their baseline status.

- [ ] **Step 3: Integrate the minimal workflow change.**

After training and `validate_output_ply`, keep the existing order for raw pose export, then:

```python
manifest_path = job_dir / "imu_manifest.json"
alignment = apply_gravity_alignment(
    manifest_path=manifest_path,
    poses_path=poses_path,
    ply_path=ply_path,
    image_names=[path.name for path in images],
)
anchor_path, anchor_method = write_anchor(
    job_dir,
    poses_path,
    ply_path,
    coordinate_system=alignment.coordinate_system,
)
```

`apply_gravity_alignment` must read and validate all inputs before writing. On missing/invalid manifest, unmatched pose, malformed pose text, or malformed PLY, it must leave all three artifacts unchanged and return `AlignmentResult(method="colmap_world", coordinate_system="colmap_world", rotation=np.eye(3), gravity_colmap=None, residual_degrees=None, valid_sample_count=0)`. On success it writes temporary PLY and pose files in their original directories and replaces both only after both temporary writes succeed, then `write_anchor` recalculates the anchor from the transformed outputs. Pass the alignment metadata into `append_event` and `write_result`; preserve existing keys and add only `alignment_method`, `gravity_colmap`, and `alignment_residual_degrees`. Update `anchor_json` to accept the optional coordinate-system string while keeping the default `colmap_world` for existing callers.

- [ ] **Step 4: Run the integration and full script tests.**

```bash
python -m pytest scripts/tests -q
```

Expected: all existing and new tests pass. Confirm no test or worker code writes `alignment.json`.

---

### Task 4: Remote Verification and Dataset Dry Run

**Files:**
- Modify: none unless verification reveals a test-only defect.

- [ ] **Step 1: Run the complete test suite in the actual FastGS environment.**

From `/home/liangjiahua/FastGS`, try:

```bash
python -m pytest scripts/tests -q
```

If the system Python lacks pytest, use the existing FastGS environment interpreter and record its path with `which python` and `python -m pytest --version`. Do not install packages or modify environments without explicit approval.

- [ ] **Step 2: Run a synthetic post-processing dry run.**

Create a temporary job directory outside the repository with at least three synthetic image names, identity C2W poses, a real-schema binary Gaussian PLY, and three consistent manifest vectors. Invoke only the new post-processing API. Verify:

```text
gravity_colmap is finite
R_align.T @ R_align is identity within 1e-7
det(R_align) is 1 within 1e-7
R_align @ gravity_colmap is [0, 1, 0] within 1e-7
PLY vertex count is unchanged
all non-geometric PLY fields are unchanged
poses and anchor use the same transformed coordinates
```

- [ ] **Step 3: Inspect the final diff and working tree without committing.**

Run:

```bash
git -C /home/liangjiahua/FastGS diff -- scripts/gravity_alignment.py scripts/reconstruct_images.py scripts/tests docs/superpowers/specs docs/superpowers/plans
git -C /home/liangjiahua/FastGS status --short
```

Confirm existing user modifications remain intact, only the planned files changed, no credentials appear in files, and no commit is created.
