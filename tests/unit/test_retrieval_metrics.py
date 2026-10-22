import pytest

from evals.retrieval import relevance_metrics


def test_document_recall_and_first_relevant_chunk_rank_are_distinct() -> None:
    recall, reciprocal = relevance_metrics({"a", "b"}, ["x", "x", "a", "a"])
    assert recall == 0.5 and reciprocal == pytest.approx(1 / 3)
    assert relevance_metrics({"a", "b"}, ["a", "b"]) == (1.0, 1.0)
    assert relevance_metrics({"a"}, []) == (0.0, 0.0)
    assert relevance_metrics(set(), ["x"]) == (None, None)
