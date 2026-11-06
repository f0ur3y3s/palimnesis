"""``palimnesis setup`` and ``palimnesis check`` (D101).

``setup`` writes one agent's Palimnesis configuration from the shipped adapter files:
the model id from ``--model``, the proxy origin from ``--host``/``--port``. It merges into
existing JSON (the provider blocks Palimnesis owns are replaced, every other key is kept,
lists gain missing entries), copies a changed file to ``<name>.bak-<timestamp>`` first,
changes nothing when everything already matches, and refuses a file that is not plain
JSON without writing anything.

``check`` reports PASS, WARN, FAIL or SKIP per item with a fix, and returns 1 on any
FAIL: the upstream's facts and the same acceptance decision ``serve`` makes (D102), the
proxy on its port, and each agent's configuration.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from palimnesis.adapters import read_bytes

# What the shipped files name, replaced on render.
SHIPPED_MODEL = "qwen3.8-flash-next-iq3_xxs"
SHIPPED_NAME = "Qwen3.8 Flash Next"
SHIPPED_ORIGIN = "http://127.0.0.1:9000"
MIN_CONTEXT = 1_000_000


class SetupError(Exception):
    pass


@dataclass(frozen=True)
class JsonFile:
    name: str
    owned: tuple[tuple[str, ...], ...] = ()  # key paths replaced wholesale


@dataclass(frozen=True)
class Agent:
    name: str
    env: str
    default_dir: str
    dir_flag: str
    json_files: tuple[JsonFile, ...]
    script: str  # the session plugin or extension, relative to the agent directory
    refuse_if: tuple[str, ...] = ()  # files the agent also reads, which setup cannot merge

    def directory(self, explicit: Path | None) -> Path:
        if explicit is not None:
            return explicit
        env = os.environ.get(self.env)
        return Path(env) if env else Path(self.default_dir).expanduser()


OPENCODE = Agent("opencode", "OPENCODE_CONFIG_DIR", "~/.config/opencode", "--config-dir",
                 (JsonFile("opencode.json", (("providers", "palimnesis"),)),),
                 "plugins/palimnesis.ts", refuse_if=("opencode.jsonc",))
PI = Agent("pi", "PI_CODING_AGENT_DIR", "~/.pi/agent", "--agent-dir",
           (JsonFile("models.json", (("providers", "palimnesis"), ("providers", "palimnesis-messages"))),
            JsonFile("settings.json")),
           "extensions/palimnesis-session.ts")
AGENTS = {a.name: a for a in (OPENCODE, PI)}


# ------------------------------------------------------------------------ rendering

def _render(value: Any, model: str, origin: str) -> Any:
    if isinstance(value, dict):
        return {(model if k == SHIPPED_MODEL else k): _render(v, model, origin) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, model, origin) for v in value]
    if isinstance(value, str):
        return (value.replace(SHIPPED_ORIGIN, origin).replace(SHIPPED_MODEL, model)
                .replace(SHIPPED_NAME, model))
    return value


def merge(existing: dict, shipped: dict, owned: tuple[tuple[str, ...], ...],
          path: tuple[str, ...] = ()) -> dict:
    """``shipped`` over ``existing``: owned paths replaced, dicts merged, lists extended."""
    out = dict(existing)
    for key, value in shipped.items():
        here = path + (key,)
        current = out.get(key)
        if here in owned or key not in out:
            out[key] = value
        elif isinstance(value, dict) and isinstance(current, dict):
            out[key] = merge(current, value, owned, here)
        elif isinstance(value, list) and isinstance(current, list):
            out[key] = current + [v for v in value if v not in current]
        elif isinstance(value, (dict, list)) or isinstance(current, (dict, list)):
            raise SetupError(f"`{'.'.join(here)}` is {type(current).__name__}, but Palimnesis needs "
                             f"{type(value).__name__}: edit it by hand")
        else:
            out[key] = value  # a setting Palimnesis owns, e.g. the default model
    return out


def _dump(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_json(path: Path) -> dict | None:
    """The file's object, None when absent; SetupError when it is not a plain JSON object."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SetupError(f"{path} is not plain JSON ({exc}). Comments and trailing commas "
                         "are not supported: edit it by hand or move it aside.") from exc
    if not isinstance(data, dict):
        raise SetupError(f"{path} is not plain JSON with an object at the top")
    return data


def rendered_script(agent: Agent, origin: str) -> bytes:
    text = read_bytes(f"{agent.name}/{agent.script}").decode("utf-8")
    return text.replace(SHIPPED_ORIGIN, origin).encode("utf-8")


