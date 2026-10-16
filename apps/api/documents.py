from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.documents.models import Document, DocumentVersion
from packages.documents.service import DocumentService, UploadUnavailable
from packages.documents.validation import InvalidUpload, validate_upload

from .dependencies import get_document_service

router = APIRouter(prefix="/documents", tags=["documents"])
type Service = Annotated[DocumentService, Depends(get_document_service)]


class VersionView(BaseModel):
    document_id: UUID
    version_id: UUID
    version_number: int
    owner_id: UUID
    title: str
    visibility: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    error_code: str | None
    created_at: datetime


def version_view(document: Document, version: DocumentVersion) -> VersionView:
    return VersionView(
        document_id=document.id,
        version_id=version.id,
        version_number=version.version_number,
        owner_id=document.owner_id,
        title=document.title,
        visibility=document.visibility,
        filename=version.filename,
        media_type=version.media_type,
        size_bytes=version.size_bytes,
        sha256=version.sha256,
        status=version.status,
        error_code=version.error_code,
        created_at=version.created_at,
    )


@router.post(
    "",
    status_code=201,
    response_model=VersionView,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload(request: Request, service: Service) -> VersionView:
    service.require_upload()  # Authorize before multipart parsing or reading file bytes.
    settings = request.app.state.settings
    try:
        async with request.form(max_files=1, max_fields=0, max_part_size=4096) as form:
            file = form.get("file")
            if (
                len(form.multi_items()) != 1
                or not isinstance(file, UploadFile)
                or not file.filename
            ):
                raise HTTPException(422, "Envía un único archivo en el campo file")
            content = await file.read(settings.upload_max_bytes + 1)
            verified = await run_in_threadpool(validate_upload, file.filename, content, settings)
    except StarletteHTTPException as exc:
        if request.scope.get("upload_too_large"):
            raise HTTPException(413, "La solicitud supera el tamaño permitido") from exc
        raise HTTPException(exc.status_code, "Solicitud de carga inválida") from exc
    except InvalidUpload as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    try:
        document, version = await run_in_threadpool(service.create, verified)
    except (UploadUnavailable, SQLAlchemyError) as exc:
        raise HTTPException(503, "No se pudo almacenar el archivo; inténtalo de nuevo") from exc
    return version_view(document, version)


@router.get("/{document_id}/versions/{version_id}", response_model=VersionView)
def get_version(document_id: UUID, version_id: UUID, service: Service) -> VersionView:
    return version_view(*service.version(document_id, version_id))
