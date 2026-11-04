"""Seeded generator for the third held-out needle set ``ho3`` (A1 "Evaluation").

``ho2`` was retired into development data (D69), so a fresh held-out set is needed. This
one is written by an author who has not seen the design it will judge. It keeps the step
skeleton, categories and answer types of ``build_history`` (so A1's coverage holds) and
replaces everything else: twelve new themes, new word banks, new file names, value
formats, tool-output bodies and a new phrasing bank for every user turn, assistant
summary, question and paste wrapper.

Steps after the import (the shared skeleton):

    Q1, P1 (paste carrying the Q9 fact), Q2, Q3, P2, Q4, Q5, P3, Q6, Q7, Q8,
    [proxy restart], Q9, Q10

Categories (A1): identifier (Q1, Q2), superseded (Q3), irrelevant matches (Q4),
vague reference (Q5, Q10), oversized transcript read (Q6), mid-task need (Q7),
several distant facts (Q8), restart plus multiple eviction events (Q9).

Only the OpenCode 2.1.4 tool-result shapes (``read_result``), the ``python -m unittest``
output shape and the message builder are imported from ``needle_gen``; they are formats,
not content. The independence check also reads ``needle_gen_ho2`` (its themes, banks and
task identifiers), only to compare against them.

Usage:
    python eval/needle_gen_ho3.py [--out DIR]   # writes ho3-h1..h12, seeds 7400-7411
    python eval/needle_gen_ho3.py --check       # independence from dev, heldout and heldout2
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from needle_gen import Builder, read_result, unittest_output  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "needles" / "heldout3"
SEED_BASE = 7400
SET = "heldout3"
GENERATOR = "eval/needle_gen_ho3.py v1"
EARLIER_SEEDS = set(range(3100, 3106)) | set(range(5200, 5212)) | set(range(6400, 6412))
EARLIER_FOLDERS = ("dev", "heldout", "heldout2")

THEMES_HO3 = [
    dict(project="vinterra", topic="brix readings lost when must moves between tanks",
         modules=["brix_log", "tank_moves", "press_cycles", "cellar_map", "barrel_lots",
                  "yeast_pitch", "bottling_runs", "harvest_bins"], svc="vinterra-cellar",
         db="vinterra_cellar_uat",
         clients=["refractometer", "excise_portal", "cooperage", "label_house", "grower_ledger",
                  "lab_titration"],
         const="BRIX_CARRYOVER_SECONDS", const_mod="tank_moves", const_values=[148, 184, 232, 256],
         helper=("_copy_readings_by_tank", "carry_readings_by_lot"), kind="carryover",
         column="brix_reading"),
    dict(project="skyhook", topic="lift plans approved above the wind limit",
         modules=["lift_plans", "crane_fleet", "anemometers", "rigging_gear", "site_permits",
                  "load_charts", "operator_certs", "shift_board"], svc="skyhook-lifts",
         db="skyhook_sites_uat",
         clients=["windfeed", "permit_office", "rigging_vendor", "cert_registry", "site_cameras",
                  "crane_telemetry"],
         const="GUST_LIMIT_KMH", const_mod="anemometers", const_values=[38, 46, 53, 61],
         helper=("_mean_wind_check", "gust_peak_check"), kind="wind check", column="gust_kmh"),
    dict(project="darkdome", topic="exposures scheduled after astronomical dawn",
         modules=["exposure_queue", "twilight", "mount_control", "filter_wheel", "dome_shutter",
                  "seeing_monitor", "target_catalog", "night_reports"], svc="darkdome-sched",
         db="darkdome_nights_uat",
         clients=["ephemeris", "allsky_cam", "weather_mast", "archive_fits", "proposal_desk",
                  "pager_astro"],
         const="TWILIGHT_MARGIN_MINUTES", const_mod="twilight", const_values=[22, 27, 33, 44],
         helper=("_civil_twilight_cutoff", "astronomical_dawn_cutoff"), kind="cutoff",
         column="dawn_utc"),
    dict(project="snowcrest", topic="season passes rejected at the gates after the midnight rollover",
         modules=["pass_scans", "turnstiles", "season_passes", "day_tickets", "rollover",
                  "lift_status", "ski_school", "rental_shop"], svc="snowcrest-gates",
         db="snowcrest_passes_uat",
         clients=["rfid_readers", "resort_pos", "pass_partner", "avalanche_desk", "guest_app",
                  "snowmaking"],
         const="ROLLOVER_GRACE_MINUTES", const_mod="rollover", const_values=[26, 31, 37, 42],
         helper=("_day_from_utc", "day_from_resort_clock"), kind="rollover",
         column="valid_through"),
    dict(project="reeferyard", topic="reefer containers flagged warm after a power transfer",
         modules=["reefer_alarms", "plug_points", "container_moves", "set_points", "yard_blocks",
                  "vessel_calls", "gate_transactions", "temp_traces"], svc="reefer-monitor",
         db="reeferyard_yard_uat",
         clients=["shipping_lines", "customs_hold", "straddle_fleet", "plug_controller",
                  "vessel_planner", "cold_chain"],
         const="UNPLUG_TOLERANCE_SECONDS", const_mod="reefer_alarms",
         const_values=[105, 135, 165, 215],
         helper=("_alarm_on_any_gap", "alarm_after_unplug_window"), kind="alarm",
         column="setpoint_c"),
    dict(project="curtaincall", topic="seats sold twice when a row is split between price zones",
         modules=["seat_maps", "price_zones", "holds_box", "checkout_flow", "season_subs",
                  "comps", "ushers", "house_reports"], svc="curtain-box", db="curtaincall_seats_uat",
         clients=["payment_gw", "promoter_feed", "access_scan", "donor_crm", "venue_mgmt",
                  "resale_market"],
         const="SEAT_HOLD_SECONDS", const_mod="holds_box", const_values=[270, 330, 390, 510],
         helper=("_lock_row_only", "lock_seat_per_zone"), kind="seat locking",
         column="seat_label"),
    dict(project="kettlehop", topic="hop additions logged at the wrong boil minute",
         modules=["boil_timer", "hop_schedule", "mash_steps", "fermenters", "gravity_log",
                  "kegging", "recipe_book", "cip_cycles"], svc="kettlehop-brew",
         db="kettlehop_batches_uat",
         clients=["hop_merchant", "plc_brewhouse", "excise_brew", "taproom_pos", "lab_micro",
                  "keg_tracker"],
         const="BOIL_CLOCK_SKEW_MS", const_mod="boil_timer", const_values=[650, 950, 1150, 1450],
         helper=("_minute_from_wallclock", "minute_from_boil_start"), kind="boil timing",
         column="boil_minute"),
    dict(project="aquameter", topic="leak alerts suppressed for seasonal homes",
         modules=["meter_reads", "leak_rules", "vacancy", "billing_cycles", "valves_remote",
                  "district_zones", "usage_bands", "notices_mail"], svc="aquameter-ami",
         db="aquameter_reads_uat",
         clients=["ami_headend", "gis_pipes", "customer_portal", "print_vendor", "field_crews",
                  "drought_board"],
         const="LEAK_FLOW_LITRES_PER_HOUR", const_mod="leak_rules", const_values=[32, 41, 48, 57],
         helper=("_skip_if_vacant", "flag_flow_when_vacant"), kind="suppression",
         column="flow_lph"),
    dict(project="contrail", topic="crew rest periods computed wrongly across the date line",
         modules=["crew_rest", "pairings", "duty_limits", "layovers", "rosters_air",
                  "fatigue_scores", "deadheads", "crew_hotels"], svc="contrail-crew",
         db="contrail_duty_uat",
         clients=["flight_ops", "union_audit", "hotel_desk", "aircraft_swaps", "sim_center",
                  "regulator_air"],
         const="MIN_REST_MINUTES", const_mod="crew_rest", const_values=[615, 645, 705, 735],
         helper=("_rest_by_local_dates", "rest_by_utc_instants"), kind="rest window",
         column="block_off_utc"),
    dict(project="trawlnet", topic="catch quotas exceeded after landing corrections",
         modules=["landings", "quota_pools", "vessel_licences", "species_codes", "port_auctions",
                  "observer_trips", "corrections", "season_close"], svc="trawlnet-quota",
         db="trawlnet_catch_uat",
         clients=["fisheries_agency", "auction_house", "vms_tracker", "processor_edi",
                  "observer_program", "coastguard"],
         const="QUOTA_OVERRUN_KG", const_mod="quota_pools", const_values=[140, 260, 380, 460],
         helper=("_apply_correction_append", "apply_correction_replace"), kind="correction",
         column="landed_kg"),
    dict(project="levelgate", topic="garage occupancy drifting after barrier resets",
         modules=["occupancy", "barriers", "plate_reads", "permits_monthly", "pay_stations",
                  "level_signs", "valet", "incidents_park"], svc="levelgate-ctl",
         db="levelgate_garage_uat",
         clients=["anpr_cameras", "city_permits", "card_acquirer", "sign_controller", "valet_app",
                  "security_desk"],
         const="BARRIER_RESET_DEBOUNCE_S", const_mod="barriers", const_values=[36, 43, 50, 58],
         helper=("_count_from_loop_pulses", "count_from_paired_events"), kind="occupancy",
         column="spaces_free"),
    dict(project="molarbase", topic="radiographs attached to the wrong tooth chart",
         modules=["tooth_charts", "radiographs", "perio_exams", "treatment_plans",
                  "recalls_dental", "sterilizer_logs", "insurer_claims", "chairside"],
         svc="molarbase-chart", db="molarbase_charts_uat",
         clients=["xray_sensor", "claims_clearing", "lab_crowns", "patient_texts",
                  "imaging_viewer", "practice_mgmt"],
         const="IMAGE_MATCH_WINDOW_S", const_mod="radiographs", const_values=[70, 115, 125, 145],
         helper=("_tooth_by_universal", "tooth_by_fdi_notation"), kind="tooth notation",
         column="tooth_fdi"),
]

VERBS_HO3 = ["hoard", "braid", "carve", "drift", "forge", "glean", "dredge", "ladle", "moor",
             "nudge", "plough", "rake", "scour", "stitch", "thresh", "tow", "whittle", "yoke"]
NOUNS_HO3 = ["acorn", "barrow", "cairn", "dinghy", "easel", "flagon", "gable", "hamper", "jetty",
             "lantern", "mallet", "nozzle", "pylon", "rudder", "satchel", "thimble", "valve",
             "wicket"]
ADJS_HO3 = ["amber", "blunt", "chalky", "dusky", "feral", "gaunt", "hushed", "jagged", "knotty",
            "lofty", "murky", "oblong", "plush", "ragged", "silty", "taut", "wiry", "zesty"]

# The ho3 phrasing bank. No four-word run is shared with the dev, heldout or heldout2
# wording (``check``).
PH = {
    "u_open": "We're on {P} this week, chasing {topic}. Book the hours to job JOB-{ticket}; "
              "the actual patch belongs on `{branch}`. Could you start by opening "
              "src/{P}/{mod_a}.py?",
    "a_open": "Read through `{mod_a}.py`: one pipeline class and {nfun} methods hanging off it. "
              "Nothing jumps out at me yet, so running its tests seems like a sensible next move.",
    "u_tests": "Go ahead and launch the {mod_a} tests.",
    "a_tests": "Exactly one case, `{fail}`, crashed: the schema migrator raised MigrationError on "
               "that column. The remaining cases are fine.",
    "u_spec": "Per decision record {req_id}, {const} needs to be {const_val} exactly, since the "
              "downstream consumer won't accept anything different. Unrelated, but {req_other} "
              "locks SPILL_BUFFER_KB to 9000. Hang on to both; we will need them.",
    "a_spec": "Got it, in my notes: {req_id} puts {const} at {const_val}, and {req_other} "
              "locks SPILL_BUFFER_KB to 9000.",
    "u_port": "On a laptop, {svc} should listen on {port_old}. Its metrics exporter sits on "
              "{port_admin} and stays put.",
    "a_port": "Understood. {svc} listens on {port_old} on a laptop; the metrics exporter "
              "sits on {port_admin}.",
    "u_clients": "What does the backends file say about our downstream services?",
    "a_clients": "etc/backends.ini lists six backends. For each there is an endpoint, a "
                 "connect timeout, a reply timeout, a retry budget and a pool limit.",
    "u_module": "Over to src/{P}/{m}.py now. Does that file touch {column} at all?",
    "a_module": "It doesn't. `{m}.py` only batches up {noun} objects; {column} is absent.",
    "u_env": "Which hostnames does UAT point at?",
    "a_env": "etc/uat.vars names three UAT hostnames (queue, cache, database) and the "
             "database role as well.",
    "u_pooler": "FYI the UAT pgbouncer listens on {db_port}; it is not on 5432.",
    "a_pooler": "Thanks, I'll use {db_port} for the UAT pgbouncer.",
    "u_tests2": "Kick off {m}'s tests too, would you?",
    "a_tests2": "There, `{f2}` exhausted its retries and raised RetryError. That has no "
                "bearing on our column problem.",
    "u_helper": "Since we're already inside {mod_a}.py, swap out its stale {kind} helper.",
    "a_helper": "Swapped. `{old_helper}` is renamed to `{new_helper}`, and the old name "
                "survives as an alias so nothing downstream breaks.",
    "u_newport": "Change of mind about {svc}: put it on {port_new} instead. {port_old} clashes "
                 "with the profiling agent.",
    "a_newport": "Done, {svc} listens on {port_new} now.",
    "u_db": "Which schema is the migration rehearsal pointed at?",
    "a_db": "In UAT it rehearses against `{db_name}`.",
    "u_integ": "Now the integration suite, every test, verbose output please.",
    "a_integ": "All {n_integ} integration tests came back ok.",
    "u_docs": "Whenever the documentation gets written, it lands on `{branch_docs}`.",
    "a_docs": "Understood; documentation lands on `{branch_docs}`.",
    "u_fixture": "And what do the fixture backends use for timeouts?",
    "a_fixture": "Every fixture backend pairs a very short connect timeout with a very long "
                 "reply timeout.",
    "u_two": "Launch the {m} suite plus the {m2} suite.",
    "a_two": "Each one shows a lone SchemaError; my guess is stale fixture columns.",
    "u_filler": ["Take another pass over src/{P}/{m}.py: what happens on errors there?",
                 "Could src/{P}/{m}.py be hiding exceptions? Check, please.",
                 "In src/{P}/{m}.py, which log lines actually earn their keep?",
                 "Scan src/{P}/{m}.py one more time for catch-all except blocks."],
    "a_filler": ["On errors, `{m}.py` logs at debug and lets the exception propagate.",
                 "`{m}.py` raises nothing itself; it just returns indexes. Looks fine.",
                 "The log lines in `{m}.py` can stay as they are.",
                 "Each except block in `{m}.py` catches a specific exception class."],
    "paste": "Dropping {what} here for safekeeping; we'll revisit it later. Please hold off "
             "on analysis and tools for the moment. A one-word 'noted' will do.\n\n```\n{body}\n```",
    "paste_deploy": "the canary controller log from last night",
    "paste_lint": "this morning's mypy report",
    "paste_prof": "a tracemalloc snapshot from the memory-hungry export",
    "Q1": "When the {mod_a} tests were first launched, the MigrationError carried a code "
          "inside square brackets. What was it? Respond with the code by itself.",
    "Q2": "On which branch should the actual patch go? Respond with that branch by itself.",
    "Q3": "Which port does {svc} listen on as of now? Respond with the port number by itself.",
    "Q4": "According to the real backends file, what connect timeout does the "
          "{target_client} backend have? Respond with the timeout by itself.",
    "Q5": "And its reply timeout? Respond with the timeout by itself.",
    "Q6": "In the verbose integration output, which test immediately followed {q6_before}? "
          "Respond with the method name by itself.",
    "Q7": "Execute `{mid_cmd}`, but don't modify any code. Going by the decision record from "
          "early on, which value should the failing constant have? Respond with the value by "
          "itself.",
    "Q8": "Put together the UAT database host, the pgbouncer port and the schema name we found, "
          "as one string shaped like host:port/database. Respond with the string by itself.",
    "Q9": "In the canary controller log I dropped in, which tag got promoted? Respond with the "
          "tag by itself.",
    "Q10": "What is the stale {kind} helper you swapped out called these days? Respond with "
           "its new name by itself.",
}

CODE_LETTERS = "ACEHKLMNPRTUWXY"


def names_ho3(rnd: random.Random, k: int, prefix: str = "test_") -> list[str]:
    seen, out = set(), []
    while len(out) < k:
        n = f"{prefix}{rnd.choice(VERBS_HO3)}_{rnd.choice(NOUNS_HO3)}_when_{rnd.choice(ADJS_HO3)}"
        if n in seen or any(n in s or s in n for s in seen):
            continue
        seen.add(n)
        out.append(n)
    return out


def err_code(rnd: random.Random, P: str) -> str:
    """``VINT-417MT``: a value format used by none of the earlier sets."""
    return (f"{P[:4].upper()}-{rnd.randint(100, 999)}{rnd.choice(CODE_LETTERS)}"
            f"{rnd.choice(CODE_LETTERS)}")


def code_file_ho3(rnd: random.Random, module: str, lines: int) -> list[str]:
    """Plausible Python source lines in the ho3 word banks: one class with methods."""
    cls = "".join(p.title() for p in module.split("_"))
    out = [f"# {module.replace('_', ' ')}: pipeline steps", "", "import logging",
           "from collections import deque", "", "log = logging.getLogger(__name__)", "", "",
           f"class {cls}Pipeline:", f'    """Steps of the {module.replace("_", " ")} pipeline."""', "",
           "    def __init__(self, limit=256):", "        self.limit = limit",
           "        self.cursor = 0", "        self.pending = deque()", ""]
    while len(out) < lines:
        v, n, a = rnd.choice(VERBS_HO3), rnd.choice(NOUNS_HO3), rnd.choice(ADJS_HO3)
        out.append(f"    def {v}_{n}_{a}(self, {n}s):")
        for _ in range(rnd.randint(2, 6)):
            out.append(rnd.choice([
                f"        kept = [x for x in {n}s if x.get('{a}_{rnd.randint(10, 99)}')]",
                f"        self.cursor = (self.cursor + {rnd.randint(2, 77)}) % self.limit",
                f"        log.debug('%s {v} {n}', self.cursor)",
                f"        self.pending.extend({n}s[-{rnd.randint(2, 30)}:])",
                f"        {n}s = list({n}s)[::{rnd.choice([1, 2, 3])}]",
                f"        # {v} the {a} {n} before the {rnd.choice(NOUNS_HO3)} goes out",
            ]))
        out.append("        return self.cursor")
        out.append("")
    return out[:lines]


def const_module_ho3(rnd: random.Random, module: str, const: str, value: int) -> str:
    """An importable module defining ``const`` (the mid-task check imports it)."""
    lines = [f"# {module.replace('_', ' ')}: settings", "", f"{const} = {value}", ""]
    for _ in range(4):
        v, n = rnd.choice(VERBS_HO3), rnd.choice(NOUNS_HO3)
        lines += ["", f"def {v}_{n}s_capped(seq):",
                  f"    # no more than {const} {n}s per {v} round",
                  f"    return list(seq)[:{const}]", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def hexs(rnd: random.Random, n: int) -> str:
    return "".join(rnd.choice("0123456789abcdef") for _ in range(n))


def canary_lines(rnd: random.Random, n: int, svc: str) -> list[str]:
    """Canary controller log lines (logfmt; own templates and timestamps)."""
    out = []
    for _ in range(n):
        ts = (f"2027-01-{rnd.randint(18, 21)}T{rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:"
              f"{rnd.randint(0, 59):02d}+0000")
        lvl = rnd.choice(["info", "info", "info", "debug", "warn"])
        msg = rnd.choice([
            f'msg="replica {svc}-{hexs(rnd, 5)} ready" probes={rnd.randint(1, 12)}',
            f'msg="canary weight adjusted" weight={rnd.randint(1, 50)} step={rnd.randint(1, 8)}/8',
            f'msg="error budget check" burn_rate={rnd.uniform(0, 4):.2f} window={rnd.choice(["5m", "1h", "6h"])}',
            f'msg="config map synced" rev={hexs(rnd, 8)}',
            f'msg="upstream latency" p99_ms={rnd.randint(20, 1900)} route=/{rnd.choice(NOUNS_HO3)}s',
            f'msg="queue drained" {rnd.choice(VERBS_HO3)}_items={rnd.randint(0, 900)}',
        ])
        out.append(f"ts={ts} level={lvl} {msg}")
    return out


def _build(index: int, seed: int) -> tuple[dict, dict]:
    """One ho3 history and the planted values the independence check looks at."""
    rnd = random.Random(seed)
    th = THEMES_HO3[index]
    P, mods = th["project"], list(th["modules"])
    rnd.shuffle(mods)
    mod_a = mods[0]
    b = Builder(rnd)

    def cls_of(mod: str) -> str:
        return "".join(p.title() for p in mod.split("_")) + "Suite"

    def ut_cmd(mod: str) -> str:
        return f"python -m unittest tests.test_{mod}"

    # ---- planted values (ho3 formats; answer types as in build_history) ----
    err_a = err_code(rnd, P)
    err_distractors = [err_code(rnd, P) for _ in range(3)]
    ticket = rnd.randint(10000, 99999)
    slug = "-".join(th["topic"].split()[:2])
    branch = f"topic/{P}-{ticket}-{slug}"
    branch_docs = f"docs-{P}/{ticket}"
    port_old, port_new, port_admin = (rnd.randint(5610, 5689), rnd.randint(6210, 6289),
                                      rnd.randint(5910, 5989))
    clients = list(th["clients"])
    rnd.shuffle(clients)
    target_client = clients[0]

    def conn_t() -> str:
        return f"PT{rnd.randint(1, 4)}.{rnd.choice([d for d in range(11, 99) if d % 5]):02d}S"

    def reply_t() -> str:
        return f"PT{rnd.randint(1, 2)}M{rnd.randrange(5, 60, 10)}S"

    timeouts = {c: (conn_t(), reply_t()) for c in clients}
    used_c = {v[0] for c, v in timeouts.items() if c != target_client}
    used_r = {v[1] for c, v in timeouts.items() if c != target_client}
    cn, rp = timeouts[target_client]
    while cn in used_c:
        cn = conn_t()
    while rp in used_r:
        rp = reply_t()
    timeouts[target_client] = (cn, rp)
    fixture_timeouts = {c: (f"PT0.{rnd.randint(11, 49)}S", f"PT{rnd.randint(7, 9)}M{rnd.randrange(5, 60, 10)}S")
                        for c in clients}
    req_id, req_other = f"DR-{rnd.randint(1000, 9999)}", f"DR-{rnd.randint(1000, 9999)}"
    while req_other == req_id:
        req_other = f"DR-{rnd.randint(1000, 9999)}"
    const_val = rnd.choice(th["const_values"])
    const_cur = const_val * 3 // 4
    host = f"pgw-uat-{rnd.randint(30, 79)}.corp.internal"
    db_port = rnd.choice([6435, 7643, 8433, 9532])
    db_name = th["db"]
    old_helper, new_helper = th["helper"]
    n_tag = rnd.randint(300, 799)
    tag_new = f"ship-{n_tag}{rnd.choice('cdfghk')}"
    tag_old = f"ship-{n_tag - rnd.randint(2, 9)}{rnd.choice('cdfghk')}"
    integ = names_ho3(rnd, 412)
    k6 = rnd.randint(70, 320)
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
    lines = code_file_ho3(rnd, mod_a, rnd.randint(120, 170))
    b.tool("read", {"path": f"src/{P}/{mod_a}.py"}, read_result(f"src/{P}/{mod_a}.py", lines))
    say("a_open", nfun=sum(1 for l in lines if l.startswith("    def ")))

    user("u_tests")
    cases = names_ho3(rnd, 34)
    fail = cases[rnd.randrange(len(cases))]
    tb = [f'  File "tests/test_{mod_a}.py", line {rnd.randint(30, 280)}, in {fail}',
          f"    self.schema.migrate_column('{th['column']}')",
          f"{P}.errors.MigrationError: [{err_a}] migration of '{th['column']}' was rolled back"]
    b.tool("shell", {"command": ut_cmd(mod_a)},
           unittest_output(rnd, f"tests.test_{mod_a}", cls_of(mod_a), cases, {fail: tb}))
    say("a_tests", fail=fail)

    user("u_spec")
    say("a_spec")
    user("u_port")
    say("a_port")

    cfg = ["; Downstream backends for production (loaded by etc.backends)", ""]
    for c in clients:
        cfg += [f"[backend:{c}]", f"endpoint = https://{c.replace('_', '-')}.{P}.corp.internal",
                f"connect_timeout = {timeouts[c][0]}", f"reply_timeout = {timeouts[c][1]}",
                f"retry_budget = {rnd.randint(1, 6)}", f"pool_limit = {rnd.randint(4, 64)}", ""]
    user("u_clients")
    b.tool("read", {"path": "etc/backends.ini"}, read_result("etc/backends.ini", cfg))
    say("a_clients")

    for m in mods[1:3]:
        user("u_module", m=m)
        lines = code_file_ho3(rnd, m, rnd.randint(110, 160))
        b.tool("read", {"path": f"src/{P}/{m}.py"}, read_result(f"src/{P}/{m}.py", lines))
        say("a_module", m=m, noun=rnd.choice(NOUNS_HO3))

    env = [f"UAT_CACHE_HOSTNAME=redis-uat-{rnd.randint(30, 79)}.corp.internal",
           f"UAT_DB_HOSTNAME={host}", f"UAT_QUEUE_HOSTNAME=amqp-uat-{rnd.randint(30, 79)}.corp.internal",
           f"UAT_DB_ROLE={P}_app", "UAT_DB_SSLMODE=verify-full",
           f"UAT_FEATURES={rnd.choice(NOUNS_HO3)},{rnd.choice(NOUNS_HO3)}"]
    user("u_env")
    b.tool("read", {"path": "etc/uat.vars"}, read_result("etc/uat.vars", env))
    say("a_env")

    user("u_pooler")
    say("a_pooler")

    m = mods[3]
    user("u_tests2", m=m)
    cases = names_ho3(rnd, 27)
    f2 = cases[rnd.randrange(len(cases))]
    b.tool("shell", {"command": ut_cmd(m)},
           unittest_output(rnd, f"tests.test_{m}", cls_of(m), cases, {f2: [
               f'  File "tests/test_{m}.py", line {rnd.randint(20, 200)}, in {f2}',
               "    self.backend.request()",
               f"{P}.errors.RetryError: [{err_distractors[0]}] retry budget spent"]}))
    say("a_tests2", f2=f2)

    user("u_helper")
    b.tool("edit", {"path": f"src/{P}/{mod_a}.py", "oldString": f"def {old_helper}(",
                    "newString": f"def {new_helper}("},
           f"Edited src/{P}/{mod_a}.py (1 replacement)")
    say("a_helper")

    user("u_newport")
    say("a_newport")

    user("u_db")
    b.tool("grep", {"pattern": "_uat", "path": "etc"},
           f"Found 1 matches\netc\\schemas.yaml:\n  Line {rnd.randint(3, 30)}:   uat: {db_name}")
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

    fx = ["; Fixture backends: short connects, long replies", ""]
    for c in clients:
        fx += [f"[backend:{c}]", f"connect_timeout = {fixture_timeouts[c][0]}",
               f"reply_timeout = {fixture_timeouts[c][1]}", ""]
    user("u_fixture")
    b.tool("read", {"path": "tests/fixtures/backends.ini"},
           read_result("tests/fixtures/backends.ini", fx))
    say("a_fixture")

    user("u_two", m=mods[5], m2=mods[6])
    for mm, e in ((mods[5], err_distractors[1]), (mods[6], err_distractors[2])):
        cases = names_ho3(rnd, 22)
        ff = cases[rnd.randrange(len(cases))]
        b.tool("shell", {"command": ut_cmd(mm)},
               unittest_output(rnd, f"tests.test_{mm}", cls_of(mm), cases, {ff: [
                   f'  File "tests/test_{mm}.py", line {rnd.randint(20, 200)}, in {ff}',
                   "    self.load_fixture_rows()",
                   f"{P}.errors.SchemaError: [{e}] fixture row carries an unknown column"]}))
    say("a_two")

    for m in mods[1:] + mods[1:4]:
        b.user(rnd.choice(ph["u_filler"]).format(P=P, m=m))
        path = f"src/{P}/{m}.py"
        lines = code_file_ho3(rnd, m, rnd.randint(130, 200))
        b.tool("read", {"path": path}, read_result(path, lines))
        b.say(rnd.choice(ph["a_filler"]).format(m=m))

    import_messages = b.messages

    # ---- steps: the shared skeleton ----
    sid = f"ho3h{index + 1}"

    def q(qid, category, answer, parts=None, restart=False, evidence=None, **kw):
        return {"kind": "question", "id": f"{sid}{qid.lower()}", "qid": qid,
                "category": category, "text": ph[qid].format(**v, **kw), "answer": answer,
                "parts": parts or [answer], "evidence": evidence or parts or [answer],
                "restart_before": restart}

    def paste(pid, what, body):
        return {"kind": "paste", "id": f"{sid}{pid.lower()}",
                "text": ph["paste"].format(what=ph[what], body="\n".join(body))}

    deploy = canary_lines(rnd, 140, th["svc"])
    deploy.insert(rnd.randint(40, 100),
                  f"ts=2027-01-{rnd.randint(18, 21)}T03:{rnd.randint(10, 59)}:{rnd.randint(10, 59)}+0000 "
                  f'level=notice msg="promoted {tag_new}; {tag_old} retired" phase=full')
    lint = []
    for _ in range(230):
        mm = rnd.choice(mods)
        lint.append(f"src/{P}/{mm}.py:{rnd.randint(1, 400)}: error: "
                    f"{rnd.choice(['Incompatible return value type', 'Missing type parameters for generic type', 'Item of Optional has no attribute', 'Argument 1 has incompatible type', 'Name already defined on line ' + str(rnd.randint(1, 99)), 'Unused type: ignore comment'])}"
                    f"  [{rnd.choice(['return-value', 'type-arg', 'union-attr', 'arg-type', 'no-redef', 'unused-ignore'])}]")
    lint.append(f"Found {len(lint)} errors in {len(set(mods))} files (checked {rnd.randint(40, 90)} source files)")
    prof = ["[ Top allocations ]"]
    for _ in range(140):
        mm = rnd.choice(mods)
        prof.append(f"src/{P}/{mm}.py:{rnd.randint(1, 400)}: size={rnd.uniform(0.1, 900):.1f} KiB, "
                    f"count={rnd.randint(1, 40000)}, average={rnd.randint(16, 4000)} B")
    cm = th["const_mod"]
    mid_cmd = ut_cmd(cm)
    mid_case = names_ho3(rnd, 1)[0]
    message = f"{th['const']} is {const_cur}, which breaks decision record {req_id}"
    mid_out = unittest_output(rnd, f"tests.test_{cm}", cls_of(cm), [mid_case], {mid_case: [
        f'  File "tests/test_{cm}.py", line 16, in {mid_case}',
        f"    self.assertEqual({th['const']}, WANTED, WHY)",
        f"AssertionError: {const_cur} != None : {message}"]}, kind="FAIL")

    steps = [
        q("Q1", "identifier", err_a),
        paste("P1", "paste_deploy", deploy),
        q("Q2", "identifier", branch),
        q("Q3", "superseded", str(port_new), evidence=[f"put it on {port_new} instead"]),
        paste("P2", "paste_lint", lint),
        q("Q4", "irrelevant_matches", timeouts[target_client][0],
          evidence=[f"connect_timeout = {timeouts[target_client][0]}"]),
        q("Q5", "vague", timeouts[target_client][1],
          evidence=[f"reply_timeout = {timeouts[target_client][1]}"]),
        paste("P3", "paste_prof", prof),
        q("Q6", "oversized_read", q6_after),
        dict(q("Q7", "mid_task", str(const_val), mid_cmd=mid_cmd,
               evidence=[f"{req_id}, {th['const']} needs to be {const_val}"]),
             mid_task={"command": mid_cmd, "output": mid_out}),
        q("Q8", "multi_fact", f"{host}:{db_port}/{db_name}", parts=[host, str(db_port), db_name],
          evidence=[f"UAT_DB_HOSTNAME={host}", f"pgbouncer listens on {db_port}", db_name]),
        q("Q9", "restart_multi_eviction", tag_new, restart=True),
        q("Q10", "vague", new_helper),
    ]
    import_messages.append({"role": "user", "content": steps[0]["text"]})
    const = th["const"]
    test_file = "\n".join([
        "import sys", "import unittest", "from pathlib import Path", "",
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))', "",
        f"from {P}.{cm} import {const}  # noqa: E402", "",
        "WANTED = None  # the value the decision record fixes",
        f'WHY = f"{const} is {{{const}}}, which breaks decision record {req_id}"', "", "",
        f"class {cls_of(cm)}(unittest.TestCase):",
        "    maxDiff = None", "",
        f"    def {mid_case}(self):",
        f"        self.assertEqual({const}, WANTED, WHY)", ""])
    workspace = {
        f"tests/test_{cm}.py": test_file,
        f"src/{P}/{cm}.py": const_module_ho3(rnd, cm, const, const_cur),
    }
    h = {"id": f"ho3-h{index + 1}", "seed": seed, "project": P, "set": SET,
         "generator": GENERATOR, "import": import_messages, "steps": steps,
         "workspace": workspace,
         "shell": [{"match": f"unittest tests.test_{cm}", "output": mid_out}]}
    planted = {
        "theme": [P, th["svc"], th["db"], th["const"], *th["helper"], *th["modules"],
                  *th["clients"], th["column"]],
        "values": [err_a, *err_distractors, f"JOB-{ticket}", branch, branch_docs, req_id,
                   req_other, host, tag_new, tag_old, q6_before, q6_after, mid_case, fail, f2,
                   timeouts[target_client][0], timeouts[target_client][1]],
        "numeric": [str(port_old), str(port_new), str(port_admin), str(db_port), str(const_val),
                    str(const_cur)],
    }
    return h, planted


def build_heldout3(index: int, seed: int) -> dict:
    return _build(index, seed)[0]


# ---------------------------------------------------------------- independence check

def _grams(h: dict) -> set:
    """Four-word runs of the wording: user turns, assistant summaries, questions and paste
    wrappers (not tool output or paste bodies), as in ``needle_gen_ho2``; inline code spans
    are left out (commands and identifiers, checked as strings)."""
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


def _theme_tokens(themes) -> set:
    out = set()
    for t in themes:
        out |= {t["project"], t["svc"], t["db"], t["const"], *t["helper"], *t["modules"],
                *t["clients"], t.get("column", "")}
    return out - {""}


def check() -> list[str]:
    """Problems with the committed ho3 set; empty when it is independent and well formed."""
    import needle_gen as ng
    import needle_gen_ho2 as ng2

    problems = []
    earlier = {}
    for folder in EARLIER_FOLDERS:
        for f in sorted((ROOT / "eval" / "needles" / folder).glob("*.json")):
            earlier[f.name] = f.read_text(encoding="utf-8")
    if not any(n.startswith("ho2-") for n in earlier):
        problems.append("the heldout2 needle files are missing")
    corpus = "\n".join(earlier.values()).casefold()
    earlier_answers = set()
    for text in earlier.values():
        for s in json.loads(text)["steps"]:
            if s["kind"] == "question":
                earlier_answers |= {s["answer"].casefold(), *(p.casefold() for p in s["parts"])}

    def word_in(tok: str, text: str) -> bool:
        return re.search(rf"(?<![a-z0-9_]){re.escape(tok.casefold())}(?![a-z0-9_])", text) is not None

    # 1. Seeds, themes and word banks.
    seeds = set(range(SEED_BASE, SEED_BASE + len(THEMES_HO3)))
    if seeds & EARLIER_SEEDS:
        problems.append("seed overlap")
    ours = _theme_tokens(THEMES_HO3)
    theirs = _theme_tokens(ng.THEMES) | _theme_tokens(ng.THEMES_HO) | _theme_tokens(ng2.THEMES_HO2)
    if ours & theirs:
        problems.append(f"theme tokens shared: {sorted(ours & theirs)}")
    for bank, others in ((VERBS_HO3, ng.VERBS + ng.VERBS_HO + ng2.VERBS_HO2),
                         (NOUNS_HO3, ng.NOUNS + ng.NOUNS_HO + ng2.NOUNS_HO2),
                         (ADJS_HO3, ng.ADJS + ng.ADJS_HO + ng2.ADJS_HO2)):
        if set(bank) & set(others):
            problems.append(f"word bank shared: {sorted(set(bank) & set(others))}")
    for tok in sorted(ours):
        if word_in(tok, corpus):
            problems.append(f"theme identifier {tok!r} occurs in an earlier needle file")
    for t in THEMES_HO3:
        for cv in t["const_values"]:
            if str(cv) in earlier_answers:
                problems.append(f"const value {cv} is an earlier answer")

    earlier_grams = set()
    for text in earlier.values():
        earlier_grams |= _grams(json.loads(text))
    dev_skeleton = _skeleton(json.loads(earlier["dev-h1.json"]))

    for i in range(len(THEMES_HO3)):
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
                problems.append(f"{h['id']}: planted string {s!r} occurs in an earlier needle file")
        # 3. Numeric answers and values: never an earlier answer.
        for s in planted["numeric"] + [x for q in qs for x in [q["answer"], *q["parts"]]
                                       if not any(c.isalpha() for c in x)]:
            if s.casefold() in earlier_answers:
                problems.append(f"{h['id']}: numeric value {s} is an earlier answer")
        # 4. Wording.
        shared = _grams(h) & earlier_grams
        if shared:
            problems.append(f"{h['id']}: {len(shared)} four-word runs shared, e.g. {sorted(shared)[:3]}")
        # 5. Evidence is in the history; the answer is unique where it must be.
        text = "\n".join((m.get("content") or "") + json.dumps(m.get("tool_calls") or "")
                         for m in h["import"]) + "\n".join(s["text"] for s in h["steps"])
        for s in qs:
            for e in s["evidence"]:
                if e not in text:
                    problems.append(f"{h['id']} {s['qid']}: evidence missing from the history")
        if h["import"][-1] != {"role": "user", "content": qs[0]["text"]}:
            problems.append(f"{h['id']}: import does not end with Q1")
    # 6. Question wording: no question text shared verbatim with an earlier set.
    earlier_q = {s["text"].casefold() for t in earlier.values() for s in json.loads(t)["steps"]
                 if s["kind"] == "question"}
    for i in range(len(THEMES_HO3)):
        for s in _build(i, SEED_BASE + i)[0]["steps"]:
            if s["kind"] == "question" and s["text"].casefold() in earlier_q:
                problems.append(f"ho3-h{i + 1} {s['qid']}: question text equals an earlier one")
    # 7. The ho3 coding tasks' identifiers: not in an earlier task module or needle file.
    task_srcs = [p for p in (ROOT / "eval" / "tasks").glob("*.py")
                 if p.stem.startswith(("dev_", "ho_", "ho2_"))]
    task_corpus = corpus + "\n".join(p.read_text(encoding="utf-8") for p in task_srcs).casefold()
    for tok in TASK_IDENTIFIERS:
        if word_in(tok, task_corpus):
            problems.append(f"task identifier {tok!r} occurs in an earlier task or needle file")
    for tok in ng2.TASK_IDENTIFIERS:
        if tok in TASK_IDENTIFIERS:
            problems.append(f"task identifier {tok!r} is an ho2 task identifier")
    return problems


# Package, module, function, error, error-code and file names of eval/tasks/ho3_t1.py ..
# ho3_t5.py.
TASK_IDENTIFIERS = [
    "ibancheck", "IbanError", "to_electronic", "to_print", "make_iban", "statement_mask",
    "IB-41", "IB-42", "IB-43", "IB-44", "iban_rules",
    "dialkit", "DialError", "to_e164", "rewrite_sheet", "vanity_digits", "dialling_plan",
    "switchboard",
    "bracecheck", "BraceIssue", "scan_text", "leading_width", "bracket_rules",
    "parcelrate", "RateError", "chargeable_weight", "quote_parcel", "label_band", "rate_card",
    "cronwheel", "CronError", "parse_cron", "cron_matches", "next_fire", "day_ordinal",
    "cron_syntax",
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
        print(f"ho3 independence check: {'ok' if not problems else f'{len(problems)} problems'}")
        return 1 if problems else 0
    out = a.out or OUT
    out.mkdir(parents=True, exist_ok=True)
    for i in range(len(THEMES_HO3)):
        h = build_heldout3(i, SEED_BASE + i)
        (out / f"{h['id']}.json").write_text(json.dumps(h, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8", newline="\n")
        chars = sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or ""))
                    for m in h["import"])
        print(f"{h['id']}: {len(h['import'])} import messages, ~{chars} chars, {len(h['steps'])} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
