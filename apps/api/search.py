from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.providers.factory import make_embedding_provider
from packages.retrieval.contracts import RetrievalResult, SearchRequest
from packages.retrieval.service import RetrievalService

from .dependencies import current_user, get_app_settings, get_session

router = APIRouter(tags=["search"])


@router.post("/search", response_model=RetrievalResult)
def search(
    payload: SearchRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> RetrievalResult:
    service = RetrievalService(db, load_actor(db, user))
    if payload.method == "lexical":
        return service.lexical(payload)
    provider = make_embedding_provider(settings)
    if payload.method == "hybrid":
        return service.hybrid(payload, provider)
    return service.vector(payload, provider)
