import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import reconstruct_images  # noqa: E402


def test_legacy_run_job_delegates_to_decoupled_pipeline(monkeypatch, tmp_path):
    captured = {}

    def fake_run_pipeline(args):
        captured.update(vars(args))
        return 0

    monkeypatch.setattr("run_pipeline.run_pipeline", fake_run_pipeline)
    args = argparse.Namespace(
        job_dir=str(tmp_path), fastgs_dir="/repo/FastGS", job_id="job",
        iterations=30000, timeout_seconds=1800, allow_alignment_fallback=False,
        resume_from=None, conda_executable="conda", conda_env="fastgs",
        python_executable="python", colmap_executable="/opt/colmap",
        max_num_features=8192, feature_gpu=False, matching_gpu=True,
        mapper_use_gpu=True, cuda_lib_dir="/opt/cuda",
    )

    assert reconstruct_images.run_job(args) == 0
    assert captured["fastgs_dir"] == "/repo/FastGS"
    assert captured["mapper_gpu"] is True
