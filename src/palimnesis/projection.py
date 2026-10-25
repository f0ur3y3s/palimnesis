"""Transcript files, format t1: a pure, lossless projection of one branch (A1 Phase 3).

Mechanism from Eunoe (docs/papers.md): readable per-session transcript files, an
``index.md`` plus one ``turn-NNNN.md`` per turn, which the agent searches with its
ordinary tools when proactive recall misses. Adaptations (docs/plans/phase3.md §3):

- **Derived and deterministic.** Files are a function of the immutable archive (no
  timestamps), so ``palimnesis transcripts rebuild`` reproduces them byte for byte
  without inference. This module renders and parses; ``palimnesis.projector`` reads
  the archive and publishes.
- **Lossless payloads with provenance.** Every archived block appears once, delimited
  by ``[[§ALIAS.N · seq S · role · tool NAME (call_id) · kind]]`` … ``[[/§ALIAS.N]]``,
  its payload escaped with the excerpt escape (``excerpts.escape_payload``: a line
  starting ``[[`` or ``\\`` gains one ``\\``; profile special tokens are broken), so
  no payload line can read as a delimiter or a role marker. Header fields from clients
  are reduced to a safe charset. Tool-call arguments are their JSON verbatim;
  reasoning is included as labeled blocks.
- **Linked payloads.** A payload over 64 KiB, not valid UTF-8 (WTF-8 lone surrogates)
  or containing NUL is written to ``payloads/ALIAS.N.txt`` (``.bin`` when not UTF-8)
  as its exact bytes; the turn file shows its path, size, line count, SHA-256 and a
  head/tail preview. Payloads are verified by SHA-256 of the exact archived bytes.
- **Incomplete turns are marked** in the header (``incomplete: in progress``,
  ``cancelled``, ``abandoned``, ``failed`` or ``superseded``). A turn is sealed, and
  published once as ``turn-NNNN.md``, when a later turn exists; the newest turn is
  published as ``turn-NNNN.pKKKK.md`` where K is its revision (a count of the archive
  rows it renders, which only grows), so each change gets a new name.
- **Index lines are bounded** (about 60 tokens): file, turn, seq range, message count,
  tool counts by name, tokens (summed over blocks, as the catalog counts them),
  status and a 100-character instruction preview.

Files are LF-separated UTF-8; a CR inside a payload is payload text, so readers that
need exact payloads split on LF only (``extract`` does). Eunoe's own folding and its
per-message transcript layout are not taken.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from .catalog import _collapse
from .excerpts import _header_field, escape_payload, unescape_payload
from .stubs import fit_prefix

FORMAT = "t1"
LINK_BYTES = 64 * 1024
PREVIEW_CHARS = 100
INDEX_LINE_TOKENS = 60
INDEX_TOOLS = 4
LINKED_PREVIEW_LINES = 5
LINKED_PREVIEW_CHARS = 160

Count = Callable[[str], int]


class ProjectionError(Exception):
    """A transcript that cannot be rendered, parsed or verified."""


@dataclass(frozen=True)
class Block:
    idx: int
    kind: str  # text | reasoning | tool_call | tool_result
    data: bytes  # the exact archived bytes (UTF-8, or WTF-8 for lone surrogates)
    tool: str | None = None
    call_id: str | None = None
    final: bool = True  # False: generated content whose attempt has not ended


@dataclass(frozen=True)
class Message:
    """One archived occurrence."""

    seq: int
    alias: str
    role: str
    blocks: tuple[Block, ...] = ()
    flags: tuple[str, ...] = ()  # e.g. "superseded", "replaces §ALIAS", "internal"


@dataclass(frozen=True)
class Turn:
    number: int
    messages: tuple[Message, ...]
    status: str = "complete"
    sealed: bool = True
    revision: int = 0

    @property
    def name(self) -> str:
        return turn_file_name(self.number, None if self.sealed else self.revision)


@dataclass(frozen=True)
class Payload:
    address: str
    turn_file: str
    linked: str | None
    sha256: str
    size: int


@dataclass(frozen=True)
class Summary:
    """What the index needs about one rendered turn."""

    name: str
    number: int
    first_seq: int | None
    last_seq: int | None
    messages: int
    tools: tuple[tuple[str, int], ...]
    tokens: int
    status: str
    preview: str


@dataclass(frozen=True)
class RenderedTurn:
    name: str
    text: str
    files: dict[str, bytes] = field(default_factory=dict)  # linked payloads, by path
    payloads: tuple[Payload, ...] = ()
    summary: Summary | None = None

    @property
    def data(self) -> bytes:
        return self.text.encode("utf-8")


def turn_file_name(number: int, revision: int | None = None) -> str:
    return f"turn-{number:04d}.md" if revision is None else f"turn-{number:04d}.p{revision:04d}.md"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _seq_range(turn: Turn) -> tuple[int | None, int | None]:
    seqs = [m.seq for m in turn.messages]
    return (min(seqs), max(seqs)) if seqs else (None, None)


def _range_text(first: int | None, last: int | None) -> str:
    return "seq -" if first is None else f"seq {first}–{last}"


def _flag(f: str) -> str:
    if f.startswith("replaces §"):
        return "replaces §" + _header_field(f[len("replaces §"):])
    return _header_field(f)


def _preview_line(line: str) -> str:
    line = line.replace("\x00", "␀")
    return line if len(line) <= LINKED_PREVIEW_CHARS else line[:LINKED_PREVIEW_CHARS] + " …"


def _linked_body(path: str, data: bytes, added_tokens: Sequence[str]) -> list[str]:
    lines = data.decode("utf-8", "replace").split("\n")
    shown = 2 * LINKED_PREVIEW_LINES
    if len(lines) <= shown:
        head, tail = lines, []
    else:
        head, tail = lines[:LINKED_PREVIEW_LINES], lines[-LINKED_PREVIEW_LINES:]
    out = [f"payload {path} · {len(data)} bytes · {len(lines)} lines · sha256 {_sha(data)}"]
    out += [escape_payload(_preview_line(line), added_tokens) for line in head]
    if tail:
        out.append(f"… {len(lines) - shown} lines not shown …")
        out += [escape_payload(_preview_line(line), added_tokens) for line in tail]
    return out


def _payload_path(m: Message, b: Block, utf8: bool, revision: int) -> str:
    stem = f"payloads/{_header_field(m.alias)}.{b.idx}"
    if not b.final:
        stem += f".p{revision:04d}"
    return stem + (".txt" if utf8 else ".bin")


def _text_for_count(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _instruction_preview(turn: Turn, added_tokens: Sequence[str]) -> str:
    if turn.number == 0 or not turn.messages or turn.messages[0].role != "user":
        return "-"
    text = next((_text_for_count(b.data) for b in turn.messages[0].blocks if b.kind == "text"),
                "")
    collapsed = _collapse(text, PREVIEW_CHARS)
    preview = fit_prefix(collapsed[:PREVIEW_CHARS + 1], lambda s: len(s) <= PREVIEW_CHARS)
    return escape_payload(preview.rstrip(), added_tokens) or "-"


def render_turn(turn: Turn, *, added_tokens: Sequence[str], count: Count) -> RenderedTurn:
    """The t1 file for one turn, its linked payload files and its index summary."""
    name = turn.name
    first, last = _seq_range(turn)
    header = f"# turn {turn.number} · {turn.status} · {_range_text(first, last)}"
    if not turn.sealed:
        header += f" · revision {turn.revision}"
    lines = [header + f" · palimnesis transcript {FORMAT}", ""]
    files: dict[str, bytes] = {}
    payloads: list[Payload] = []
    tools: dict[str, int] = {}
    tokens = 0
    for m in turn.messages:
        flags = "".join(f" · {_flag(f)}" for f in m.flags)
        if not m.blocks:
            lines += [f"[[§{_header_field(m.alias)} · seq {m.seq} · {_header_field(m.role)}"
                      f" · no content{flags}]]", ""]
            continue
        for b in m.blocks:
            address = f"{_header_field(m.alias)}.{b.idx}"
            text = _decode_utf8(b.data)
            linked = text is None or len(b.data) > LINK_BYTES or "\x00" in text
            if b.kind == "tool_call" and b.tool:
                tools[b.tool] = tools.get(b.tool, 0) + 1
            tokens += count(_text_for_count(b.data))
            if linked:
                path = _payload_path(m, b, text is not None, turn.revision)
                files[path] = b.data
                body = _linked_body(path, b.data, added_tokens)
            else:
                path = None
                body = [escape_payload(text, added_tokens)]
            header_line = _block_header_line(m, b, flags, linked)
            lines += [header_line, *body, f"[[/§{address}]]", ""]
            payloads.append(Payload(address, name, path, _sha(b.data), len(b.data)))
    summary = Summary(name, turn.number, first, last, len(turn.messages),
                      tuple(sorted(tools.items(), key=lambda kv: (-kv[1], kv[0]))), tokens,
                      turn.status, _instruction_preview(turn, added_tokens))
    return RenderedTurn(name, "\n".join(lines), files, tuple(payloads), summary)


def _block_header_line(m: Message, b: Block, flags: str, linked: bool) -> str:
    fields = [f"§{_header_field(m.alias)}.{b.idx}", f"seq {m.seq}", _header_field(m.role)]
    if b.tool is not None or b.call_id is not None:
        call = f" ({_header_field(b.call_id)})" if b.call_id is not None else ""
        fields.append(f"tool {_header_field(b.tool or '?')}{call}")
    fields.append(_header_field(b.kind))
    return "[[" + " · ".join(fields) + flags + (" · linked" if linked else "") + "]]"


# --- index and manifest ------------------------------------------------------


def _index_line(s: Summary, count: Count) -> str:
    def line(tools_shown: int, preview: str) -> str:
        names = [f"{_header_field(n, 24)}×{c}" for n, c in s.tools[:tools_shown]]
        if len(s.tools) > tools_shown:
            names.append(f"+{len(s.tools) - tools_shown}")
        msgs = f"{s.messages} msg" + ("" if s.messages == 1 else "s")
        return (f"{s.name} · turn {s.number} · {_range_text(s.first_seq, s.last_seq)} · {msgs}"
                f" · tools {' '.join(names) or '-'} · {s.tokens} tok · {s.status} · {preview}")

    for shown in range(min(INDEX_TOOLS, len(s.tools)), -1, -1):
        if count(line(shown, "")) <= INDEX_LINE_TOKENS:
            preview = fit_prefix(s.preview, lambda p: count(line(shown, p)) <= INDEX_LINE_TOKENS)
            return line(shown, preview.rstrip() or "-")
    return line(0, "-")


def render_index(summaries: Iterable[Summary], *, generation: int, revision: int,
                 count: Count) -> str:
    """``index.md``: a header naming the generation, then one bounded line per turn."""
    lines = [
        f"# palimnesis transcript index · generation {generation} · archive cutoff seq "
        f"{generation} · revision {revision} · format {FORMAT}",
        "# Search; do not read whole: grep the turn files for a specific term, then read only"
        " the matching lines.",
        "",
    ]
    lines += [_index_line(s, count) for s in summaries]
    return "\n".join(lines) + "\n"


def manifest(files: Mapping[str, tuple[str, int]], payloads: Iterable[Payload], *,
             generation: int, revision: int, branch: str, profile: str) -> bytes:
    """``manifest.json``: every published turn and payload file (path -> SHA-256, size),
    and every payload's archive SHA-256. ``index.md`` is published after it and is not
    listed."""
    body = {"format": FORMAT, "generation": generation, "archive_cutoff_seq": generation,
            "revision": revision, "branch": branch, "profile": profile,
            "files": {path: {"sha256": sha, "size": size} for path, (sha, size) in files.items()},
            "payloads": {p.address: {"turn_file": p.turn_file, "linked": p.linked,
                                     "sha256": p.sha256, "size": p.size} for p in payloads}}
    return (json.dumps(body, sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode()


def file_meta(rendered: RenderedTurn) -> dict[str, tuple[str, int]]:
    """Path -> (SHA-256, size) of a rendered turn's files, the turn file last."""
    files = {path: (_sha(blob), len(blob)) for path, blob in sorted(rendered.files.items())}
    data = rendered.data
    files[rendered.name] = (_sha(data), len(data))
    return files


