import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from run_pipeline import STAGES, stage_command  # noqa: E402


def arguments(tmp_path):
    return argparse.Namespace(job_dir=str(tmp_path), fastgs_dir="/repo/FastGS", job_id="job", iterations=30000, timeout_seconds=1800, allow_alignment_fallback=True, resume_from=None, conda_executable="conda", conda_env="fastgs", python_executable="python", colmap_executable="/opt/colmap", max_num_features=8192, feature_gpu=False, matching_gpu=True, mapper_gpu=True, cuda_lib_dir="/opt/cuda")


def test_stage_command_has_explicit_five_stage_order(tmp_path):
    args = arguments(tmp_path)
    assert [stage_command(stage, args)[1].split("/")[-1] for stage in STAGES] == [
        "run_colmap.py", "align_colmap.py", "run_fastgs.py", "run_prune.py", "export_outputs.py",
    ]


def test_alignment_command_carries_explicit_fallback(tmp_path):
    args = arguments(tmp_path)
    command = stage_command("alignment", args)
    assert "--allow-alignment-fallback" in command
