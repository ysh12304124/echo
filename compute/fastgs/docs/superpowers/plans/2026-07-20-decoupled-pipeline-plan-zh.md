# FastGS 图片与 IMU 解耦流水线实施计划

> **给执行代理的说明：** 实现时按任务逐项执行；每个任务先写失败测试，再实现，再运行对应测试。除非用户明确授权，不得创建 git commit。

**目标：** 将 200 机 FastGS 工作流拆成 COLMAP、COLMAP 重力对齐、FastGS 训练、结果导出四个独立阶段，并提供一个只负责编排和停止策略的总入口，使最终 Gaussian 点云、`poses.json`、兼容用 `poses.txt`、锚点和阶段状态都有明确的数据契约。

**架构：** 原始 COLMAP 输出写入 `colmap_raw/`，永远不修改；重力对齐成功后写入全新的 `colmap_gravity_aligned/`，FastGS 只读取该目录；对齐失败时默认立即停止，只有后端显式传入 `--allow-alignment-fallback` 才允许复制原始 COLMAP 作为 FastGS 输入并将该阶段标记为 `completed_with_warnings`。`run_pipeline.py` 只编排四个阶段、检查状态和停止后续调用，不实现 COLMAP、IMU、训练或锚点数学逻辑。

**技术栈：** Python 3.10（200 机 `fastgs` 环境）、现有 COLMAP CUDA 可执行文件、FastGS 的 `convert.py`/`train.py`、NumPy、`plyfile`、标准库 `argparse`/`json`/`subprocess`/`pathlib`。

## 全局约束

- 修改范围只在 `/home/liangjiahua/FastGS`，不修改 130 机代码。
- 不新增第三方运行时依赖；继续使用 FastGS 已有的 NumPy 和 `plyfile`。
- 输入图片目录固定为 `<job_dir>/input/`，支持 `.jpg` 和 `.jpeg`，图片文件名是全流程的唯一关联键。
- 输入 IMU 文件固定为 `<job_dir>/imu_manifest.json`。
- COLMAP 注册成功率必须满足 `registered_images / input_images >= 0.8`；低于 80% 时 COLMAP 阶段失败并停止整个流程。
- COLMAP 注册率达到 80% 但仍有未注册图片时，阶段状态为 `completed_with_warnings`；未注册图片不得伪造位姿。
- 重力对齐不设置有效 IMU 数量下限；至少一个有效且匹配已注册图片的向量即可尝试对齐。
- 默认任一阶段失败立即停止后续阶段，并在阶段状态 JSON 中给出稳定的 `error_code` 和可读 `message`。
- 重力对齐失败默认是 `failed`；仅在后端显式传入 `--allow-alignment-fallback` 时，才允许回到原始 COLMAP 并继续。
- 原始 COLMAP 目录 `colmap_raw/` 不得被重力对齐阶段修改。
- 重力对齐输出必须是新目录 `colmap_gravity_aligned/`，不能原地修改 `colmap_raw/`。
- 正式位姿接口为 `outputs/poses.json`；`outputs/poses.txt` 只用于兼容已有读取端，且二者顺序必须一致。
- `poses.json` 和 `poses.txt` 只包含已注册图片；未注册图片只写入 `unregistered_images`。
- `anchor.json`、`poses.json` 和最终 Gaussian PLY 必须使用同一个 `coordinate_system`。
- 不生成 `alignment.json`；重力对齐元数据写入 `colmap_gravity_aligned/alignment_meta.json` 或回退结果目录中的同名文件。
- 不提交代码；实现完成后只报告验证结果和未解决的测试环境问题。

## 目录与阶段产物

每个任务目录使用以下结构：

