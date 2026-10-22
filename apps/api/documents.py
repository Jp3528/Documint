import hashlib
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.documents.library import LibraryService
from packages.documents.models import Document, DocumentGrant, DocumentVersion
from packages.documents.service import UploadUnavailable
from packages.documents.validation import InvalidUpload, ValidatedUpload, validate_upload
from packages.identity.models import Department
from packages.identity.policies import RoleName

from .dependencies import get_document_service
from .organization import Page, Pagination, Params

router = APIRouter(prefix="/documents", tags=["documents"])
type Service = Annotated[LibraryService, Depends(get_document_service)]


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
    verified = await read_upload(request)
    try:
        document, version = await run_in_threadpool(service.create, verified)
    except (UploadUnavailable, SQLAlchemyError) as exc:
        raise HTTPException(503, "No se pudo almacenar el archivo; inténtalo de nuevo") from exc
    return version_view(document, version)


async def read_upload(request: Request) -> ValidatedUpload:
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
    return verified


@router.get("/{document_id}/versions/{version_id}", response_model=VersionView)
def get_version(document_id: UUID, version_id: UUID, service: Service) -> VersionView:
    return version_view(*service.version(document_id, version_id))


class DocumentView(BaseModel):
    id: UUID
    title: str
    owner_id: UUID
    department_id: UUID | None
    department_name: str | None
    visibility: Literal["COMPANY", "DEPARTMENT", "RESTRICTED"]
    archived: bool
    can_manage: bool
    created_at: datetime
    latest_version: VersionView | None
    active_index_revision_id: UUID | None


def document_view(document: Document, service: LibraryService) -> DocumentView:
    latest = service.latest_version(document.id)
    department = (
        service.db.get(Department, document.department_id) if document.department_id else None
    )
    return DocumentView(
        id=document.id,
        title=document.title,
        owner_id=document.owner_id,
        department_id=document.department_id,
        department_name=department.name if department else None,
        visibility=document.visibility,
        archived=document.archived,
        can_manage=service.may_manage(document),
        created_at=document.created_at,
        latest_version=version_view(document, latest) if latest else None,
        active_index_revision_id=document.active_index_revision_id,
    )


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]
        | None
    ) = None
    visibility: Literal["COMPANY", "DEPARTMENT", "RESTRICTED"] | None = None
    department_id: UUID | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def non_nullable_fields(self) -> "DocumentUpdate":
        if any(
            getattr(self, key) is None for key in self.model_fields_set if key != "department_id"
        ):
            raise ValueError("field cannot be null")
        return self


class DocumentParams(Pagination):
    include_archived: bool = False


@router.get("", response_model=Page[DocumentView])
def list_documents(
    params: Annotated[DocumentParams, Query()], service: Service
) -> Page[DocumentView]:
    rows, total = service.list_documents(params.offset, params.limit, params.include_archived)
    return Page(
        items=[document_view(row, service) for row in rows],
        total=total,
        offset=params.offset,
        limit=params.limit,
    )


@router.get("/{document_id}", response_model=DocumentView)
def get_document(document_id: UUID, service: Service) -> DocumentView:
    return document_view(service.document(document_id), service)


@router.patch("/{document_id}", response_model=DocumentView)
def update_document(document_id: UUID, payload: DocumentUpdate, service: Service) -> DocumentView:
    return document_view(
        service.update_document(document_id, payload.model_dump(exclude_unset=True)), service
    )


@router.get("/{document_id}/versions", response_model=Page[VersionView])
def list_versions(document_id: UUID, params: Params, service: Service) -> Page[VersionView]:
    document, rows, total = service.list_versions(document_id, params.offset, params.limit)
    return Page(
        items=[version_view(document, row) for row in rows], total=total, **params.model_dump()
    )


@router.post("/{document_id}/versions", status_code=201, response_model=VersionView)
async def new_version(document_id: UUID, request: Request, service: Service) -> VersionView:
    await run_in_threadpool(service.document, document_id, manage=True)
    verified = await read_upload(request)
    try:
        result = await run_in_threadpool(service.new_version, document_id, verified)
    except (UploadUnavailable, SQLAlchemyError) as exc:
        raise HTTPException(503, "No se pudo almacenar la nueva versión") from exc
    return version_view(*result)


@router.get("/{document_id}/versions/{version_id}/original")
def original(document_id: UUID, version_id: UUID, service: Service) -> Response:
    _, version = service.version(document_id, version_id)
    if version.status in {"UPLOADING", "UPLOAD_FAILED"}:
        raise HTTPException(409, "El original todavía no está disponible")
    try:
        content = service.storage.get(version.object_key)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise HTTPException(503, "El original no está disponible temporalmente") from exc
    if len(content) != version.size_bytes or hashlib.sha256(content).hexdigest() != version.sha256:
        raise HTTPException(503, "No se pudo verificar el original")
    encoded_name = quote(version.filename, safe="")
    return Response(
        content,
        media_type=version.media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=original; filename*=UTF-8''{encoded_name}"
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


class GrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID | None = None
    role_name: RoleName | None = None
    permission: Literal["READ", "MANAGE"]

    @model_validator(mode="after")
    def one_subject(self) -> "GrantInput":
        if (self.user_id is None) == (self.role_name is None):
            raise ValueError("exactly one subject required")
        return self


class GrantView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID | None
    role_name: str | None
    permission: str
    granted_by: UUID


@router.get("/{document_id}/grants", response_model=Page[GrantView])
def grants(document_id: UUID, params: Params, service: Service) -> Page[GrantView]:
    rows, total = service.list_grants(document_id, params.offset, params.limit)
    return Page(
        items=[GrantView.model_validate(row) for row in rows], total=total, **params.model_dump()
    )


@router.post("/{document_id}/grants", response_model=GrantView, status_code=201)
def grant(document_id: UUID, payload: GrantInput, service: Service) -> DocumentGrant:
    return service.add_grant(document_id, payload.user_id, payload.role_name, payload.permission)


@router.delete("/{document_id}/grants/{grant_id}", status_code=204)
def revoke_grant(document_id: UUID, grant_id: UUID, service: Service) -> None:
    service.remove_grant(document_id, grant_id)
