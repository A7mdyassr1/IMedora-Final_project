"""
Test environment.

Tests must never touch the developer's real database, so DATABASE_URL is
forced BEFORE the app is imported:
  - TEST_DATABASE_URL set  -> that (disposable) database is used, and the
                              integration tests run against it
  - TEST_DATABASE_URL unset -> an unreachable dummy URL; the engine is lazy,
                              so unit tests never open a connection and the
                              integration tests are skipped

B1 tests only run SELECTs, but later phases will write data, so point
TEST_DATABASE_URL at a throwaway database (e.g. imedora_test), never
your dev data.
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # picks up TEST_DATABASE_URL if kept there

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql+psycopg2://test:test@127.0.0.1:1/imedora_test"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-used-anywhere-else-0123456789"
os.environ["LOG_JSON"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def real_db_url():
    if not TEST_DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    return TEST_DATABASE_URL


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:  # entering the context runs the startup/shutdown lifespan
        yield c