```text
<job_dir>/
├── input/
│   ├── frame_000000.jpg
│   └── ...
├── imu_manifest.json
├── colmap_raw/
│   ├── database.db
│   ├── images/
│   └── sparse/0/
│       ├── cameras.bin
│       ├── images.bin
│       └── points3D.bin
├── colmap_gravity_aligned/
│   ├── database.db
│   ├── images/
│   ├── sparse/0/
│   │   ├── cameras.bin
│   │   ├── images.bin
│   │   └── points3D.bin
│   └── alignment_meta.json
├── fastgs_model/
│   └── point_cloud/iteration_<N>/point_cloud.ply
├── outputs/
│   ├── point_cloud.ply
│   ├── poses.json
│   ├── poses.txt
│   ├── anchor.json
│   └── result.json
├── stages/
│   ├── colmap/status.json
│   ├── alignment/status.json
│   ├── fastgs/status.json
│   └── export/status.json
└── events.jsonl
```

每个阶段的 `status.json` 使用统一格式：

```json
{
  "version": 1,
  "job_id": "example-job",
  "stage": "colmap",
  "status": "completed_with_warnings",
  "started_at": "2026-07-20T10:00:00+00:00",
  "finished_at": "2026-07-20T10:12:00+00:00",
  "error_code": null,
  "message": "Registered 98 of 120 input images.",
  "input": {"image_dir": "input"},
  "output": {"colmap_dir": "colmap_raw"},
  "metrics": {
    "input_image_count": 120,
    "registered_image_count": 98,
    "registration_ratio": 0.8166666667
  },
  "warnings": ["22 images were not registered by COLMAP."]
}
```

失败时必须满足：`status == "failed"`、`error_code` 非空、`message` 说明原因、阶段返回非零退出码；编排器看到失败后不得调用后续脚本。

## 数据契约

### IMU manifest

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

`image` 必须和 `input/` 文件名完全匹配。`acceleration_type` 为 `gravity` 时直接使用；为 `specific_force` 时先取反。只保留有限、非零且模长在 `[0.5, 20.0]` 的向量。时间戳用于 `poses.json` 关联和诊断，不参与姿态匹配。

### poses.json

```json
{
  "version": 1,
  "coordinate_system": "gravity_aligned_world",
  "pose_type": "camera_to_world",
  "input_image_count": 120,
  "registered_image_count": 98,
  "registration_ratio": 0.8166666667,
  "poses": [
    {
      "image": "frame_000000.jpg",
      "timestamp_ms": 0,
      "matrix": [
        [1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0, 2.0],
        [0.0, 0.0, 1.0, 3.0],
        [0.0, 0.0, 0.0, 1.0]
      ]
    }
  ],
  "unregistered_images": ["frame_000098.jpg", "frame_000099.jpg"]
}
```

`poses` 按输入图片文件名的自然排序输出。`poses.txt` 按完全相同的顺序输出每个 4x4 C2W 矩阵的 16 个数；它不包含未注册图片，因此不能脱离 `poses.json` 推断图片对应关系。

### anchor.json

```json
{
  "version": 1,
  "method": "robust_ray_intersection",
  "coordinate_system": "gravity_aligned_world",
  "position": {"x": 1.2, "y": 0.4, "z": -2.1}
}
```

### result.json

`result.json` 汇总任务状态、阶段状态、产物路径、哈希、注册统计、坐标系、对齐元数据和锚点方法。它不是阶段间的输入，不允许被某一阶段作为成功判断的唯一依据。

## 阶段状态与停止策略

流程只允许在以下状态进入下一阶段：

```text
completed
completed_with_warnings
```

以下状态立即停止：

```text
failed
cancelled
```

具体规则：

| 阶段 | 可继续条件 | 必须停止条件 |
|---|---|---|
| COLMAP | 有完整模型，且注册率 `>= 0.8` | 无有效模型，关键文件缺失，或注册率 `< 0.8` |
| 重力对齐 | 有至少一个有效匹配 IMU，输出新模型完整 | manifest 错误、没有有效匹配向量、输入模型损坏、输出写入失败 |
| FastGS | 训练进程成功退出，最终 PLY 非空且可解析 | 训练退出非零、超时、最终 PLY 缺失/空文件/不可解析 |
| 导出 | poses、PLY、anchor、result 全部成功写出且互相一致 | 任一必需产物缺失、pose 数量和图片映射不一致、锚点不可计算 |

