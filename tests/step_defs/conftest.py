"""Shared fixtures for all test levels."""

import os

import pytest

from backend.schemas import WS_ENDPOINT


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"Environment variable {name} is required")
    return value


def _derive_ws_url(backend_url: str) -> str:
    """Derive WebSocket URL from backend HTTP URL + WS_ENDPOINT."""
    if backend_url.startswith("https://"):
        return "wss://" + backend_url[len("https://") :] + WS_ENDPOINT
    return "ws://" + backend_url[len("http://") :] + WS_ENDPOINT


@pytest.fixture(scope="session")
def backend_url():
    return _require_env("TEST_BACKEND_URL")


@pytest.fixture(scope="session")
def backend_ws_url(backend_url):
    return _derive_ws_url(backend_url)


@pytest.fixture(scope="session")
def frontend_url():
    return _require_env("TEST_FRONTEND_URL")
