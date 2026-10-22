"""Bounded, at-least-once Celery delivery for the document pipeline."""

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
        broker_connection_timeout=2,
        task_publish_retry=False,
        worker_prefetch_multiplier=1,
        task_routes={"documind.process_document": {"queue": "documind.processing"}},
        result_expires=3600,
        broker_transport_options={
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
            "visibility_timeout": 300,
        },
    )
    return application


celery_app = create_celery_app(get_settings())