重力对齐阶段在默认严格模式下失败即停。只有显式开启 `--allow-alignment-fallback` 时，才执行：复制或硬链接 `colmap_raw` 为 FastGS 输入目录，写入 `method: "colmap_world"`、`fallback: true`、`fallback_reason`，并将该阶段状态设为 `completed_with_warnings`。

## 文件职责总览

- `scripts/colmap_model_io.py`：COLMAP cameras/images/points3D 模型文件的二进制读写和完整性校验，不负责运行命令。
- `scripts/pipeline_stage.py`：流水线阶段状态、事件、原子 JSON 写入、命令执行和错误码定义，不包含具体阶段逻辑。
- `scripts/run_colmap.py`：只运行图片到 `colmap_raw/` 的 COLMAP 流程并计算注册统计。
- `scripts/align_colmap.py`：只读取 `colmap_raw/` 和 IMU，生成新的 `colmap_gravity_aligned/`。
- `scripts/run_fastgs.py`：只把已完成 undistortion 的指定 COLMAP 场景直接交给 FastGS 训练，生成 `fastgs_model/`；不重复运行 `convert.py` 或 COLMAP。
- `scripts/anchor_calculator.py`：只提供锚点数学和 PLY 包围盒读取等纯函数。
- `scripts/export_outputs.py`：从对齐后的 COLMAP 位姿和 FastGS PLY 写出最终输出。
- `scripts/run_pipeline.py`：只按顺序调用四个阶段，检查返回码和 `status.json`，阶段失败后停止。
- `scripts/tests/test_*.py`：每个模块的单元测试、格式测试、合成端到端测试。

---

### Task 1: 建立阶段公共状态和 COLMAP 模型 I/O

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/pipeline_stage.py`
- Create: `/home/liangjiahua/FastGS/scripts/colmap_model_io.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_pipeline_stage.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_colmap_model_io.py`

**Interfaces:**
- `write_stage_status(path: Path, payload: dict) -> None`
- `read_stage_status(path: Path) -> dict`
- `run_stage_command(command: list[str], cwd: Path, stdout_path: Path, stderr_path: Path, timeout_seconds: int) -> int`
- `read_cameras_binary(path: Path) -> dict[int, CameraRecord]`
- `read_images_binary(path: Path) -> dict[int, ImageRecord]`
- `read_points3d_binary(path: Path) -> dict[int, Point3DRecord]`
- `write_images_binary(path: Path, images: dict[int, ImageRecord]) -> None`
- `write_points3d_binary(path: Path, points: dict[int, Point3DRecord]) -> None`
- `validate_colmap_model(model_dir: Path) -> ModelMetrics`

- [ ] **Step 1: Write failing tests for atomic stage status.**

Test that status JSON is valid UTF-8, parent directories are created, the file is atomically replaceable, and `read_stage_status` rejects a missing `status` or unsupported status value.

- [ ] **Step 2: Write failing tests for COLMAP binary round trips.**

Create a two-camera, two-image, three-point synthetic model, write it with the new writer, read it back, and assert IDs, qvec/tvec, camera IDs, 3D coordinates, colors, reprojection errors, tracks, property counts, and registered image count are unchanged.

- [ ] **Step 3: Implement the common status and command helpers.**

Use a same-directory temporary file and `os.replace` for JSON. `run_stage_command` must append stdout/stderr, enforce timeout, return the process exit code, and raise a typed timeout error only after killing and reaping the child process.

- [ ] **Step 4: Implement the COLMAP binary reader/writer.**

Reuse the binary layout already used by `scene/colmap_loader.py`: cameras use the COLMAP camera record layout, images preserve the null-terminated UTF-8 name and all 2D observations, and points preserve RGB, error, and tracks. Writers must preserve IDs and use little-endian encoding.

- [ ] **Step 5: Run focused tests.**

Run:

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests/test_pipeline_stage.py scripts/tests/test_colmap_model_io.py -q
```

