from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ParserError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Locator(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    format: Literal["pdf", "docx", "txt", "md"]
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    heading_path: tuple[str, ...] = ()
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    table_path: tuple[int, ...] = ()
    row: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def location_present(self) -> Self:
        if self.format == "pdf" and self.page is None:
            raise ValueError("pdf requires page")
        if self.format == "docx" and self.paragraph is None:
            raise ValueError("docx requires paragraph")
        if self.format in {"txt", "md"} and (
            self.line_start is None or self.line_end is None or self.line_end < self.line_start
        ):
            raise ValueError("text requires ordered line range")
        return self


class TextBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int = Field(default=0, ge=0)
    text: str = Field(min_length=1)
    kind: Literal["PARAGRAPH", "HEADING", "PAGE", "TABLE_CELL", "CODE"] = "PARAGRAPH"
    heading_level: int | None = Field(default=None, ge=0, le=9)
    locator: Locator


@dataclass(frozen=True)
class ParsedDocument:
    parser_revision: str
    source_sha256: str
    normalized_sha256: str
    blocks: tuple[TextBlock, ...]
    character_count: int
