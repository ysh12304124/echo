import base64

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


class FakeEncoder:
    def encode_texts(self, texts):
        return [[1.0] + [0.0] * 511 for _ in texts]

    def encode_images(self, images):
        return [[0.0, 1.0] + [0.0] * 510 for _ in images]


def client():
    app = create_app(Settings(internal_token="secret"), FakeEncoder())
    return TestClient(app)


def image_bytes():
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
    )


def test_health_reports_runtime_quantization():
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json()["runtime_quantization"] == "nf4"
    assert response.json()["dimension"] == 512


def test_text_embedding_requires_token_and_preserves_batch():
    unauthorized = client().post("/embed/text", json={"texts": ["测试"]})
    assert unauthorized.status_code == 401

    response = client().post(
        "/embed/text",
        headers={"X-Internal-Token": "secret"},
        json={"texts": ["白板", "设备"]},
    )
    assert response.status_code == 200
    assert len(response.json()["vectors"]) == 2


def test_image_embedding_accepts_supported_images():
    response = client().post(
        "/embed/images",
        headers={"X-Internal-Token": "secret"},
        files=[("files", ("frame.png", image_bytes(), "image/png"))],
    )
    assert response.status_code == 200
    assert len(response.json()["vectors"][0]) == 512
