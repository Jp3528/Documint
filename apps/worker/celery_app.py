"""Celery configuration without document processing or provider calls."""

from celery import Celery

from packages.config import Settings, get_settings


def create_celery_app(settings: Settings) -> Celery:
    application = Celery(
        "documind",
        broker=settings.redis_url,
        backend=settings.result_backend,
        include=["apps.worker.tasks"],
    )
    application.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
    )
    return application


celery_app = create_celery_app(get_settings())
