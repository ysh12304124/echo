from __future__ import annotations

import gc
import io
from collections.abc import Sequence
from typing import Literal

Quantization = Literal["fp16", "int8", "nf4"]


class ChineseClipEncoder:
    def __init__(self, model_path: str, text_max_length: int = 512):
        self.model_path = model_path
        self.text_max_length = text_max_length
        self.model = None
        self.processor = None
        self.torch = None
        self.image_module = None
        self.quantization: Quantization | None = None

    def load(self, quantization: Quantization) -> None:
        import torch
        from PIL import Image
        from transformers import (
            BitsAndBytesConfig,
            ChineseCLIPModel,
            ChineseCLIPProcessor,
        )

        if not torch.cuda.is_available():
            raise RuntimeError("Chinese-CLIP benchmark requires a CUDA GPU")

        model_kwargs: dict = {
            "device_map": "auto",
            "torch_dtype": torch.float16,
            "low_cpu_mem_usage": True,
        }
        if quantization == "nf4":
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
        elif quantization == "int8":
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_8bit=True,
            )

        self.processor = ChineseCLIPProcessor.from_pretrained(self.model_path)
        self.model = ChineseCLIPModel.from_pretrained(
            self.model_path, **model_kwargs
        ).eval()
        self.torch = torch
        self.image_module = Image
        self.quantization = quantization

    def unload(self) -> None:
        self.model = None
        self.processor = None
        self.image_module = None
        gc.collect()
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()
            self.torch.cuda.ipc_collect()
        self.quantization = None

    def _require_loaded(self):
        if self.model is None or self.processor is None or self.torch is None:
            raise RuntimeError("Chinese-CLIP model is not loaded")

    def _normalize(self, features):
        return features / features.norm(p=2, dim=-1, keepdim=True).clamp(min=1e-12)

    def encode_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self._require_loaded()
        inputs = self.processor(
            text=list(texts),
            padding=True,
            truncation=True,
            max_length=self.text_max_length,
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
        self._require_loaded()
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

    def memory_stats(self) -> dict[str, int | str | None]:
        if self.torch is None or not self.torch.cuda.is_available():
            return {
                "device_name": None,
                "device_total_bytes": 0,
                "device_used_bytes": 0,
                "device_free_bytes": 0,
                "process_allocated_bytes": 0,
                "process_reserved_bytes": 0,
            }
        device = self.torch.cuda.current_device()
        free_bytes, total_bytes = self.torch.cuda.mem_get_info(device)
        return {
            "device_name": self.torch.cuda.get_device_name(device),
            "device_total_bytes": int(total_bytes),
            "device_used_bytes": int(total_bytes - free_bytes),
            "device_free_bytes": int(free_bytes),
            "process_allocated_bytes": int(self.torch.cuda.memory_allocated(device)),
            "process_reserved_bytes": int(self.torch.cuda.memory_reserved(device)),
        }
