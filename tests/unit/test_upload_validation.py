import hashlib
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from packages.config import Settings
from packages.documents.validation import InvalidUpload, safe_filename, validate_upload

FILES = Path(__file__).resolve().parents[2] / "demo_corpus/files"


@pytest.mark.parametrize("path", sorted(FILES.iterdir()), ids=lambda p: p.name)
def test_valid_corpus_files_preserve_bytes_and_hashes(path: Path) -> None:
    content = path.read_bytes()
    upload = validate_upload(path.name, content, Settings())
    assert upload.content == content and upload.sha256 == hashlib.sha256(content).hexdigest()
    assert upload.filename == path.name


@pytest.mark.parametrize(
    ("filename", "content", "status"),
    [
        ("empty.txt", b"", 422),
        ("script.exe", b"hello", 415),
        ("fake.pdf", b"%PDF-1.7\nnot a pdf\n%%EOF", 415),
        ("fake.docx", b"not a ZIP", 415),
        ("binary.txt", b"hello\x00world", 415),
        ("invalid.md", b"\xff\xfe", 415),
        ("no-extension", b"hello", 415),
    ],
)
def test_mismatches_and_binary_text_are_rejected(
    filename: str, content: bytes, status: int
) -> None:
    with pytest.raises(InvalidUpload) as error:
        validate_upload(filename, content, Settings())
    assert error.value.status == status


def test_exact_size_limit_is_allowed_and_one_extra_byte_is_rejected() -> None:
    settings = Settings(upload_max_bytes=4)
    assert validate_upload("valid.txt", b"abcd", settings).content == b"abcd"
    with pytest.raises(InvalidUpload) as error:
        validate_upload("large.txt", b"abcde", settings)
    assert error.value.status == 413


def test_path_and_control_characters_never_survive_display_filename() -> None:
    assert safe_filename("C:\\private\\../../report<script>\x00.PDF") == "reportscript.pdf"
    assert len(safe_filename("é" * 500 + ".docx")) <= 180


def test_encrypted_pdf_is_rejected_without_attempting_a_password() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("test-only")
    content = io.BytesIO()
    writer.write(content)
    with pytest.raises(InvalidUpload):
        validate_upload("encrypted.pdf", content.getvalue(), Settings())


@pytest.mark.parametrize("attack", ["traversal", "macro", "entity", "expanded", "duplicate"])
def test_docx_archive_and_xml_budgets_reject_attacks(attack: str) -> None:
    source = next(FILES.glob("*.docx"))
    output = io.BytesIO()
    with ZipFile(source) as original, ZipFile(output, "w", ZIP_DEFLATED) as changed:
        for entry in original.infolist():
            value = original.read(entry.filename)
            if attack == "entity" and entry.filename == "word/document.xml":
                value = b'<!DOCTYPE d [<!ENTITY secret SYSTEM "file:///private">]><d>&secret;</d>'
            changed.writestr(entry.filename, value)
        if attack == "traversal":
            changed.writestr("../outside.txt", b"ignored")
        if attack == "macro":
            changed.writestr("word/vbaProject.bin", b"not executed")
        if attack == "duplicate":
            with pytest.warns(UserWarning):
                changed.writestr("word/document.xml", b"duplicate")
    settings = Settings(docx_max_expanded_bytes=10) if attack == "expanded" else Settings()
    with pytest.raises(InvalidUpload):
        validate_upload("attack.docx", output.getvalue(), settings)