def plan(agent: Agent, directory: Path, model: str, origin: str) -> list[tuple[Path, bytes]]:
    """Every file setup owns, with its new content. Reads only."""
    for name in agent.refuse_if:
        if (directory / name).exists():
            raise SetupError(f"{directory / name} exists, and {agent.name} reads it too. Setup only "
                             "writes plain JSON: merge integrations/ into it by hand")
    out = []
    for f in agent.json_files:
        shipped = _render(json.loads(read_bytes(f"{agent.name}/{f.name}")), model, origin)
        existing = read_json(directory / f.name) or {}
        out.append((directory / f.name, _dump(merge(existing, shipped, f.owned))))
    out.append((directory / agent.script, rendered_script(agent, origin)))
    return out


def setup(agent: Agent, directory: Path, model: str, origin: str, *, dry_run: bool = False) -> int:
    try:
        files = plan(agent, directory, model, origin)
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    changes = [(p, b) for p, b in files if not p.exists() or p.read_bytes() != b]
    if not changes:
        print(f"{agent.name}: nothing to change in {directory}")
        return 0
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    for path, data in changes:
        if dry_run:
            print(f"would write {path}")
            continue
        try:
            note = ""
            if path.exists():
                backup = _free(path.with_name(f"{path.name}.bak-{stamp}"))
                backup.write_bytes(path.read_bytes())
                note = f" (backup: {backup.name})"
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError as exc:
            print(f"error: could not write {path}: {exc}. Files listed above were written, "
                  "each with its backup", file=sys.stderr)
            return 1
        print(f"wrote {path}{note}")
    if not dry_run:
        print("next: start `palimnesis serve`, then run `palimnesis check`")
    return 0


def _free(path: Path) -> Path:
    """``path``, or ``path-2``, ``path-3`` ... when a backup from the same second exists."""
    n, candidate = 1, path
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}-{n}")
    return candidate


# ------------------------------------------------------------------------ check

@dataclass
class Item:
    status: str  # PASS, WARN, FAIL, SKIP
    label: str
    detail: str
    fix: str = ""


def _upstream_items(upstream: str) -> tuple[list[Item], str | None]:
    """The default upstream profile's facts and verdict: what ``serve`` would decide."""
    from palimnesis.upstreams import profile

    facts = profile.load(profile.DEFAULT_PROFILE, upstream).facts

    async def refresh() -> None:
        async with httpx.AsyncClient() as client:
            await facts.refresh(client)

    asyncio.run(refresh())
    diag = facts.diagnostics()
    props = diag.get("facts")
    if not props:
        error = diag.get("last_error") or ""
        if "malformed" in error or "returned" in error:  # it answered, but not as Strata does
            return [Item("WARN", "upstream", f"{upstream} answers, but is not Strata ({error})"),
                    Item("FAIL", "bounded views", "off: they need Strata's /props and count_tokens",
                         "the proxy still archives and forwards every request with the full history")], None
        return [Item("FAIL", "upstream", f"no answer from {upstream}/props ({error})",
                     "start the model server, or pass --upstream URL")], None
    alias = props.get("model_alias")
    items = [Item("PASS", "upstream", f"{props.get('build_info')}, model {alias}, "
                                      f"context {props.get('n_ctx'):,} tokens")]
    if facts.pinned_ok:
        items.append(Item("PASS", "bounded views",
                          f"on: token counts match ({diag.get('accepted_by') or 'pinned'})"))
    else:
        canary = diag.get("template_canary") or diag.get("canary") or {}
        if canary.get("ok") is None:
            items.append(Item("FAIL", "bounded views",
                              f"off: the server did not answer count_tokens ({canary.get('error')})",
                              "wait for the model to finish loading, then check again"))
            return items, alias
        why = "; ".join(diag.get("mismatches") or ()) or canary.get("error") or "count_tokens canary failed"
        items.append(Item("FAIL", "bounded views",
                          f"off: the server counts tokens differently ({why})",
                          "the proxy still archives and forwards, but sends the full history. "
                          "Use a Strata build whose counts match, or report the build"))
    return items, alias


def _proxy_item(host: str, port: int, upstream: str) -> Item:
    url = f"http://{host}:{port}"
    try:
        r = httpx.get(f"{url}/v1/models", timeout=2.0)
    except httpx.HTTPError:
        return Item("FAIL", "proxy", f"nothing answers on {url}",
                    f"run `palimnesis serve --upstream {upstream} --port {port}`")
    if r.status_code == 400 and b"session_required" in r.content:
        return Item("PASS", "proxy", f"Palimnesis answers on {url}")
    return Item("FAIL", "proxy", f"something other than Palimnesis answers on {url}",
                "stop it, or run Palimnesis on another --port and pass the same port here")


