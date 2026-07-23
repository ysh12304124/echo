from __future__ import annotations

import io
from collections.abc import Sequence

from app.settings import Settings


class ChineseClipEncoder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.processor = None
        self.torch = None
        self.image_module = None

    def load(self) -> None:
        import torch
        from PIL import Image
        from transformers import (
            BitsAndBytesConfig,
            ChineseCLIPModel,
            ChineseCLIPProcessor,
        )

        if not torch.cuda.is_available():
            raise RuntimeError("Chinese-CLIP requires a CUDA GPU")

        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        self.processor = ChineseCLIPProcessor.from_pretrained(
            self.settings.model_path
        )
        self.model = ChineseCLIPModel.from_pretrained(
            self.settings.model_path,
            quantization_config=quantization,
            device_map="auto",
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
        ).eval()
        self.torch = torch
        self.image_module = Image

    def _normalize(self, features):
        return features / features.norm(p=2, dim=-1, keepdim=True).clamp(min=1e-12)

    def encode_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if self.model is None or self.processor is None or self.torch is None:
            raise RuntimeError("Chinese-CLIP model is not loaded")
        if not texts:
            return []
        inputs = self.processor(
            text=list(texts),
            padding=True,
            truncation=True,
            max_length=self.settings.text_max_length,
            return_tensors="pt",
        )
        inputs = {key: value.to(self.model.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            outputs = self.model.text_model(**inputs)
            pooled = outputs.pooler_output
            if pooled is None:
                pooled = outputs.last_hidden_state[:, 0]
            features = self._normalize(self.model.text_projection(pooled))
        return features.float().cpu().tolist()

    def encode_images(self, images: Sequence[bytes]) -> list[list[float]]:
        if (
            self.model is None
            or self.processor is None
            or self.torch is None
            or self.image_module is None
        ):
            raise RuntimeError("Chinese-CLIP model is not loaded")
        if not images:
            return []
        decoded = [
            self.image_module.open(io.BytesIO(data)).convert("RGB") for data in images
        ]
        inputs = self.processor(images=decoded, return_tensors="pt")
        inputs = {key: value.to(self.model.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            outputs = self.model.vision_model(**inputs)
            pooled = outputs.pooler_output
            if pooled is None:
                pooled = outputs.last_hidden_state[:, 0]
            features = self._normalize(self.model.visual_projection(pooled))
        return features.float().cpu().tolist()
