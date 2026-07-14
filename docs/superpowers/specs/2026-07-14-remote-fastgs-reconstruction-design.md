# Remote FastGS Reconstruction Design

**Date:** 2026-07-14

## Goal

When a user finishes spatial capture, asynchronously send all stored JPEG frames from the Echo backend on host 130 to host 200, reconstruct a Gaussian point cloud with COLMAP and FastGS, return the final PLY file to host 130, and expose it to the phone for rendering.

## Scope

This change covers the end-to-end MVP reconstruction path:

1. A new host-200 script accepts a directory of images only.
2. The script runs COLMAP conversion and FastGS training.
3. Host 130 starts reconstruction after a spatial session is completed.
4. The backend uploads the session frames, waits for reconstruction, downloads the PLY, and stores it in the local blob store.
5. The existing space API exposes the PLY URL and the phone consumes it through the existing model viewer.

The MVP does not use IMU data to initialize COLMAP, does not block reconstruction on loop detection, and does not add a queue service or distributed job database.

## Architecture

### Host 200: image reconstruction worker

Create `FastGS/scripts/reconstruct_images.py`. The script receives a job directory containing `input/` JPEG files and writes the trained model beneath that directory.

The script will:

1. Validate that `input/` exists and contains at least three `.jpg`/`.jpeg` files.
2. Run `convert.py --source_path <job_dir> --sequential --camera OPENCV` so COLMAP estimates poses and creates `sparse/0`.
3. Run `train.py -s <job_dir> -m <job_dir>/model --images images --iterations <N> --save_iterations <N> --checkpoint_iterations <N>` inside the `fastgs` conda environment.
4. Verify `<job_dir>/model/point_cloud/iteration_<N>/point_cloud.ply` exists and is non-empty.
5. Print a single machine-readable success record containing the iteration and PLY path. Errors are logged and return a non-zero exit code.

The worker will not modify the source dataset or the FastGS checkout. Each invocation uses a unique job directory so concurrent jobs do not share COLMAP databases or model outputs.

### Host 130: remote executor

Create a backend service responsible for one reconstruction job. It will:

1. Read the session frame paths from the existing repository.
2. Create a unique local staging directory and copy the session JPEGs into `input/` using stable sequential filenames.
3. Create a unique remote job directory under a configured FastGS work root.
4. Transfer the staging `input/` directory to host 200 over SSH/SFTP.
5. Invoke the worker with the configured FastGS project path, conda environment, and iteration count.
6. Download the validated PLY to the local staging directory.
7. Save it through the existing `BlobStore` at `spaces/{space_id}/models/point_cloud.ply`.
8. Return the generated media URL and model format.
9. Remove local and remote temporary files in a `finally` block, while retaining structured log context for failures.

SSH settings are environment variables and have no code defaults for passwords:

```text
FASTGS_SSH_HOST
FASTGS_SSH_PORT=22
FASTGS_SSH_USER
FASTGS_SSH_PASSWORD
FASTGS_REMOTE_PROJECT=/home/liangjiahua/FastGS
FASTGS_REMOTE_ENV=fastgs
FASTGS_REMOTE_WORK_ROOT=/tmp/echo-fastgs
FASTGS_TRAIN_ITERATIONS=30000
FASTGS_TRAIN_TIMEOUT_SECONDS
```

The executor will use a Python SSH/SFTP client so the password is not interpolated into shell commands. The password is read only at runtime from the environment and is never logged.

### Session lifecycle

For a space session, `complete_session` will create a `SpaceMemory` in `processing` state and return it without waiting for FastGS. A background task then runs the remote executor.

```text
POST /ingest/sessions/{id}/complete
  -> create SpaceMemory(status=processing)
  -> return memory summary
  -> background reconstruction
       -> upload frames to 200
       -> COLMAP conversion
       -> FastGS training
       -> download PLY to 130
       -> save model_url
       -> status=completed
```

If any step fails, the space memory is updated to `failed`, the model URL remains empty, and the failure is logged with the session and space identifiers. Loop detection is still calculated and stored as metadata, but its result does not control whether reconstruction starts.

The implementation must avoid starting duplicate jobs when the same session completion request is retried. The session-to-memory relation and an in-process job guard will be used for this MVP. A later version can replace the guard with a durable task queue.

## API and client behavior

The existing space response fields remain the client contract:

- `status=processing`: show reconstruction in progress and do not attempt to load the model.
- `status=completed` and `model_url` present: load the PLY URL with the existing PLY viewer.
- `status=failed`: show that reconstruction failed and allow the user to retry the session.
- `model_format=ply`: identify the renderer format.

No new phone transport protocol is required for this MVP. The phone polls or refreshes the existing space detail endpoint until the status changes, then uses the already implemented absolute media URL handling.

## Failure handling

- Fewer than three frames: fail before remote transfer with a clear validation error.
- Missing or invalid JPEG: reject the job and mark the space failed.
- SSH/SFTP connection failure: mark failed and include host/user/job context without credentials.
- COLMAP failure: preserve the worker exit code and stderr in logs.
- FastGS timeout: terminate the worker, mark failed, and clean the remote job directory.
- Missing or zero-byte PLY: treat as failure; do not publish a model URL.
- Blob save failure: mark failed; do not report completion.

## Testing

Tests will use fake SSH and blob boundaries rather than a real GPU or network:

- Worker command construction, input validation, output validation, and non-zero failure behavior.
- Remote executor uploads the expected sequential images, invokes the worker, downloads the PLY, and cleans temporary paths.
- Remote executor never includes the password in command arguments or logs.
- Space completion returns `processing` immediately and schedules one job.
- Successful background completion stores `model_url`, `model_format=ply`, and `status=completed`.
- Failed background completion stores `status=failed` and leaves `model_url` empty.
- Existing API response and phone model URL mapping remain compatible.

## Non-goals

- No automatic stopping of image capture.
- No IMU-based pose injection into COLMAP.
- No loop-closure requirement for reconstruction.
- No conversion to GLB or mobile-specific Gaussian compression.
- No production-grade durable job queue, retry policy, or multi-worker scheduler.