def _big(context: Any) -> bool:
    return isinstance(context, int) and context >= MIN_CONTEXT


def _points_at(base_url: Any, host: str, port: int) -> bool:
    if not isinstance(base_url, str):
        return False
    parts = urlsplit(base_url)
    return parts.port == port and parts.hostname in {host, "127.0.0.1", "localhost"}


def _agent_items(agent: Agent, directory: Path, explicit: bool, host: str, port: int,
                 alias: str | None) -> list[Item]:
    hint = (f"palimnesis setup {agent.name} --model {alias or '<model>'} --port {port}"
            + (f" {agent.dir_flag} {directory}" if explicit else ""))
    try:
        docs = {f.name: read_json(directory / f.name) for f in agent.json_files}
    except SetupError as exc:
        return [Item("WARN", agent.name, str(exc))]
    first = docs[agent.json_files[0].name] or {}
    providers = first.get("providers") or {}
    if not explicit and "palimnesis" not in providers:
        return [Item("SKIP", agent.name, f"not set up in {directory}", hint)]
    items: list[Item] = [Item("WARN", f"{agent.name} config", f"{directory / name} exists too: "
                              "make sure it does not override the Palimnesis provider")
                         for name in agent.refuse_if if (directory / name).exists()]

    def add(ok: bool, label: str, good: str, bad: str, fix: str = hint) -> None:
        items.append(Item("PASS", label, good) if ok else Item("FAIL", label, bad, fix))

    label = f"{agent.name}"
    if agent is OPENCODE:
        provider = providers.get("palimnesis") or {}
        models = provider.get("models") or {}
        add(_points_at((provider.get("settings") or {}).get("baseURL"), host, port),
            f"{label} provider", f"points at port {port}",
            f"no `palimnesis` provider pointing at {host}:{port} in opencode.json")
        small = [m for m, spec in models.items()
                 if not _big(((spec or {}).get("limit") or {}).get("context"))]
        add(bool(models) and not small, f"{label} context", "limit.context is at least 1,000,000",
            f"limit.context below 1,000,000 or no model: {', '.join(small) or 'none listed'}")
        add((first.get("compaction") or {}).get("auto") is False, f"{label} compaction",
            "OpenCode's compaction is off", "OpenCode's own compaction is on: set compaction.auto to false")
        model_ids = list(models)
    else:
        settings = docs["settings.json"] or {}
        model_ids = []
        for name, path in (("palimnesis", "/v1"), ("palimnesis-messages", "")):
            provider = providers.get(name) or {}
            add(_points_at(provider.get("baseUrl"), host, port), f"{label} provider {name}",
                f"points at port {port}", f"no `{name}` provider pointing at {host}:{port}{path} in models.json")
            for m in provider.get("models") or []:
                model_ids.append(m.get("id"))
                add(_big(m.get("contextWindow")), f"{label} context {name}",
                    "contextWindow is at least 1,000,000", f"contextWindow of {m.get('id')} is below 1,000,000")
        add((settings.get("compaction") or {}).get("enabled") is False, f"{label} compaction",
            "Pi's compaction is off", "Pi's own compaction is on: set compaction.enabled to false in settings.json")
    script = directory / agent.script
    current = script.exists() and script.read_bytes() == rendered_script(agent, f"http://{host}:{port}")
    add(current, f"{label} session {'plugin' if agent is OPENCODE else 'extension'}",
        f"{agent.script} is current",
        f"{agent.script} is {'out of date' if script.exists() else 'missing'}")
    if alias is not None and model_ids:
        others = sorted({m for m in model_ids if m != alias})
        if others:
            items.append(Item("WARN", f"{label} model", f"configured {', '.join(others)}, "
                              f"but the server's model is {alias}", hint))
        else:
            items.append(Item("PASS", f"{label} model", f"{alias}, as the server names it"))
    return items


def check(upstream: str, host: str, port: int, dirs: dict[str, Path | None]) -> int:
    items, alias = _upstream_items(upstream)
    items.append(_proxy_item(host, port, upstream))
    for name, agent in AGENTS.items():
        explicit = dirs.get(name)
        items.extend(_agent_items(agent, agent.directory(explicit), explicit is not None,
                                  host, port, alias))
    for item in _lines(items):
        print(item)
    return 1 if any(i.status == "FAIL" for i in items) else 0


def _lines(items: list[Item]) -> Iterator[str]:
    for i in items:
        yield f"{i.status:<4}  {i.label}: {i.detail}"
        if i.fix and i.status in ("FAIL", "WARN", "SKIP"):
            yield f"      fix: {i.fix}"
