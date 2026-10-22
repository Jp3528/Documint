from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.indexing.chunking import ChunkSpan
from packages.parsers.contracts import Locator
from packages.retrieval.contracts import Candidate
from packages.retrieval.fusion import FusionConfig, fuse


def candidate(number: int, document: int, score: float = 1) -> Candidate:
    return Candidate(
        chunk_id=UUID(int=number),
        document_id=UUID(int=document),
        version_id=UUID(int=500),
        index_revision_id=UUID(int=600),
        title="Synthetic source",
        filename="fixture.txt",
        text="Evidence",
        sha256="a" * 64,
        score=score,
        rank=1,
        spans=(
            ChunkSpan(
                block_index=0,
                char_start=0,
                char_end=8,
                locator=Locator(format="txt", line_start=1, line_end=1),
            ),
        ),
    )


def test_rrf_rewards_agreement_without_adding_incompatible_score_scales() -> None:
    a, b, c = candidate(1, 10, 99999), candidate(2, 20, -0.9), candidate(3, 30, 0.1)
    result = fuse([a, b], [c, b], 3)
    assert [row.chunk_id for row in result] == [b.chunk_id, a.chunk_id, c.chunk_id]
    assert result[0].score == pytest.approx(2 / 62)
    changed = fuse([a.model_copy(update={"score": -99999}), b], [c, b], 3)
    assert [(r.chunk_id, r.score) for r in changed] == [(r.chunk_id, r.score) for r in result]
    assert [r.rank for r in result] == [1, 2, 3]


def test_duplicate_chunks_cannot_inflate_rrf_and_document_diversity_is_bounded() -> None:
    a, b, c, d = [candidate(i, 10 if i < 4 else 20) for i in range(1, 5)]
    config = FusionConfig(max_per_document=1)
    result = fuse([a, a, b, c, d], [a, a], 4, config)
    assert [row.chunk_id for row in result] == [a.chunk_id, d.chunk_id]
    assert result[0].score == pytest.approx(2 / 61)
    assert len({row.chunk_id for row in result}) == len(result)


def test_weights_can_disable_a_leg_and_ties_have_stable_order() -> None:
    a, b = candidate(1, 10), candidate(2, 20)
    assert fuse([b], [a], 2)[0].chunk_id == a.chunk_id
    assert fuse([a], [b], 2, FusionConfig(lexical_weight=0))[0].chunk_id == b.chunk_id
    assert fuse([a], [b], 2, FusionConfig(vector_weight=0))[0].chunk_id == a.chunk_id
    assert not fuse([], [], 10)
    for invalid in [
        {"lexical_weight": 0, "vector_weight": 0},
        {"vector_weight": float("nan")},
        {"rank_constant": 0},
        {"candidate_pool": 101},
        {"max_per_document": 0},
    ]:
        with pytest.raises(ValidationError):
            FusionConfig.model_validate(invalid)
