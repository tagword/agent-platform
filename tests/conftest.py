"""Pytest fixtures: isolated DB per test, FastAPI TestClient."""

from __future__ import annotations

import os

# Set up test environment BEFORE importing anything that reads config
os.environ["AGENT_PLATFORM_HOME"] = "/tmp/agent-platform-test"
os.environ["AGENT_PLATFORM_JWT_SECRET"] = "test-secret-do-not-use-in-prod-must-be-32+chars"

import pytest
from fastapi.testclient import TestClient

from gateway import config
from gateway.db import repo


@pytest.fixture(autouse=True)
def _reset_state():
    """Wipe DB and uploads dir before each test for full isolation."""
    import shutil
    repo.reset_db_for_tests()
    if config.UPLOADS_DIR.exists():
        shutil.rmtree(config.UPLOADS_DIR, ignore_errors=True)
    config.ensure_dirs()
    repo.init_db()
    yield
    repo.reset_db_for_tests()
    if config.UPLOADS_DIR.exists():
        shutil.rmtree(config.UPLOADS_DIR, ignore_errors=True)


@pytest.fixture
def client() -> TestClient:
    from gateway.app import create_app
    from gateway.async_runner import reset_queue
    # Ensure no stale queue from a prior test's event loop
    reset_queue()
    app = create_app()
    with TestClient(app) as c:
        # Ensure the app's lifespan started a fresh queue bound to this loop
        reset_queue()
        yield c
    reset_queue()
