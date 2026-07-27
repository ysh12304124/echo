import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from run_pipeline import STAGES, stage_command  # noqa: E402
from run_prune import build_prune_command, find_pruned_outputs  # noqa: E402


def pipeline_args(tmp_path):
    return argparse.Namespace(
        job_dir=str(tmp_path), fastgs_dir="/repo/FastGS", job_id="job",
        iterations=30000, timeout_seconds=1800, allow_alignment_fallback=True,
        resume_from=None, conda_executable="conda", conda_env="fastgs",
        python_executable="python", colmap_executable="/opt/colmap",
        max_num_features=8192, feature_gpu=False, matching_gpu=True,
        mapper_gpu=True, cuda_lib_dir="/opt/cuda", prune_max_ratio=0.01,
        prune_finetune_iterations=800, prune_evaluate_psnr=True,
    )


def test_pipeline_places_pruning_before_export(tmp_path):
    args = pipeline_args(tmp_path)

    assert STAGES == ("colmap", "alignment", "fastgs", "prune", "export")
    assert stage_command("prune", args)[1].endswith("run_prune.py")
    assert stage_command("export", args)[1].endswith("export_outputs.py")


def test_prune_command_uses_trained_model_and_forces_finetuning(tmp_path):
    command = build_prune_command(
        scene_dir=tmp_path / "colmap_gravity_aligned",
        model_dir=tmp_path / "fastgs_model",
        fastgs_dir=Path("/repo/FastGS"),
        iterations=30000,
        max_prune_ratio=0.0,
        finetune_iterations=800,
        evaluate_psnr=True,
    )

    assert str(Path("/repo/FastGS") / "prune_gaussians.py") in command
    assert "--max_prune_ratio" in command
    assert "0.0" in command
    assert "--finetune_iterations" in command
    assert "800" in command
    assert "--evaluate_psnr" in command


def test_find_pruned_outputs_requires_stats_checkpoint_and_ply(tmp_path):
    with pytest.raises(ValueError, match="pruned"):
        find_pruned_outputs(tmp_path / "fastgs_model", 30000)
