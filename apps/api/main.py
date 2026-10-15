"""Application entrypoint; business features are introduced in later sessions."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from packages import __version__


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["documind-api"] = "documind-api"
    version: str = __version__


def create_app() -> FastAPI:
    application = FastAPI(title="DocuMind AI", version=__version__)

    @application.get("/health", response_model=HealthResponse, tags=["operations"])
    def health() -> HealthResponse:
        """Process liveness only; dependency readiness is introduced in session 0B."""
        return HealthResponse()

    return application


app = create_app()
