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
    return base / "palimnesis" / "palimnesis.db"


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
    serve.add_argument("--view", choices=["on", "off"], default="on",
                       help="bounded views: 'on' masks over the watermark, 'off' only "
                            "enforces budgets")
    serve.add_argument("--input-budget", type=int, metavar="TOKENS",
                       help="input budget cap (default 48000; never above capacity)")
    files = serve.add_mutually_exclusive_group()
    files.add_argument("--transcripts", type=Path, metavar="DIR",
                       help="transcript files root (default: 'transcripts' beside the archive)")
    files.add_argument("--no-transcripts", action="store_true",
                       help="do not publish transcript files")


def _settings(args: argparse.Namespace) -> Settings:
    if args.capture_dir and not args.passthrough:
        # Archive mode stores exact request bodies and generated content itself;
        # raw exchange capture is a passthrough diagnostic.
        print("error: --capture-dir requires --passthrough (archive mode already stores "
              "exact request bodies)", file=sys.stderr)
        raise SystemExit(2)
    db_path = None if args.passthrough else (args.db or default_db_path())
    return Settings(upstream_base_url=args.upstream, capture_dir=args.capture_dir,
                    db_path=db_path, synchronous=args.synchronous, view=args.view,
                    input_budget=args.input_budget, transcripts=args.transcripts,
                    transcripts_enabled=not args.no_transcripts)


def serve_settings(argv: list[str]) -> Settings:
    """The Settings `palimnesis serve` would run with for these arguments."""
    parser = argparse.ArgumentParser(prog="palimnesis serve")
    _add_serve_arguments(parser)
    return _settings(parser.parse_args(argv))


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app
    from .server import uvicorn_config

    settings = _settings(args)
    if settings.db_path is not None:
        from .projection import ProjectionError
        from .projector import check_root

        if settings.transcripts is not None and settings.transcripts_enabled:
            try:
                check_root(settings.transcripts)
            except ProjectionError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"archive: {settings.db_path} (synchronous={settings.synchronous})")
    else:
        print("passthrough: nothing is archived")
    uvicorn.Server(uvicorn_config(create_app(settings), host=args.host, port=args.port)).run()
    return 0


def _read_only(db: Path):
    import sqlite3

    if not db.exists():
        print(f"error: no archive at {db}", file=sys.stderr)
        raise SystemExit(2)
    # A proper file URI: '#', '%' and '?' in the path must not become URI syntax
    # (which would drop mode=ro and open, or create, a different file).
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)


def _catalog(args: argparse.Namespace) -> int:
    """Print one catalog page of a session (inspection; never model-facing in Phase 2)."""
    from . import catalog, ledger, profile

    counter = profile.load(profile.DEFAULT_PROFILE, "http://inspect.invalid").counter
    branch = ledger.branch_id_for(args.session)
    conn = _read_only(args.db or default_db_path())
    try:
        if args.cursor:
            page = catalog.next(conn, branch, args.cursor, count=counter.count_cached)
        elif args.page:
            page = catalog.page(conn, branch, args.page, count=counter.count_cached)
        else:
            page = catalog.first(conn, branch, count=counter.count_cached)
    except catalog.CatalogError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    print(f"page {page.number} · cursor {page.cursor} · next {page.next or '-'}")
    for e in page.entries:
        flags = ",".join(e.flags) or "-"
        print(f"§{e.alias} {e.seq} {e.role} {e.kind} {e.tokens} {flags} {e.preview}")
    return 0


def _excerpts(args: argparse.Namespace) -> int:
    """List a session's excerpt blocks (inspection only)."""
    from . import ledger

    conn = _read_only(args.db or default_db_path())
    try:
        blocks = ledger.excerpt_blocks(conn, ledger.branch_id_for(args.session))
        aliases = dict(conn.execute("SELECT target_id, alias FROM aliases"))
    finally:
        conn.close()
    if not blocks:
        print(f"no excerpt blocks for session {args.session}")
    for host, b in blocks.items():
        print(f"host §{aliases.get(host, host)} · status {b.status} · charge {b.token_charge}"
              f" of {b.allocation} · items {len(b.items)} · query {b.query!r}"
              f" · {b.query_version}/{b.retrieval_version}/{b.renderer_version}")
    return 0


