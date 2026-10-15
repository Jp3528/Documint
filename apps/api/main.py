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

from .auth import profile_router
from .auth import router as auth_router
from .readiness import ReadinessResponse, dependency_probes, evaluate


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

    application = FastAPI(title="DocuMind AI", version=__version__, lifespan=lifespan)
    application.state.settings = config
    probes = dependency_probes(config)
    application.include_router(auth_router)
    application.include_router(profile_router)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        # Validation errors can contain raw passwords in their `input`; never echo them.
        return JSONResponse({"detail": "Datos de solicitud inválidos"}, status_code=422)

    @application.middleware("http")
    async def protect_auth_cache(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/auth/") or request.url.path == "/me":
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
