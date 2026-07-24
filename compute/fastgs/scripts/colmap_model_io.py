"""Read, write, and validate COLMAP binary reconstruction models."""

from __future__ import annotations

import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import numpy as np


@dataclass(frozen=True)
class CameraRecord:
    camera_id: int
    model_id: int
    width: int
    height: int
    params: np.ndarray


@dataclass(frozen=True)
class ImageRecord:
    image_id: int
    qvec: np.ndarray
    tvec: np.ndarray
    camera_id: int
    name: str
    xys: np.ndarray
    point3d_ids: np.ndarray


@dataclass(frozen=True)
class Point3DRecord:
    point3d_id: int
    xyz: np.ndarray
    rgb: np.ndarray
    error: float
    image_ids: np.ndarray
    point2d_idxs: np.ndarray


@dataclass(frozen=True)
class ModelMetrics:
    camera_count: int
    registered_image_count: int
    point3d_count: int


def _read_exact(stream, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("truncated COLMAP binary model")
    return data


def _atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".%s." % path.name,
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def read_cameras_binary(path: Path) -> Dict[int, CameraRecord]:
    cameras: Dict[int, CameraRecord] = {}
    with path.open("rb") as stream:
        count = struct.unpack("<Q", _read_exact(stream, 8))[0]
        for _ in range(count):
            camera_id, model_id, width, height = struct.unpack(
                "<iiQQ", _read_exact(stream, 24)
            )
            # COLMAP's model registry is required to determine parameter count.
            # OPENCV is the configured production model; the common models are
            # included so existing reconstructions remain readable.
            parameter_counts = {
                0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 8, 6: 12,
                7: 5, 8: 4, 9: 5, 10: 12,
            }
            try:
                parameter_count = parameter_counts[model_id]
            except KeyError as exc:
                raise ValueError("unsupported COLMAP camera model: %s" % model_id) from exc
            params = np.asarray(
                struct.unpack(
                    "<" + "d" * parameter_count,
                    _read_exact(stream, 8 * parameter_count),
                ),
                dtype=float,
            )
            cameras[camera_id] = CameraRecord(
                camera_id=camera_id,
                model_id=model_id,
                width=width,
                height=height,
                params=params,
            )
    return cameras


def write_cameras_binary(path: Path, cameras: Dict[int, CameraRecord]) -> None:
    def writer(stream) -> None:
        stream.write(struct.pack("<Q", len(cameras)))
        for camera_id in sorted(cameras):
            camera = cameras[camera_id]
            params = np.asarray(camera.params, dtype=float).reshape(-1)
            stream.write(
                struct.pack(
                    "<iiQQ",
                    int(camera.camera_id), int(camera.model_id),
                    int(camera.width), int(camera.height),
                )
            )
            stream.write(struct.pack("<" + "d" * len(params), *params))

    _atomic_write(path, writer)


def read_images_binary(path: Path) -> Dict[int, ImageRecord]:
    images: Dict[int, ImageRecord] = {}
    with path.open("rb") as stream:
        count = struct.unpack("<Q", _read_exact(stream, 8))[0]
        for _ in range(count):
            image_id, *pose_values, camera_id = struct.unpack(
                "<idddddddi", _read_exact(stream, 64)
            )
            name_bytes = bytearray()
            while True:
                char = _read_exact(stream, 1)
                if char == b"\x00":
                    break
                name_bytes.extend(char)
            try:
                name = name_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("invalid UTF-8 image name") from exc
            point_count = struct.unpack("<Q", _read_exact(stream, 8))[0]
            raw_points = _read_exact(stream, 24 * point_count)
            if point_count:
                values = struct.unpack("<" + "ddq" * point_count, raw_points)
                xys = np.column_stack((values[0::3], values[1::3])).astype(float)
                point3d_ids = np.asarray(values[2::3], dtype=np.int64)
            else:
                xys = np.empty((0, 2), dtype=float)
                point3d_ids = np.empty((0,), dtype=np.int64)
            images[image_id] = ImageRecord(
                image_id=image_id,
                qvec=np.asarray(pose_values[:4], dtype=float),
                tvec=np.asarray(pose_values[4:], dtype=float),
                camera_id=camera_id,
                name=name,
                xys=xys,
                point3d_ids=point3d_ids,
            )
    return images


def write_images_binary(path: Path, images: Dict[int, ImageRecord]) -> None:
    def writer(stream) -> None:
        stream.write(struct.pack("<Q", len(images)))
        for image_id in sorted(images):
            image = images[image_id]
            qvec = np.asarray(image.qvec, dtype=float).reshape(4)
            tvec = np.asarray(image.tvec, dtype=float).reshape(3)
            xys = np.asarray(image.xys, dtype=float).reshape(-1, 2)
            point3d_ids = np.asarray(image.point3d_ids, dtype=np.int64).reshape(-1)
            if len(xys) != len(point3d_ids):
                raise ValueError("COLMAP image xys and point3d_ids length mismatch")
            stream.write(struct.pack("<i" + "d" * 7 + "i", int(image.image_id), *qvec, *tvec, int(image.camera_id)))
            stream.write(image.name.encode("utf-8") + b"\x00")
            stream.write(struct.pack("<Q", len(xys)))
            for xy, point3d_id in zip(xys, point3d_ids):
                stream.write(struct.pack("<ddq", float(xy[0]), float(xy[1]), int(point3d_id)))

    _atomic_write(path, writer)


def read_points3d_binary(path: Path) -> Dict[int, Point3DRecord]:
    points: Dict[int, Point3DRecord] = {}
    with path.open("rb") as stream:
        count = struct.unpack("<Q", _read_exact(stream, 8))[0]
        for _ in range(count):
            point_id, x, y, z, red, green, blue, error = struct.unpack(
                "<QdddBBBd", _read_exact(stream, 43)
            )
            track_length = struct.unpack("<Q", _read_exact(stream, 8))[0]
            raw_track = _read_exact(stream, 8 * track_length)
            if track_length:
                track = struct.unpack("<" + "ii" * track_length, raw_track)
                image_ids = np.asarray(track[0::2], dtype=np.int32)
                point2d_idxs = np.asarray(track[1::2], dtype=np.int32)
            else:
                image_ids = np.empty((0,), dtype=np.int32)
                point2d_idxs = np.empty((0,), dtype=np.int32)
            points[point_id] = Point3DRecord(
                point3d_id=point_id,
                xyz=np.asarray([x, y, z], dtype=float),
                rgb=np.asarray([red, green, blue], dtype=np.uint8),
                error=float(error),
                image_ids=image_ids,
                point2d_idxs=point2d_idxs,
            )
    return points


def write_points3d_binary(path: Path, points: Dict[int, Point3DRecord]) -> None:
    def writer(stream) -> None:
        stream.write(struct.pack("<Q", len(points)))
        for point_id in sorted(points):
            point = points[point_id]
            xyz = np.asarray(point.xyz, dtype=float).reshape(3)
            rgb = np.asarray(point.rgb, dtype=np.uint8).reshape(3)
            image_ids = np.asarray(point.image_ids, dtype=np.int32).reshape(-1)
            point2d_idxs = np.asarray(point.point2d_idxs, dtype=np.int32).reshape(-1)
            if len(image_ids) != len(point2d_idxs):
                raise ValueError("COLMAP track length mismatch")
            stream.write(
                struct.pack(
                    "<QdddBBBd",
                    int(point.point3d_id), *xyz, int(rgb[0]), int(rgb[1]),
                    int(rgb[2]), float(point.error),
                )
            )
            stream.write(struct.pack("<Q", len(image_ids)))
            for image_id, point2d_idx in zip(image_ids, point2d_idxs):
                stream.write(struct.pack("<ii", int(image_id), int(point2d_idx)))

    _atomic_write(path, writer)


def validate_colmap_model(model_dir: Path) -> ModelMetrics:
    required = ["cameras.bin", "images.bin", "points3D.bin"]
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise ValueError("COLMAP model is missing: " + ", ".join(missing))
    cameras = read_cameras_binary(model_dir / "cameras.bin")
    images = read_images_binary(model_dir / "images.bin")
    points = read_points3d_binary(model_dir / "points3D.bin")
    if not cameras:
        raise ValueError("COLMAP model contains no cameras")
    if not images:
        raise ValueError("COLMAP model contains no registered images")
    return ModelMetrics(
        camera_count=len(cameras),
        registered_image_count=len(images),
        point3d_count=len(points),
    )
