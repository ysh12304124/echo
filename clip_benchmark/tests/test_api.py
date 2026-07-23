from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.manager import BenchmarkManager, CatalogImage, IndexedImage
from app.settings import Settings


class FakeEncoder:
    quantization = "nf4"

    def load(self, quantization):
        self.quantization = quantization

    def unload(self):
        self.quantization = None

    def encode_texts(self, _texts):
        return [[1.0, 0.0]]

    def encode_images(self, images):
        return [[1.0, 0.0] for _ in images]

    def memory_stats(self):
        return {
            "device_name": "Fake GPU",
            "device_total_bytes": 100,
            "device_used_bytes": 40,
            "device_free_bytes": 60,
            "process_allocated_bytes": 20,
            "process_reserved_bytes": 25,
        }


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(image_root=str(tmp_path), top_k=20)
    manager = BenchmarkManager(settings, FakeEncoder())
    indexed = []
    for index in range(25):
        path = tmp_path / f"image-{index:02d}.png"
        path.write_bytes(b"png")
        image = CatalogImage(f"id-{index}", path, path.name)
        indexed.append(IndexedImage(image, [1.0 - index / 100, 0.0]))
    manager.indexed = indexed
    manager.state = "ready"
    manager.quantization = "nf4"
    return TestClient(create_app(settings, manager, load_on_startup=False))


def test_search_returns_top_20_without_threshold(tmp_path):
    with build_client(tmp_path) as client:
        response = client.post("/api/search", json={"query": "测试图片"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_candidates"] == 25
    assert body["returned"] == 20
    assert [item["rank"] for item in body["results"]] == list(range(1, 21))
    assert body["results"][0]["similarity"] == 1.0
    assert body["results"][-1]["similarity"] == 0.81


def test_status_exposes_quantization_and_gpu_memory(tmp_path):
    with build_client(tmp_path) as client:
        response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["quantization"] == "nf4"
    assert body["quantization_options"] == ["fp16", "int8", "nf4"]
    assert body["gpu"]["device_name"] == "Fake GPU"
    assert body["image_count"] == 25


def test_image_endpoint_uses_catalog_id(tmp_path):
    with build_client(tmp_path) as client:
        response = client.get("/api/images/id-0")
        missing = client.get("/api/images/unknown")
    assert response.status_code == 200
    assert response.content == b"png"
    assert missing.status_code == 404


def test_reload_rejects_unknown_quantization(tmp_path):
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/model/reload", json={"quantization": "q2"}
        )
    assert response.status_code == 422
