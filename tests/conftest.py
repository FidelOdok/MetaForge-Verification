import importlib.util
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from metaforge_verification.api import create_app
from metaforge_verification.config import Settings

spec = importlib.util.spec_from_file_location(
    "fixtures", Path(__file__).parents[1] / "examples" / "make_fixtures.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def payload():
    return module.lamp_request()


@pytest.fixture
def settings(tmp_path):
    database_url = os.environ.get("VERIFICATION_TEST_DATABASE_URL")
    if database_url:
        from sqlalchemy import create_engine

        from metaforge_verification.store import metadata

        engine = create_engine(database_url)
        metadata.drop_all(engine)  # Dedicated disposable CI database only.
        engine.dispose()
    return Settings(
        database_url=database_url or f"sqlite:///{tmp_path / 'jobs.db'}",
        artifact_root=tmp_path / "artifacts",
        auth_mode="tokens",
        tokens={"tenant-a-long-random-token": "a", "tenant-b-long-random-token": "b"},
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def headers():
    return {"Authorization": "Bearer tenant-a-long-random-token", "Idempotency-Key": "one"}
