from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import posixpath
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.providers.base import BlobStore

log = logging.getLogger("echo.reconstruction")


class ReconstructionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconstructionArtifact:
    job_id: str
    model_url: str
    model_format: str
    size_bytes: int
    sha256: str
    poses_url: str
    poses_size_bytes: int
    poses_sha256: str
    anchor_url: str
    anchor_size_bytes: int
    anchor_sha256: str
    anchor_method: str


class SftpClient(Protocol):
    def mkdir(self, path: str) -> None: ...
    def put(self, local: str, remote: str) -> None: ...
    def get(self, remote: str, local: str) -> None: ...
    def stat(self, path: str) -> Any: ...


class SshClient(Protocol):
    def open_sftp(self) -> SftpClient: ...
    def exec(self, command: str, timeout: int) -> tuple[int, str, str]: ...
    def close(self) -> None: ...


class ParamikoSshClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._client = None

    def connect(self) -> None:
        try:
            import paramiko
        except ImportError as exc:
            raise ReconstructionError(
                "paramiko is required for remote FastGS reconstruction"
            ) from exc
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
        )
        self._client = client

    def open_sftp(self):
        if self._client is None:
            raise ReconstructionError("SSH client is not connected")
        return self._client.open_sftp()

    def exec(self, command: str, timeout: int) -> tuple[int, str, str]:
        if self._client is None:
            raise ReconstructionError("SSH client is not connected")
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        return stdout.channel.recv_exit_status(), stdout.read().decode(), stderr.read().decode()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def env_value(name: str, default: str | None = None) -> str | None:
    return os.getenv(name) or os.getenv(f"ECHO_{name}") or default


