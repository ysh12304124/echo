# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastGS is a general acceleration framework for 3D Gaussian Splatting training (CVPR 2026). It achieves 3.32× faster training than DashGaussian on Mip-NeRF 360 and 15.45× acceleration over vanilla 3DGS on Deep Blending. The core innovation is multi-view consistent densification: sampling multiple cameras during densification to compute per-Gaussian importance scores that guide split/clone/prune decisions.

This is based on the original 3D Gaussian Splatting codebase from INRIA GRAPHDECO.

## Environment Setup

```bash
conda env create -f environment.yml
conda activate fastgs
```

The environment uses Python 3.7.13, PyTorch 1.12.1, CUDA 11.6. Three custom CUDA extensions are installed from `submodules/` via pip.

## Commands

### Training
```bash
# Single scene (minimal)
python train.py -s ./datasets/<dataset>/<scene> -m output/<scene>

# With evaluation at iteration 30000 (standard benchmark)
python train.py -s ./datasets/mipnerf360/bicycle -i images --eval \
    --densification_interval 500 --optimizer_type default \
    --test_iterations 30000 --grad_abs_thresh 0.0012
```

Key training flags (see `arguments/__init__.py` for full list):
- `--densification_interval 500` — how often to run multi-view densification
- `--grad_abs_thresh` — gradient threshold for densification candidates
- `--dense` — density threshold for importance score filtering
- `--loss_thresh` — L1 loss threshold for metric map binarization
- `--highfeature_lr` — learning rate for DC color features (scene-tuned)
- `--mult` — tile count multiplier for compact box (0.5 default, 0.7 for Tanks/DB)
- `--optimizer_type default|sparse_adam` — optimizer choice

### Rendering & Evaluation
```bash
python render.py -m output/<scene> --skip_train          # render test views
python metrics.py -m output/<scene>                       # compute PSNR/SSIM/LPIPS
```

### Full Benchmark
```bash
bash train_base.sh   # train + render + metrics for all 13 benchmark scenes
bash train_big.sh    # higher quality variant
```

## Data Pipelines

### Pipeline 1: Custom RGBD Dataset → COLMAP → FastGS

Use `convert_custom_to_colmap.py` for datasets that have RGB + pose + depth + point per frame but are NOT in COLMAP format.

```bash
# Convert custom dataset to COLMAP format
python convert_custom_to_colmap.py \
    -s /path/to/custom_dataset \
    -o ./datasets/<scene> \
    --voxel_size 0.05    # voxel downsampling size in meters
```

**Input format expected:**
```
<source>/
├── rgb/frame_XXXXXX.jpg         # RGB images
├── poses/frame_XXXXXX.txt       # 4x4 camera-to-world (c2w) matrix
├── depth/frame_XXXXXX.png       # uint16 depth (or .npy float32)
├── point/frame_XXXXXX.npy       # (H,W,3) float32 world xyz per pixel
└── intrinsics.yaml              # fx, fy, cx, cy, image_width, image_height
```

**Output:** COLMAP-format dataset with `images/`, `sparse/0/cameras.bin`, `sparse/0/images.bin`, `sparse/0/points3D.bin`.

Key details:
- Pose must be c2w (camera-to-world) 4×4 matrix in OpenCV convention (Z forward)
- Script inverts c2w→w2c and converts rotation to quaternion for COLMAP
- Point clouds from all frames are merged and voxel-downsampled
- RGB colors are sampled from corresponding images
- Use `--voxel_size 0.05` for ~500K-700K points, `0.02` for ~2.5M (but 2.5M may crash the rasterizer backward pass)

### Pipeline 2: Video → COLMAP SfM → FastGS

For raw video files (e.g. phone recordings) with no poses at all.

```bash
# Step 1: Extract frames from video (3fps from 30fps video)
mkdir -p datasets/<scene>/input
python3 -c "
import cv2, os
cap = cv2.VideoCapture('<video.mp4>')
interval = 10  # every 10th frame
count, saved = 0, 0
while cap.isOpened():
    ret, frame = cap.read()
    if not ret: break
    if count % interval == 0:
        cv2.imwrite(f'datasets/<scene>/input/frame_{saved:06d}.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        saved += 1
    count += 1
cap.release()
print(f'Extracted {saved} frames')
"

# Step 2: Run COLMAP (CPU mode — GPU mode crashes without display)
DS=datasets/<scene>
colmap feature_extractor --database_path $DS/distorted/database.db --image_path $DS/input \
    --ImageReader.single_camera 1 --ImageReader.camera_model OPENCV --SiftExtraction.use_gpu 0
colmap exhaustive_matcher --database_path $DS/distorted/database.db --SiftMatching.use_gpu 0
colmap mapper --database_path $DS/distorted/database.db --image_path $DS/input --output_path $DS/sparse
# Copy reconstruction to sparse/0
mkdir -p $DS/sparse/0 && cp $DS/sparse/0/* $DS/sparse/0/ 2>/dev/null || true
# Undistort images (outputs PINHOLE camera model + undistorted images)
colmap image_undistorter --image_path $DS/input --input_path $DS/sparse/0 --output_path $DS --output_type COLMAP
# IMPORTANT: undistorter writes to $DS/sparse/ but FastGS reads from $DS/sparse/0/
# Must copy the undistorted (PINHOLE) files over the originals:
cp $DS/sparse/cameras.bin $DS/sparse/0/cameras.bin
cp $DS/sparse/images.bin $DS/sparse/0/images.bin
cp $DS/sparse/points3D.bin $DS/sparse/0/points3D.bin

# Step 3: Train
python train.py -s ./datasets/<scene> -i images --eval \
    -m output/<scene> --densification_interval 500 --optimizer_type default \
    --test_iterations 30000 --grad_abs_thresh 0.0012

# Step 4: Render & evaluate
python render.py -m output/<scene> --skip_train
python metrics.py -m output/<scene>
```

