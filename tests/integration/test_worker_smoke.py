import pytest
from celery.contrib.testing.worker import start_worker

from apps.worker.celery_app import celery_app
from apps.worker.tasks import smoke_task


@pytest.mark.integration
def test_registered_task_runs_through_an_actual_worker() -> None:
    """An in-memory transport exercises dispatch, serialization and worker execution.

    This is not eager emulation and does not claim to test Redis connectivity.
    The Redis-backed smoke check is added in session 0B.
    """
    previous_broker = celery_app.conf.broker_url
    previous_backend = celery_app.conf.result_backend
    celery_app.conf.update(broker_url="memory://", result_backend="cache+memory://")
    try:
        with start_worker(celery_app, pool="solo", perform_ping_check=False):
            result = smoke_task.delay("prueba de conexión").get(timeout=10)
        assert result == {
            "status": "ok",
            "service": "documind-worker",
            "message": "prueba de conexión",
        }
    finally:
        celery_app.conf.update(broker_url=previous_broker, result_backend=previous_backend)