def _transcript_context(args: argparse.Namespace):
    from . import profile
    from .projection import ProjectionError
    from .projector import check_root, default_root

    db = args.db or default_db_path()
    root = args.root or default_root(db)
    try:
        check_root(root)
    except ProjectionError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2)
    upstream = profile.load(profile.DEFAULT_PROFILE, "http://inspect.invalid")
    return db, Path(root), upstream


def _snapshot(conn, session: str, **kw):
    from . import projector

    conn.execute("BEGIN")
    try:
        return projector.load(conn, session, **kw)
    finally:
        conn.execute("COMMIT")


def _transcripts_rebuild(args: argparse.Namespace) -> int:
    """Re-project a session's transcript files from the archive (no inference)."""
    from . import projector
    from .projection import ProjectionError

    try:
        db, root, upstream = _transcript_context(args)
    except SystemExit as e:
        return e.code
    conn = _read_only(db)
    try:
        snapshot = _snapshot(conn, args.session)
    except ProjectionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    projector.prepare_root(root, empty_staging=False)
    try:
        result = projector.publish(root, snapshot,
                                   added_tokens=upstream.counter.added_token_strings,
                                   count=upstream.counter.count_cached, profile=upstream.id,
                                   repair=True)
    except ProjectionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"transcripts: {projector.session_dir(root, args.session)} · generation "
          f"{result.generation} · {result.turns} turns · {result.written} files written")
    return 0


def _transcripts_verify(args: argparse.Namespace) -> int:
    """Check a session's published transcript files against the archive."""
    import json as _json

    from . import projection, projector

    try:
        db, root, upstream = _transcript_context(args)
    except SystemExit as e:
        return e.code
    directory = projector.session_dir(root, args.session)
    read = projector.read_published(directory)
    try:
        cutoff = _json.loads(read("manifest.json"))["archive_cutoff_seq"]
    except (OSError, ValueError, KeyError):
        print(f"error: no published transcripts at {directory}", file=sys.stderr)
        return 1
    conn = _read_only(db)
    try:
        expected = _snapshot(conn, args.session, max_seq=cutoff).payloads()
    except projection.ProjectionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    problems = projection.verify(read, expected,
                                 added_tokens=upstream.counter.added_token_strings)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"ok: {len(expected)} payloads verified at generation {cutoff}")
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
    parser = argparse.ArgumentParser(prog="palimnesis")
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

    inspect = commands.add_parser("catalog", help="print a session's catalog page")
    inspect.add_argument("session")
    inspect.add_argument("--db", type=Path, help=f"archive (default: {default_db_path()})")
    where = inspect.add_mutually_exclusive_group()
    where.add_argument("--page", type=int, help="1-based page number")
    where.add_argument("--cursor", help="a page's cursor or next cursor")
    inspect.set_defaults(run=_catalog)

    excerpts = commands.add_parser("excerpts", help="list a session's excerpt blocks")
    excerpts.add_argument("session")
    excerpts.add_argument("--db", type=Path, help=f"archive (default: {default_db_path()})")
    excerpts.set_defaults(run=_excerpts)

    transcripts = commands.add_parser("transcripts", help="rebuild or verify transcript files")
    transcript_commands = transcripts.add_subparsers(dest="transcripts_command", required=True)
    for name, run, text in (("rebuild", _transcripts_rebuild, "re-project from the archive"),
                            ("verify", _transcripts_verify, "check payloads against the archive")):
        sub = transcript_commands.add_parser(name, help=text)
        sub.add_argument("session")
        sub.add_argument("--db", type=Path, help=f"archive (default: {default_db_path()})")
        sub.add_argument("--root", type=Path,
                         help="transcripts root (default: 'transcripts' beside the archive)")
        sub.set_defaults(run=run)

    args = parser.parse_args(argv)
    return args.run(args)