## Architecture

### Core Pipeline
```
Dataset (COLMAP/NeRF) → Scene → GaussianModel → render_fastgs() → Loss → Backward → Densify/Prune
```

### Key Modules

- **`train.py`** — Main training loop. Handles the iterative cycle of camera sampling, rendering, loss computation (L1 + SSIM), densification (via `compute_gaussian_score_fastgs`), and optimization. Training runs 30K iterations by default.

- **`scene/gaussian_model.py`** — `GaussianModel` class managing all Gaussian attributes (positions, SH colors, opacity, scaling, rotation). Contains `densify_and_prune_fastgs()` and `final_prune_fastgs()` which implement the multi-view consistent split/clone/prune logic.

- **`utils/fast_utils.py`** — FastGS core algorithm. `compute_gaussian_score_fastgs()` samples 10 random cameras, renders from each, computes photometric loss and binary metric maps, then accumulates per-Gaussian importance and pruning scores. `sampling_cams()` randomly selects viewpoints.

- **`gaussian_renderer/__init__.py`** — `render_fastgs()` wraps the custom CUDA rasterizer (`diff_gaussian_rasterization_fastgs`). Supports a `metric_map` mode that returns per-Gaussian metric accumulation counts used during densification.

- **`scene/__init__.py`** — `Scene` class handles dataset loading (COLMAP format via `dataset_readers.py`), camera management, and point cloud initialization.

- **`arguments/__init__.py`** — `ModelParams`, `OptimizationParams`, `PipelineParams` define all CLI arguments. FastGS-specific params are in `OptimizationParams`.

- **`convert_custom_to_colmap.py`** — Converts custom RGBD datasets (with pre-existing poses and point clouds) to COLMAP binary format. Handles c2w→w2c conversion, quaternion rotation, point cloud merging and voxel downsampling.

### CUDA Submodules

Three custom CUDA extensions in `submodules/`, each with its own `setup.py`:
1. **`diff-gaussian-rasterization_fastgs`** — Modified differentiable Gaussian rasterizer. Extended to support `metric_map` input and `accum_metric_counts` output for multi-view scoring. Also supports `mult` parameter for tile count control. **Warning:** can crash with OOM in backward pass if initial point count is too large (>2M points).
2. **`simple-knn`** — K-nearest neighbors (used for initial point cloud distance computation).
3. **`fused-ssim`** — Fused differentiable SSIM (5-8× faster than standard implementations).

### Training Flow (Densification)

1. Every `densification_interval` (500) iterations between `densify_from_iter` (500) and `densify_until_iter` (15K):
   - Sample 10 random cameras via `sampling_cameras()`
   - `compute_gaussian_score_fastgs()` renders each viewpoint, computes photometric loss and metric maps
   - Accumulates `importance_score` (view count) and `pruning_score` (weighted loss)
   - `densify_and_prune_fastgs()` uses gradient thresholds + importance scores to decide split/clone/prune

2. After iteration 15K, every 3K iterations:
   - Multi-view pruning only via `final_prune_fastgs()` using `pruning_score`

### Datasets

Expected under `datasets/`:
- `mipnerf360/` — outdoor (bicycle, flowers, garden, stump, treehill) and indoor (room, counter, kitchen, bonsai) scenes
- `tanksandtemples/` — truck, train
- `db/` — Deep Blending (drjohnson, playroom)

Scene-specific hyperparameters are documented in `train_base.sh` and `train_big.sh`. Different scenes need different `grad_abs_thresh`, `dense`, `highfeature_lr`, and `mult` values for best results.

## Known Issues & Lessons Learned

### Data quality is the primary quality bottleneck
Training hyperparameters (iterations, learning rates, densification thresholds) have minimal impact if the input data is poor. The three factors that matter most:
1. **Image resolution**: 518×378 (low) → 23 dB PSNR; 960×540 (medium) → 31 dB PSNR
2. **Image compression**: JPEG quality matters. Use quality ≥95 for frame extraction. Low bpp (<1.0) destroys fine details.
3. **Pose/depth accuracy**: Inter-frame point cloud inconsistency >5cm creates conflicting training signals. COLMAP SfM poses are generally more accurate than sensor-provided poses.

### COLMAP quirks
- `dataset_readers.py` only accepts `PINHOLE` or `SIMPLE_PINHOLE` camera models. `OPENCV` causes an assertion error. Always run `colmap image_undistorter` after mapper, then copy the undistorted `sparse/` files to `sparse/0/`.
- COLMAP GPU mode (`--SiftExtraction.use_gpu 1`) crashes on headless servers. Use `--SiftExtraction.use_gpu 0` and `--SiftMatching.use_gpu 0`.
- The undistorter writes output to `$DS/sparse/` (not `sparse/0/`), so manual copy is needed.

### Rasterizer limitations
- Initial point count >2M can cause `RuntimeError: Function _RasterizeGaussiansBackward returned an invalid gradient` crash. Keep initial points under ~1M.
- Default `densify_until_iter=15000` is reasonable. Extending to 25K+ with dense initial points risks rasterizer overflow.

### Hyperparameter tuning has diminishing returns
On the lingbot_copy dataset, tuning `highfeature_lr`, `grad_abs_thresh`, `dense`, doubling iterations (30K→60K), and denser initial point clouds all produced the same ~23 dB PSNR. The data ceiling was the bottleneck, not training config.
