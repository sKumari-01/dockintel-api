from celery import Celery

from app.config import get_settings

settings = get_settings()
broker = "memory://" if settings.celery_eager else settings.redis_url
backend = "cache+memory://" if settings.celery_eager else settings.redis_url

celery = Celery("dockintel", broker=broker, backend=backend)
celery.conf.update(
    task_always_eager=settings.celery_eager,
    task_eager_propagates=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

# Imported after the Celery app exists so the task decorator can register.
from app import tasks as tasks  # noqa: E402,F401