Expected: all tests pass. If `pytest` is unavailable, run the same fixture through the FastGS interpreter as a standalone Python script and record the exact missing dependency.

---

### Task 2: Implement the independent COLMAP stage

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/run_colmap.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_run_colmap.py`

**Interfaces:**
- `count_input_images(input_dir: Path) -> list[Path]`
- `inspect_colmap_registration(model_dir: Path, input_image_names: list[str]) -> RegistrationMetrics`
- `run_colmap_stage(args: argparse.Namespace) -> int`

- [ ] **Step 1: Write failing tests for registration statistics.**

Use a synthetic model registering 8 of 10 input names. Assert `registered_image_count == 8`, `input_image_count == 10`, `registration_ratio == 0.8`, and the two missing names are listed in sorted order. Add a 7-of-10 test that returns `failed` with `error_code: "LOW_REGISTRATION_RATIO"`.

- [ ] **Step 2: Write failing tests for output validation and command construction.**

Patch `run_stage_command` and assert the stage passes `input/` as the source, writes into `colmap_raw/`, uses the configured COLMAP executable, and does not read `imu_manifest.json`. Add tests for missing `cameras.bin`, `images.bin`, and `points3D.bin`.

- [ ] **Step 3: Implement the COLMAP stage.**

The script must create the output directory, call the existing FastGS conversion/COLMAP path with the configured GPU and sequential matching options, inspect the largest valid sparse model, copy/link the input image directory into `colmap_raw/images`, and write `stages/colmap/status.json`.

The success criterion is both a complete model and `registered / input >= 0.8`. A successful 80% boundary result is `completed_with_warnings`; a result above 80% with no missing images is `completed`.

- [ ] **Step 4: Run focused tests.**

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests/test_run_colmap.py -q
```

Expected: all registration threshold, missing output, command, and warning tests pass.

---

### Task 3: Implement gravity alignment into a new COLMAP directory

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/align_colmap.py`
- Modify: `/home/liangjiahua/FastGS/scripts/gravity_alignment.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_align_colmap.py`

**Interfaces:**
- `estimate_gravity_from_manifest(manifest_path: Path, images: dict[int, ImageRecord]) -> GravityEstimate`
- `align_colmap_model(input_dir: Path, manifest_path: Path, output_dir: Path) -> AlignmentMetadata`
- `run_alignment_stage(args: argparse.Namespace) -> int`
- Existing manifest fields remain `version`, `acceleration_frame`, `acceleration_type`, `frames[].image`, `frames[].timestamp_ms`, `frames[].acceleration`.

- [ ] **Step 1: Write failing tests for one-sample and multi-sample alignment.**

Create a synthetic COLMAP model with one registered image and one gravity vector. Assert alignment succeeds, the output is a new directory, the point coordinate and camera center are rotated, and the target gravity is `[0, 1, 0]`. Add a multi-image fixture asserting all matched vectors are transformed and the residual is recorded.

- [ ] **Step 2: Write failing tests for model preservation.**

Assert that `cameras.bin`, image names, image dimensions, 2D observations, point IDs, RGB, reprojection errors, tracks, and registered image count are unchanged. Assert only `images.bin` extrinsics and `points3D.bin` XYZ coordinates change. Assert `colmap_raw` bytes remain unchanged.

- [ ] **Step 3: Write failing tests for strict failure and explicit fallback.**

Cover missing manifest, invalid JSON, no matching valid acceleration, malformed input model, and output write failure. Default mode must return nonzero and write `status: "failed"`. With `allow_fallback=True`, the stage must create the FastGS input directory from the raw model, write `coordinate_system: "colmap_world"`, set `fallback: true`, and return `completed_with_warnings`.

- [ ] **Step 4: Implement the gravity and model transform.**

For each matched registered image, normalize the camera-frame acceleration; negate it for `specific_force`; transform it using the camera-to-world rotation derived from COLMAP qvec/tvec. With one valid sample, accept the estimate. With multiple samples, compute a normalized robust direction and record angular residuals, but do not introduce a minimum sample count. Build the minimum-angle proper rotation satisfying `R_align @ gravity_colmap == [0, 1, 0]`.

Write the transformed `images.bin` and `points3D.bin` to a temporary output directory, copy or hard-link unchanged files, atomically publish the completed `colmap_gravity_aligned` directory, and write `alignment_meta.json` only after all model files validate.

- [ ] **Step 5: Run focused tests.**

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests/test_align_colmap.py scripts/tests/test_gravity_alignment.py -q
```

