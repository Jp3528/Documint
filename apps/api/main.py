"""Application entrypoint; business features are introduced in later sessions."""

from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel

from packages import __version__
from packages.config import Settings, get_settings

from .readiness import ReadinessResponse, dependency_probes, evaluate


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["documind-api"] = "documind-api"
    version: str = __version__


def create_app(settings: Settings | None = None) -> FastAPI:
    application = FastAPI(title="DocuMind AI", version=__version__)
    probes = dependency_probes(settings or get_settings())

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