class RemoteReconstructionService:
    def __init__(self, settings=None, ssh_factory=None):
        self.settings = settings
        self.ssh_factory = ssh_factory or self._default_ssh_factory

    def _setting(self, name: str, default=None):
        if self.settings is not None:
            if isinstance(self.settings, dict):
                value = self.settings.get(name)
            else:
                value = getattr(self.settings, name.lower(), None)
            if value not in (None, ""):
                return value
        settings_name = name.lower()
        if settings_name.startswith("fastgs_"):
            try:
                from app.providers import get_settings
                value = getattr(get_settings(), settings_name, None)
                if value not in (None, ""):
                    return value
            except Exception:
                pass
        return env_value(name, default)

    def _default_ssh_factory(self) -> ParamikoSshClient:
        host = self._setting("FASTGS_SSH_HOST")
        user = self._setting("FASTGS_SSH_USER")
        password = self._setting("FASTGS_SSH_PASSWORD")
        if not host or not user or not password:
            raise ReconstructionError(
                "FASTGS_SSH_HOST, FASTGS_SSH_USER and FASTGS_SSH_PASSWORD are required"
            )
        client = ParamikoSshClient(
            host=host,
            port=int(self._setting("FASTGS_SSH_PORT", "22")),
            username=user,
            password=password,
        )
        client.connect()
        return client

    def is_configured(self) -> bool:
        return bool(
            self._setting("FASTGS_SSH_HOST")
            and self._setting("FASTGS_SSH_USER")
            and self._setting("FASTGS_SSH_PASSWORD")
        )

    async def reconstruct(
        self,
        session_id: UUID,
        space_id: UUID,
        frame_paths: list[str],
        blob_store: BlobStore,
    ) -> ReconstructionArtifact:
        if len(frame_paths) < 3:
            raise ReconstructionError("at least 3 frames are required for reconstruction")

        job_id = str(uuid4())
        remote_root = self._setting("FASTGS_REMOTE_WORK_ROOT", "/tmp/echo-fastgs")
        remote_job = posixpath.join(remote_root, job_id)
        remote_input = posixpath.join(remote_job, "input")
        fastgs_dir = self._setting("FASTGS_REMOTE_PROJECT", "/home/liangjiahua/FastGS")
        env_name = self._setting("FASTGS_REMOTE_ENV", "fastgs")
        iterations = int(self._setting("FASTGS_TRAIN_ITERATIONS", "30000"))
        timeout = int(self._setting("FASTGS_TRAIN_TIMEOUT_SECONDS", "1800"))
        local_dir = Path(tempfile.mkdtemp(prefix=f"echo-fastgs-{job_id}-"))
        events: list[dict] = []
        ssh: SshClient | None = None

        def event(stage: str, status: str, **fields):
            payload = {
                "job_id": job_id,
                "session_id": str(session_id),
                "space_id": str(space_id),
                "stage": stage,
                "status": status,
                **fields,
            }
            events.append(payload)
            log.info("reconstruction_event %s", json.dumps(payload, ensure_ascii=False))

        try:
            event("created", "completed", frame_count=len(frame_paths))
            input_dir = local_dir / "input"
            input_dir.mkdir()
            total_bytes = 0
            for index, source in enumerate(frame_paths):
                source_path = Path(source)
                if source_path.suffix.lower() not in {".jpg", ".jpeg"}:
                    raise ReconstructionError(f"unsupported frame format: {source_path.name}")
                destination = input_dir / f"frame_{index:06d}.jpg"
                shutil.copy2(source_path, destination)
                total_bytes += destination.stat().st_size
            event("staging", "completed", image_count=len(frame_paths), image_bytes=total_bytes)

            ssh = self.ssh_factory()
            sftp = ssh.open_sftp()
            _mkdir_recursive(sftp, remote_root)
            _mkdir_recursive(sftp, remote_job)
            _mkdir_recursive(sftp, remote_input)
            for image in sorted(input_dir.iterdir()):
                sftp.put(str(image), posixpath.join(remote_input, image.name))
            event("uploading", "completed", remote_job=remote_job)

            worker = posixpath.join(fastgs_dir, "scripts", "reconstruct_images.py")
            python = self._setting(
                "FASTGS_PYTHON_EXECUTABLE",
                "/home/liangjiahua/miniconda3/envs/fastgs/bin/python",
            )
            command = " ".join(
                shlex.quote(part)
                for part in [
                    python,
                    worker,
                    "--job-dir", remote_job,
                    "--fastgs-dir", fastgs_dir,
                    "--conda-env", env_name,
                    "--iterations", str(iterations),
                    "--timeout-seconds", str(timeout),
                    "--python-executable", python,
                    "--conda-executable",
                    self._setting("FASTGS_CONDA_EXECUTABLE", "/home/liangjiahua/miniconda3/bin/conda"),
                ]
            )
            return_code, stdout, stderr = await asyncio.to_thread(ssh.exec, command, timeout)
            (local_dir / "remote_stdout.log").write_text(stdout, encoding="utf-8")
            (local_dir / "remote_stderr.log").write_text(stderr, encoding="utf-8")
            event("training", "completed" if return_code == 0 else "failed", exit_code=return_code)
            if return_code != 0:
                raise ReconstructionError(f"remote worker exited with code {return_code}")

            remote_result = posixpath.join(remote_job, "result.json")
            local_result = local_dir / "result.json"
            sftp.get(remote_result, str(local_result))
            result = json.loads(local_result.read_text(encoding="utf-8"))
            remote_ply = result.get("ply_path")
            remote_poses = result.get("poses_path")
            remote_anchor = result.get("anchor_path")
            if (
                not remote_ply
                or not remote_poses
                or not remote_anchor
                or result.get("status") != "completed"
            ):
                raise ReconstructionError("remote result did not contain completed PLY, poses and anchor")

            local_ply = local_dir / "point_cloud.ply"
            sftp.get(remote_ply, str(local_ply))
            if local_ply.stat().st_size <= 0:
                raise ReconstructionError("downloaded PLY is empty")
            digest = sha256_file(local_ply)
            if result.get("sha256") and result["sha256"] != digest:
                raise ReconstructionError("downloaded PLY SHA256 does not match remote result")
            event("downloading", "completed", size_bytes=local_ply.stat().st_size, sha256=digest)

            local_poses = local_dir / "poses.txt"
            sftp.get(remote_poses, str(local_poses))
            if local_poses.stat().st_size <= 0:
                raise ReconstructionError("downloaded poses.txt is empty")
            pose_digest = sha256_file(local_poses)
            if result.get("poses_sha256") and result["poses_sha256"] != pose_digest:
                raise ReconstructionError("downloaded poses SHA256 does not match remote result")
            pose_count = len(local_poses.read_text(encoding="utf-8").splitlines())
            if result.get("pose_count") != pose_count:
                raise ReconstructionError("downloaded poses count does not match remote result")
            event(
                "downloading_poses",
                "completed",
                size_bytes=local_poses.stat().st_size,
                sha256=pose_digest,
                pose_count=pose_count,
            )

            local_anchor = local_dir / "anchor.json"
            sftp.get(remote_anchor, str(local_anchor))
            if local_anchor.stat().st_size <= 0:
                raise ReconstructionError("downloaded anchor.json is empty")
            anchor_digest = sha256_file(local_anchor)
            if result.get("anchor_sha256") and result["anchor_sha256"] != anchor_digest:
                raise ReconstructionError("downloaded anchor SHA256 does not match remote result")
            try:
                anchor_values = json.loads(local_anchor.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ReconstructionError("downloaded anchor.json is invalid JSON") from exc
            anchor_method = anchor_values.get("method")
            if not anchor_method or anchor_method != result.get("anchor_method"):
                raise ReconstructionError("downloaded anchor method does not match remote result")
            position = anchor_values.get("position")
            if not isinstance(position, dict) or not all(
                key in position for key in ("x", "y", "z")
            ):
                raise ReconstructionError("downloaded anchor.json is missing coordinates")
            event(
                "downloading_anchor",
                "completed",
                size_bytes=local_anchor.stat().st_size,
                sha256=anchor_digest,
                method=anchor_method,
            )

            blob_key = f"spaces/{space_id}/models/point_cloud.ply"
            await blob_store.save(blob_key, local_ply.read_bytes(), "application/octet-stream")
            poses_blob_key = f"spaces/{space_id}/models/poses.txt"
            await blob_store.save(poses_blob_key, local_poses.read_bytes(), "text/plain; charset=utf-8")
            anchor_blob_key = f"spaces/{space_id}/models/anchor.json"
            await blob_store.save(anchor_blob_key, local_anchor.read_bytes(), "application/json")
            event(
                "storing", "completed", blob_key=blob_key,
                poses_blob_key=poses_blob_key, anchor_blob_key=anchor_blob_key,
            )
            artifact = ReconstructionArtifact(
                job_id=job_id,
                model_url=blob_store.get_url(blob_key),
                model_format="ply",
                size_bytes=local_ply.stat().st_size,
                sha256=digest,
                poses_url=blob_store.get_url(poses_blob_key),
                poses_size_bytes=local_poses.stat().st_size,
                poses_sha256=pose_digest,
                anchor_url=blob_store.get_url(anchor_blob_key),
                anchor_size_bytes=local_anchor.stat().st_size,
                anchor_sha256=anchor_digest,
                anchor_method=anchor_method,
            )
            event(
                "completed", "completed", size_bytes=artifact.size_bytes,
                sha256=digest, poses_size_bytes=artifact.poses_size_bytes,
                poses_sha256=pose_digest,
                anchor_size_bytes=artifact.anchor_size_bytes,
                anchor_sha256=anchor_digest,
                anchor_method=anchor_method,
            )
            return artifact
        except Exception as exc:
            event("failed", "failed", error=str(exc))
            raise
        finally:
            if ssh is not None:
                try:
                    ssh.close()
                except Exception:
                    log.exception("failed to close FastGS SSH client job_id=%s", job_id)
            shutil.rmtree(local_dir, ignore_errors=True)


def _mkdir_recursive(sftp: SftpClient, path: str) -> None:
    current = "/"
    for part in path.strip("/").split("/"):
        current = posixpath.join(current, part)
        try:
            sftp.stat(current)
            continue
        except Exception:
            pass
        try:
            sftp.mkdir(current)
        except Exception:
            # A concurrent worker may create the directory between stat and mkdir.
            try:
                sftp.stat(current)
            except Exception:
                raise