Expected: one-sample alignment, multi-sample metadata, model preservation, raw-directory immutability, strict failure, and explicit fallback tests pass.

---

### Task 4: Make FastGS training an independent stage

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/run_fastgs.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_run_fastgs.py`

**Interfaces:**
- `build_fastgs_commands(scene_dir: Path, model_dir: Path, fastgs_dir: Path, iterations: int, ...) -> list[list[str]]`
- `validate_fastgs_scene(scene_dir: Path) -> None`
- `find_trained_ply(model_dir: Path, iterations: int) -> Path`
- `run_fastgs_stage(args: argparse.Namespace) -> int`

- [ ] **Step 1: Write failing tests for scene and output validation.**

Assert that a scene with `images/` and `sparse/0/{cameras.bin,images.bin,points3D.bin}` is accepted, a missing aligned model is rejected, and the stage never substitutes `colmap_raw` implicitly.

- [ ] **Step 2: Write failing tests for command construction.**

Patch process execution and assert `convert.py` and `train.py` both receive the selected `colmap_gravity_aligned` scene and the requested model directory and iteration count.

- [ ] **Step 3: Implement the independent FastGS runner.**

Use the already undistorted `colmap_gravity_aligned/` scene directly with FastGS `train.py`; do not call `convert.py` again because Task 2's COLMAP output already contains `images/` and `sparse/0/`. Validate the final PLY using `plyfile.PlyData.read`, require a vertex element with `x`, `y`, and `z`, write stage status, and return nonzero for timeout, process failure, missing PLY, empty PLY, or malformed PLY.

- [ ] **Step 4: Run focused tests.**

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests/test_run_fastgs.py -q
```

Expected: scene validation, aligned-scene command routing, PLY validation, and failure status tests pass.

---

### Task 5: Extract anchor math and implement final exports

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/anchor_calculator.py`
- Create: `/home/liangjiahua/FastGS/scripts/export_outputs.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_anchor_calculator.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_export_outputs.py`

**Interfaces:**
- `calculate_anchor(poses: list[np.ndarray], point_cloud_center: Optional[np.ndarray]) -> tuple[str, np.ndarray]`
- `point_cloud_bbox_center(ply_path: Path) -> np.ndarray`
- `write_poses_json(path: Path, poses: list[PoseRecord], input_image_count: int, unregistered_images: list[str], coordinate_system: str) -> None`
- `write_poses_txt(path: Path, poses: list[PoseRecord]) -> None`
- `write_anchor_json(path: Path, method: str, position: np.ndarray, coordinate_system: str) -> None`
- `run_export_stage(args: argparse.Namespace) -> int`

- [ ] **Step 1: Write failing pure anchor tests.**

Test the priority order: robust ray intersection first, PLY bounding-box center second, camera-center centroid third. Test rejection when there are no usable poses and verify all returned coordinates are finite.

- [ ] **Step 2: Write failing JSON export tests.**

Create registered and unregistered images, transformed C2W matrices, timestamps, and a synthetic Gaussian PLY. Assert `poses.json` contains only registered images, preserves input order, includes `unregistered_images`, records counts and ratio, and sets `pose_type: "camera_to_world"`. Assert `poses.txt` has the same registered order and 16 values per row.

- [ ] **Step 3: Implement `anchor_calculator.py`.**

Move the existing robust ray intersection, PLY bounding-box center, and camera centroid logic into pure functions. Keep the exact fallback order and reject an empty pose list with the stable error code `NO_REGISTERED_POSES`.

- [ ] **Step 4: Implement `export_outputs.py`.**

Read final COLMAP `images.bin` for C2W poses, read the optional IMU timestamps by image name, read `alignment_meta.json` for the coordinate-system label, copy the trained PLY to `outputs/point_cloud.ply`, call `anchor_calculator.py`, then atomically write `poses.json`, `poses.txt`, `anchor.json`, and `result.json`. Validate that all generated artifacts are readable before writing `status: "completed"`.

- [ ] **Step 5: Run focused tests.**

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests/test_anchor_calculator.py scripts/tests/test_export_outputs.py -q
```

