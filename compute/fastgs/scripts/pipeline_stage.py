"""Shared stage execution, status, and event helpers."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


VALID_STATUSES = frozenset(
    {"running", "completed", "completed_with_warnings", "failed", "cancelled"}
)


class StageStatusError(ValueError):
    """Raised when a stage status document is malformed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_status(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise StageStatusError("stage status must be a JSON object")
    status = payload.get("status")
    if status not in VALID_STATUSES:
        raise StageStatusError("unsupported stage status: %r" % (status,))


def write_stage_status(path: Path, payload: dict[str, Any]) -> None:
    """Validate and atomically write a stage status document."""
    _validate_status(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".%s." % path.name,
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def read_stage_status(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageStatusError("cannot read stage status: %s" % path) from exc
    _validate_status(payload)
    return payload


def append_event(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON event, creating the parent directory if necessary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_stage_command(
    command: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
    environment: Optional[dict[str, str]] = None,
) -> int:
    """Run a command while preserving logs and reaping timed-out children."""
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **(environment or {})}
    with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open(
        "a", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
            text=True,
            env=env,
        )
        try:
            return process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise

