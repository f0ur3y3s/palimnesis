"""Command line: run the proxy and mint/resume session base URLs."""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import datetime
from pathlib import Path

from .sessions import SessionError, resolve_session

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000


def _print_urls(session: str, host: str, port: int) -> None:
    base = f"http://{host}:{port}/s/{session}"
    print(f"session: {session}")
    print(f"openai_base_url: {base}/v1")
    print(f"anthropic_base_url: {base}")


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app
    from .config import Settings
    from .server import uvicorn_config

    settings = Settings(upstream_base_url=args.upstream, capture_dir=args.capture_dir)
    uvicorn.Server(uvicorn_config(create_app(settings), host=args.host, port=args.port)).run()
    return 0


def _session_new(args: argparse.Namespace) -> int:
    # Readable, sortable, and unguessable enough to avoid accidental reuse.
    session = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(4)}"
    _print_urls(session, args.host, args.port)
    return 0


def _session_url(args: argparse.Namespace) -> int:
    try:
        resolve_session(args.session, None)
    except SessionError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 2
    _print_urls(args.session, args.host, args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mnemon")
    commands = parser.add_subparsers(dest="command", required=True)

    def address(p: argparse.ArgumentParser) -> None:
        p.add_argument("--host", default=DEFAULT_HOST)
        p.add_argument("--port", type=int, default=DEFAULT_PORT)

    serve = commands.add_parser("serve", help="run the proxy")
    address(serve)
    serve.add_argument("--upstream", required=True, help="upstream origin, e.g. http://host:8080")
    serve.add_argument(
        "--capture-dir", type=Path, help="opt-in raw exchange capture (stores conversation bodies)"
    )
    serve.set_defaults(run=_serve)

    session = commands.add_parser("session", help="session base URLs")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    new = session_commands.add_parser("new", help="start an unrelated chat")
    address(new)
    new.set_defaults(run=_session_new)
    url = session_commands.add_parser("url", help="resume an existing session")
    url.add_argument("session")
    address(url)
    url.set_defaults(run=_session_url)

    args = parser.parse_args(argv)
    return args.run(args)
