from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.identity.models import User
from packages.identity.organization import load_actor
from packages.providers.factory import make_embedding_provider, make_llm_provider
from packages.rag.service import AnswerService, AnswerView
from packages.retrieval.contracts import SearchRequest

from .dependencies import current_user, get_app_settings, get_session

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/answers", response_model=AnswerView)
def answer(
    payload: SearchRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> AnswerView:
    service = AnswerService(
        db,
        load_actor(db, user),
        settings,
        make_embedding_provider(settings),
        make_llm_provider(settings),
    )
    return service.answer(payload).view
