from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.providers.factory import make_embedding_provider
from packages.retrieval.citations import CitationService, SearchView, SourceView
from packages.retrieval.contracts import SearchRequest
from packages.retrieval.service import RetrievalService

from .dependencies import current_user, get_app_settings, get_session

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchView)
def search(
    payload: SearchRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SearchView:
    service = RetrievalService(db, load_actor(db, user))
    if payload.method == "lexical":
        result = service.lexical(payload)
    else:
        provider = make_embedding_provider(settings)
        result = (
            service.hybrid(payload, provider)
            if payload.method == "hybrid"
            else service.vector(payload, provider)
        )
    return CitationService(db, service.actor).search_view(result)


@router.get("/sources/{chunk_id}", response_model=SourceView)
def source(
    chunk_id: UUID,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> SourceView:
    return CitationService(db, load_actor(db, user)).source(chunk_id)
