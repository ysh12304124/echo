# FastGS End-to-End Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax to track progress.

**Goal:** Complete the existing `complete`-triggered video + IMU -> COLMAP -> FastGS -> callback -> phone rendering workflow on 153.

**Architecture:** Keep backend as the database and blob owner. Compute runs reconstruction asynchronously in a worker thread, creates the IMU manifest before invoking the existing staged FastGS pipeline, copies validated artifacts to the shared blob store, and calls the existing backend callback. Phone only sends `scene_type` and consumes the existing processing/completed model fields.

**Tech Stack:** Python 3.10, FastAPI, Pydantic settings, SQLite/BlobStore, COLMAP, FastGS CUDA environment, Kotlin/Compose.

## Global Constraints

- Use the existing `POST /api/v1/ingest/sessions/{session_id}/complete` trigger.
- Do not reset or overwrite unrelated uncommitted changes in the root project.
- Keep reconstruction jobs isolated by `job_id`.
- Accept missing/invalid IMU only through explicit `colmap_world` fallback and record the method.
- Validate PLY, poses.txt and anchor.json before callback.

---

### Task 1: IMU Manifest Builder

**Files:**
- Create: `compute/app/analyze/imu_manifest.py`
- Test: `compute/tests/test_imu_manifest.py`

**Interfaces:**
- `build_imu_manifest(imu_path: Path | None, frame_dir: Path, fps: float, start_timestamp_ms: int, output_path: Path, acceleration_type: str = "gravity") -> dict`
- Manifest format remains FastGS v1: `version`, `acceleration_frame`, `acceleration_type`, `frames[]`.

- [ ] Write tests for nearest timestamp matching, malformed-line filtering, and missing IMU fallback.
- [ ] Run the focused tests and confirm failure because the module is absent.
- [ ] Implement finite numeric parsing, sorted JSONL samples, nearest-sample selection, frame timestamp derivation, and atomic JSON output.
- [ ] Run focused tests and confirm all pass.

### Task 2: Compute Space Worker

**Files:**
- Modify: `compute/app/analyze/space_memory.py`
- Modify: `compute/app/settings.py`
- Modify: `compute/.env.example`
- Test: `compute/tests/test_space_memory.py`

**Interfaces:**
- `inputs` gains `recording_started_at_ms` and optional `imu_acceleration_type`.
- `_extract_frames` returns the count and the worker calls `build_imu_manifest` before `_run_fastgs`.

- [ ] Write tests for command construction inputs, manifest creation call, and output validation/copy fields.
- [ ] Run focused tests and confirm failure on the new behavior.
- [ ] Add explicit FastGS settings for project path, Python/Conda, COLMAP, iterations, FPS, timeout, work root, and blob root; integrate manifest generation and preserve fallback behavior.
- [ ] Run compute unit tests and Python compilation.

### Task 3: Backend Task Contract

**Files:**
- Modify: `backend/app/services/compute_client.py`
- Modify: `backend/app/services/ingest_pipeline.py`
- Test: `backend/tests/test_async_space_reconstruction.py`

- [ ] Add a failing assertion that the space payload includes the recording start timestamp and scene type.
- [ ] Run the focused backend tests and observe the missing field failure.
- [ ] Pass `recording_started_at_ms` from `IngestSession.created_at`, retain existing async state transition, and keep callback fields for all three artifacts.
- [ ] Run the focused backend tests.

### Task 4: Phone Request Compatibility

**Files:**
- Modify: `phone/app/src/main/java/com/echo/phone/data/EchoRepository.kt`
- Test/verify: `phone` Gradle Kotlin compilation.

- [ ] Add the failing compile scenario for `RecordingController` calling `sceneType`.
- [ ] Add `sceneType: SpaceSceneType?` to `startSession` and serialize `scene_type` in `CreateSessionRequest`.
- [ ] Run `./gradlew compileDebugKotlin` or the available project equivalent.

### Task 5: huiyi Synthetic-IMU Acceptance

**Files:**
- Create: `compute/fastgs/scripts/generate_synthetic_imu_manifest.py`
- Test: `compute/fastgs/scripts/tests/test_generate_synthetic_imu_manifest.py`
- Modify: `docs/compute.md`

- [ ] Write tests for generating camera-frame gravity samples from COLMAP camera records.
- [ ] Run the focused test and confirm failure.
- [ ] Implement the test-only helper using existing `colmap_model_io`, with no production service dependency.
- [ ] Run COLMAP on `datasets/huiyi`, generate synthetic manifest, resume from alignment, and run FastGS/export at a bounded verification iteration count.
- [ ] Verify PLY/poses/anchor non-empty, result metadata, and SHA256 values.

### Task 6: Service E2E Verification

**Files:**
- No production files unless verification exposes a defect.

- [ ] Start compute on 8100 with the existing backend on 8000; verify both health endpoints.
- [ ] Submit a small synthetic space job through `/analyze/space` using a generated test video or the huiyi job directory.
- [ ] Verify callback updates `SpaceMemory` and media URLs are served by backend.
- [ ] Remove temporary SSH authorization and report exact job/result paths and residual failures.
