"""Celery configuration without document processing or provider calls."""

import os

from celery import Celery

celery_app = Celery(
    "documind",
    broker=os.getenv("DOCUMIND_REDIS_URL", "redis://127.0.0.1:6379/0"),
    backend=os.getenv("DOCUMIND_RESULT_BACKEND", "redis://127.0.0.1:6379/1"),
    include=["apps.worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)
