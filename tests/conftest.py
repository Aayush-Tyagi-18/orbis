"""Shared fixtures. Tests run against the Postgres in DATABASE_URL (a Neon test branch locally,
a postgres service container in CI). Each test gets its own user id, and its rows are wiped afterwards."""
import os
import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from backend.app import main

# store.py loads .env on import, which can bring a real API key back. Drop it only after the
# import and reset the cached extractor, so the tests always use the rule-based baseline.
os.environ.pop("ANTHROPIC_API_KEY", None)
main._extractor = None


def _user_from_header(request: Request) -> str:
    return request.headers["x-test-user"]


@pytest.fixture
def make_client():
    """Returns a function that makes a client signed in as a brand-new user."""
    main.app.dependency_overrides[main.current_user] = _user_from_header
    users: list[str] = []

    def make() -> TestClient:
        uid = f"test-{uuid.uuid4()}"
        users.append(uid)
        return TestClient(main.app, headers={"x-test-user": uid})

    yield make
    for uid in users:
        main.store.wipe(uid)
    main.app.dependency_overrides.clear()


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()
