#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

import os
import logging
import json
import time
from datetime import datetime, timezone
from argparse import ArgumentParser
import shutil
import yaml

# This Python script is based on the shell converter script provided in the MipNerF 360 repository.
parser = ArgumentParser("Colmap converter")
parser.add_argument("--no_gpu", action='store_true')
parser.add_argument("--matching_gpu", action='store_true',
                    help="Use GPU for feature matching while feature extraction stays on CPU.")
parser.add_argument("--colmap_new_api", action='store_true')
parser.add_argument("--mapper_use_gpu", action='store_true')
parser.add_argument("--max_num_features", type=int, default=None)
parser.add_argument("--max_num_matches", type=int, default=None)
parser.add_argument("--sequential_overlap", type=int, default=None)
parser.add_argument("--skip_matching", action='store_true')
parser.add_argument("--source_path", "-s", required=True, type=str)
parser.add_argument("--camera", default="OPENCV", type=str)
parser.add_argument("--sequential", action='store_true', help="Use sequential matcher (for ordered video frames)")
parser.add_argument("--intrinsics", default=None, type=str,
                    help="Path to intrinsics.yaml. If set, COLMAP uses these intrinsics and fixes them during BA.")
parser.add_argument("--colmap_executable", default="", type=str)
parser.add_argument("--resize", action="store_true")
parser.add_argument("--magick_executable", default="", type=str)
args = parser.parse_args()
colmap_command = '"{}"'.format(args.colmap_executable) if len(args.colmap_executable) > 0 else "colmap"
magick_command = '"{}"'.format(args.magick_executable) if len(args.magick_executable) > 0 else "magick"
feature_use_gpu = 0 if args.no_gpu else 1
matching_use_gpu = 1 if args.matching_gpu else feature_use_gpu
feature_gpu_option = "--FeatureExtraction.use_gpu" if args.colmap_new_api else "--SiftExtraction.use_gpu"
matching_gpu_option = "--FeatureMatching.use_gpu" if args.colmap_new_api else "--SiftMatching.use_gpu"
max_features_option = (" --SiftExtraction.max_num_features " + str(args.max_num_features)) if args.max_num_features else ""
max_matches_option = (" --SiftMatching.max_num_matches " + str(args.max_num_matches)) if args.max_num_matches else ""
sequential_overlap_option = (" --SequentialMatching.overlap " + str(args.sequential_overlap)) if args.sequential_overlap else ""
mapper_gpu_option = " --Mapper.ba_use_gpu 1" if args.mapper_use_gpu else ""
mapper_tolerance_option = " --Mapper.ba_global_function_tolerance=0.000001" if args.colmap_new_api else ""
stage_metrics = []


def select_largest_reconstruction(sparse_root):
    """COLMAP may emit multiple reconstructions; use the one with most images."""
    candidates = []
    for name in os.listdir(sparse_root):
        candidate = os.path.join(sparse_root, name)
        if not os.path.isdir(candidate):
            continue
        images_bin = os.path.join(candidate, "images.bin")
        images_txt = os.path.join(candidate, "images.txt")
        if os.path.exists(images_bin):
            candidates.append((os.path.getsize(images_bin), candidate))
        elif os.path.exists(images_txt):
            candidates.append((os.path.getsize(images_txt), candidate))
    if not candidates:
        raise RuntimeError(f"No COLMAP reconstruction found in {sparse_root}")
    return max(candidates)[1]


def write_stage_metrics():
    path = os.path.join(args.source_path, "colmap_metrics.json")
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stages": stage_metrics,
    }
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run_colmap_stage(name, command):
    started = time.monotonic()
    exit_code = os.system(command)
    stage_metrics.append({
        "stage": name,
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
    })
    write_stage_metrics()
    return exit_code

# Load custom intrinsics if provided
camera_params_str = ""
mapper_fix_intrinsics = ""
if args.intrinsics:
    with open(args.intrinsics, 'r') as f:
        cfg = yaml.safe_load(f)
    cam = cfg['camera_params']
    fx, fy, cx, cy = cam['fx'], cam['fy'], cam['cx'], cam['cy']
    camera_params_str = " --ImageReader.camera_params {},{},{},{}".format(fx, fy, cx, cy)
    mapper_fix_intrinsics = ""
    print(f"Using intrinsics prior from {args.intrinsics}: fx={fx:.2f}, fy={fy:.2f}, cx={cx:.1f}, cy={cy:.1f}")