def render_manifest(rendered: Sequence[RenderedTurn], *, generation: int, revision: int,
                    branch: str, profile: str) -> bytes:
    files = {path: meta for r in rendered for path, meta in file_meta(r).items()}
    return manifest(files, [p for r in rendered for p in r.payloads], generation=generation,
                    revision=revision, branch=branch, profile=profile)


# --- parsing and verification ------------------------------------------------

_LINK_LINE = re.compile(r"payload (\S+) · (\d+) bytes · \d+ lines · sha256 ([0-9a-f]{64})")


def extract(text: str, *, added_tokens: Sequence[str],
            read: Callable[[str], bytes] | None = None) -> dict[str, bytes]:
    """Every payload of a t1 turn file, by address, as its exact bytes.

    Inline payloads are unescaped; linked ones are read through ``read(path)`` and must
    match the SHA-256 and size their turn file states."""
    lines = text.split("\n")
    out: dict[str, bytes] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.startswith("[["):
            continue
        if not (line.startswith("[[§") and line.endswith("]]")):
            raise ProjectionError(f"unexpected delimiter at line {i}")
        fields = line[3:-2].split(" · ")
        address = fields[0]
        if "." not in address:
            continue  # an occurrence without blocks
        close = f"[[/§{address}]]"
        body: list[str] = []
        while i < len(lines) and not lines[i].startswith("[["):
            body.append(lines[i])
            i += 1
        if i >= len(lines) or lines[i] != close:
            raise ProjectionError(f"block §{address} is not closed")
        i += 1
        if address in out:
            raise ProjectionError(f"block §{address} appears twice")
        if fields[-1] == "linked":
            match = _LINK_LINE.fullmatch(body[0]) if body else None
            if match is None or read is None:
                raise ProjectionError(f"block §{address} has no readable payload link")
            data = read(match.group(1))
            if len(data) != int(match.group(2)) or _sha(data) != match.group(3):
                raise ProjectionError(f"linked payload of §{address} does not match its sha256")
            out[address] = data
        else:
            out[address] = unescape_payload("\n".join(body), added_tokens).encode(
                "utf-8", "surrogatepass")
    return out


INDEX_FILE = re.compile(r"^(turn-\d{4,}(?:\.p\d{4,})?\.md) · ", re.M)


def index_files(index_text: str) -> list[str]:
    """The turn files an ``index.md`` references."""
    return INDEX_FILE.findall(index_text)


def verify(read: Callable[[str], bytes], expected: Mapping[str, bytes], *,
           added_tokens: Sequence[str]) -> list[str]:
    """Problems with one published session directory, by address and file name only.

    ``read(path)`` reads a file relative to the directory (raising ``OSError`` when it
    is missing); ``expected`` is every archived payload at the published cutoff."""
    problems: list[str] = []
    try:
        manifest = json.loads(read("manifest.json"))
        index = read("index.md").decode("utf-8")
    except (OSError, ValueError) as e:
        return [f"manifest.json or index.md unreadable: {type(e).__name__}"]
    for name in index_files(index):
        if name not in manifest["files"]:
            problems.append(f"index.md references {name}, which manifest.json does not list")
    published: dict[str, bytes] = {}
    for name, meta in sorted(manifest["files"].items()):
        try:
            data = read(name)
        except OSError:
            problems.append(f"{name} is missing")
            continue
        if len(data) != meta["size"] or _sha(data) != meta["sha256"]:
            problems.append(f"{name} does not match manifest.json")
            continue
        if name.startswith("turn-"):
            try:
                found = extract(data.decode("utf-8"), added_tokens=added_tokens, read=read)
            except (ProjectionError, OSError, UnicodeDecodeError) as e:
                problems.append(f"{name} does not parse: {type(e).__name__}")
                continue
            published.update(found)
    for address, meta in sorted(manifest["payloads"].items()):
        data = published.get(address)
        if data is None:
            problems.append(f"§{address} is listed but not published")
        elif _sha(data) != meta["sha256"]:
            problems.append(f"§{address} does not match its manifest sha256")
    for address, data in sorted(expected.items()):
        got = published.get(address)
        if got is None:
            problems.append(f"§{address} is in the archive but not published")
        elif _sha(got) != _sha(data):
            problems.append(f"§{address} differs from the archive")
    for address in sorted(set(published) - set(expected)):
        problems.append(f"§{address} is published but not in the archive")
    return problems