Expected: anchor priority, JSON schema, pose ordering, unregistered image reporting, PLY copy, and export failure tests pass.

---

### Task 6: Add the pipeline orchestrator with fail-fast behavior

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/run_pipeline.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_run_pipeline.py`

**Interfaces:**
- `run_pipeline(args: argparse.Namespace) -> int`
- CLI options: `--job-dir`, `--fastgs-dir`, `--iterations`, `--timeout-seconds`, `--allow-alignment-fallback`, `--resume-from`.

- [ ] **Step 1: Write failing orchestration tests.**

Patch the four stage entry points and record calls. Assert the normal order is `colmap -> alignment -> fastgs -> export`. Assert a COLMAP failure makes exactly one call and does not call alignment. Repeat for alignment and FastGS failures. Assert `completed_with_warnings` continues.

- [ ] **Step 2: Write a failing resume test.**

Create valid prior status files and assert `--resume-from alignment` skips COLMAP, while `--resume-from export` skips the first three stages only when all required prior outputs validate.

- [ ] **Step 3: Implement the thin orchestrator.**

Invoke each script as a subprocess using the same Python interpreter and explicit arguments. After each return, read its `status.json`; continue only for `completed` or `completed_with_warnings`. On failure, write root `result.json` with `stage` and the stage's `error_code`/`message`, append an `events.jsonl` failure event, and return nonzero. Do not catch a failure and silently substitute another input.

- [ ] **Step 4: Run focused tests.**

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests/test_run_pipeline.py -q
```

Expected: ordering, fail-fast, warning continuation, resume validation, result propagation, and nonzero return tests pass.

---

### Task 7: Convert the existing reconstruction entry point into a compatibility wrapper

**Files:**
- Modify: `/home/liangjiahua/FastGS/scripts/reconstruct_images.py`
- Modify: `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images_anchor.py`
- Modify: `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images_poses.py`
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images_compat.py`

**Interfaces:**
- Keep the existing CLI arguments accepted by callers.
- Delegate new executions to `run_pipeline.py` or expose a compatibility mode that maps the old flat job layout to the new stage directories.
- Remove post-training gravity mutation from this wrapper; alignment must happen before FastGS.

- [ ] **Step 1: Write failing compatibility tests.**

Assert old arguments still parse, new jobs invoke the four-stage pipeline, and no code path calls `apply_gravity_alignment` after the Gaussian PLY is generated.

- [ ] **Step 2: Implement the wrapper migration.**

Keep old output paths only where existing external callers require them; write canonical artifacts under `outputs/` and provide a deterministic copy or symlink for the old path. Preserve current logging fields that are not contradicted by the new result schema.

- [ ] **Step 3: Run compatibility tests.**

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests/test_reconstruct_images_compat.py scripts/tests/test_reconstruct_images_anchor.py scripts/tests/test_reconstruct_images_poses.py -q
```

Expected: old argument parsing and output compatibility pass, while the new ordering remains COLMAP -> alignment -> FastGS -> export.

---

### Task 8: Add synthetic end-to-end verification and backend runbook

**Files:**
- Create: `/home/liangjiahua/FastGS/scripts/tests/test_pipeline_e2e.py`
- Create: `/home/liangjiahua/FastGS/docs/fastgs-pipeline-backend-runbook-zh.md`
- Modify: `/home/liangjiahua/FastGS/docs/superpowers/specs/2026-07-18-gravity-aligned-gaussian-design.md` only if the final JSON contract differs from the existing design

