from __future__ import annotations

from typing import Sequence

from app.settings import Settings


class QwenReranker:
    PREFIX = (
        '<|im_start|>system\nJudge whether the Document meets the requirements based on '
        'the Query and the Instruct provided. Note that the answer can only be "yes" or '
        '"no".<|im_end|>\n<|im_start|>user\n'
    )
    SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.tokenizer = None
        self.model = None
        self.torch = None
        self.true_token_id: int | None = None
        self.false_token_id: int | None = None
        self.prefix_tokens: list[int] = []
        self.suffix_tokens: list[int] = []

    def load(self) -> None:
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )

        if not torch.cuda.is_available():
            raise RuntimeError("Qwen reranker requires a CUDA GPU")

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.settings.model_path, padding_side="left"
        )
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            self.settings.model_path,
            quantization_config=quantization,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        ).eval()

        self.true_token_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.false_token_id = self.tokenizer.convert_tokens_to_ids("no")
        self.prefix_tokens = self.tokenizer.encode(self.PREFIX, add_special_tokens=False)
        self.suffix_tokens = self.tokenizer.encode(self.SUFFIX, add_special_tokens=False)

        available = self.settings.max_length - len(self.prefix_tokens) - len(self.suffix_tokens)
        if available <= 0:
            raise RuntimeError("RERANKER_MAX_LENGTH is too small for the model prompt")

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if self.model is None or self.tokenizer is None or self.torch is None:
            raise RuntimeError("reranker model is not loaded")
        if not documents:
            return []
        if len(documents) > self.settings.max_batch_size:
            raise ValueError("candidate batch exceeds configured maximum")

        pairs = [
            f"<Instruct>: {self.settings.instruction}\n<Query>: {query}\n<Document>: {doc}"
            for doc in documents
        ]
        content_limit = (
            self.settings.max_length - len(self.prefix_tokens) - len(self.suffix_tokens)
        )
        inputs = self.tokenizer(
            pairs,
            padding=False,
            truncation="longest_first",
            return_attention_mask=False,
            max_length=content_limit,
        )
        for index, token_ids in enumerate(inputs["input_ids"]):
            inputs["input_ids"][index] = (
                self.prefix_tokens + token_ids + self.suffix_tokens
            )
        inputs = self.tokenizer.pad(
            inputs,
            padding=True,
            return_tensors="pt",
            max_length=self.settings.max_length,
        )
        inputs = {key: value.to(self.model.device) for key, value in inputs.items()}

        with self.torch.no_grad():
            logits = self.model(**inputs).logits[:, -1, :]
            yes_logits = logits[:, self.true_token_id]
            no_logits = logits[:, self.false_token_id]
            pair_logits = self.torch.stack([no_logits, yes_logits], dim=1)
            scores = self.torch.nn.functional.log_softmax(pair_logits, dim=1)[:, 1].exp()
        return [float(score) for score in scores.cpu().tolist()]
