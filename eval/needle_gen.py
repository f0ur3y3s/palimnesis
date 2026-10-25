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

Usage: python eval/needle_gen.py --out eval/needles/dev
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


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("eval/needles/dev"))
    p.add_argument("--seed-base", type=int, default=3100)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for i in range(len(THEMES)):
        h = build_history(i, a.seed_base + i)
        (a.out / f"{h['id']}.json").write_text(json.dumps(h, indent=1, ensure_ascii=False) + "\n",
                                               encoding="utf-8", newline="\n")
        chars = sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or ""))
                    for m in h["import"])
        print(f"{h['id']}: {len(h['import'])} import messages, ~{chars} chars, {len(h['steps'])} steps")


if __name__ == "__main__":
    main()