- [ ] **Step 1: Write the synthetic end-to-end fixture.**

Use 10 input image names, a synthetic COLMAP model registering 8 images, one or more camera-frame gravity vectors, a small FastGS-compatible Gaussian PLY, and mocked external commands. Assert the pipeline produces `colmap_raw`, `colmap_gravity_aligned`, `fastgs_model`, `outputs/poses.json`, `outputs/poses.txt`, `outputs/anchor.json`, and `outputs/result.json`; assert registered ratio is exactly 0.8 and unregistered names are reported.

- [ ] **Step 2: Add negative end-to-end cases.**

Cover 7/10 registration, missing manifest in strict mode, no matching valid IMU, malformed PLY, and FastGS nonzero exit. Assert the first failed stage is recorded and later stage marker files are absent.

- [ ] **Step 3: Write the backend runbook.**

Document: create job directory, upload images and manifest, create a ready marker after upload, invoke `run_pipeline.py`, poll `stages/*/status.json` or `events.jsonl`, stop on `failed`, download `outputs/*`, and use SSH keys instead of embedding passwords. Include exact example commands and the JSON error fields the backend should expose to the user.

- [ ] **Step 4: Run the complete verification suite.**

```bash
cd /home/liangjiahua/FastGS
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m pytest scripts/tests -q
/home/liangjiahua/miniconda3/envs/fastgs/bin/python -m compileall -q scripts
git diff --check
```

Expected: all available tests pass, compilation succeeds, and `git diff --check` produces no output. A real GPU run is a separate acceptance test and must record COLMAP registered count, alignment residual, FastGS iteration, final PLY vertex count, pose count, and anchor method.

## Backend 调用流程

后端将 200 机视为远程任务执行器。每个任务使用唯一目录：

```text
/home/liangjiahua/FastGS/jobs/<job_id>/
```

上传完成后才创建 `job.ready`，然后执行：

```bash
python /home/liangjiahua/FastGS/scripts/run_pipeline.py \
  --job-dir /home/liangjiahua/FastGS/jobs/<job_id> \
  --fastgs-dir /home/liangjiahua/FastGS \
  --iterations 30000 \
  --timeout-seconds 1800
```

默认不允许对齐失败回退。只有产品明确选择“允许无重力坐标继续”时才增加：

```bash
--allow-alignment-fallback
```

后端读取 `result.json`：

- `status == "completed"`：正常返回所有输出。
- `status == "completed_with_warnings"`：返回输出并展示警告，例如未注册图片或使用 COLMAP 回退坐标系。
- `status == "failed"`：停止下载后续阶段产物，向用户展示 `stage`、`error_code`、`message`，并根据 `can_retry` 决定是否允许重试。

## 实施后的验收标准

1. 10 张输入图片注册 8 张时流程可以继续，`poses.json` 有 8 条 pose，2 张图片出现在 `unregistered_images`。
2. 注册 7 张时 COLMAP 阶段失败，重力对齐、FastGS、导出均不启动。
3. 重力对齐成功时，`colmap_raw` 不变，新目录包含完整模型，FastGS 使用新目录训练。
4. 一个有效匹配 IMU 向量即可完成重力方向计算；零个有效匹配向量时严格模式失败。
5. 重力对齐失败且未开启回退时流程停止；开启显式回退时才使用原始 COLMAP，并记录警告。
6. FastGS 失败时不生成成功的最终结果。
7. `poses.json`、`poses.txt`、`anchor.json` 和 Gaussian PLY 使用一致坐标系。
8. 锚点计算逻辑只存在于 `anchor_calculator.py`，导出脚本只负责调用它和写文件。
9. 四个阶段可以独立运行和重试，编排器不会重复执行已验证成功的阶段。
10. 不提交任何代码，除非用户另行明确授权。
