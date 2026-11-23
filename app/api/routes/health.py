import logging

from fastapi import APIRouter
from redis import Redis
from sqlalchemy import text

import app.database as database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness probe. It does not check dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def ready():
    """Readiness probe for PostgreSQL and Redis."""
    database_state = _database_status()
    redis_state = _redis_status()
    ready_ok = database_state == "ok" and redis_state == "ok"
    payload = {"status": "ok" if ready_ok else "degraded", "database": database_state, "redis": redis_state}
    if ready_ok:
        return payload
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=503, content=payload)


def _database_status() -> str:
    try:
        database.init_engine()
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        logger.exception("database readiness check failed")
        return "unavailable"


def _redis_status() -> str:
    try:
        from app.config import get_settings

        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
        client.ping()
        return "ok"
    except Exception:
        logger.info("redis readiness check failed")
        return "unavailable"
