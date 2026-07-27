from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from reconstruct_images import build_commands


def test_build_commands_keeps_explicit_gpu_override_available():
    commands = build_commands(
        job_dir=Path("/tmp/job"),
        fastgs_dir=Path("/home/liangjiahua/FastGS"),
        conda_env="fastgs",
        iterations=30000,
        colmap_executable="/home/liangjiahua/colmap-cuda/bin/colmap",
        colmap_new_api=True,
        mapper_use_gpu=True,
        cuda_lib_dir="/home/liangjiahua/miniconda3/envs/dgsg/targets/x86_64-linux/lib",
        feature_use_gpu=True,
    )

    assert "--colmap_executable" in commands.colmap
    assert "/home/liangjiahua/colmap-cuda/bin/colmap" in commands.colmap
    assert "--colmap_new_api" in commands.colmap
    assert "--mapper_use_gpu" in commands.colmap
    assert "--no_gpu" not in commands.colmap


def test_default_production_commands_use_hybrid_gpu_pipeline():
    commands = build_commands(
        job_dir=Path("/tmp/job"),
        fastgs_dir=Path("/home/liangjiahua/FastGS"),
        conda_env="fastgs",
        iterations=30000,
    )

    assert "/home/asus/opt/colmap-cuda-ceres/bin/colmap" in commands.colmap
    assert "--colmap_new_api" in commands.colmap
    assert "--no_gpu" in commands.colmap
    assert "--matching_gpu" in commands.colmap
    assert "--mapper_use_gpu" in commands.colmap
    assert "--max_num_features" in commands.colmap
    assert "8192" in commands.colmap
