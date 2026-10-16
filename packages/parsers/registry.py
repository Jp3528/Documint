"""Extract data and provenance. Document instructions are never executed."""

import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from importlib.metadata import version
from pathlib import PurePosixPath

from docx import Document as open_docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from markdown_it import MarkdownIt
from pypdf import PdfReader

from packages.config import Settings
from packages.documents.validation import InvalidUpload, validate_upload

from .contracts import Locator, ParsedDocument, ParserError, TextBlock


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n".join(
        re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip()
    )


def normalized_digest(blocks: Iterable[TextBlock]) -> str:
    canonical = json.dumps(
        [block.model_dump(mode="json") for block in blocks],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def pdf_blocks(content: bytes, settings: Settings) -> Iterator[TextBlock]:
    reader = PdfReader(io.BytesIO(content), strict=True)
    if len(reader.pages) > settings.parser_max_pdf_pages:
        raise ParserError("EXTRACTION_LIMIT")
    for page_number, page in enumerate(reader.pages, 1):
        text = normalize_text(page.extract_text() or "")
        if text:
            yield TextBlock(text=text, kind="PAGE", locator=Locator(format="pdf", page=page_number))


def docx_blocks(content: bytes, settings: Settings) -> Iterator[TextBlock]:
    document = open_docx(io.BytesIO(content))
    paragraph_number = table_number = 0
    seen_cells: set[object] = set()

    def walk(
        items: Iterable[Paragraph | Table],
        headings: list[tuple[int, str]],
        tables: tuple[int, ...] = (),
        row: int | None = None,
        column: int | None = None,
    ) -> Iterator[TextBlock]:
        nonlocal paragraph_number, table_number
        if len(tables) > 8:
            raise ParserError("EXTRACTION_LIMIT")
        for item in items:
            if isinstance(item, Table):
                table_number += 1
                table_path = (*tables, table_number)
                for row_number, table_row in enumerate(item.rows, 1):
                    for column_number, cell in enumerate(table_row.cells, 1):
                        # Merged cells share an XML node; keep its text once.
                        if cell._tc in seen_cells:
                            continue
                        seen_cells.add(cell._tc)
                        yield from walk(
                            cell.iter_inner_content(),
                            headings.copy(),
                            table_path,
                            row_number,
                            column_number,
                        )
                continue
            paragraph_number += 1
            text = normalize_text(item.text)
            if not text:
                continue
            name = item.style.name if item.style else ""
            match = re.fullmatch(r"Heading ([1-9])", name)
            level = int(match.group(1)) if match else 0 if name == "Title" else None
            if level is not None:
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, text))
            yield TextBlock(
                text=text,
                kind="HEADING" if level is not None else "TABLE_CELL" if tables else "PARAGRAPH",
                heading_level=level,
                locator=Locator(
                    format="docx",
                    paragraph=paragraph_number,
                    heading_path=tuple(value for _, value in headings),
                    table_path=tables,
                    row=row,
                    column=column,
                ),
            )

    yield from walk(document.iter_inner_content(), [])


def text_blocks(content: bytes, settings: Settings) -> Iterator[TextBlock]:
    lines = content.decode("utf-8-sig").splitlines()
    start = 0
    paragraph: list[str] = []
    for index, line in enumerate([*lines, ""], 1):
        if line.strip():
            if not paragraph:
                start = index
            paragraph.append(line)
        elif paragraph:
            yield TextBlock(
                text=normalize_text("\n".join(paragraph)),
                locator=Locator(format="txt", line_start=start, line_end=index - 1),
            )
            paragraph = []


def markdown_blocks(content: bytes, settings: Settings) -> Iterator[TextBlock]:
    tokens = MarkdownIt("commonmark", {"html": False}).parse(content.decode("utf-8-sig"))
    headings: list[tuple[int, str]] = []
    pending_heading: int | None = None
    for token in tokens:
        if token.type == "heading_open":
            pending_heading = int(token.tag[1:])
        elif token.type in {"inline", "fence", "code_block"} and token.map:
            text = (
                token.content
                if token.type in {"fence", "code_block"}
                else normalize_text(token.content)
            )
            if not text.strip():
                pending_heading = None
                continue
            level = pending_heading
            if level is not None:
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, text))
            yield TextBlock(
                text=text,
                kind="HEADING"
                if level is not None
                else "CODE"
                if token.type in {"fence", "code_block"}
                else "PARAGRAPH",
                heading_level=level,
                locator=Locator(
                    format="md",
                    line_start=token.map[0] + 1,
                    line_end=token.map[1],
                    heading_path=tuple(value for _, value in headings),
                ),
            )
            pending_heading = None


class ParserRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.parsers: dict[str, tuple[str, Callable[[bytes, Settings], Iterator[TextBlock]]]] = {
            ".pdf": (f"pdf-v1:pypdf-{version('pypdf')}", pdf_blocks),
            ".docx": (f"docx-v1:python-docx-{version('python-docx')}", docx_blocks),
            ".txt": ("txt-utf8-v1", text_blocks),
            ".md": (f"md-v1:markdown-it-py-{version('markdown-it-py')}", markdown_blocks),
        }

    def revision_for(self, filename: str) -> str:
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in self.parsers:
            raise ParserError("INVALID_DOCUMENT")
        return self.parsers[extension][0]

    def parse(self, filename: str, content: bytes) -> ParsedDocument:
        try:
            upload = validate_upload(filename, content, self.settings)
            extension = PurePosixPath(upload.filename).suffix
            revision, parser = self.parsers[extension]
            if (
                extension in {".txt", ".md"}
                and len(content.decode("utf-8-sig")) > self.settings.parser_max_characters
            ):
                raise ParserError("EXTRACTION_LIMIT")
            blocks: list[TextBlock] = []
            characters = 0
            for block in parser(content, self.settings):
                characters += len(block.text)
                if (
                    characters > self.settings.parser_max_characters
                    or len(blocks) >= self.settings.parser_max_blocks
                ):
                    raise ParserError("EXTRACTION_LIMIT")
                blocks.append(block.model_copy(update={"index": len(blocks)}))
            if not blocks:
                raise ParserError("NO_EXTRACTABLE_TEXT")
        except ParserError:
            raise
        except InvalidUpload as exc:
            raise ParserError("INVALID_DOCUMENT") from exc
        except Exception as exc:
            raise ParserError("PARSER_FAILED") from exc
        return ParsedDocument(
            revision,
            upload.sha256,
            normalized_digest(blocks),
            tuple(blocks),
            characters,
        )
