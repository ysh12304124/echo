from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Tokenize English words and Chinese characters for mixed-language memory text."""
    return _TOKEN_PATTERN.findall(text.lower())


@dataclass(frozen=True)
class BM25Document:
    id: str
    text: str


class BM25Index:
    def __init__(self, documents: list[BM25Document], k1: float = 1.2, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(document.text) for document in documents]
        self.avgdl = (
            sum(len(tokens) for tokens in self.tokens) / len(self.tokens)
            if self.tokens
            else 0.0
        )
        self.document_frequency: Counter[str] = Counter()
        for tokens in self.tokens:
            self.document_frequency.update(set(tokens))

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.documents:
            return []

        query_terms = set(query_tokens)
        total = len(self.documents)
        results: list[tuple[str, float]] = []
        for document, tokens in zip(self.documents, self.tokens, strict=True):
            counts = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for term in query_terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self.document_frequency[term]
                idf = math.log(
                    1.0 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * length / max(self.avgdl, 1.0)
                )
                score += idf * frequency * (self.k1 + 1.0) / denominator
            if score > 0.0:
                results.append((document.id, score))
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:top_k]


def normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    minimum = min(scores.values())
    maximum = max(scores.values())
    if math.isclose(minimum, maximum):
        return {key: 1.0 for key in scores}
    return {
        key: (value - minimum) / (maximum - minimum)
        for key, value in scores.items()
    }
