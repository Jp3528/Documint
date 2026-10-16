"""Minimal registered worker task, intentionally independent of the RAG domain."""

from apps.worker.celery_app import celery_app
from apps.worker.processing import process_document


def smoke(message: str = "documind") -> dict[str, str]:
    return {"status": "ok", "service": "documind-worker", "message": message}


smoke_task = celery_app.task(name="documind.smoke")(smoke)
process_document_task = celery_app.task(
    name="documind.process_document", acks_late=True, reject_on_worker_lost=True
)(process_document)
