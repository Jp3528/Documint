"""Minimal registered worker task, intentionally independent of the RAG domain."""

from apps.worker.celery_app import celery_app


def smoke(message: str = "documind") -> dict[str, str]:
    return {"status": "ok", "service": "documind-worker", "message": message}


smoke_task = celery_app.task(name="documind.smoke")(smoke)
