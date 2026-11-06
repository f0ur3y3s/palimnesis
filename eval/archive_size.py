"""How big an archive is, and what it is made of.

    uv run python eval/archive_size.py DB [DB ...] [--json OUT]

For each archive database (read-only) it reports the file size (database plus WAL),
bytes per table and index from ``dbstat`` (or column lengths when ``dbstat`` is not
compiled in), row counts, and the raw request bodies' logical size (what the client sent,
summed over every request) against their stored size (snapshots plus deltas). It also
counts the archived content: the text and tool data of every message, which is what the
transcript files publish.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def measure(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        page = conn.execute("PRAGMA page_size").fetchone()[0]
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        try:
            rows = conn.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name").fetchall()
            tables = {name: int(size) for name, size in rows}
        except sqlite3.OperationalError:
            tables = {}
        count = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        raw = conn.execute("SELECT COUNT(*), SUM(total_len), SUM(length(payload)),"
                           " SUM(format = 0), SUM(CASE WHEN format = 0 THEN length(payload) END)"
                           " FROM raw_bodies").fetchone()
        content = conn.execute("SELECT SUM(length(bytes)) FROM segments").fetchone()[0] or 0
        out = {
            "path": str(path),
            "file_bytes": path.stat().st_size + (path.with_name(path.name + "-wal").stat().st_size
                                                  if path.with_name(path.name + "-wal").exists() else 0),
            "page_bytes": page * pages,
            "tables": tables,
            "requests": count("requests"),
            "occurrences": count("occurrences"),
            "segments": count("segments"),
            "events": count("events"),
            "raw": {"records": raw[0], "logical": raw[1] or 0, "stored": raw[2] or 0,
                    "snapshots": raw[3] or 0, "snapshot_bytes": raw[4] or 0},
            "content_bytes": content,
        }
        return out
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dbs", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    rows = [measure(p) for p in a.dbs]
    for r in rows:
        print(f"{r['path']}: {r['file_bytes']:,} B, {r['requests']} requests, "
              f"raw logical {r['raw']['logical']:,} stored {r['raw']['stored']:,} "
              f"({r['raw']['snapshots']} snapshots, {r['raw']['snapshot_bytes']:,} B), "
              f"content {r['content_bytes']:,} B, segments {r['segments']:,}, events {r['events']:,}")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
