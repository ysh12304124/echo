import hashlib
import shlex
from pathlib import Path
from uuid import uuid4

import pytest

from app.providers.mock.providers import LocalBlobStore
from app.services.remote_reconstruction import RemoteReconstructionService


class FakeSftp:
    def __init__(self, remote_root: Path):
        self.remote_root = remote_root
        self.remote_root.mkdir(parents=True, exist_ok=True)

    def _path(self, remote: str) -> Path:
        return self.remote_root / remote.lstrip("/")

    def mkdir(self, path: str):
        self._path(path).mkdir(parents=False, exist_ok=False)

    def put(self, local: str, remote: str):
        target = self._path(remote)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(local).read_bytes())

    def get(self, remote: str, local: str):
        Path(local).write_bytes(self._path(remote).read_bytes())

    def stat(self, path: str):
        return self._path(path).stat()


class FakeSsh:
    def __init__(self, remote_root: Path, worker_root: Path):
        self.sftp = FakeSftp(remote_root)
        self.worker_root = worker_root
        self.command = None

    def open_sftp(self):
        return self.sftp

    def exec(self, command: str, timeout: int):
        self.command = command
        parts = shlex.split(command)
        remote_job = self.sftp.remote_root / parts[parts.index("--job-dir") + 1].lstrip("/")
        result_dir = remote_job / "model" / "point_cloud" / "iteration_3"
        result_dir.mkdir(parents=True, exist_ok=True)
        ply = result_dir / "point_cloud.ply"
        ply.write_bytes(b"ply\n")
        remote_ply = "/jobs/" + str(ply.relative_to(self.sftp.remote_root / "jobs"))
        (remote_job / "result.json").write_text(
            '{"status":"completed","ply_path":"%s","sha256":"%s"}'
            % (remote_ply, hashlib.sha256(b"ply\n").hexdigest())
        )
        return 0, "ok", ""

    def close(self):
        pass


class FakeBlobStore(LocalBlobStore):
    def get_url(self, key: str) -> str:
        return f"/api/v1/media/{key}"


@pytest.mark.asyncio
async def test_remote_reconstruction_uploads_images_and_publishes_ply(tmp_path):
    frames = []
    for index in range(3):
        frame = tmp_path / f"original-{index}.jpg"
        frame.write_bytes(f"frame-{index}".encode())
        frames.append(str(frame))

    remote_root = tmp_path / "remote"
    fake_ssh = FakeSsh(remote_root, tmp_path)
    service = RemoteReconstructionService(
        settings={
            "FASTGS_REMOTE_WORK_ROOT": "/jobs",
            "FASTGS_REMOTE_PROJECT": "/FastGS",
            "FASTGS_REMOTE_ENV": "fastgs",
            "FASTGS_TRAIN_ITERATIONS": "3",
            "FASTGS_TRAIN_TIMEOUT_SECONDS": "10",
        },
        ssh_factory=lambda: fake_ssh,
    )
    blob = FakeBlobStore(str(tmp_path / "blobs"))

    artifact = await service.reconstruct(uuid4(), uuid4(), frames, blob)

    assert artifact.model_format == "ply"
    assert artifact.size_bytes == 4
    assert fake_ssh.command is not None
    assert (remote_root / "jobs").exists()
    assert list((tmp_path / "blobs").rglob("point_cloud.ply"))
