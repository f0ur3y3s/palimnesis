"""Seeded generator for Phase 3 development needle histories (plan §5, A1 "Evaluation").

Each history is an OpenCode-shaped coding session: user instructions, assistant tool
calls (read, grep, shell, edit) with OpenCode 2.1.4-formatted tool results, and short
assistant summaries. Planted facts have exact-string answers. The history is imported
as the first request of a session (Palimnesis archives prior assistant/tool messages of
a first request as ``client_import``); later steps are genuine user turns answered by
the live model through the emulator in ``eval/needle.py``.

Steps after the import (fixed skeleton, values and positions vary by seed):

    Q1 (host of the import request), P1 (paste carrying the Q9 fact), Q2, Q3, P2, Q4, Q5,
    P3, Q6, Q7, Q8, [proxy restart], Q9, Q10

Categories (A1): identifier (Q1, Q2), superseded (Q3), irrelevant matches (Q4),
vague reference (Q5, Q10), oversized transcript read (Q6), mid-task need (Q7),
several distant facts (Q8), restart plus multiple eviction events (Q9).

Usage: python eval/needle_gen.py [--set development|heldout] [--out DIR]

The held-out set (``--set heldout``, D44.3) comes from ``build_heldout``: twelve new themes,
seeds 5200-5211, held-out word banks, file names and value formats, and its own phrasing
bank, on the same step skeleton, categories and answer types.
"""

from __future__ import annotations

import argparse
import json
import random
import string
from pathlib import Path

THEMES = [
    dict(project="ledger", topic="rounding errors in minor-unit amounts",
         modules=["rounding", "settlement", "refunds", "fx_rates", "webhooks", "reconciler",
                  "audit", "scheduler"], svc="ledger-api", db="ledger_v2_stg",
         clients=["inventory", "billing", "fraud", "payouts", "kyc", "notify"],
         const="MAX_SETTLEMENT_BATCH", const_mod="settlement", helper=("_legacy_round",
                                                                        "round_half_even_minor")),
    dict(project="stockroom", topic="double reservations under concurrent checkouts",
         modules=["reservations", "warehouse", "sku_index", "pricing", "sync", "notifier",
                  "gateway", "replenish"], svc="stock-api", db="stockroom_core_stg",
         clients=["catalog", "orders", "shipping", "suppliers", "returns", "search"],
         const="RESERVATION_TTL_SECONDS", const_mod="reservations",
         helper=("_old_lock_key", "reservation_lock_key")),
    dict(project="tidepool", topic="duplicate rows after partial backfills",
         modules=["ingest", "dedupe", "enrich", "partitioner", "loader", "schema_registry",
                  "backfill", "metrics"], svc="tidepool-worker", db="tidepool_events_stg",
         clients=["warehouse", "lake", "registry", "alerts", "geo", "identity"],
         const="DEDUPE_WINDOW_MINUTES", const_mod="dedupe",
         helper=("_hash_row_v1", "stable_row_digest")),
    dict(project="carthorse", topic="cart totals drifting after coupon edits",
         modules=["cart", "checkout", "coupons", "catalog_cache", "session_store", "analytics",
                  "i18n", "router"], svc="cart-web", db="carthorse_app_stg",
         clients=["payments", "tax", "promotions", "loyalty", "recommend", "address"],
         const="COUPON_STACK_LIMIT", const_mod="coupons",
         helper=("_apply_coupon_legacy", "apply_coupon_sequence")),
    dict(project="quillctl", topic="config precedence bugs in the CLI",
         modules=["config", "parser", "renderer", "cache", "updater", "plugins", "telemetry",
                  "auth"], svc="quill-daemon", db="quill_state_stg",
         clients=["registry", "telemetry", "license", "mirror", "auth", "updates"],
         const="CONFIG_MAX_DEPTH", const_mod="config",
         helper=("_merge_dicts_old", "merge_layered_config")),
    dict(project="harbormaster", topic="flaky provisioning of preview environments",
         modules=["network", "dns", "iam", "buckets", "queues", "alerts", "runners",
                  "secrets"], svc="harbor-api", db="harbor_infra_stg",
         clients=["cloud", "dns", "vault", "github", "pager", "metrics"],
         const="PREVIEW_ENV_QUOTA", const_mod="runners",
         helper=("_tf_plan_legacy", "plan_with_lock")),
]

VERBS = ["load", "parse", "apply", "merge", "flush", "resolve", "compute", "validate", "emit",
         "fetch", "store", "render", "split", "collect", "build", "schedule", "sync", "trim"]
NOUNS = ["batch", "entry", "window", "record", "token", "bucket", "snapshot", "cursor", "plan",
         "event", "span", "offset", "ledger", "segment", "manifest", "quota", "payload", "slot"]
ADJS = ["fast", "stale", "pending", "partial", "nested", "empty", "large", "retry", "cold",
        "warm", "late", "dirty", "locked", "remote", "local", "signed", "sorted", "legacy"]


def call_id(rnd: random.Random) -> str:
    return "call_" + "".join(rnd.choice("0123456789abcdef") for _ in range(24))


def code_file(rnd: random.Random, module: str, lines: int, extra: dict[int, str] | None = None) -> list[str]:
    """Plausible Python source lines; ``extra`` places fixed lines at indices."""
    out = [f'"""{module.replace("_", " ").title()} helpers."""', "", "from __future__ import annotations",
           "", "import logging", "from dataclasses import dataclass", "",
           f"log = logging.getLogger(__name__)", ""]
    cls = "".join(p.title() for p in module.split("_"))
    out += ["@dataclass", f"class {cls}State:", "    cursor: int = 0", "    pending: int = 0", ""]
    while len(out) < lines:
        v, n, a = rnd.choice(VERBS), rnd.choice(NOUNS), rnd.choice(ADJS)
        out.append(f"def {v}_{a}_{n}(state: {cls}State, {n}s: list[dict]) -> int:")
        for _ in range(rnd.randint(2, 6)):
            k = rnd.choice([
                f"    total = sum(item.get('{n}_{rnd.randint(1, 9)}', 0) for item in {n}s)",
                f"    if state.pending > {rnd.randint(2, 900)}:",
                f"        log.debug('{v} {a} {n}: %d pending', state.pending)",
                f"    state.cursor += len({n}s)",
                f"    {n}s = [x for x in {n}s if x.get('{a}') is not None]",
                f"    # {v} the {a} {n}s before the {rnd.choice(NOUNS)} is committed",
            ])
            out.append(k)
        out.append(f"    return state.cursor")
        out.append("")
    out = out[:lines]
    for i, text in (extra or {}).items():
        out[min(i, len(out) - 1)] = text
    return out


def read_result(path: str, lines: list[str], offset: int = 1) -> str:
    """OpenCode 2.1.4 read output (hF in the 2.1.4 bundle)."""
    body = [f"Read file {path}, lines {offset}-{offset + len(lines) - 1}"]
    body += [f"{offset + i}: {t}" for i, t in enumerate(lines)]
    return "\n".join(body)


def pytest_output(rnd: random.Random, test_path: str, cases: list[str], failures: dict[str, list[str]]) -> str:
    """pytest -q style output; ``failures`` maps a case to its traceback lines."""
    out = []
    dots = "".join("F" if c in failures else "." for c in cases)
    for i in range(0, len(dots), 50):
        out.append(f"{dots[i:i + 50]:<56}[{min(100, int(100 * (i + 50) / len(dots))):>3}%]")
    if failures:
        out.append("=" * 30 + " FAILURES " + "=" * 30)
        for case, tb in failures.items():
            out.append(f"{'_' * 20} {case} {'_' * 20}")
            out.append("")
            out += tb
            out.append("")
        out.append("=" * 20 + " short test summary info " + "=" * 20)
        for case, tb in failures.items():
            err = next((t[4:].strip() for t in tb if t.startswith("E   ")), "AssertionError")
            out.append(f"FAILED {test_path}::{case} - {err}")
    passed = len(cases) - len(failures)
    res = (f"{len(failures)} failed, " if failures else "") + f"{passed} passed"
    out.append(f"{res} in {rnd.uniform(0.8, 9.5):.2f}s")
    return "\n".join(out)


