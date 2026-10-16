from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.config import Settings
from packages.indexing.chunking import ChunkConfig, ChunkingError, chunk_blocks
from packages.parsers.contracts import Locator, TextBlock
from packages.parsers.registry import ParserRegistry

FILES = Path(__file__).resolve().parents[2] / "demo_corpus/files"


@pytest.mark.parametrize("path", sorted(FILES.iterdir()), ids=lambda p: p.name)
def test_chunking_is_deterministic_bounded_and_covers_source_characters(path: Path) -> None:
    blocks = ParserRegistry(Settings()).parse(path.name, path.read_bytes()).blocks
    config = ChunkConfig(max_characters=128, overlap_characters=16)
    chunks = chunk_blocks(blocks, config)
    assert chunks == chunk_blocks(blocks, config)
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    coverage: dict[int, set[int]] = {block.index: set() for block in blocks}
    for chunk in chunks:
        assert len(chunk.text) <= 128
        assert len({(span.locator.page, span.locator.heading_path) for span in chunk.spans}) == 1
        for span in chunk.spans:
            assert blocks[span.block_index].text[span.char_start : span.char_end] in chunk.text
            coverage[span.block_index].update(range(span.char_start, span.char_end))
    assert all(coverage[block.index] == set(range(len(block.text))) for block in blocks)


def test_exact_overlap_and_budget_are_character_counts_not_provider_tokens() -> None:
    block = TextBlock(
        text="abcdefghijklmnopqrstuvwxyz", locator=Locator(format="txt", line_start=1, line_end=1)
    )
    result = chunk_blocks((block,), ChunkConfig(max_characters=8, overlap_characters=2))
    assert [chunk.text for chunk in result] == ["abcdefgh", "ghijklmn", "mnopqrst", "stuvwxyz"]
    with pytest.raises(ValidationError):
        ChunkConfig(max_characters=8, overlap_characters=8)
    with pytest.raises(ChunkingError, match="CHUNK_LIMIT"):
        chunk_blocks((block,), ChunkConfig(max_characters=8, overlap_characters=2, max_chunks=1))
