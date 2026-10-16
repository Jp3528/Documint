"""Bounded structural validation; MIME sent by a client never authorizes content."""

import hashlib
import io
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring
from pypdf import PdfReader
from pypdf.generic import DictionaryObject

from packages.config import Settings


class InvalidUpload(Exception):
    def __init__(self, message: str, status: int = 415) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ValidatedUpload:
    content: bytes
    filename: str
    media_type: str
    sha256: str


def safe_filename(filename: str) -> str:
    name = unicodedata.normalize("NFKC", filename).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isalnum() or c in " ._()-").strip(" .")
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem or len(extension) > 8:
        raise InvalidUpload("Nombre de archivo inválido")
    return f"{stem[:160]}.{extension.lower()}"


def validate_docx(content: bytes, settings: Settings) -> None:
    with ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 1000 or len(names) != len(set(names)):
            raise ValueError("invalid archive entries")
        if sum(entry.file_size for entry in entries) > settings.docx_max_expanded_bytes:
            raise ValueError("expanded archive exceeds budget")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                entry.flag_bits & 1
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or "vbaproject" in entry.filename.casefold()
            ):
                raise ValueError("unsupported archive entry")
        types = fromstring(archive.read("[Content_Types].xml"))
        expected = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        )
        if not any(
            node.attrib.get("PartName") == "/word/document.xml"
            and node.attrib.get("ContentType") == expected
            for node in types
        ):
            raise ValueError("not an ordinary docx document")
        document = fromstring(archive.read("word/document.xml"))
        if document.tag != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document":
            raise ValueError("invalid main document")
        if "_rels/.rels" not in names or archive.testzip() is not None:
            raise ValueError("invalid archive structure")


def validate_upload(filename: str, content: bytes, settings: Settings) -> ValidatedUpload:
    if len(content) > settings.upload_max_bytes:
        raise InvalidUpload("El archivo supera el tamaño permitido", 413)
    if not content:
        raise InvalidUpload("El archivo está vacío", 422)
    name = safe_filename(filename)
    extension = PurePosixPath(name).suffix
    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
    }
    if extension not in media_types:
        raise InvalidUpload("Formato no permitido: utiliza PDF, DOCX, TXT o MD")
    try:
        if extension == ".pdf":
            if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:]:
                raise ValueError("invalid pdf signature")
            reader = PdfReader(io.BytesIO(content), strict=True)
            root = reader.trailer["/Root"]
            if (
                reader.is_encrypted
                or not isinstance(root, DictionaryObject)
                or root.get("/Type") != "/Catalog"
            ):
                raise ValueError("unsupported pdf")
        elif extension == ".docx":
            validate_docx(content, settings)
        else:
            text = content.decode("utf-8-sig")
            if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in text):
                raise ValueError("binary content")
    except InvalidUpload:
        raise
    except Exception as exc:
        # Parser exceptions may contain document text or names. Never return them to a client.
        raise InvalidUpload("El contenido no corresponde a un archivo permitido y válido") from exc
    return ValidatedUpload(
        content, name, media_types[extension], hashlib.sha256(content).hexdigest()
    )
