from app.services.bm25 import BM25Document, BM25Index, normalize_scores, tokenize


def test_tokenize_supports_chinese_and_english_terms():
    assert tokenize("SM-880 交付样品") == ["sm", "880", "交", "付", "样", "品"]


def test_bm25_prioritizes_exact_work_terms():
    index = BM25Index(
        [
            BM25Document("irrelevant", "讨论下周会议安排"),
            BM25Document("relevant", "张经理下周三交付样品"),
            BM25Document("partial", "张经理下周三参加会议"),
        ]
    )
    results = index.search("张经理什么时候交付样品", top_k=3)
    assert results[0][0] == "relevant"


def test_normalize_scores_handles_constant_scores():
    assert normalize_scores({"a": 0.2, "b": 0.2}) == {"a": 1.0, "b": 1.0}
