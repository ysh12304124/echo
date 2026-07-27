# Design: Custom Dataset → COLMAP Format → FastGS Training

## Goal

Convert a custom dataset (RGB + pose + depth + point) at `/home/liangjiahua/dgsg-orin/data/mydata/lingbot_copy` into COLMAP format, then run FastGS training to produce a Gaussian point cloud PLY file.

## Input Format

```
lingbot_copy/
├── rgb/frame_XXXXXX.jpg        # 300 images, 518×378, RGB
├── poses/frame_XXXXXX.txt      # 4×4 c2w matrix (camera-to-world)
├── depth/frame_XXXXXX.png      # uint16 depth, same resolution
├── point/frame_XXXXXX.npy      # (378, 518, 3) float32 world xyz per pixel
└── intrinsics.yaml             # fx≈365, fy≈365, cx=259, cy=189
```

## Output

- COLMAP-formatted directory at `datasets/lingbot/`
- Trained Gaussian model at `output/lingbot/point_cloud/iteration_30000/point_cloud.ply`

## Pipeline

### Step 1: Convert to COLMAP format (`convert_custom_to_colmap.py`)

Creates:
```
datasets/lingbot/
├── images/frame_XXXXXX.jpg
└── sparse/0/
    ├── cameras.bin    # PINHOLE model, fx, fy, cx, cy
    ├── images.bin     # per-image qvec + tvec (w2c), camera_id=1
    └── points3D.bin   # merged + voxel-downsampled point cloud
```

#### cameras.bin
- Single camera (id=1), PINHOLE model (model_id=1)
- Params: [fx, fy, cx, cy] from intrinsics.yaml
- width=518, height=378

#### images.bin
- For each frame: load c2w from poses/*.txt, invert to w2c
- Convert rotation matrix to quaternion via `rotmat2qvec`
- Extract tvec from w2c
- xys and point3D_ids are empty arrays (not needed for training)

#### points3D.bin
- Merge all 300 point clouds (~58M points total)
- Voxel downsample to ~500K points (voxel size ~0.02m, adjustable)
- Sample RGB colors from corresponding images
- Each point gets a dummy error=1.0, empty track

### Step 2: Run FastGS training

```bash
python train.py -s ./datasets/lingbot -i images --eval \
    --densification_interval 500 \
    --optimizer_type default \
    --test_iterations 30000 \
    --grad_abs_thresh 0.0012
```

### Step 3: Render and evaluate (optional)

```bash
python render.py -m output/lingbot --skip_train
python metrics.py -m output/lingbot
```

## Key Technical Details

- **Pose convention**: c2w is OpenCV-style (Z forward), same as COLMAP — no axis flip needed
- **Downsampling**: Voxel grid downsampling at ~0.02m resolution targets ~500K points
- **Binary format**: Uses COLMAP's binary format (not text) for compatibility with `read_extrinsics_binary` / `read_intrinsics_binary`
- **Coordinate frame**: points are already in world coordinates from the npy files

## Risks

- If rendering is all black/distorted, check c2w→w2c conversion and coordinate conventions
- 300 images means each image is sampled ~100 times in 30K iterations (sufficient)
- Initial point cloud quality depends on depth accuracy; FastGS densification will fill gaps
