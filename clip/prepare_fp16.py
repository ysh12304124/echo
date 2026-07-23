from pathlib import Path

import torch
from transformers import ChineseCLIPModel, ChineseCLIPProcessor


SOURCE = Path("/home/realmagic/models/chinese-clip-vit-base-patch16-source")
TARGET = Path("/home/realmagic/models/chinese-clip-vit-base-patch16-fp16")


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    processor = ChineseCLIPProcessor.from_pretrained(SOURCE)
    model = ChineseCLIPModel.from_pretrained(SOURCE, torch_dtype=torch.float16)
    model.save_pretrained(TARGET, safe_serialization=True)
    processor.save_pretrained(TARGET)
    tensors = list(model.state_dict().values())
    floating = [tensor for tensor in tensors if tensor.is_floating_point()]
    if not floating or any(tensor.dtype != torch.float16 for tensor in floating):
        raise RuntimeError("FP16 conversion verification failed")
    print(f"saved FP16 model to {TARGET}")


if __name__ == "__main__":
    main()
