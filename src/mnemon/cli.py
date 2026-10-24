"""Command line: run the proxy and mint/resume session base URLs."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

from .config import Settings
from .sessions import SessionError, resolve_session

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000


def _print_urls(session: str, host: str, port: int) -> None:
    base = f"http://{host}:{port}/s/{session}"
    print(f"session: {session}")
    print(f"openai_base_url: {base}/v1")
    print(f"anthropic_base_url: {base}")


def default_db_path() -> Path:
    """Per-user archive location (D10.11): %LOCALAPPDATA% on Windows, XDG elsewhere."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "mnemon" / "mnemon.db"


def _add_serve_arguments(serve: argparse.ArgumentParser) -> None:
    serve.add_argument("--upstream", required=True, help="upstream origin, e.g. http://host:8080")
    serve.add_argument(
        "--capture-dir", type=Path, help="opt-in raw exchange capture (stores conversation bodies)"
    )
    mode = serve.add_mutually_exclusive_group()
    mode.add_argument("--db", type=Path, help=f"archive database (default: {default_db_path()})")
    mode.add_argument("--passthrough", action="store_true",
                      help="relay without archiving or rewriting")
    serve.add_argument(
        "--synchronous", choices=["FULL", "NORMAL"], default="FULL",
        help="SQLite durability: FULL survives power loss; NORMAL only process crashes",
    )


def _settings(args: argparse.Namespace) -> Settings:
    db_path = None if args.passthrough else (args.db or default_db_path())
    return Settings(upstream_base_url=args.upstream, capture_dir=args.capture_dir,
                    db_path=db_path, synchronous=args.synchronous)


def serve_settings(argv: list[str]) -> Settings:
    """The Settings `mnemon serve` would run with for these arguments."""
    parser = argparse.ArgumentParser(prog="mnemon serve")
    _add_serve_arguments(parser)
    return _settings(parser.parse_args(argv))


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app
    from .server import uvicorn_config

    settings = _settings(args)
    if settings.db_path is not None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"archive: {settings.db_path} (synchronous={settings.synchronous})")
    else:
        print("passthrough: nothing is archived")
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
    _add_serve_arguments(serve)
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
