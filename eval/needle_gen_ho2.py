"""Seeded generator for the Phase 3B fresh held-out needle set ``ho2`` (O-B1, A1 "Evaluation").

The Phase 3 held-out set (``needle_gen.py --set heldout``) was seen before Phase 3B was
designed, so the 3B gate is judged on this set. It keeps the step skeleton, categories and
answer types of ``build_history`` (so A1's coverage holds) and replaces everything else:
twelve new themes, new word banks, new file names, value formats, tool-output bodies and
a new phrasing bank for every user turn, assistant summary, question and paste wrapper.

Steps after the import (the shared skeleton):

    Q1, P1 (paste carrying the Q9 fact), Q2, Q3, P2, Q4, Q5, P3, Q6, Q7, Q8,
    [proxy restart], Q9, Q10

Categories (A1): identifier (Q1, Q2), superseded (Q3), irrelevant matches (Q4),
vague reference (Q5, Q10), oversized transcript read (Q6), mid-task need (Q7),
several distant facts (Q8), restart plus multiple eviction events (Q9).

Only the OpenCode 2.1.4 tool-result shapes (``read_result``), the ``python -m unittest``
output shape and the message builder are imported from ``needle_gen``; they are formats,
not content.

Usage:
    python eval/needle_gen_ho2.py [--out DIR]   # writes ho2-h1..h12, seeds 6400-6411
    python eval/needle_gen_ho2.py --check       # independence from dev and heldout
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import needle_gen as ng  # noqa: E402
from needle_gen import Builder, read_result, unittest_output  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "needles" / "heldout2"
SEED_BASE = 6400
SET = "heldout2"
GENERATOR = "eval/needle_gen_ho2.py v1"

THEMES_HO2 = [
    dict(project="loomline", topic="thread tension alarms dropped during shift handover",
         modules=["tension", "spindles", "shift_handover", "looms", "dye_lots", "alarm_bus",
                  "yarn_stock", "qc_photos"], svc="loomline-gw", db="loomline_mill_pp",
         clients=["dyehouse", "spinners", "payroll_feed", "visionqc", "pager_bridge",
                  "supplier_portal"],
         const="TENSION_ALARM_DEBOUNCE_MS", const_mod="tension", const_values=[175, 225, 350, 425],
         helper=("_debounce_fixed", "debounce_adaptive"), kind="debounce", column="tension_cn"),
    dict(project="cinderpath", topic="evacuation routes that ignore closed roads",
         modules=["closures", "routes_evac", "shelters", "fire_perimeter", "traffic_feed",
                  "notices_public", "zones", "drills"], svc="cinder-router", db="cinderpath_routes_pp",
         clients=["dot_closures", "firewatch", "shelter_reg", "radio_alerts", "census_blocks",
                  "transit_ops"],
         const="MAX_DETOUR_KM", const_mod="routes_evac", const_values=[17, 23, 29, 41],
         helper=("_dijkstra_static", "route_around_closures"), kind="pathfinding",
         column="closure_until"),
    dict(project="brinevat", topic="salinity readings drifting after probe recalibration",
         modules=["salinity", "vats", "recal", "batch_labels", "brine_mix", "cold_room",
                  "lot_trace", "dashboards"], svc="brinevat-ctl", db="brinevat_lots_pp",
         clients=["labsuite", "chillers", "labelprint", "traceback_reg", "grocer_edi",
                  "facilities"],
         const="SALINITY_SAMPLE_INTERVAL_S", const_mod="salinity", const_values=[55, 65, 95, 105],
         helper=("_apply_offset_once", "apply_calibration_curve"), kind="calibration",
         column="brine_ppt"),
    dict(project="starling", topic="sightings duplicated after offline sync",
         modules=["sightings", "observers", "species_list", "sync_queue", "transects",
                  "photo_ids", "rarity", "exports_survey"], svc="starling-sync",
         db="starling_survey_pp",
         clients=["taxonomy", "gis_layers", "photo_store", "volunteer_hub", "parks_api",
                  "rarities_board"],
         const="SIGHTING_MERGE_RADIUS_M", const_mod="sightings", const_values=[35, 65, 95, 140],
         helper=("_dedupe_by_time", "merge_sightings_spatial"), kind="merging",
         column="observed_lat"),
    dict(project="copperline", topic="breaker trips blamed on the wrong feeder",
         modules=["feeders", "breakers", "substations", "trip_log", "load_shed", "scada_link",
                  "maint_windows", "tariffs"], svc="copperline-scada", db="copperline_grid_pp",
         clients=["scada_hist", "crew_dispatch", "weather_grid", "billing_meter", "asset_reg",
                  "control_room"],
         const="TRIP_ATTRIBUTION_WINDOW_MS", const_mod="trip_log", const_values=[260, 410, 530, 870],
         helper=("_nearest_feeder_guess", "attribute_trip_by_phase"), kind="attribution",
         column="feeder_code"),
    dict(project="marrowbone", topic="expired blood units still offered for crossmatch",
         modules=["blood_units", "crossmatch", "expiry", "donors", "storage_temp",
                  "ward_requests", "recall", "audit_trail"], svc="marrow-bank",
         db="marrowbone_units_pp",
         clients=["lis_gateway", "ward_orders", "courier", "donor_registry", "temp_probes",
                  "regulator_feed"],
         const="CROSSMATCH_HOLD_HOURS", const_mod="crossmatch", const_values=[33, 54, 66, 78],
         helper=("_expiry_date_naive", "expiry_with_collection_tz"), kind="expiry",
         column="expires_on"),
    dict(project="tinsmith", topic="parts overlapping in the sheet nesting optimizer",
         modules=["nesting", "sheets", "kerf", "toolpaths", "offcuts", "cnc_jobs", "quotes",
                  "machines"], svc="tinsmith-nest", db="tinsmith_jobs_pp",
         clients=["cad_import", "laser_cells", "steel_supplier", "quote_portal", "shop_floor",
                  "scrap_yard"],
         const="KERF_WIDTH_MICRONS", const_mod="kerf", const_values=[130, 175, 220, 290],
         helper=("_bbox_overlap", "polygon_overlap_exact"), kind="overlap", column="sheet_gauge"),
    dict(project="sandglass", topic="submissions accepted after the exam window closes",
         modules=["exam_windows", "submissions", "proctor", "extensions", "rubrics",
                  "grades_sync", "accommodations", "exam_clock"], svc="sandglass-exam",
         db="sandglass_exams_pp",
         clients=["lms_bridge", "sis_roster", "originality", "webcam_proc", "registrar",
                  "accessibility"],
         const="LATE_WINDOW_SLACK_S", const_mod="exam_windows", const_values=[20, 40, 70, 130],
         helper=("_compare_wallclock", "compare_monotonic_deadline"), kind="deadline",
         column="turned_in_ts"),
    dict(project="fernwood", topic="holds skipped when a copy returns to another branch",
         modules=["hold_queue", "circulation", "branches_lib", "transit_slips", "patrons",
                  "catalog_marc", "fines", "pickup_shelf"], svc="fernwood-circ",
         db="fernwood_circ_pp",
         clients=["marc_feed", "courier_van", "patron_sms", "ebook_vendor", "consortium",
                  "self_check"],
         const="HOLD_SHELF_DAYS", const_mod="hold_queue", const_values=[5, 7, 10, 13],
         helper=("_first_branch_wins", "assign_hold_by_queue"), kind="queueing",
         column="pickup_branch"),
    dict(project="riverbend", topic="waiver signatures lost when kayak bookings are transferred",
         modules=["bookings", "fleet", "weather_cancel", "waivers", "deposits", "launch_sites",
                  "guides", "refund_rules"], svc="riverbend-book", db="riverbend_rentals_pp",
         clients=["river_gauge", "card_psp", "waiver_sign", "sms_gateway", "guide_roster",
                  "insurer"],
         const="WAIVER_CARRYOVER_DAYS", const_mod="waivers", const_values=[3, 4, 9, 11],
         helper=("_copy_waiver_shallow", "transfer_waiver_signed"), kind="transfer",
         column="waiver_sig"),
    dict(project="hollowreed", topic="chapter markers misaligned after audio trimming",
         modules=["chapter_marks", "episodes", "trimmer", "feeds_rss", "episode_text", "ad_slots",
                  "download_stats", "episode_uploads"], svc="hollowreed-feed",
         db="hollowreed_shows_pp",
         clients=["cdn_audio", "ad_market", "podcast_dir", "speech_text", "host_portal",
                  "stats_sink"],
         const="CHAPTER_SNAP_TOLERANCE_MS", const_mod="chapter_marks", const_values=[120, 240, 360, 600],
         helper=("_shift_by_trim_start", "remap_chapters_after_trim"), kind="remapping",
         column="chapter_start_ms"),
    dict(project="gristmill", topic="moisture discounts applied twice on split loads",
         modules=["grain_loads", "moisture", "discounts", "scale_tickets", "grain_bins",
                  "grain_contracts", "farm_settlements", "trucks"], svc="gristmill-scale",
         db="gristmill_tickets_pp",
         clients=["scale_head", "grain_market", "farmer_portal", "bank_ach", "dryer_ctl",
                  "inspector"],
         const="MOISTURE_SHRINK_BASIS", const_mod="discounts", const_values=[115, 135, 185, 245],
         helper=("_discount_per_split", "discount_once_per_load"), kind="discount",
         column="moisture_pct"),
]

VERBS_HO2 = ["weave", "spool", "thread", "bind", "graft", "knit", "temper", "anneal", "quench",
             "ferry", "relay", "reckon", "winnow", "sieve", "churn", "steep", "kindle", "mend"]
NOUNS_HO2 = ["bobbin", "skein", "ingot", "rivet", "ledger_line", "parcel", "quiver", "lattice",
             "spindle", "trellis", "kettle", "anvil", "hinge", "socket", "ember", "keel", "plank",
             "girder"]
ADJS_HO2 = ["brittle", "supple", "molten", "hollow", "gilded", "rusty", "dormant", "nimble",
            "sturdy", "faded", "crisp", "humid", "brisk", "rugged", "mellow", "sparse", "tepid",
            "woven"]

# The ho2 phrasing bank. No four-word run is shared with the development or the
# Phase 3 held-out wording (``check``).
PH = {
    "u_open": "Today's subject in {P} is {topic}. Log the work against case CASE-{ticket}, and "
              "commit the core change to `{branch}`. Begin with src/{P}/{mod_a}.py, please.",
    "a_open": "I looked through `{mod_a}.py`. It defines a settings dataclass plus {nfun} plain "
              "functions, and nothing in it looks broken. The test results would tell us more.",
    "u_tests": "Please execute the unit tests for {mod_a}.",
    "a_tests": "A single test, `{fail}`, blows up with MigrationError while altering the column. "
               "All other cases succeed.",
    "u_spec": "Ticket {req_id} says {const} must equal {const_val}; our vendor's importer rejects "
              "every other setting. Also, ticket {req_other} freezes JITTER_FLOOR_MS at 700. "
              "Remember both for later.",
    "a_spec": "Will do. {req_id}: {const} equals {const_val}. {req_other}: JITTER_FLOOR_MS "
              "frozen at 700.",
    "u_port": "Whenever {svc} needs to run on your machine, give it port {port_old}. The "
              "maintenance dashboard keeps {port_admin}.",
    "a_port": "Right: {svc} gets {port_old} locally and the maintenance dashboard keeps "
              "{port_admin}.",
    "u_clients": "Can you show me the peer client definitions?",
    "a_clients": "conf/peers.toml declares six peers. Every peer carries a URL, a read timeout, "
                 "a write timeout, an attempt limit and a connection cap.",
    "u_module": "Have a look at src/{P}/{m}.py next. Is {column} used anywhere in it?",
    "a_module": "Nope, `{m}.py` only reorders {noun} records, and {column} isn't referenced.",
    "u_env": "What hosts are set for preprod?",
    "a_env": "conf/preprod.env sets the cache host, the database host, the bus host and the "
             "database login for preprod.",
    "u_pooler": "Quick note: in preprod the pgbouncer pooler is on {db_port}, rather than 5432.",
    "a_pooler": "Thanks, pooler on {db_port} for preprod.",
    "u_tests2": "Also execute the unit tests for {m}.",
    "a_tests2": "`{f2}` reports a RetryError after using up its retries. It's unrelated to "
                "the column change.",
    "u_helper": "Since {mod_a}.py is open, please replace the outdated {kind} helper.",
    "a_helper": "Replaced: `{old_helper}` became `{new_helper}`, and an alias under the "
                "previous name keeps old callers importing fine.",
    "u_newport": "New decision on {svc}: it moves to port {port_new}. {port_old} fights with "
                 "the log shipper.",
    "a_newport": "Updated, {svc} uses port {port_new} going forward.",
    "u_db": "For the migration rehearsal, what database do we aim at?",
    "a_db": "The rehearsal targets `{db_name}` in preprod.",
    "u_integ": "Kick the integration tests, all of them, with -v.",
    "a_integ": "Every one of the {n_integ} integration tests passed.",
    "u_docs": "Later, the write-up for this goes on `{branch_docs}`.",
    "a_docs": "Sure, the write-up will be on `{branch_docs}`.",
    "u_fixture": "And the timeouts in the test data peers file?",
    "a_fixture": "The test data gives each peer a tiny read timeout and a huge write timeout.",
    "u_two": "Execute both the {m} tests and the {m2} tests.",
    "a_two": "Both have exactly one SchemaError, most likely from outdated fixture data.",
    "u_filler": ["Open src/{P}/{m}.py again; how does it deal with failures?",
                 "Are exceptions being silenced somewhere in src/{P}/{m}.py?",
                 "Go over src/{P}/{m}.py: which logging calls matter?",
                 "Search src/{P}/{m}.py again for except clauses without a type."],
    "a_filler": ["Failures in `{m}.py` are logged at debug level and re-raised.",
                 "`{m}.py` never raises; it hands back positions, which is fine.",
                 "The logging in `{m}.py` is fine as it is.",
                 "Every except clause in `{m}.py` names its exception type."],
    "paste": "For the record, here is {what}. We will look at it later. Please skip any "
             "analysis and tool use; a reply of 'noted' is enough.\n\n```\n{body}\n```",
    "paste_deploy": "the release train log from this evening",
    "paste_lint": "the flake8 report from the pipeline",
    "paste_prof": "profiler output for the slow batch import",
    "Q1": "The very first {mod_a} unit test run hit a MigrationError, and the message had a "
          "bracketed code. Give me that code and nothing else.",
    "Q2": "Remind me: the core change was supposed to be committed to which branch? Give me "
          "the branch and nothing else.",
    "Q3": "Right now, which port does {svc} use? Give me the port and nothing else.",
    "Q4": "For the {target_client} peer, what read timeout do the real peer definitions set? "
          "Give me the value and nothing else.",
    "Q5": "Same peer, write timeout? Give me the value and nothing else.",
    "Q6": "During the -v integration run, what test ran directly after {q6_before}? Give me "
          "the method name and nothing else.",
    "Q7": "Please run `{mid_cmd}`. Leave the code alone for now. Based on the ticket I "
          "mentioned at the start, what value does the failing constant need? Give me the "
          "value and nothing else.",
    "Q8": "Combine the preprod DB host, the pooler port and the database name into one "
          "host:port/database string, using the earlier findings. Give me that and nothing else.",
    "Q9": "From the release train log I shared, which tag was newly cut? Give me the tag and "
          "nothing else.",
    "Q10": "The outdated {kind} helper you replaced earlier: what's it called now? Give me "
           "the name and nothing else.",
}

CODE_LETTERS = "BCDFGHJKMNPQRSTVWXZ"


def names_ho2(rnd: random.Random, k: int, prefix: str = "test_") -> list[str]:
    seen, out = set(), []
    while len(out) < k:
        n = f"{prefix}{rnd.choice(VERBS_HO2)}_{rnd.choice(ADJS_HO2)}_{rnd.choice(NOUNS_HO2)}"
        if n in seen or any(n in s or s in n for s in seen):
            continue
        seen.add(n)
        out.append(n)
    return out


def err_code(rnd: random.Random, P: str) -> str:
    """``LOO.E4821.K7``: a value format used by neither earlier set."""
    return f"{P[:3].upper()}.E{rnd.randint(1000, 9999)}.{rnd.choice(CODE_LETTERS)}{rnd.randint(1, 9)}"


def code_file_ho2(rnd: random.Random, module: str, lines: int) -> list[str]:
    cls = "".join(p.title() for p in module.split("_"))
    out = [f'"""Routines for the {module.replace("_", " ")} stage."""', "",
           "from __future__ import annotations", "", "import logging", "import typing as t",
           "from dataclasses import dataclass", "", "_LOG = logging.getLogger(__name__)", "",
           "@dataclass", f"class {cls}Settings:", "    position: int = 0",
           "    budget: int = 128", ""]
    while len(out) < lines:
        v, n, a = rnd.choice(VERBS_HO2), rnd.choice(NOUNS_HO2), rnd.choice(ADJS_HO2)
        out.append(f"def {v}_{a}_{n}(cfg: {cls}Settings, items: t.Sequence[dict]) -> int:")
        for _ in range(rnd.randint(2, 6)):
            out.append(rnd.choice([
                f"    picked = [it for it in items if it.get('{n}_k{rnd.randint(1, 9)}')]",
                f"    cfg.position = min(cfg.position + {rnd.randint(1, 48)}, cfg.budget)",
                f"    _LOG.debug('{v} {a} {n} at %s', cfg.position)",
                f"    cfg.budget -= len(items) // {rnd.randint(2, 9)}",
                f"    items = tuple(reversed(items))  # {a} {n} first",
                f"    # {v} each {a} {n} ahead of the {rnd.choice(NOUNS_HO2)} handoff",
            ]))
        out.append("    return cfg.position")
        out.append("")
    return out[:lines]


def const_module_ho2(rnd: random.Random, module: str, const: str, value: int) -> str:
    lines = [f'"""Tunables for the {module.replace("_", " ")} stage."""', "",
             f"{const} = {value}", ""]
    for _ in range(4):
        v, n = rnd.choice(VERBS_HO2), rnd.choice(NOUNS_HO2)
        lines += ["", f"def {v}_{n}_window(items: list) -> list:",
                  f'    """Keep at most {const} {n} items for the {v} pass."""',
                  f"    return list(items)[:{const}]", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def log_lines_ho2(rnd: random.Random, n: int, svc: str) -> list[str]:
    """Release-train log lines (own templates and timestamps)."""
    out = []
    for _ in range(n):
        ts = (f"2026-12-{rnd.randint(1, 4):02d} {rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:"
              f"{rnd.randint(0, 59):02d}.{rnd.randint(0, 999):03d}")
        lvl = rnd.choice(["info", "info", "info", "trace", "warning"])
        msg = rnd.choice([
            f"{svc} instance i-{''.join(rnd.choice('0123456789abcdef') for _ in range(10))} "
            f"healthcheck passed after {rnd.randint(1, 30)} tries",
            f"wave {rnd.randint(1, 12)} of 12 holding at {rnd.randint(1, 99)} percent",
            f"{rnd.choice(VERBS_HO2)} worker backlog={rnd.randint(0, 2000)} lag={rnd.randint(0, 90)}s",
            f"secrets bundle refreshed sha={''.join(rnd.choice('0123456789abcdef') for _ in range(16))}",
            f"request {rnd.choice(['PUT', 'DELETE', 'PATCH'])} /api/{rnd.choice(NOUNS_HO2)} "
            f"status={rnd.choice([200, 204, 409, 429, 502])} took={rnd.uniform(0.01, 3):.3f}s",
            f"heap compaction freed {rnd.randint(4, 600)} MB in {rnd.randint(2, 400)} ms",
        ])
        out.append(f"[{ts}] {lvl:<7} {msg}")
    return out


def _build(index: int, seed: int) -> tuple[dict, dict]:
    """One ho2 history and the planted values the independence check looks at."""
    rnd = random.Random(seed)
    th = THEMES_HO2[index]
    P, mods = th["project"], list(th["modules"])
    rnd.shuffle(mods)
    mod_a = mods[0]
    b = Builder(rnd)

    def cls_of(mod: str) -> str:
        return "".join(p.title() for p in mod.split("_")) + "Case"

    def ut_cmd(mod: str) -> str:
        return f"python -m unittest tests.test_{mod}"

    # ---- planted values (ho2 formats; answer types as in build_history) ----
    err_a = err_code(rnd, P)
    err_distractors = [err_code(rnd, P) for _ in range(3)]
    ticket = rnd.randint(100000, 999999)
    slug = th["topic"].split()[0]
    branch = f"bugfix/{P}/{slug}-{ticket}"
    branch_docs = f"writeup/{ticket}-{P}"
    port_old, port_new, port_admin = rnd.randint(4100, 4199), rnd.randint(4700, 4799), rnd.randint(4400, 4499)
    clients = list(th["clients"])
    rnd.shuffle(clients)
    target_client = clients[0]
    timeouts = {c: (f"{rnd.randrange(1100, 5000, 50)}ms", f"{rnd.randrange(10000, 40000, 500)}ms")
                for c in clients}
    used_r = {v[0] for c, v in timeouts.items() if c != target_client}
    used_w = {v[1] for c, v in timeouts.items() if c != target_client}
    r, w = timeouts[target_client]
    while r in used_r:
        r = f"{rnd.randrange(5000, 7000, 50)}ms"
    while w in used_w:
        w = f"{rnd.randrange(41000, 59000, 500)}ms"
    timeouts[target_client] = (r, w)
    fixture_timeouts = {c: (f"{rnd.randrange(50, 600, 25)}ms", f"{rnd.randrange(90000, 120000, 1000)}ms")
                        for c in clients}
    req_id, req_other = f"TKT-{rnd.randint(10000, 99999)}", f"TKT-{rnd.randint(10000, 99999)}"
    const_val = rnd.choice(th["const_values"])
    const_cur = const_val * 2 // 3
    host = f"rdb-preprod-{rnd.randint(3, 29)}.mesh.lan"
    db_port = rnd.choice([3307, 4921, 5333, 6077])
    db_name = th["db"]
    old_helper, new_helper = th["helper"]
    week = rnd.randint(47, 52)
    tag_new = f"train-26w{week}.{rnd.randint(2, 9)}"
    tag_old = f"train-26w{week - rnd.randint(1, 3)}.{rnd.randint(2, 9)}"
    integ = names_ho2(rnd, 404)
    k6 = rnd.randint(70, 310)
    q6_before, q6_after = integ[k6], integ[k6 + 1]
    v = dict(P=P, topic=th["topic"], ticket=ticket, branch=branch, mod_a=mod_a, svc=th["svc"],
             req_id=req_id, req_other=req_other, const=th["const"], const_val=const_val,
             port_old=port_old, port_new=port_new, port_admin=port_admin, db_port=db_port,
             db_name=db_name, kind=th["kind"], old_helper=old_helper, new_helper=new_helper,
             branch_docs=branch_docs, column=th["column"], target_client=target_client,
             q6_before=q6_before)
    ph = PH

    def say(key: str, **kw) -> None:
        b.say(ph[key].format(**v, **kw))

    def user(key: str, **kw) -> None:
        b.user(ph[key].format(**v, **kw))

    # ---- import turns ----
    user("u_open")
    lines = code_file_ho2(rnd, mod_a, rnd.randint(120, 170))
    b.tool("read", {"path": f"src/{P}/{mod_a}.py"}, read_result(f"src/{P}/{mod_a}.py", lines))
    say("a_open", nfun=sum(1 for l in lines if l.startswith("def ")))

    user("u_tests")
    cases = names_ho2(rnd, 36)
    fail = cases[rnd.randrange(len(cases))]
    tb = [f'  File "tests/test_{mod_a}.py", line {rnd.randint(30, 280)}, in {fail}',
          f"    self.migrator.alter('{th['column']}')",
          f"{P}.faults.MigrationError: [{err_a}] column '{th['column']}' could not be altered"]
    b.tool("shell", {"command": ut_cmd(mod_a)},
           unittest_output(rnd, f"tests.test_{mod_a}", cls_of(mod_a), cases, {fail: tb}))
    say("a_tests", fail=fail)

    user("u_spec")
    say("a_spec")
    user("u_port")
    say("a_port")

    cfg = ["# Peer clients used in production (read by conf.peers.load)", ""]
    for c in clients:
        cfg += [f"[peer.{c}]", f'url = "https://{c.replace("_", "-")}.{P}.mesh.lan"',
                f'read_timeout = "{timeouts[c][0]}"', f'write_timeout = "{timeouts[c][1]}"',
                f"attempts = {rnd.randint(2, 7)}", f"max_conns = {rnd.randint(3, 48)}", ""]
    user("u_clients")
    b.tool("read", {"path": "conf/peers.toml"}, read_result("conf/peers.toml", cfg))
    say("a_clients")

    for m in mods[1:3]:
        user("u_module", m=m)
        lines = code_file_ho2(rnd, m, rnd.randint(110, 160))
        b.tool("read", {"path": f"src/{P}/{m}.py"}, read_result(f"src/{P}/{m}.py", lines))
        say("a_module", m=m, noun=rnd.choice(NOUNS_HO2))

    env = [f"PREPROD_CACHE_HOST=kv-preprod-{rnd.randint(3, 29)}.mesh.lan",
           f"PREPROD_DB_HOST={host}", f"PREPROD_BUS_HOST=bus-preprod-{rnd.randint(3, 29)}.mesh.lan",
           f"PREPROD_DB_LOGIN={P}_rw", "PREPROD_DB_SSL=prefer",
           f"PREPROD_SWITCHES={rnd.choice(NOUNS_HO2)}+{rnd.choice(NOUNS_HO2)}"]
    user("u_env")
    b.tool("read", {"path": "conf/preprod.env"}, read_result("conf/preprod.env", env))
    say("a_env")

    user("u_pooler")
    say("a_pooler")

    m = mods[3]
    user("u_tests2", m=m)
    cases = names_ho2(rnd, 28)
    f2 = cases[rnd.randrange(len(cases))]
    b.tool("shell", {"command": ut_cmd(m)},
           unittest_output(rnd, f"tests.test_{m}", cls_of(m), cases, {f2: [
               f'  File "tests/test_{m}.py", line {rnd.randint(20, 200)}, in {f2}',
               "    self.assertTrue(self.client.call())",
               f"{P}.faults.RetryError: [{err_distractors[0]}] gave up after the last attempt"]}))
    say("a_tests2", f2=f2)

    user("u_helper")
    b.tool("edit", {"path": f"src/{P}/{mod_a}.py", "oldString": f"def {old_helper}(",
                    "newString": f"def {new_helper}("},
           f"Edited src/{P}/{mod_a}.py (1 replacement)")
    say("a_helper")

    user("u_newport")
    say("a_newport")

    user("u_db")
    b.tool("grep", {"pattern": "_pp", "path": "conf"},
           f"Found 1 matches\nconf\\databases.yaml:\n  Line {rnd.randint(3, 30)}:   preprod: {db_name}")
    say("a_db")

    user("u_integ")
    out = []
    areas = [(f"tests.integration.test_{x}", cls_of(x)) for x in mods]
    for i, n in enumerate(integ):
        dotted, cls = areas[i * len(areas) // len(integ)]
        out.append(f"{n} ({dotted}.{cls}.{n}) ... ok")
    out += ["", "-" * 70, f"Ran {len(integ)} tests in {rnd.uniform(70, 210):.3f}s", "", "OK"]
    b.tool("shell", {"command": "python -m unittest discover -s tests/integration -v"}, "\n".join(out))
    say("a_integ", n_integ=len(integ))

    user("u_docs")
    say("a_docs")

    fx = ["# Test data: tiny reads, huge writes", ""]
    for c in clients:
        fx += [f"[peer.{c}]", f'read_timeout = "{fixture_timeouts[c][0]}"',
               f'write_timeout = "{fixture_timeouts[c][1]}"', ""]
    user("u_fixture")
    b.tool("read", {"path": "tests/data/peers_test.toml"}, read_result("tests/data/peers_test.toml", fx))
    say("a_fixture")

    user("u_two", m=mods[5], m2=mods[6])
    for mm, e in ((mods[5], err_distractors[1]), (mods[6], err_distractors[2])):
        cases = names_ho2(rnd, 24)
        ff = cases[rnd.randrange(len(cases))]
        b.tool("shell", {"command": ut_cmd(mm)},
               unittest_output(rnd, f"tests.test_{mm}", cls_of(mm), cases, {ff: [
                   f'  File "tests/test_{mm}.py", line {rnd.randint(20, 200)}, in {ff}',
                   "    self.seed_fixture()",
                   f"{P}.faults.SchemaError: [{e}] fixture has a column the schema lacks"]}))
    say("a_two")

    for m in mods[1:] + mods[1:4]:
        b.user(rnd.choice(ph["u_filler"]).format(P=P, m=m))
        path = f"src/{P}/{m}.py"
        lines = code_file_ho2(rnd, m, rnd.randint(130, 200))
        b.tool("read", {"path": path}, read_result(path, lines))
        b.say(rnd.choice(ph["a_filler"]).format(m=m))

    import_messages = b.messages

    # ---- steps: the shared skeleton ----
    sid = f"ho2h{index + 1}"

    def q(qid, category, answer, parts=None, restart=False, evidence=None, **kw):
        return {"kind": "question", "id": f"{sid}{qid.lower()}", "qid": qid,
                "category": category, "text": ph[qid].format(**v, **kw), "answer": answer,
                "parts": parts or [answer], "evidence": evidence or parts or [answer],
                "restart_before": restart}

    def paste(pid, what, body):
        return {"kind": "paste", "id": f"{sid}{pid.lower()}",
                "text": ph["paste"].format(what=ph[what], body="\n".join(body))}

    deploy = log_lines_ho2(rnd, 140, th["svc"])
    deploy.insert(rnd.randint(40, 100),
                  f"[2026-12-0{rnd.randint(1, 4)} 23:{rnd.randint(10, 59)}:{rnd.randint(10, 59)}.000] info    "
                  f"train: cut {tag_new}, superseding {tag_old}; first wave scheduled")
    lint = []
    for _ in range(240):
        mm = rnd.choice(mods)
        lint.append(f"src/{P}/{mm}.py:{rnd.randint(1, 400)}:{rnd.randint(1, 80)}: "
                    f"{rnd.choice(['E203', 'E711', 'F811', 'W503', 'B007', 'E128'])} "
                    f"{rnd.choice(['whitespace before colon', 'comparison to None', 'redefinition of unused name', 'line break before binary operator', 'loop control variable not used', 'continuation line under-indented'])}")
    prof = ["   ncalls  tottime  percall  cumtime  percall filename:lineno(function)"]
    for _ in range(140):
        mm = rnd.choice(mods)
        prof.append(f"{rnd.randint(1, 90000):>9} {rnd.uniform(0, 9):8.3f} {rnd.uniform(0, 0.01):8.5f} "
                    f"{rnd.uniform(0, 20):8.3f} {rnd.uniform(0, 0.02):8.5f} {mm}.py:{rnd.randint(1, 400)}"
                    f"({rnd.choice(VERBS_HO2)}_{rnd.choice(ADJS_HO2)}_{rnd.choice(NOUNS_HO2)})")
    cm = th["const_mod"]
    mid_cmd = ut_cmd(cm)
    mid_case = names_ho2(rnd, 1)[0]
    message = f"{th['const']}={const_cur} does not satisfy ticket {req_id}"
    mid_out = unittest_output(rnd, f"tests.test_{cm}", cls_of(cm), [mid_case], {mid_case: [
        f'  File "tests/test_{cm}.py", line 15, in {mid_case}',
        f"    self.assertEqual({th['const']}, EXPECTED, NOTE)",
        f"AssertionError: {const_cur} != None : {message}"]}, kind="FAIL")

    steps = [
        q("Q1", "identifier", err_a),
        paste("P1", "paste_deploy", deploy),
        q("Q2", "identifier", branch),
        q("Q3", "superseded", str(port_new), evidence=[f"moves to port {port_new}"]),
        paste("P2", "paste_lint", lint),
        q("Q4", "irrelevant_matches", timeouts[target_client][0],
          evidence=[f'read_timeout = "{timeouts[target_client][0]}"']),
        q("Q5", "vague", timeouts[target_client][1],
          evidence=[f'write_timeout = "{timeouts[target_client][1]}"']),
        paste("P3", "paste_prof", prof),
        q("Q6", "oversized_read", q6_after),
        dict(q("Q7", "mid_task", str(const_val), mid_cmd=mid_cmd,
               evidence=[f"{req_id} says {th['const']} must equal {const_val}"]),
             mid_task={"command": mid_cmd, "output": mid_out}),
        q("Q8", "multi_fact", f"{host}:{db_port}/{db_name}", parts=[host, str(db_port), db_name],
          evidence=[f"PREPROD_DB_HOST={host}", f"pooler is on {db_port}", db_name]),
        q("Q9", "restart_multi_eviction", tag_new, restart=True),
        q("Q10", "vague", new_helper),
    ]
    import_messages.append({"role": "user", "content": steps[0]["text"]})
    const = th["const"]
    test_file = "\n".join([
        "import sys", "import unittest", "from pathlib import Path", "",
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))', "",
        f"from {P}.{cm} import {const}  # noqa: E402", "",
        "EXPECTED = None  # set from the ticket",
        f'NOTE = f"{const}={{{const}}} does not satisfy ticket {req_id}"', "", "",
        f"class {cls_of(cm)}(unittest.TestCase):",
        f"    def {mid_case}(self):",
        f"        self.assertEqual({const}, EXPECTED, NOTE)", ""])
    workspace = {
        f"tests/test_{cm}.py": test_file,
        f"src/{P}/{cm}.py": const_module_ho2(rnd, cm, const, const_cur),
    }
    h = {"id": f"ho2-h{index + 1}", "seed": seed, "project": P, "set": SET,
         "generator": GENERATOR, "import": import_messages, "steps": steps,
         "workspace": workspace,
         "shell": [{"match": f"unittest tests.test_{cm}", "output": mid_out}]}
    planted = {
        "theme": [P, th["svc"], th["db"], th["const"], *th["helper"], *th["modules"],
                  *th["clients"], th["column"]],
        "values": [err_a, *err_distractors, f"CASE-{ticket}", branch, branch_docs, req_id, req_other,
                   host, tag_new, tag_old, q6_before, q6_after, mid_case, fail, f2,
                   timeouts[target_client][0], timeouts[target_client][1]],
        "numeric": [str(port_old), str(port_new), str(port_admin), str(db_port), str(const_val),
                    str(const_cur)],
    }
    return h, planted


def build_heldout2(index: int, seed: int) -> dict:
    return _build(index, seed)[0]


# ---------------------------------------------------------------- independence check

def _grams(h: dict) -> set:
    """Four-word runs of the wording: user turns, assistant summaries, questions and paste
    wrappers (not tool output or paste bodies), as in the Phase 3 test, except that inline
    code spans are left out: they hold commands (Q7's ``python -m unittest tests.test_<m>``
    is the same command shape as Phase 3's) and identifiers, which are checked as strings."""
    texts = [m["content"] for m in h["import"] if m["role"] == "user"]
    texts += [m["content"] for m in h["import"] if m["role"] == "assistant" and m.get("content")]
    texts += [s["text"].split("```")[0] for s in h["steps"]]
    out = set()
    for t in texts:
        t = re.sub(r"`[^`]*`", " ", t)
        w = re.findall(r"[a-z']+", t.lower())
        out |= {tuple(w[k:k + 4]) for k in range(len(w) - 3)}
    return out


def _skeleton(h: dict) -> list:
    return [(s["kind"], s.get("qid"), s.get("category"), s.get("restart_before"),
             "mid_task" in s) for s in h["steps"]]


def check() -> list[str]:
    """Problems with the committed ho2 set; empty when it is independent and well formed."""
    problems = []
    earlier = {}
    for folder in ("dev", "heldout"):
        for f in sorted((ROOT / "eval" / "needles" / folder).glob("*.json")):
            earlier[f.name] = f.read_text(encoding="utf-8")
    corpus = "\n".join(earlier.values()).casefold()
    earlier_answers = set()
    for text in earlier.values():
        for s in json.loads(text)["steps"]:
            if s["kind"] == "question":
                earlier_answers |= {s["answer"].casefold(), *(p.casefold() for p in s["parts"])}

    def word_in_corpus(tok: str) -> bool:
        return re.search(rf"(?<![a-z0-9_]){re.escape(tok.casefold())}(?![a-z0-9_])", corpus) is not None

    # 1. Seeds, themes and word banks.
    seeds = set(range(SEED_BASE, SEED_BASE + len(THEMES_HO2)))
    if seeds & (set(range(3100, 3106)) | set(range(5200, 5212))):
        problems.append("seed overlap")

    def theme_tokens(themes):
        out = set()
        for t in themes:
            out |= {t["project"], t["svc"], t["db"], t["const"], *t["helper"], *t["modules"],
                    *t["clients"], t.get("column", "")}
        return out - {""}

    ours = theme_tokens(THEMES_HO2)
    if ours & (theme_tokens(ng.THEMES) | theme_tokens(ng.THEMES_HO)):
        problems.append(f"theme tokens shared: {sorted(ours & (theme_tokens(ng.THEMES) | theme_tokens(ng.THEMES_HO)))}")
    for bank, others in ((VERBS_HO2, ng.VERBS + ng.VERBS_HO), (NOUNS_HO2, ng.NOUNS + ng.NOUNS_HO),
                         (ADJS_HO2, ng.ADJS + ng.ADJS_HO)):
        if set(bank) & set(others):
            problems.append(f"word bank shared: {sorted(set(bank) & set(others))}")
    for tok in sorted(ours):
        if word_in_corpus(tok):
            problems.append(f"theme identifier {tok!r} occurs in an earlier needle file")
    for t in THEMES_HO2:
        for cv in t["const_values"]:
            if str(cv) in earlier_answers:
                problems.append(f"const value {cv} is an earlier answer")

    earlier_grams = set()
    for text in earlier.values():
        earlier_grams |= _grams(json.loads(text))
    dev_skeleton = _skeleton(json.loads(earlier["dev-h1.json"]))

    for i in range(len(THEMES_HO2)):
        h, planted = _build(i, SEED_BASE + i)
        path = OUT / f"{h['id']}.json"
        committed = path.read_bytes() if path.exists() else b""
        if (json.dumps(h, indent=1, ensure_ascii=False) + "\n").encode("utf-8") != committed:
            problems.append(f"{h['id']}: committed file differs from the generator")
        if _skeleton(h) != dev_skeleton:
            problems.append(f"{h['id']}: step skeleton differs")
        qs = [s for s in h["steps"] if s["kind"] == "question"]
        if len(qs) != 10:
            problems.append(f"{h['id']}: {len(qs)} questions")
        # 2. Answers, parts, evidence and planted identifiers with a letter: not anywhere.
        strings = set(planted["values"])
        for s in qs:
            strings |= {s["answer"], *s["parts"], *s["evidence"]}
        for s in sorted(strings):
            if any(c.isalpha() for c in s) and s.casefold() in corpus:
                problems.append(f"{h['id']}: a planted string occurs in an earlier needle file")
        # 3. Numeric answers and values: never an earlier answer (their evidence, which
        #    carries words, is checked as a string above).
        for s in planted["numeric"] + [x for q in qs for x in [q["answer"], *q["parts"]]
                                       if not any(c.isalpha() for c in x)]:
            if s.casefold() in earlier_answers:
                problems.append(f"{h['id']}: numeric value {s} is an earlier answer")
        # 4. Wording.
        shared = _grams(h) & earlier_grams
        if shared:
            problems.append(f"{h['id']}: {len(shared)} four-word runs shared, e.g. {sorted(shared)[:3]}")
        # 5. Evidence is in the history.
        text = "\n".join((m.get("content") or "") + json.dumps(m.get("tool_calls") or "")
                         for m in h["import"]) + "\n".join(s["text"] for s in h["steps"])
        for s in qs:
            for e in s["evidence"]:
                if e not in text:
                    problems.append(f"{h['id']} {s['qid']}: evidence missing from the history")
        if h["import"][-1] != {"role": "user", "content": qs[0]["text"]}:
            problems.append(f"{h['id']}: import does not end with Q1")
    # 6. The ho2 coding tasks' identifiers: not in an earlier task module or needle file.
    task_srcs = [p for p in (ROOT / "eval" / "tasks").glob("*.py") if p.stem.startswith(("dev_", "ho_"))]
    task_corpus = corpus + "\n".join(p.read_text(encoding="utf-8") for p in task_srcs).casefold()
    for tok in TASK_IDENTIFIERS:
        if re.search(rf"(?<![a-z0-9_]){re.escape(tok.casefold())}(?![a-z0-9_])", task_corpus):
            problems.append(f"task identifier {tok!r} occurs in an earlier task or needle file")
    return problems


# Package, module, function, error and file names of eval/tasks/ho2_t1.py .. ho2_t5.py.
TASK_IDENTIFIERS = [
    "gridloc", "LocatorError", "to_locator", "from_locator", "compass_point", "maidenhead",
    "GR-301", "GR-302", "GR-303", "chordshift", "ChordError", "transpose_chord",
    "transpose_sheet", "bpm_label", "chord_sheets", "river_road", "rosterlap", "roster",
    "ShiftError", "parse_rows", "find_overlaps", "initials", "roster_format", "shift_id",
    "recipescale", "UnitError", "scale_line", "scale_recipe", "fahrenheit", "kitchen_units",
    "ignorekit", "load_rules", "is_ignored", "ext_of", "ignore_patterns",
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path)
    p.add_argument("--check", action="store_true",
                   help="verify the committed files against the generator and the earlier sets")
    a = p.parse_args()
    if a.check:
        problems = check()
        for x in problems:
            print("FAIL", x)
        print(f"ho2 independence check: {'ok' if not problems else f'{len(problems)} problems'}")
        return 1 if problems else 0
    out = a.out or OUT
    out.mkdir(parents=True, exist_ok=True)
    for i in range(len(THEMES_HO2)):
        h = build_heldout2(i, SEED_BASE + i)
        (out / f"{h['id']}.json").write_text(json.dumps(h, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8", newline="\n")
        chars = sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or ""))
                    for m in h["import"])
        print(f"{h['id']}: {len(h['import'])} import messages, ~{chars} chars, {len(h['steps'])} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
