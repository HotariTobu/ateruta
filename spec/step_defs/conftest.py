"""Shared fixtures for all test levels."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from dotenv import load_dotenv

from backend.schemas import WS_ENDPOINT


load_dotenv(Path(__file__).with_name(".env"), override=False)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"Environment variable {name} is required")
    return value


def _require_origin_url(name: str) -> str:
    value = _require_env(name)
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
        pytest.fail(f"Environment variable {name} must be an HTTP URL")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _require_base_url(name: str) -> str:
    return f"{_require_origin_url(name)}/"


def _derive_ws_url(backend_url: str) -> str:
    parsed = urlsplit(backend_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, WS_ENDPOINT, "", ""))


@pytest.fixture(scope="session")
def backend_url():
    return _require_origin_url("TEST_BACKEND_URL")


@pytest.fixture(scope="session")
def backend_ws_url(backend_url):
    return _derive_ws_url(backend_url)


@pytest.fixture(scope="session")
def frontend_url():
    return _require_base_url("TEST_FRONTEND_URL")
