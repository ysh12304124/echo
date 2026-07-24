import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from pipeline_stage import (  # noqa: E402
    VALID_STATUSES,
    StageStatusError,
    read_stage_status,
    run_stage_command,
    write_stage_status,
)


def test_write_and_read_stage_status_atomically(tmp_path):
    path = tmp_path / "stages" / "colmap" / "status.json"
    payload = {
        "version": 1,
        "job_id": "job-1",
        "stage": "colmap",
        "status": "completed",
    }

    write_stage_status(path, payload)

    assert read_stage_status(path) == payload
    assert not list(path.parent.glob(".*.tmp"))


def test_stage_status_rejects_unknown_status(tmp_path):
    path = tmp_path / "status.json"

    with pytest.raises(StageStatusError):
        write_stage_status(path, {"status": "unknown"})

    path.write_text(json.dumps({"status": "unknown"}), encoding="utf-8")
    with pytest.raises(StageStatusError):
        read_stage_status(path)

    assert "completed_with_warnings" in VALID_STATUSES


def test_run_stage_command_captures_output_and_exit_code(tmp_path):
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    command = [
        sys.executable,
        "-c",
        "print('stdout-line'); import sys; print('stderr-line', file=sys.stderr)",
    ]

    code = run_stage_command(command, tmp_path, stdout, stderr, timeout_seconds=10)

    assert code == 0
    assert "stdout-line" in stdout.read_text(encoding="utf-8")
    assert "stderr-line" in stderr.read_text(encoding="utf-8")


def test_run_stage_command_raises_typed_timeout(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_stage_command(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            tmp_path,
            tmp_path / "stdout.log",
            tmp_path / "stderr.log",
            timeout_seconds=0.05,
        )