if not args.skip_matching:
    os.makedirs(args.source_path + "/distorted/sparse", exist_ok=True)

    ## Feature extraction
    feat_extracton_cmd = (
        f"{colmap_command} feature_extractor "
        f"--database_path {args.source_path}/distorted/database.db "
        f"--image_path {args.source_path}/input "
        "--ImageReader.single_camera 1 "
        f"--ImageReader.camera_model {args.camera} "
        f"{feature_gpu_option} {feature_use_gpu}{max_features_option}{camera_params_str}"
    )
    exit_code = run_colmap_stage("feature_extraction", feat_extracton_cmd)
    if exit_code != 0:
        logging.error(f"Feature extraction failed with code {exit_code}. Exiting.")
        exit(exit_code)

    ## Feature matching
    matcher = "sequential_matcher" if args.sequential else "exhaustive_matcher"
    feat_matching_cmd = (
        f"{colmap_command} {matcher} "
        f"--database_path {args.source_path}/distorted/database.db "
        f"{matching_gpu_option} {matching_use_gpu}{max_matches_option}{sequential_overlap_option}"
    )
    exit_code = run_colmap_stage("feature_matching", feat_matching_cmd)
    if exit_code != 0:
        logging.error(f"Feature matching failed with code {exit_code}. Exiting.")
        exit(exit_code)

    ### Bundle adjustment
    # The default Mapper tolerance is unnecessarily large,
    # decreasing it speeds up bundle adjustment steps.
    mapper_cmd = (
        f"{colmap_command} mapper "
        f"--database_path {args.source_path}/distorted/database.db "
        f"--image_path {args.source_path}/input "
        f"--output_path {args.source_path}/distorted/sparse"
        f"{mapper_tolerance_option}"
        f"{mapper_fix_intrinsics}{mapper_gpu_option}"
    )
    exit_code = run_colmap_stage("mapper", mapper_cmd)
    if exit_code != 0:
        logging.error(f"Mapper failed with code {exit_code}. Exiting.")
        exit(exit_code)

### Image undistortion
## We need to undistort our images into ideal pinhole intrinsics.
mapper_output = args.source_path + "/distorted/sparse"
selected_reconstruction = select_largest_reconstruction(mapper_output)
print(f"Using COLMAP reconstruction: {selected_reconstruction}")
img_undist_cmd = (colmap_command + " image_undistorter \
    --image_path " + args.source_path + "/input \
    --input_path " + selected_reconstruction + " \
    --output_path " + args.source_path + "\
    --output_type COLMAP")
exit_code = run_colmap_stage("undistortion", img_undist_cmd)
if exit_code != 0:
    logging.error(f"Mapper failed with code {exit_code}. Exiting.")
    exit(exit_code)

files = os.listdir(args.source_path + "/sparse")
os.makedirs(args.source_path + "/sparse/0", exist_ok=True)
# Copy each file from the source directory to the destination directory
for file in files:
    if file == '0':
        continue
    source_file = os.path.join(args.source_path, "sparse", file)
    destination_file = os.path.join(args.source_path, "sparse", "0", file)
    shutil.move(source_file, destination_file)

if(args.resize):
    print("Copying and resizing...")

    # Resize images.
    os.makedirs(args.source_path + "/images_2", exist_ok=True)
    os.makedirs(args.source_path + "/images_4", exist_ok=True)
    os.makedirs(args.source_path + "/images_8", exist_ok=True)
    # Get the list of files in the source directory
    files = os.listdir(args.source_path + "/images")
    # Copy each file from the source directory to the destination directory
    for file in files:
        source_file = os.path.join(args.source_path, "images", file)

        destination_file = os.path.join(args.source_path, "images_2", file)
        shutil.copy2(source_file, destination_file)
        exit_code = os.system(magick_command + " mogrify -resize 50% " + destination_file)
        if exit_code != 0:
            logging.error(f"50% resize failed with code {exit_code}. Exiting.")
            exit(exit_code)

        destination_file = os.path.join(args.source_path, "images_4", file)
        shutil.copy2(source_file, destination_file)
        exit_code = os.system(magick_command + " mogrify -resize 25% " + destination_file)
        if exit_code != 0:
            logging.error(f"25% resize failed with code {exit_code}. Exiting.")
            exit(exit_code)

        destination_file = os.path.join(args.source_path, "images_8", file)
        shutil.copy2(source_file, destination_file)
        exit_code = os.system(magick_command + " mogrify -resize 12.5% " + destination_file)
        if exit_code != 0:
            logging.error(f"12.5% resize failed with code {exit_code}. Exiting.")
            exit(exit_code)

print("Done.")
