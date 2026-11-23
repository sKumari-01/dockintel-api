import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="dockintel-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db")
os.environ["STORAGE_DIR"] = os.path.join(_TMP, "storage")
os.environ["CELERY_EAGER"] = "true"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/15"

import pytest
from fastapi.testclient import TestClient

import app.database as database
from app.main import app
from app.models import Base


@pytest.fixture
def client():
    database.init_engine()
    Base.metadata.drop_all(bind=database.engine)
    Base.metadata.create_all(bind=database.engine)
    with TestClient(app) as test_client:
        yield test_client