def names(rnd: random.Random, k: int, prefix: str = "test_") -> list[str]:
    seen, out = set(), []
    while len(out) < k:
        n = f"{prefix}{rnd.choice(VERBS)}_{rnd.choice(ADJS)}_{rnd.choice(NOUNS)}"
        if n in seen or any(n in s or s in n for s in seen):
            continue
        seen.add(n)
        out.append(n)
    return out


def code(rnd: random.Random, letters: str, n: int = 4) -> str:
    return f"{letters}-{rnd.randint(10 ** (n - 1), 10 ** n - 1)}-{rnd.choice(string.ascii_uppercase)}"


class Builder:
    def __init__(self, rnd: random.Random, cwd_hint: str = "") -> None:
        self.rnd = rnd
        self.messages: list[dict] = []

    def user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def say(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def tool(self, name: str, args: dict, result: str) -> None:
        cid = call_id(self.rnd)
        self.messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": json.dumps(args, separators=(",", ":"))}}]})
        self.messages.append({"role": "tool", "tool_call_id": cid, "content": result})


def log_lines(rnd: random.Random, n: int, svc: str, extra: dict[int, str] | None = None) -> list[str]:
    out = []
    for i in range(n):
        t = f"2026-10-2{rnd.randint(0, 3)}T{rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}Z"
        lvl = rnd.choice(["INFO", "INFO", "INFO", "DEBUG", "WARN"])
        msg = rnd.choice([
            f"{svc} pod/{svc}-{rnd.randint(1000, 9999)} readiness probe ok ({rnd.randint(2, 90)}ms)",
            f"rollout step {rnd.randint(1, 9)}/9 weight={rnd.randint(1, 100)}%",
            f"{rnd.choice(VERBS)} {rnd.choice(NOUNS)} queue depth={rnd.randint(0, 500)}",
            f"config reload checksum={''.join(rnd.choice('0123456789abcdef') for _ in range(12))}",
            f"http {rnd.choice(['GET', 'POST'])} /v1/{rnd.choice(NOUNS)}s {rnd.choice([200, 200, 201, 404, 503])} {rnd.randint(1, 900)}ms",
            f"gc pause {rnd.uniform(0.1, 40):.1f}ms heap={rnd.randint(200, 900)}MiB",
        ])
        out.append(f"{t} {lvl:<5} {msg}")
    for i, text in (extra or {}).items():
        out[i] = text
    return out


def build_history(index: int, seed: int) -> dict:
    rnd = random.Random(seed)
    th = THEMES[index]
    P, mods = th["project"], list(th["modules"])
    rnd.shuffle(mods)
    mod_a = mods[0]
    b = Builder(rnd)

    # ---- planted values ----
    err_a = code(rnd, P[:3].upper())
    err_distractors = [code(rnd, P[:3].upper()) for _ in range(3)]
    ticket = rnd.randint(10000, 99999)
    slug = th["topic"].split()[0]
    branch = f"fix/{P}-{slug}-{ticket}"
    branch_docs = f"docs/{P}-faq-{ticket}"
    port_old, port_new, port_admin = rnd.randint(8100, 8199), rnd.randint(9200, 9299), rnd.randint(8300, 8399)
    clients = list(th["clients"])
    rnd.shuffle(clients)
    target_client = clients[0]
    timeouts = {c: (f"{rnd.choice([1.25, 2.5, 3.75, 4.5, 6.0, 7.5, 2.25, 5.25])}s",
                    f"{rnd.randint(8, 30)}s") for c in clients}
    # make the target's read/write values unique among clients
    used_r = {v[0] for c, v in timeouts.items() if c != target_client}
    used_w = {v[1] for c, v in timeouts.items() if c != target_client}
    r, w = timeouts[target_client]
    while r in used_r:
        r = f"{rnd.randint(1, 9)}.{rnd.choice(['25', '5', '75'])}s"
    while w in used_w:
        w = f"{rnd.randint(31, 59)}s"
    timeouts[target_client] = (r, w)
    fixture_timeouts = {c: (f"{rnd.randint(1, 9)}.0s", f"{rnd.randint(60, 90)}s") for c in clients}
    req_id, req_other = f"REQ-{rnd.randint(1000, 9999)}", f"REQ-{rnd.randint(1000, 9999)}"
    const_val = rnd.choice([96, 192, 384, 640, 768, 1536]) if not th["const"].startswith("RESERVATION_TTL") else rnd.choice([45, 90, 150, 210])
    const_cur = const_val // 2
    host = f"pg-stg-{rnd.randint(2, 19):02d}.internal"
    db_port = rnd.choice([6432, 6543, 6610, 7432])
    db_name = th["db"]
    old_helper, new_helper = th["helper"]
    tag_new = f"r2026.10.{rnd.randint(10, 24)}-hf{rnd.randint(2, 9)}"
    tag_old = f"r2026.10.{rnd.randint(1, 9):02d}-hf{rnd.randint(1, 9)}"
    integ = names(rnd, 420)
    k6 = rnd.randint(60, 300)
    q6_before, q6_after = integ[k6], integ[k6 + 1]

    facts = []
    # ---- import turns ----
    b.user(f"We're working on {th['topic']} in {P}. Track this under ticket OPS-{ticket} and use "
           f"the branch `{branch}` for the main fix. Start by reading src/{P}/{mod_a}.py.")
    lines = code_file(rnd, mod_a, rnd.randint(120, 170))
    b.tool("read", {"path": f"src/{P}/{mod_a}.py"}, read_result(f"src/{P}/{mod_a}.py", lines))
    b.say(f"`{mod_a}.py` holds the state dataclass and {sum(1 for l in lines if l.startswith('def '))} "
          f"helpers. Nothing obviously wrong yet; the tests are the next thing to check.")

    b.user(f"Run the {mod_a} tests.")
    cases = names(rnd, 38)
    fail = cases[rnd.randrange(len(cases))]
    tb = [f"    def {fail}(db):", f">       migrate(db, 'amount_minor')",
          f"E   {P}.errors.MigrationError: [{err_a}] cannot migrate column 'amount_minor'",
          "", f"tests/test_{mod_a}.py:{rnd.randint(40, 300)}: MigrationError"]
    b.tool("shell", {"command": f"python -m pytest tests/test_{mod_a}.py -q"},
           pytest_output(rnd, f"tests/test_{mod_a}.py", cases, {fail: tb}))
    b.say(f"One failure: `{fail}` hits a MigrationError during the column migration. "
          "The rest pass.")
    facts.append(("Q1", "first test run, tool output"))

    b.user(f"Requirement {req_id}: {th['const']} must be {const_val}; the downstream consumer "
           f"rejects anything else. Also {req_other}: MIN_RETRY_DELAY_MS stays at 250. Keep both "
           f"in mind, we'll come back to them.")
    b.say(f"Noted: {req_id} fixes {th['const']} and {req_other} keeps MIN_RETRY_DELAY_MS at 250.")

    b.user(f"When you need the {th['svc']} dev server, run it on port {port_old}. The admin UI "
           f"stays on {port_admin}.")
    b.say(f"Understood: {th['svc']} dev server on {port_old}, admin UI on {port_admin}.")

    cfg = ["# Production client settings (loaded by config.load_clients)", ""]
    for c in clients:
        cfg += [f"[clients.{c}]", f'base_url = "https://{c}.svc.internal"',
                f'read_timeout = "{timeouts[c][0]}"', f'write_timeout = "{timeouts[c][1]}"',
                f"retries = {rnd.randint(1, 6)}", f"pool_size = {rnd.randint(4, 64)}", ""]
    b.user("Show me how the HTTP clients are configured.")
    b.tool("read", {"path": "config/clients.toml"}, read_result("config/clients.toml", cfg))
    b.say(f"Six clients are configured in config/clients.toml, each with its own read and write "
          f"timeouts, retries and pool size.")

    for m in mods[1:3]:
        b.user(f"Now read src/{P}/{m}.py and tell me if it touches amounts.")
        lines = code_file(rnd, m, rnd.randint(110, 160))
        b.tool("read", {"path": f"src/{P}/{m}.py"}, read_result(f"src/{P}/{m}.py", lines))
        b.say(f"`{m}.py` only moves {rnd.choice(NOUNS)}s around; it does not touch amounts directly.")

    env = [f"STAGING_CACHE_HOST=redis-stg-{rnd.randint(2, 9):02d}.internal",
           f"STAGING_DB_HOST={host}", f"STAGING_QUEUE_HOST=mq-stg-{rnd.randint(2, 9):02d}.internal",
           f"STAGING_DB_USER={P}_app", "STAGING_DB_SSLMODE=require",
           f"STAGING_FEATURE_FLAGS={rnd.choice(NOUNS)},{rnd.choice(NOUNS)}"]
    b.user("Where do the staging hosts come from?")
    b.tool("read", {"path": "config/staging.env"}, read_result("config/staging.env", env))
    b.say("They come from config/staging.env: cache, database and queue hosts plus the DB user.")

    b.user(f"FYI the staging pooler listens on {db_port}, not the default 5432.")
    b.say(f"Got it, the staging pooler port is {db_port}.")

    m = mods[3]
    b.user(f"Run the {m} tests too.")
    cases = names(rnd, 30)
    f2 = cases[rnd.randrange(len(cases))]
    b.tool("shell", {"command": f"python -m pytest tests/test_{m}.py -q"},
           pytest_output(rnd, f"tests/test_{m}.py", cases, {f2: [
               f"    def {f2}():", f">       assert run() == 0",
               f"E   {P}.errors.RetryError: [{err_distractors[0]}] retry budget exhausted", ""]}))
    b.say(f"`{f2}` fails with a RetryError (retry budget exhausted); unrelated to the migration.")

    # rename helper (F10)
    b.user(f"Clean up the old {'rounding ' if index == 0 else ''}helper in {mod_a}.py while you're there.")
    b.tool("edit", {"path": f"src/{P}/{mod_a}.py", "oldString": f"def {old_helper}(",
                    "newString": f"def {new_helper}("},
           f"Edited src/{P}/{mod_a}.py (1 replacement)")
    b.say(f"Done. I renamed the old `{old_helper}` helper to `{new_helper}` and left a "
          f"deprecation shim under the old name so callers keep working.")

    b.user(f"Change of plan: move the {th['svc']} dev server to port {port_new}; {port_old} clashes "
           f"with the metrics agent.")
    b.say(f"OK, {th['svc']} dev server moves to {port_new}.")

    b.user("Which database should the migration dry-run target?")
    b.tool("grep", {"pattern": "_stg", "path": "config"},
           f"Found 1 matches\nconfig\\databases.yaml:\n  Line {rnd.randint(3, 30)}:   staging: {db_name}")
    b.say(f"I'll point the migration dry-run at the `{db_name}` database on staging.")

    m = mods[4]
    b.user(f"Run the full integration suite, verbose.")
    out = ["============================= test session starts =============================",
           f"collected {len(integ)} items", ""]
    areas = [f"tests/integration/test_{x}.py" for x in mods]
    for i, n in enumerate(integ):
        out.append(f"{areas[i * len(areas) // len(integ)]}::{n} PASSED{'':>10}[{int(100 * (i + 1) / len(integ)):>3}%]")
    out.append(f"============================= {len(integ)} passed in {rnd.uniform(60, 200):.2f}s =============================")
    b.tool("shell", {"command": "python -m pytest tests/integration -v"}, "\n".join(out))
    b.say(f"All {len(integ)} integration tests pass.")

    b.user(f"For the docs follow-up later, use the branch `{branch_docs}`.")
    b.say(f"Noted, docs follow-up goes on `{branch_docs}`.")

    fx = ["# Test fixture: deliberately short timeouts", ""]
    for c in clients:
        fx += [f"[clients.{c}]", f'read_timeout = "{fixture_timeouts[c][0]}"',
               f'write_timeout = "{fixture_timeouts[c][1]}"', ""]
    b.user("What do the test fixtures use for client timeouts?")
    b.tool("read", {"path": "tests/fixtures/clients_test.toml"}, read_result("tests/fixtures/clients_test.toml", fx))
    b.say("The fixtures override every client with short read timeouts and long write timeouts.")

    m = mods[5]
    b.user(f"Run tests for {m} and {mods[6]}.")
    for mm, e in ((m, err_distractors[1]), (mods[6], err_distractors[2])):
        cases = names(rnd, 25)
        ff = cases[rnd.randrange(len(cases))]
        b.tool("shell", {"command": f"python -m pytest tests/test_{mm}.py -q"},
               pytest_output(rnd, f"tests/test_{mm}.py", cases, {ff: [
                   f"    def {ff}():", f"E   {P}.errors.SchemaError: [{e}] unexpected column", ""]}))
    b.say(f"Both suites have one SchemaError failure each; they look like fixture drift.")

    # filler to push facts out of the recent window
    for m in mods[1:] + mods[1:4]:
        b.user(rnd.choice([f"Read src/{P}/{m}.py again and check the error handling.",
                           f"Look at src/{P}/{m}.py for anything that swallows exceptions.",
                           f"Check src/{P}/{m}.py for logging we should keep."]))
        path = f"src/{P}/{m}.py"
        lines = code_file(rnd, m, rnd.randint(130, 200))
        b.tool("read", {"path": path}, read_result(path, lines))
        b.say(rnd.choice([f"`{m}.py` logs at debug level only; nothing is swallowed.",
                          f"Error handling in `{m}.py` is fine; it returns cursors and never raises.",
                          f"`{m}.py` keeps its debug logging; no change needed."]))

    import_messages = b.messages

    # ---- steps ----
    def q(qid, category, text, answer, parts=None, restart=False, evidence=None):
        # ``evidence``: source strings that must all be in the model's context for the
        # fact to count as present (distinct even when the answer itself is short).
        return {"kind": "question", "id": f"h{index + 1}{qid.lower()}", "qid": qid,
                "category": category, "text": text, "answer": answer,
                "parts": parts or [answer], "evidence": evidence or parts or [answer],
                "restart_before": restart}

    def paste(pid, text):
        return {"kind": "paste", "id": f"h{index + 1}{pid.lower()}", "text": text}

    deploy = log_lines(rnd, 140, th["svc"])
    deploy.insert(rnd.randint(40, 100), f"2026-10-24T21:07:44Z INFO  canary: new release tag {tag_new} "
                                        f"(previous {tag_old}) promoted to 5% of traffic")
    lint = []
    for _ in range(240):
        mm = rnd.choice(mods)
        lint.append(f"src/{P}/{mm}.py:{rnd.randint(1, 400)}:{rnd.randint(1, 80)}: "
                    f"{rnd.choice(['E501', 'F401', 'W605', 'B008', 'C901', 'E741'])} "
                    f"{rnd.choice(['line too long', 'imported but unused', 'invalid escape', 'call in default arg', 'too complex', 'ambiguous name'])}")
    prof = ["   ncalls  tottime  percall  cumtime  percall filename:lineno(function)"]
    for _ in range(140):
        mm = rnd.choice(mods)
        prof.append(f"{rnd.randint(1, 90000):>9} {rnd.uniform(0, 9):8.3f} {rnd.uniform(0, 0.01):8.5f} "
                    f"{rnd.uniform(0, 20):8.3f} {rnd.uniform(0, 0.02):8.5f} {mm}.py:{rnd.randint(1, 400)}"
                    f"({rnd.choice(VERBS)}_{rnd.choice(ADJS)}_{rnd.choice(NOUNS)})")
    mid_cmd = f"python -m pytest tests/test_{th['const_mod']}.py -q"
    mid_case = names(rnd, 1)[0]
    mid_cases = names(rnd, 22)
    mid_cases[rnd.randrange(len(mid_cases))] = mid_case
    mid_out = pytest_output(rnd, f"tests/test_{th['const_mod']}.py", mid_cases, {mid_case: [
        f"    def {mid_case}():", f">       assert {th['const']} == REQUIRED",
        f"E   AssertionError: {th['const']} is {const_cur}; it must match requirement {req_id}", ""]})

    steps = [
        q("Q1", "identifier",
          f"Earlier, when we first ran the {mod_a} tests, the migration failed with an error code. "
          f"What was that exact code? Reply with only the code.", err_a),
        paste("P1", "Here's the canary deploy log from tonight, for reference; we'll come back to it. No analysis or tools needed now, just reply 'noted'.\n\n```\n"
              + "\n".join(deploy) + "\n```"),
        q("Q2", "identifier",
          "What branch name did I ask you to use for the main fix? Reply with only the branch name.",
          branch),
        q("Q3", "superseded",
          f"Which port should the {th['svc']} dev server use now? Reply with only the port number.",
          str(port_new), evidence=[f"to port {port_new}"]),
        paste("P2", "Here's the lint output from CI, for reference; we'll come back to it. No analysis or tools needed now, just reply 'noted'.\n\n```\n"
              + "\n".join(lint) + "\n```"),
        q("Q4", "irrelevant_matches",
          f"What read timeout is configured for the {target_client} client in the production "
          f"client settings? Reply with only the value.", timeouts[target_client][0],
          evidence=[f'read_timeout = "{timeouts[target_client][0]}"']),
        q("Q5", "vague",
          "And the write timeout for that same client? Reply with only the value.",
          timeouts[target_client][1],
          evidence=[f'write_timeout = "{timeouts[target_client][1]}"']),
        paste("P3", "Here's a profile of the slow job, for reference; we'll come back to it. No analysis or tools needed now, just reply 'noted'.\n\n```\n"
              + "\n".join(prof) + "\n```"),
        q("Q6", "oversized_read",
          f"In the full verbose integration test run, which test ran immediately after "
          f"{q6_before}? Reply with only the test function name.", q6_after),
        dict(q("Q7", "mid_task",
               f"Run `{mid_cmd}`. Don't change any code yet: tell me the value the failing constant "
               f"must have, according to the requirement I gave you earlier. Reply with only the value.",
               str(const_val), evidence=[f"{req_id}: {th['const']} must be {const_val}"]), mid_task={"command": mid_cmd, "output": mid_out}),
        q("Q8", "multi_fact",
          "Give me the full staging database target as host:port/database, using what we "
          "established earlier. Reply with only that string.",
          f"{host}:{db_port}/{db_name}", parts=[host, str(db_port), db_name],
          evidence=[f"STAGING_DB_HOST={host}", f"listens on {db_port}", db_name]),
        q("Q9", "restart_multi_eviction",
          "What new release tag did the canary deploy log I pasted earlier report? Reply with only the tag.",
          tag_new, restart=True),
        q("Q10", "vague",
          "What did you rename that old rounding helper to? Reply with only the new name."
          if index == 0 else
          "What did you rename that old helper to during the cleanup? Reply with only the new name.",
          new_helper),
    ]
    import_messages.append({"role": "user", "content": steps[0]["text"]})
    workspace = {
        f"tests/test_{th['const_mod']}.py": "\n".join([
            f"from {P}.{th['const_mod']} import {th['const']}", "", "REQUIRED = None  # see the requirement ticket", "",
            f"def {mid_case}():", f"    assert {th['const']} == REQUIRED", ""]),
        f"src/{P}/{th['const_mod']}.py": "\n".join(
            code_file(rnd, th["const_mod"], 60, {12: f"{th['const']} = {const_cur}"})) + "\n",
    }
    return {"id": f"dev-h{index + 1}", "seed": seed, "project": P, "set": "development",
            "generator": "eval/needle_gen.py v1", "import": import_messages, "steps": steps,
            "workspace": workspace,
            "shell": [{"match": f"pytest tests/test_{th['const_mod']}.py", "output": mid_out}]}


# ================================================================ held-out set (D44.3)
#
# A separate builder with its own themes, word banks, file names, value formats and a
# separate phrasing bank for every user turn, question and paste, so nothing is shared
# with the development texts except the step skeleton, the categories and the answer
# types. The project's tests are stdlib ``unittest`` here, so the mid-task command runs
# for real under OpenCode (the system Python has no pytest). ``build_history`` above is
# untouched: ``--set development`` regenerates the committed dev files byte-identically.

THEMES_HO = [
    dict(project="orchard", topic="late harvest forecasts after timezone shifts",
         modules=["forecast", "tz_shift", "yields", "plots", "irrigation", "exporter", "sensors",
                  "frost_alerts"], svc="orchard-sched", db="orchard_ops_qa",
         clients=["weather", "soil", "drones", "market", "labor", "logistics"],
         const="FORECAST_HORIZON_DAYS", const_mod="forecast", const_values=[14, 21, 28, 42],
         helper=("_shift_tz_naive", "shift_to_plot_tz"), kind="timezone", column="harvest_at"),
    dict(project="ferrylog", topic="missed sailings in the timetable importer",
         modules=["timetable", "berths", "tickets", "manifest", "tides", "crew", "importer",
                  "notices"], svc="ferry-sync", db="ferrylog_routes_qa",
         clients=["ports", "tidewatch", "fares", "crewing", "seastate", "sms"],
         const="MAX_BERTH_HOLD_MINUTES", const_mod="berths", const_values=[35, 50, 75, 110],
         helper=("_parse_sailing_old", "parse_sailing_row"), kind="parser", column="departs_local"),
    dict(project="glassbox", topic="stale feature flags after cache eviction",
         modules=["flags", "evaluator", "segments", "cache_layer", "audit_log", "rollout",
                  "sdk_bridge", "admin"], svc="glassbox-edge", db="glassbox_flags_qa",
         clients=["sso", "invoicing", "insights", "edgecdn", "email", "mobile"],
         const="FLAG_CACHE_TTL_MS", const_mod="cache_layer", const_values=[1250, 2500, 4500, 9000],
         helper=("_evict_lru_old", "evict_by_generation"), kind="eviction", column="rule_json"),
    dict(project="kilnworks", topic="temperature drift in batch firing schedules",
         modules=["firing", "ramps", "kilns", "glazes", "batches", "probes", "shift_plan",
                  "reports"], svc="kiln-control", db="kilnworks_plant_qa",
         clients=["thermo", "stockpile", "quality", "maintenance", "erp", "oncall"],
         const="MAX_RAMP_DEGREES_PER_HOUR", const_mod="ramps", const_values=[60, 85, 120, 150],
         helper=("_interp_ramp_v1", "interpolate_ramp_curve"), kind="interpolation",
         column="peak_celsius"),
    dict(project="patchbay", topic="audio routing loops after hot-plug events",
         modules=["route_table", "devices", "mixer", "hotplug", "presets", "meters", "latency",
                  "midi"], svc="patchbay-daemon", db="patchbay_rigs_qa",
         clients=["drivers", "cloudsync", "licensing", "crashlogs", "presetshare", "firmware"],
         const="MAX_ROUTE_HOPS", const_mod="route_table", const_values=[6, 9, 12, 16],
         helper=("_walk_graph_old", "walk_route_graph"), kind="graph-walk", column="channel_map"),
    dict(project="lumenpost", topic="broken image thumbnails after resizing",
         modules=["thumbs", "resizer", "storage", "cdn_purge", "exif", "queue_worker", "gallery",
                  "quotas"], svc="lumen-render", db="lumenpost_media_qa",
         clients=["blobstore", "edge", "moderation", "discovery", "plans", "mailer"],
         const="THUMBNAIL_MAX_EDGE_PX", const_mod="resizer", const_values=[320, 480, 640, 1080],
         helper=("_resize_nearest", "resize_lanczos_tiles"), kind="resize", column="pixel_ratio"),
    dict(project="quarrydesk", topic="ticket assignment races in the helpdesk queue",
         modules=["assign", "inbound_queues", "sla", "macros", "inbox", "agents", "escalation",
                  "digest"], svc="quarry-help", db="quarrydesk_tickets_qa",
         clients=["mailbox", "chat", "crm", "phone", "survey", "directory"],
         const="SLA_BREACH_GRACE_SECONDS", const_mod="sla", const_values=[45, 90, 180, 300],
         helper=("_pick_agent_rr", "pick_agent_weighted"), kind="assignment", column="assignee_id"),
    dict(project="saltmarsh", topic="sensor gaps in tide-gauge ingestion",
         modules=["gauges", "ingest_tide", "gapfill", "calib", "archive", "forecast_tide", "qc",
                  "exporter"], svc="saltmarsh-ingest", db="saltmarsh_gauges_qa",
         clients=["noaa", "satellite", "buoy", "radar", "portal", "warnings"],
         const="GAP_FILL_LIMIT_SAMPLES", const_mod="gapfill", const_values=[12, 18, 36, 72],
         helper=("_linear_fill_old", "fill_gaps_spline"), kind="gap-fill", column="water_level_mm"),
    dict(project="tallyho", topic="vote totals off by one in the election tabulator",
         modules=["tabulate", "ballots", "precincts", "audits", "canvass", "export_csv", "rules",
                  "signatures"], svc="tally-core", db="tallyho_results_qa",
         clients=["voter_roll", "courts", "press", "archive", "mapping", "bulletins"],
         const="RECOUNT_MARGIN_BASIS_POINTS", const_mod="rules", const_values=[25, 50, 75, 150],
         helper=("_count_marks_v1", "count_ballot_marks"), kind="counting", column="ballot_weight"),
    dict(project="wayfarer", topic="map tiles that fail to load offline",
         modules=["tiles", "offline_pack", "routing", "geocode", "sync_mobile", "styles", "poi",
                  "usage_stats"], svc="wayfarer-tiles", db="wayfarer_maps_qa",
         clients=["osm", "imagery", "traffic", "transit", "places", "crash"],
         const="OFFLINE_PACK_MAX_MB", const_mod="offline_pack", const_values=[256, 384, 512, 768],
         helper=("_tile_key_legacy", "tile_key_quadkey"), kind="tile-key", column="zoom_level"),
    dict(project="beekeeper", topic="hive metrics overwritten by delayed uploads",
         modules=["hives", "uploads", "metrics_hive", "alerts_swarm", "apiary", "weights",
                  "calendar", "sharing"], svc="beekeeper-api", db="beekeeper_hives_qa",
         clients=["scales", "forecaster", "handset", "export", "vet", "forum"],
         const="UPLOAD_REORDER_WINDOW_S", const_mod="uploads", const_values=[30, 45, 90, 120],
         helper=("_merge_last_write", "merge_by_sample_time"), kind="merge", column="sampled_at"),
    dict(project="inkwell", topic="footnote numbering that breaks across chapters",
         modules=["footnotes", "chapters", "typeset", "epub", "pdf_out", "styles_doc", "xref",
                  "spellcheck"], svc="inkwell-build", db="inkwell_books_qa",
         clients=["fonts", "vault_docs", "review", "print", "bookstore", "translate"],
         const="MAX_FOOTNOTES_PER_PAGE", const_mod="footnotes", const_values=[6, 8, 12, 14],
         helper=("_renumber_global", "renumber_per_chapter"), kind="numbering", column="note_index"),
]

VERBS_HO = ["gather", "rank", "prune", "align", "probe", "seal", "drain", "stage", "pack",
            "tally", "route", "fold", "clamp", "patch", "sweep", "index", "hoist", "lift"]
NOUNS_HO = ["frame", "lane", "chunk", "ticket", "pulse", "shard", "grid", "tier", "marker",
            "pool", "stamp", "range", "stack", "packet", "tray", "sample", "bundle", "beacon"]
ADJS_HO = ["hot", "idle", "spare", "frozen", "eager", "lazy", "stray", "brief", "coarse",
           "fine", "orphan", "shadow", "primary", "spent", "muted", "loose", "tight", "draft"]

# The held-out phrasing bank: every user turn, assistant summary, question and paste
# wrapper differs from the development wording in ``build_history``.
PH_HO = {
    "u_open": "Picking up {topic} in {P}. File everything under work order WO-{ticket}; the main "
              "fix lives on `{branch}`. First, open src/{P}/{mod_a}.py.",
    "a_open": "Opened `{mod_a}.py`: a context dataclass and {nfun} functions. Nothing stands "
              "out; I'd look at the tests next.",
    "u_tests": "Kick off the {mod_a} unit tests.",
    "a_tests": "`{fail}` errors out with a MigrationError while migrating the column; everything "
               "else is green.",
    "u_spec": "Spec {req_id}: {const} has to be {const_val}, because the partner integration "
              "refuses any other value. Separately, {req_other} pins BACKOFF_CEILING_MS at 4000. "
              "Hold on to both; they matter later.",
    "a_spec": "Recorded: {req_id} sets {const} to {const_val}; {req_other} pins "
              "BACKOFF_CEILING_MS at 4000.",
    "u_port": "If you need to start {svc} locally, bind it to {port_old}. Leave the operator "
              "console on {port_admin}.",
    "a_port": "OK: local {svc} on {port_old}, operator console on {port_admin}.",
    "u_clients": "How are the outbound service clients set up?",
    "a_clients": "settings/upstreams.toml defines six clients; each has its own read timeout, "
                 "write timeout, retry count and pool size.",
    "u_module": "Next, go through src/{P}/{m}.py. Does it do anything with {column}?",
    "a_module": "`{m}.py` just shuffles {noun} rows around; {column} never appears in it.",
    "u_env": "Which hosts does the QA environment use?",
    "a_env": "settings/qa.env lists the cache, database and broker hosts for QA, plus the "
             "database user.",
    "u_pooler": "Heads-up: the QA connection pooler is on port {db_port}, not 5432.",
    "a_pooler": "Noted, the QA pooler port is {db_port}.",
    "u_tests2": "Now run the {m} unit tests as well.",
    "a_tests2": "`{f2}` fails on a RetryError because its retry allowance ran out; that has "
                "nothing to do with the column migration.",
    "u_helper": "While you're in {mod_a}.py, retire the old {kind} helper.",
    "a_helper": "Done: `{old_helper}` is now `{new_helper}`, with a thin alias kept so "
                "existing imports still resolve.",
    "u_newport": "Scratch that port: run {svc} on {port_new} from now on, because {port_old} "
                 "collides with the tracing sidecar.",
    "a_newport": "Switched: {svc} now runs on {port_new}.",
    "u_db": "Which database is the dry-run of the migration supposed to hit?",
    "a_db": "The dry-run should go to `{db_name}` in QA.",
    "u_integ": "Run the whole integration suite in verbose mode.",
    "a_integ": "{n_integ} integration tests, all passing.",
    "u_docs": "When we get to the documentation pass, put it on `{branch_docs}`.",
    "a_docs": "OK, the documentation pass goes on `{branch_docs}`.",
    "u_fixture": "Which client timeouts are set in the test fixture file?",
    "a_fixture": "In the fixture, reads time out quickly and writes get a long allowance, for "
                 "every client.",
    "u_two": "Run the {m} and {m2} suites.",
    "a_two": "Each suite has a single SchemaError; the fixtures are probably stale.",
    "u_filler": ["Re-read src/{P}/{m}.py and look at how it handles errors.",
                 "Does src/{P}/{m}.py swallow any exceptions? Take a look.",
                 "Which log statements in src/{P}/{m}.py are worth keeping?",
                 "Skim src/{P}/{m}.py once more for bare excepts."],
    "a_filler": ["`{m}.py` keeps its logging at debug and never hides an exception.",
                 "`{m}.py` returns offsets and doesn't raise, so its error handling is fine.",
                 "Nothing to change in `{m}.py`; the debug logging can stay.",
                 "No bare excepts in `{m}.py`."],
    "paste": "Pasting {what} so it's on record; we'll return to it. Don't analyze it or run "
             "anything, just answer 'noted'.\n\n```\n{body}\n```",
    "paste_deploy": "tonight's rollout log",
    "paste_lint": "the CI lint report",
    "paste_prof": "a cProfile dump from the sluggish nightly task",
    "Q1": "Back when the {mod_a} unit tests first ran, the migration errored with a code in "
          "square brackets. Which code? Answer with the code alone.",
    "Q2": "Which branch did I say the main fix lives on? Answer with the branch name alone.",
    "Q3": "What port is {svc} supposed to run on at this point? Answer with the number alone.",
    "Q4": "In the live upstream client settings, what is the read timeout for the "
          "{target_client} client? Answer with the value alone.",
    "Q5": "What about its write timeout? Answer with the value alone.",
    "Q6": "In that verbose integration run, which test came right after {q6_before}? Answer "
          "with the test method name alone.",
    "Q7": "Run `{mid_cmd}`. Don't edit anything yet: according to the spec I gave you, what "
          "must the constant that fails be set to? Answer with the value alone.",
    "Q8": "Using what we found earlier, give the full QA database target in the form "
          "host:port/database. Answer with that string alone.",
    "Q9": "In the rollout log I pasted, what was the new release tag? Answer with the tag alone.",
    "Q10": "That old {kind} helper you retired: what name does it go by now? Answer with the "
           "new name alone.",
}


def names_ho(rnd: random.Random, k: int, prefix: str = "test_") -> list[str]:
    seen, out = set(), []
    while len(out) < k:
        n = f"{prefix}{rnd.choice(VERBS_HO)}_{rnd.choice(ADJS_HO)}_{rnd.choice(NOUNS_HO)}"
        if n in seen or any(n in s or s in n for s in seen):
            continue
        seen.add(n)
        out.append(n)
    return out


def code_file_ho(rnd: random.Random, module: str, lines: int) -> list[str]:
    """Plausible Python source lines in the held-out word banks."""
    cls = "".join(p.title() for p in module.split("_"))
    out = [f'"""{module.replace("_", " ").capitalize()} routines."""', "",
           "from __future__ import annotations", "", "import logging",
           "from dataclasses import dataclass, field", "", "logger = logging.getLogger(__name__)", "",
           "@dataclass", f"class {cls}Context:", "    offset: int = 0",
           "    backlog: list = field(default_factory=list)", ""]
    while len(out) < lines:
        v, n, a = rnd.choice(VERBS_HO), rnd.choice(NOUNS_HO), rnd.choice(ADJS_HO)
        out.append(f"def {v}_{a}_{n}(ctx: {cls}Context, {n}_rows: list[dict]) -> int:")
        for _ in range(rnd.randint(2, 6)):
            out.append(rnd.choice([
                f"    count = len([r for r in {n}_rows if r.get('{a}_{rnd.randint(1, 9)}')])",
                f"    ctx.offset += {rnd.randint(1, 64)}",
                f"    logger.debug('{v} {a} {n}: offset=%d', ctx.offset)",
                f"    ctx.backlog.extend({n}_rows[:{rnd.randint(2, 40)}])",
                f"    {n}_rows = sorted({n}_rows, key=lambda r: r.get('{n}_id', 0))",
                f"    # {v} {a} {n} rows before the {rnd.choice(NOUNS_HO)} is sealed",
            ]))
        out.append("    return ctx.offset")
        out.append("")
    return out[:lines]


def const_module_ho(rnd: random.Random, module: str, const: str, value: int) -> str:
    """An importable module defining ``const`` (the mid-task check imports it)."""
    lines = [f'"""{module.replace("_", " ").capitalize()} limits and helpers."""', "",
             f"{const} = {value}", ""]
    for _ in range(4):
        v, n = rnd.choice(VERBS_HO), rnd.choice(NOUNS_HO)
        lines += ["", f"def {v}_{n}_rows(rows: list[dict]) -> list[dict]:",
                  f'    """{v.capitalize()} {n} rows, at most {const} at a time."""',
                  f"    return rows[:{const}]", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def unittest_output(rnd: random.Random, dotted: str, cls: str, cases: list[str],
                    failures: dict[str, list[str]], kind: str = "ERROR") -> str:
    """``python -m unittest`` output; ``failures`` maps a case to its traceback lines."""
    mark = "E" if kind == "ERROR" else "F"
    out = ["".join(mark if c in failures else "." for c in cases)]
    for case, tb in failures.items():
        out += ["=" * 70, f"{kind}: {case} ({dotted}.{cls}.{case})", "-" * 70,
                "Traceback (most recent call last):", *tb, ""]
    out += ["-" * 70, f"Ran {len(cases)} test{'' if len(cases) == 1 else 's'} in "
                      f"{rnd.uniform(0.4, 7.5):.3f}s", ""]
    out.append(f"FAILED ({'errors' if kind == 'ERROR' else 'failures'}={len(failures)})"
               if failures else "OK")
    return "\n".join(out)


def build_heldout(index: int, seed: int) -> dict:
    """One held-out history: ``build_history``'s skeleton with held-out content."""
    rnd = random.Random(seed)
    th = THEMES_HO[index]
    P, mods = th["project"], list(th["modules"])
    rnd.shuffle(mods)
    mod_a = mods[0]
    b = Builder(rnd)
    ph = PH_HO

    def cls_of(mod: str) -> str:
        return "".join(p.title() for p in mod.split("_")) + "Tests"

    def ut_cmd(mod: str) -> str:
        return f"python -m unittest tests.test_{mod}"

    # ---- planted values (held-out formats; answer types as in build_history) ----
    err_a = code(rnd, P[:3].upper())
    err_distractors = [code(rnd, P[:3].upper()) for _ in range(3)]
    ticket = rnd.randint(10000, 99999)
    slug = th["topic"].split()[0]
    branch = f"hotfix/{ticket}-{P}-{slug}"
    branch_docs = f"chore/{P}-docs-{ticket}"
    port_old, port_new, port_admin = rnd.randint(7100, 7199), rnd.randint(7600, 7699), rnd.randint(7300, 7399)
    clients = list(th["clients"])
    rnd.shuffle(clients)
    target_client = clients[0]
    timeouts = {c: (f"{rnd.choice([0.75, 1.5, 2.75, 3.25, 4.25, 5.5, 6.25, 8.5])}s",
                    f"{rnd.randint(9, 28)}s") for c in clients}
    used_r = {v[0] for c, v in timeouts.items() if c != target_client}
    used_w = {v[1] for c, v in timeouts.items() if c != target_client}
    r, w = timeouts[target_client]
    while r in used_r:
        r = f"{rnd.randint(1, 9)}.{rnd.choice(['25', '5', '75'])}s"
    while w in used_w:
        w = f"{rnd.randint(32, 58)}s"
    timeouts[target_client] = (r, w)
    fixture_timeouts = {c: (f"{rnd.randint(1, 9)}.0s", f"{rnd.randint(60, 90)}s") for c in clients}
    req_id, req_other = f"SPEC-{rnd.randint(1000, 9999)}", f"SPEC-{rnd.randint(1000, 9999)}"
    const_val = rnd.choice(th["const_values"])
    const_cur = const_val // 2
    host = f"db-qa-{rnd.randint(2, 19):02d}.corp"
    db_port = rnd.choice([5544, 6101, 6888, 7010])
    db_name = th["db"]
    old_helper, new_helper = th["helper"]
    tag_new = f"rel-2026.11.{rnd.randint(10, 28)}-p{rnd.randint(2, 9)}"
    tag_old = f"rel-2026.11.{rnd.randint(1, 9):02d}-p{rnd.randint(1, 9)}"
    integ = names_ho(rnd, 420)
    k6 = rnd.randint(60, 300)
    q6_before, q6_after = integ[k6], integ[k6 + 1]
    v = dict(P=P, topic=th["topic"], ticket=ticket, branch=branch, mod_a=mod_a, svc=th["svc"],
             req_id=req_id, req_other=req_other, const=th["const"], const_val=const_val,
             port_old=port_old, port_new=port_new, port_admin=port_admin, db_port=db_port,
             db_name=db_name, kind=th["kind"], old_helper=old_helper, new_helper=new_helper,
             branch_docs=branch_docs, column=th["column"], target_client=target_client,
             q6_before=q6_before)

    def say(key: str, **kw) -> None:
        b.say(ph[key].format(**v, **kw))

    def user(key: str, **kw) -> None:
        b.user(ph[key].format(**v, **kw))

    # ---- import turns ----
    user("u_open")
    lines = code_file_ho(rnd, mod_a, rnd.randint(120, 170))
    b.tool("read", {"path": f"src/{P}/{mod_a}.py"}, read_result(f"src/{P}/{mod_a}.py", lines))
    say("a_open", nfun=sum(1 for l in lines if l.startswith("def ")))

    user("u_tests")
    cases = names_ho(rnd, 38)
    fail = cases[rnd.randrange(len(cases))]
    tb = [f'  File "tests/test_{mod_a}.py", line {rnd.randint(40, 300)}, in {fail}',
          f"    migrate(self.db, '{th['column']}')",
          f"{P}.errors.MigrationError: [{err_a}] cannot migrate column '{th['column']}'"]
    b.tool("shell", {"command": ut_cmd(mod_a)},
           unittest_output(rnd, f"tests.test_{mod_a}", cls_of(mod_a), cases, {fail: tb}))
    say("a_tests", fail=fail)

    user("u_spec")
    say("a_spec")
    user("u_port")
    say("a_port")

    cfg = ["# Live upstream clients (parsed by settings.load_upstreams)", ""]
    for c in clients:
        cfg += [f"[upstream.{c}]", f'endpoint = "https://{c}.{P}.corp"',
                f'read_timeout = "{timeouts[c][0]}"', f'write_timeout = "{timeouts[c][1]}"',
                f"max_retries = {rnd.randint(1, 6)}", f"pool = {rnd.randint(4, 64)}", ""]
    user("u_clients")
    b.tool("read", {"path": "settings/upstreams.toml"}, read_result("settings/upstreams.toml", cfg))
    say("a_clients")

    for m in mods[1:3]:
        user("u_module", m=m)
        lines = code_file_ho(rnd, m, rnd.randint(110, 160))
        b.tool("read", {"path": f"src/{P}/{m}.py"}, read_result(f"src/{P}/{m}.py", lines))
        say("a_module", m=m, noun=rnd.choice(NOUNS_HO))

    env = [f"QA_CACHE_HOST=cache-qa-{rnd.randint(2, 9):02d}.corp",
           f"QA_DB_HOST={host}", f"QA_BROKER_HOST=broker-qa-{rnd.randint(2, 9):02d}.corp",
           f"QA_DB_USER={P}_svc", "QA_DB_TLS=verify-full",
           f"QA_TOGGLES={rnd.choice(NOUNS_HO)},{rnd.choice(NOUNS_HO)}"]
    user("u_env")
    b.tool("read", {"path": "settings/qa.env"}, read_result("settings/qa.env", env))
    say("a_env")

    user("u_pooler")
    say("a_pooler")

    m = mods[3]
    user("u_tests2", m=m)
    cases = names_ho(rnd, 30)
    f2 = cases[rnd.randrange(len(cases))]
    b.tool("shell", {"command": ut_cmd(m)},
           unittest_output(rnd, f"tests.test_{m}", cls_of(m), cases, {f2: [
               f'  File "tests/test_{m}.py", line {rnd.randint(20, 200)}, in {f2}',
               "    self.assertEqual(run(), 0)",
               f"{P}.errors.RetryError: [{err_distractors[0]}] retry budget exhausted"]}))
    say("a_tests2", f2=f2)

    user("u_helper")
    b.tool("edit", {"path": f"src/{P}/{mod_a}.py", "oldString": f"def {old_helper}(",
                    "newString": f"def {new_helper}("},
           f"Edited src/{P}/{mod_a}.py (1 replacement)")
    say("a_helper")

    user("u_newport")
    say("a_newport")

    user("u_db")
    b.tool("grep", {"pattern": "_qa", "path": "settings"},
           f"Found 1 matches\nsettings\\databases.yaml:\n  Line {rnd.randint(3, 30)}:   qa: {db_name}")
    say("a_db")

    user("u_integ")
    out = []
    areas = [(f"tests.integration.test_{x}", cls_of(x)) for x in mods]
    for i, n in enumerate(integ):
        dotted, cls = areas[i * len(areas) // len(integ)]
        out.append(f"{n} ({dotted}.{cls}.{n}) ... ok")
    out += ["", "-" * 70, f"Ran {len(integ)} tests in {rnd.uniform(60, 200):.3f}s", "", "OK"]
    b.tool("shell", {"command": "python -m unittest discover -s tests/integration -v"}, "\n".join(out))
    say("a_integ", n_integ=len(integ))

    user("u_docs")
    say("a_docs")

    fx = ["# Fixture: short read timeouts, long write timeouts", ""]
    for c in clients:
        fx += [f"[upstream.{c}]", f'read_timeout = "{fixture_timeouts[c][0]}"',
               f'write_timeout = "{fixture_timeouts[c][1]}"', ""]
    user("u_fixture")
    b.tool("read", {"path": "tests/fixtures/upstreams_fixture.toml"},
           read_result("tests/fixtures/upstreams_fixture.toml", fx))
    say("a_fixture")

    user("u_two", m=mods[5], m2=mods[6])
    for mm, e in ((mods[5], err_distractors[1]), (mods[6], err_distractors[2])):
        cases = names_ho(rnd, 25)
        ff = cases[rnd.randrange(len(cases))]
        b.tool("shell", {"command": ut_cmd(mm)},
               unittest_output(rnd, f"tests.test_{mm}", cls_of(mm), cases, {ff: [
                   f'  File "tests/test_{mm}.py", line {rnd.randint(20, 200)}, in {ff}',
                   "    load_fixture(self)",
                   f"{P}.errors.SchemaError: [{e}] unexpected column"]}))
    say("a_two")

    # filler to push facts out of the recent window
    for m in mods[1:] + mods[1:4]:
        b.user(rnd.choice(ph["u_filler"]).format(P=P, m=m))
        path = f"src/{P}/{m}.py"
        lines = code_file_ho(rnd, m, rnd.randint(130, 200))
        b.tool("read", {"path": path}, read_result(path, lines))
        b.say(rnd.choice(ph["a_filler"]).format(m=m))

    import_messages = b.messages

    # ---- steps: the same skeleton, categories and answer types as build_history ----
    sid = f"ho{index + 1}"

    def q(qid, category, answer, parts=None, restart=False, evidence=None, **kw):
        return {"kind": "question", "id": f"{sid}{qid.lower()}", "qid": qid,
                "category": category, "text": ph[qid].format(**v, **kw), "answer": answer,
                "parts": parts or [answer], "evidence": evidence or parts or [answer],
                "restart_before": restart}

    def paste(pid, what, body):
        return {"kind": "paste", "id": f"{sid}{pid.lower()}",
                "text": ph["paste"].format(what=ph[what], body="\n".join(body))}

    deploy = log_lines(rnd, 140, th["svc"])
    deploy.insert(rnd.randint(40, 100), f"2026-11-0{rnd.randint(1, 9)}T22:41:09Z INFO  rollout: "
                                        f"promoting {tag_new} over {tag_old} to the 10% cohort")
    lint = []
    for _ in range(240):
        mm = rnd.choice(mods)
        lint.append(f"src/{P}/{mm}.py:{rnd.randint(1, 400)}:{rnd.randint(1, 80)}: "
                    f"{rnd.choice(['E302', 'F841', 'W291', 'B006', 'C416', 'N802'])} "
                    f"{rnd.choice(['expected 2 blank lines', 'local variable never used', 'trailing whitespace', 'mutable default argument', 'unnecessary comprehension', 'function name should be lowercase'])}")
    prof = ["   ncalls  tottime  percall  cumtime  percall filename:lineno(function)"]
    for _ in range(140):
        mm = rnd.choice(mods)
        prof.append(f"{rnd.randint(1, 90000):>9} {rnd.uniform(0, 9):8.3f} {rnd.uniform(0, 0.01):8.5f} "
                    f"{rnd.uniform(0, 20):8.3f} {rnd.uniform(0, 0.02):8.5f} {mm}.py:{rnd.randint(1, 400)}"
                    f"({rnd.choice(VERBS_HO)}_{rnd.choice(ADJS_HO)}_{rnd.choice(NOUNS_HO)})")
    cm = th["const_mod"]
    mid_cmd = ut_cmd(cm)
    mid_case = names_ho(rnd, 1)[0]
    message = f"{th['const']} is {const_cur}; it must match requirement {req_id}"
    mid_out = unittest_output(rnd, f"tests.test_{cm}", cls_of(cm), [mid_case], {mid_case: [
        f'  File "tests/test_{cm}.py", line 15, in {mid_case}',
        f"    self.assertEqual({th['const']}, REQUIRED, MESSAGE)",
        f"AssertionError: {const_cur} != None : {message}"]}, kind="FAIL")

    steps = [
        q("Q1", "identifier", err_a),
        paste("P1", "paste_deploy", deploy),
        q("Q2", "identifier", branch),
        q("Q3", "superseded", str(port_new), evidence=[f"{th['svc']} on {port_new} from now on"]),
        paste("P2", "paste_lint", lint),
        q("Q4", "irrelevant_matches", timeouts[target_client][0],
          evidence=[f'read_timeout = "{timeouts[target_client][0]}"']),
        q("Q5", "vague", timeouts[target_client][1],
          evidence=[f'write_timeout = "{timeouts[target_client][1]}"']),
        paste("P3", "paste_prof", prof),
        q("Q6", "oversized_read", q6_after),
        dict(q("Q7", "mid_task", str(const_val), mid_cmd=mid_cmd,
               evidence=[f"{req_id}: {th['const']} has to be {const_val}"]),
             mid_task={"command": mid_cmd, "output": mid_out}),
        q("Q8", "multi_fact", f"{host}:{db_port}/{db_name}", parts=[host, str(db_port), db_name],
          evidence=[f"QA_DB_HOST={host}", f"on port {db_port}", db_name]),
        q("Q9", "restart_multi_eviction", tag_new, restart=True),
        q("Q10", "vague", new_helper),
    ]
    import_messages.append({"role": "user", "content": steps[0]["text"]})
    const = th["const"]
    test_file = "\n".join([
        "import sys", "import unittest", "from pathlib import Path", "",
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))', "",
        f"from {P}.{cm} import {const}  # noqa: E402", "",
        "REQUIRED = None  # see the requirement ticket",
        f'MESSAGE = f"{const} is {{{const}}}; it must match requirement {req_id}"', "", "",
        f"class {cls_of(cm)}(unittest.TestCase):",
        f"    def {mid_case}(self):",
        f"        self.assertEqual({const}, REQUIRED, MESSAGE)", ""])
    workspace = {
        f"tests/test_{cm}.py": test_file,
        f"src/{P}/{cm}.py": const_module_ho(rnd, cm, const, const_cur),
    }
    return {"id": f"ho-h{index + 1}", "seed": seed, "project": P, "set": "heldout",
            "generator": "eval/needle_gen.py heldout v1", "import": import_messages, "steps": steps,
            "workspace": workspace,
            "shell": [{"match": f"unittest tests.test_{cm}", "output": mid_out}]}


SETS = {"development": (THEMES, build_history, Path("eval/needles/dev"), 3100),
        "heldout": (THEMES_HO, build_heldout, Path("eval/needles/heldout"), 5200)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--set", choices=sorted(SETS), default="development",
                   help="development: dev-h1..h6 (seeds 3100-3105); heldout: ho-h1..h12 "
                        "(seeds 5200-5211, D44.3)")
    p.add_argument("--out", type=Path)
    p.add_argument("--seed-base", type=int)
    a = p.parse_args()
    themes, build, out, seed_base = SETS[a.set]
    out = a.out or out
    seed_base = a.seed_base if a.seed_base is not None else seed_base
    out.mkdir(parents=True, exist_ok=True)
    for i in range(len(themes)):
        h = build(i, seed_base + i)
        (out / f"{h['id']}.json").write_text(json.dumps(h, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8", newline="\n")
        chars = sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or ""))
                    for m in h["import"])
        print(f"{h['id']}: {len(h['import'])} import messages, ~{chars} chars, {len(h['steps'])} steps")


if __name__ == "__main__":
    main()
