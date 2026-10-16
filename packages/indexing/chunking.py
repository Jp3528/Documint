import hashlib
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.parsers.contracts import Locator, TextBlock


class ChunkingError(Exception):
    pass


class ChunkConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strategy: Literal["section-characters-v1"] = "section-characters-v1"
    max_characters: int = Field(default=1200, ge=8, le=12000)
    overlap_characters: int = Field(default=150, ge=0)
    max_chunks: int = Field(default=20000, ge=1, le=100000)

    @model_validator(mode="after")
    def overlap_fits(self) -> Self:
        if self.overlap_characters >= self.max_characters:
            raise ValueError("overlap must be smaller than chunk size")
        return self


class EmbeddingProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=120)
    mode: Literal["FAKE", "REAL"]
    dimensions: int = Field(ge=1, le=4096)


class ChunkSpan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    block_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    locator: Locator


@dataclass(frozen=True)
class GeneratedChunk:
    position: int
    text: str
    sha256: str
    spans: tuple[ChunkSpan, ...]


def chunk_blocks(blocks: tuple[TextBlock, ...], config: ChunkConfig) -> tuple[GeneratedChunk, ...]:
    """Pack contiguous blocks within a page/heading, then apply exact character windows."""
    groups: list[list[TextBlock]] = []
    for block in blocks:
        key = (block.locator.format, block.locator.page, block.locator.heading_path)
        previous = groups[-1][-1] if groups else None
        old_key = (
            (previous.locator.format, previous.locator.page, previous.locator.heading_path)
            if previous
            else None
        )
        if key != old_key:
            groups.append([])
        groups[-1].append(block)
    result: list[GeneratedChunk] = []
    for group in groups:
        text = "\n\n".join(block.text for block in group)
        intervals: list[tuple[int, int, TextBlock]] = []
        offset = 0
        for block in group:
            intervals.append((offset, offset + len(block.text), block))
            offset += len(block.text) + 2
        start = 0
        while start < len(text):
            end = min(len(text), start + config.max_characters)
            value = text[start:end]
            spans = tuple(
                ChunkSpan(
                    block_index=block.index,
                    char_start=max(start, left) - left,
                    char_end=min(end, right) - left,
                    locator=block.locator,
                )
                for left, right, block in intervals
                if left < end and right > start
            )
            if value.strip() and spans:
                if len(result) >= config.max_chunks:
                    raise ChunkingError("CHUNK_LIMIT")
                result.append(
                    GeneratedChunk(
                        len(result), value, hashlib.sha256(value.encode()).hexdigest(), spans
                    )
                )
            if end == len(text):
                break
            start = end - config.overlap_characters
    if not result:
        raise ChunkingError("NO_CHUNKS")
    return tuple(result)
