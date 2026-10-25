from __future__ import annotations

import socket
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings

from .fake_upstream import FakeUpstream
from .servers import serve


@dataclass
class Stack:
    upstream: FakeUpstream
    upstream_url: str
    proxy_url: str
    settings: Settings


@pytest.fixture
def stack() -> Iterator[Stack]:
    with _stack() as s:
        yield s


@pytest.fixture
def capturing_stack(tmp_path) -> Iterator[Stack]:
    with _stack(capture_dir=tmp_path / "captures") as s:
        yield s


@pytest.fixture
def archive_stack(tmp_path) -> Iterator[Stack]:
    with _stack(db_path=tmp_path / "archive.db") as s:
        yield s


@pytest.fixture
def stack_with_broken_capture(tmp_path) -> Iterator[Stack]:
    """Capture directory path is occupied by a file, so every write fails."""
    blocker = tmp_path / "captures"
    blocker.write_text("not a directory")
    with _stack(capture_dir=blocker) as s:
        yield s


@pytest.fixture
def dead_upstream_stack() -> Iterator[Stack]:
    """A proxy whose upstream port has nothing listening."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = Settings(upstream_base_url=f"http://127.0.0.1:{port}")
    with serve(create_app(settings), palimnesis=True) as proxy_url:
        yield Stack(FakeUpstream(), settings.upstream_base_url, proxy_url, settings)


@contextmanager
def _stack(**overrides) -> Iterator[Stack]:
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        settings = Settings(upstream_base_url=upstream_url, **overrides)
        with serve(create_app(settings), palimnesis=True) as proxy_url:
            yield Stack(fake, upstream_url, proxy_url, settings)
