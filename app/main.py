from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

import app.database as database
from app.api.routes import documents, health
from app.config import get_settings
from app.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_engine()
    # PostgreSQL schema is owned by Alembic. SQLite (used by the test suite)
    # creates tables here.
    if database.engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=database.engine)
    Path(get_settings().storage_dir).mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Extract searchable, structured data from PDFs and images.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(documents.search_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs", "health": "/health"}

    return app


app = create_app()
