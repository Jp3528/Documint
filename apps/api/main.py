"""Application entrypoint; business features are introduced in later sessions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker
from starlette.middleware.base import RequestResponseEndpoint

from packages import __version__
from packages.config import Settings, get_settings
from packages.database import make_engine
from packages.identity.organization import ConflictError, ForbiddenError, NotFoundError
from packages.providers.contracts import ProviderError

from .auth import profile_router
from .auth import router as auth_router
from .documents import router as documents_router
from .organization import router as organization_router
from .processing import router as processing_router
from .readiness import ReadinessResponse, dependency_probes, evaluate
from .search import router as search_router
from .upload_limit import UploadLimitMiddleware


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["documind-api"] = "documind-api"
    version: str = __version__


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(config)
        application.state.session_factory = sessionmaker(engine, expire_on_commit=False)
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(title="Documint", version=__version__, lifespan=lifespan)
    application.state.settings = config
    probes = dependency_probes(config)
    application.include_router(auth_router)
    application.include_router(profile_router)
    application.include_router(organization_router)
    application.include_router(documents_router)
    application.include_router(processing_router)
    application.include_router(search_router)
    application.add_middleware(UploadLimitMiddleware, max_bytes=config.upload_max_bytes)

    @application.exception_handler(ForbiddenError)
    async def forbidden(_request: Request, _exc: ForbiddenError) -> JSONResponse:
        return JSONResponse({"detail": "Operación no permitida"}, status_code=403)

    @application.exception_handler(NotFoundError)
    async def not_found(_request: Request, _exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"detail": "Recurso no disponible"}, status_code=404)

    @application.exception_handler(ConflictError)
    async def conflict(_request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        # Validation errors can contain raw passwords in their `input`; never echo them.
        return JSONResponse({"detail": "Datos de solicitud inválidos"}, status_code=422)

    @application.exception_handler(ProviderError)
    async def provider_unavailable(_request: Request, _exc: ProviderError) -> JSONResponse:
        return JSONResponse({"detail": "La búsqueda vectorial no está disponible"}, status_code=503)

    @application.middleware("http")
    async def protect_auth_cache(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if (
            request.url.path.startswith(
                ("/auth/", "/admin/", "/departments", "/documents", "/search")
            )
            or request.url.path == "/me"
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    def health() -> HealthResponse:
        """Process liveness only, independent of dependency availability."""
        return HealthResponse()

    @application.get(
        "/ready",
        response_model=ReadinessResponse,
        tags=["operations"],
        responses={503: {"model": ReadinessResponse}},
    )
    def ready(response: Response) -> ReadinessResponse:
        report = evaluate(probes)
        response.status_code = 200 if report.status == "ready" else 503
        return report

    return application


app = create_app()
