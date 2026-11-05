"""Seeded generator for the fourth held-out needle set ``ho4`` (A1 "Evaluation", Phase 7).

A fresh held-out set for the Phase 7 evaluation on OpenCode 2.1.4 and Pi 1.5.0. Like
``ho3`` it was written by an author who has not seen the design it will judge. It keeps
the step skeleton, categories and answer types of ``build_history`` (so A1's coverage
holds) and replaces everything else: twelve new themes, new word banks, new file names,
value formats, tool-output bodies and a new phrasing bank for every user turn, assistant
summary, question and paste wrapper. No wording names a harness or a harness tool.

Steps after the import (the shared skeleton):

    Q1, P1 (paste carrying the Q9 fact), Q2, Q3, P2, Q4, Q5, P3, Q6, Q7, Q8,
    [proxy restart], Q9, Q10

Categories (A1): identifier (Q1, Q2), superseded (Q3), irrelevant matches (Q4),
vague reference (Q5, Q10), oversized transcript read (Q6), mid-task need (Q7),
several distant facts (Q8), restart plus multiple eviction events (Q9).

Only the tool-result shapes (``read_result``), the ``python -m unittest`` output shape
and the message builder are imported from ``needle_gen``; they are formats, not content.
The independence check also reads ``needle_gen_ho2`` and ``needle_gen_ho3`` (their
themes, banks and task identifiers), only to compare against them.

Usage:
    python eval/needle_gen_ho4.py [--out DIR]   # writes ho4-h1..h12, seeds 7500-7511
    python eval/needle_gen_ho4.py --check       # independence from dev, heldout, heldout2, heldout3
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
OUT = ROOT / "eval" / "needles" / "heldout4"
SEED_BASE = 7500
SET = "heldout4"
GENERATOR = "eval/needle_gen_ho4.py v1"
EARLIER_SEEDS = (set(range(3100, 3106)) | set(range(5200, 5212)) | set(range(6400, 6412))
                 | set(range(7400, 7412)))
EARLIER_FOLDERS = ("dev", "heldout", "heldout2", "heldout3")

THEMES_HO4 = [
    dict(project="mistbench", topic="misting cycles skipped while the roof vents are open",
         modules=["mist_cycles", "vent_actuators", "bench_zones", "humidity_probes",
                  "crop_batches", "shade_screens", "irrigation_valves", "grower_tasks"],
         svc="mistbench-climate", db="mistbench_climate_perf",
         clients=["weather_station", "nutrient_doser", "crop_planner", "energy_meter",
                  "pest_scout", "wholesale_orders"],
         const="VENT_LOCKOUT_SECONDS", const_mod="vent_actuators", const_values=[47, 59, 71, 83],
         helper=("_skip_when_vent_open", "defer_until_vent_closed"), kind="vent lockout",
         column="rh_percent"),
    dict(project="switchtrack", topic="freight wagons routed onto a closed siding",
         modules=["siding_status", "wagon_routes", "yard_tracks", "consist_builder",
                  "hump_sorting", "brake_tests", "track_closures", "crew_tickets"],
         svc="switchtrack-yard", db="switchtrack_yard_perf",
         clients=["dispatch_center", "wagon_registry", "signal_interlock", "hazmat_desk",
                  "customer_edi", "track_inspection"],
         const="SIDING_CLEARANCE_METRES", const_mod="siding_status",
         const_values=[142, 154, 166, 178],
         helper=("_route_by_track_number", "route_by_open_siding"), kind="routing",
         column="siding_id"),
    dict(project="pawprint", topic="vaccine boosters booked before the minimum interval",
         modules=["booster_rules", "vaccine_lots", "patient_pets", "appointment_book",
                  "clinic_rooms", "lab_results", "owner_reminders", "invoice_lines"],
         svc="pawprint-clinic", db="pawprint_clinic_perf",
         clients=["lot_recall_feed", "reminder_sms", "pet_insurance", "reference_lab",
                  "pharmacy_supplier", "microchip_registry"],
         const="BOOSTER_MIN_DAYS", const_mod="booster_rules", const_values=[219, 223, 229, 237],
         helper=("_interval_from_booking", "interval_from_last_dose"), kind="booster interval",
         column="dose_date"),
    dict(project="printfarm", topic="jobs resumed on the wrong spool after a filament runout",
         modules=["spool_tracker", "runout_sensor", "print_jobs", "printer_bays",
                  "slicer_profiles", "nozzle_wear", "bed_levelling", "part_bins"],
         svc="printfarm-fleet", db="printfarm_fleet_perf",
         clients=["filament_vendor", "slicer_cloud", "order_portal", "bay_cameras",
                  "power_strips", "qc_station"],
         const="RUNOUT_PAUSE_SECONDS", const_mod="runout_sensor", const_values=[344, 352, 368, 376],
         helper=("_resume_on_last_spool", "resume_on_loaded_spool"), kind="resume",
         column="spool_serial"),
    dict(project="lockkeeper", topic="boats queued twice when a lock cycle aborts",
         modules=["lock_cycles", "boat_queue", "gate_sensors", "water_levels", "toll_passes",
                  "bridge_swings", "mooring_slots", "keeper_shifts"],
         svc="lockkeeper-canal", db="lockkeeper_canal_perf",
         clients=["river_authority", "gauge_network", "ais_receiver", "boater_app",
                  "sluice_plc", "maintenance_crew"],
         const="LOCK_CYCLE_TIMEOUT_S", const_mod="lock_cycles", const_values=[372, 444, 516, 588],
         helper=("_requeue_on_abort", "release_slot_on_abort"), kind="abort handling",
         column="queue_position"),
    dict(project="icecore", topic="core depths shifted after sections are spliced",
         modules=["core_sections", "splice_log", "depth_scale", "isotope_runs", "freezer_racks",
                  "drill_logs", "dust_counts", "sample_cuts"],
         svc="icecore-lab", db="icecore_lab_perf",
         clients=["drill_camp", "mass_spec", "freezer_alarm", "polar_archive",
                  "field_logistics", "dating_model"],
         const="SPLICE_OVERLAP_MM", const_mod="splice_log", const_values=[617, 626, 634, 639],
         helper=("_depth_from_section_top", "depth_from_splice_table"), kind="depth mapping",
         column="depth_mm"),
    dict(project="doughline", topic="proofing timers reset when racks move between ovens",
         modules=["proof_timers", "rack_moves", "oven_decks", "dough_batches", "flour_silos",
                  "mixer_runs", "shelf_labels", "delivery_rounds"],
         svc="doughline-bake", db="doughline_bake_perf",
         clients=["flour_mill", "oven_controller", "retail_orders", "allergen_register",
                  "van_routing", "scale_station"],
         const="PROOF_DRIFT_SECONDS", const_mod="proof_timers", const_values=[787, 793, 811, 829],
         helper=("_restart_timer_on_move", "carry_timer_across_move"), kind="proof timer",
         column="proof_started"),
    dict(project="orbitpass", topic="downlink passes booked past the antenna slew limit",
         modules=["pass_planner", "antenna_slew", "ground_stations", "telemetry_frames",
                  "tle_updates", "contact_windows", "mission_ops", "frame_archive"],
         svc="orbitpass-ground", db="orbitpass_ground_perf",
         clients=["tle_provider", "rf_chain", "spectrum_office", "operator_console",
                  "frame_vault", "conjunction_alerts"],
         const="SLEW_MARGIN_SECONDS", const_mod="antenna_slew", const_values=[137, 149, 163, 181],
         helper=("_slew_from_azimuth_only", "slew_from_az_el_path"), kind="slew check",
         column="elevation_deg"),
    dict(project="refillwell", topic="prescription refills released before the early-refill threshold",
         modules=["refill_rules", "scripts_rx", "dispense_log", "patient_profiles",
                  "insurer_rules", "stock_shelves", "pickup_lockers", "counsel_notes"],
         svc="refillwell-rx", db="refillwell_rx_perf",
         clients=["eprescribe_hub", "payer_switch", "drug_wholesaler", "locker_vendor",
                  "monitoring_registry", "prescriber_fax"],
         const="EARLY_REFILL_PERMILLE", const_mod="refill_rules", const_values=[742, 771, 813, 864],
         helper=("_days_from_fill_date", "days_from_supply_end"), kind="refill threshold",
         column="days_supply"),
    dict(project="pitlane", topic="lap times credited to the wrong car after a pit stop",
         modules=["lap_timing", "pit_stops", "transponders", "car_entries", "race_control",
                  "sector_splits", "tyre_sets", "penalty_board"],
         svc="pitlane-timing", db="pitlane_timing_perf",
         clients=["loop_decoders", "broadcast_feed", "steward_desk", "team_portal",
                  "track_marshals", "results_publisher"],
         const="PIT_LANE_DELAY_MS", const_mod="pit_stops", const_values=[1340, 1560, 1780, 1920],
         helper=("_lap_by_car_number", "lap_by_transponder_id"), kind="lap attribution",
         column="transponder_id"),
    dict(project="seedvault", topic="germination tests filed against the wrong accession",
         modules=["accessions", "germ_tests", "cold_rooms", "seed_lots", "viability_curves",
                  "regen_plots", "donor_records", "shipment_packs"],
         svc="seedvault-bank", db="seedvault_bank_perf",
         clients=["genebank_portal", "phyto_certs", "field_station", "courier_cold",
                  "taxonomy_service", "lab_scanner"],
         const="RETEST_INTERVAL_DAYS", const_mod="germ_tests", const_values=[398, 427, 455, 486],
         helper=("_match_by_tray_label", "match_by_accession_barcode"), kind="accession matching",
         column="accession_no"),
    dict(project="washline", topic="wash cycles billed twice after a door-lock fault",
         modules=["wash_cycles", "door_locks", "coin_boxes", "dryer_bank", "card_readers",
                  "detergent_pumps", "machine_faults", "loyalty_cards"],
         svc="washline-store", db="washline_store_perf",
         clients=["payment_terminal", "machine_vendor", "store_cameras", "loyalty_backend",
                  "water_utility", "service_techs"],
         const="DOOR_LOCK_RETRY_MS", const_mod="door_locks", const_values=[820, 940, 1060, 1180],
         helper=("_bill_on_cycle_start", "bill_on_cycle_complete"), kind="billing",
         column="cycle_id"),
]

VERBS_HO4 = ["buff", "coil", "dab", "fetter", "gild", "hem", "jostle", "lace", "mull", "pare",
             "quell", "rinse", "sift", "tamp", "unfurl", "vex", "wring", "yank"]
NOUNS_HO4 = ["bellows", "candle", "dowel", "funnel", "goblet", "harness", "inkpot", "ladder",
             "mitten", "nutmeg", "oarlock", "pebble", "ribbon", "spigot", "tassel", "teapot",
             "walnut", "yardarm"]
ADJS_HO4 = ["ashen", "bristly", "cobalt", "dappled", "fleecy", "grainy", "husky", "inky",
            "leaden", "mossy", "nubby", "pearly", "quilted", "russet", "sooty", "tawny",
            "velvety", "wispy"]

# The ho4 phrasing bank. No four-word run is shared with the dev, heldout, heldout2 or
# heldout3 wording (``check``). Harness-neutral: no tool or harness is named.
PH = {
    "u_open": "This sprint is {P}, specifically {topic}. Log time against change ticket "
              "CT-{ticket}, and commit the real fix to `{branch}`. First, please show me "
              "src/{P}/{mod_a}.py.",
    "a_open": "Looked over `{mod_a}.py`: a stage registry and {nfun} registered stage "
              "functions. No obvious culprit so far; its test module is probably the next stop.",
    "u_tests": "Fine, run the {mod_a} test module.",
    "a_tests": "A single test, `{fail}`, errored out: SchemaShiftError while shifting that "
               "column. Every other test passed.",
    "u_spec": "Change notice {req_id}: {const} must be exactly {const_val}, because the "
              "consumer at the other end rejects any other number. Separately, {req_other} "
              "fixes DRAIN_BATCH_ROWS at 4400. Keep both of those in mind for later.",
    "a_spec": "Recorded: under {req_id}, {const} must be {const_val}; under {req_other}, "
              "DRAIN_BATCH_ROWS stays at 4400.",
    "u_port": "For local development {svc} binds port {port_old}. The health endpoint "
              "binds {port_admin}, which never moves.",
    "a_port": "Okay: locally, {svc} binds {port_old} and its health endpoint binds "
              "{port_admin}.",
    "u_clients": "Show me what conf/upstreams.toml declares for our upstream dependencies.",
    "a_clients": "conf/upstreams.toml declares six upstreams, each with a URL, connect and "
                 "response timeouts, an attempt cap and a connection ceiling.",
    "u_module": "Next one: src/{P}/{m}.py. Is {column} referenced anywhere in it?",
    "a_module": "No reference. `{m}.py` merely shuffles {noun} rows between stages; "
                "{column} never appears.",
    "u_env": "Where do the perf environment's services live?",
    "a_env": "conf/perf.env gives the perf hosts for the database, the cache and the broker, "
             "and also the database login.",
    "u_pooler": "Heads-up: on perf, pgcat listens on {db_port} rather than 5432.",
    "a_pooler": "Noted, pgcat on perf means port {db_port}.",
    "u_tests2": "Please also try the {m} test module.",
    "a_tests2": "That module hit one failure: `{f2}` ran out of attempts with AttemptsExhausted. "
                "The column bug is a separate matter.",
    "u_helper": "While {mod_a}.py is open, rename its outdated {kind} helper.",
    "a_helper": "Renamed `{old_helper}` to `{new_helper}`; the previous name stays bound to "
                "the new function, so existing callers keep working.",
    "u_newport": "Scratch the earlier port for {svc}: move it to {port_new}. Something "
                 "else already grabs {port_old}.",
    "a_newport": "Updated; {svc} now binds {port_new}.",
    "u_db": "What database does the perf replay job target?",
    "a_db": "On perf, the replay job targets `{db_name}`.",
    "u_integ": "Integration suite next, please: every test, verbose.",
    "a_integ": "All {n_integ} passed, with no failures or errors.",
    "u_docs": "Note for later: any write-up of this goes to `{branch_docs}`.",
    "a_docs": "Will do; write-ups go to `{branch_docs}`.",
    "u_fixture": "And the test-data copy of the upstreams: which timeouts does that one use?",
    "a_fixture": "The test-data upstreams all use tiny connect timeouts and huge response "
                 "timeouts.",
    "u_two": "Give the {m} and {m2} test modules a run.",
    "a_two": "Both report one ColumnMismatch; probably outdated test data.",
    "u_filler": ["Have a fresh look at src/{P}/{m}.py: what is its failure handling like?",
                 "Does src/{P}/{m}.py swallow anything it shouldn't? Have a look.",
                 "Of the logging calls in src/{P}/{m}.py, which deserve to stay?",
                 "Recheck src/{P}/{m}.py, hunting for overly broad exception handlers."],
    "a_filler": ["`{m}.py` logs failures quietly and re-raises them unchanged.",
                 "`{m}.py` never raises on its own; each stage only hands rows on. Fine.",
                 "Keep every logging call in `{m}.py`; none is noise.",
                 "`{m}.py` names the precise exception type in each handler."],
    "paste": "Parking {what} below so it's in the conversation; it can wait until afterwards. No "
             "tools and no analysis yet, please. Just acknowledge with 'ok'.\n\n```\n{body}\n```",
    "paste_deploy": "yesterday's rollout controller event stream",
    "paste_lint": "the overnight pylint run",
    "paste_prof": "a line_profiler dump of the slow reconcile job",
    "Q1": "Back when the {mod_a} test module first ran, the SchemaShiftError quoted a "
          "bracketed code. Which code? Reply with nothing but that code.",
    "Q2": "Which branch gets the real fix? Reply with nothing but the branch name.",
    "Q3": "What port does {svc} bind at this point? Reply with nothing but the number.",
    "Q4": "In the real conf/upstreams.toml (not the test-data copy), what is the connect "
          "timeout of {target_client}? Reply with nothing but the value.",
    "Q5": "Same upstream, response timeout? Reply with nothing but the value.",
    "Q6": "Scanning the verbose integration listing, what test came directly after {q6_before}? "
          "Reply with nothing but the test method.",
    "Q7": "Please run `{mid_cmd}` and leave all code untouched. Per the change notice from "
          "early in our chat, what number does that constant need to be? Reply with nothing "
          "but the number.",
    "Q8": "Join the perf database host, the pgcat port and the replay database name as "
          "host:port/dbname. Reply with nothing but that.",
    "Q9": "In the rollout event stream I parked earlier, which build was activated? Reply "
          "with nothing but the build.",
    "Q10": "That outdated {kind} helper you renamed: what is it called now? Reply with "
           "nothing but the new name.",
}

CODE_LETTERS = "BDFGJKQSVZ"


def names_ho4(rnd: random.Random, k: int, prefix: str = "test_") -> list[str]:
    seen, out = set(), []
    while len(out) < k:
        n = f"{prefix}{rnd.choice(ADJS_HO4)}_{rnd.choice(NOUNS_HO4)}_must_{rnd.choice(VERBS_HO4)}"
        if n in seen or any(n in s or s in n for s in seen):
            continue
        seen.add(n)
        out.append(n)
    return out


def err_code(rnd: random.Random, P: str) -> str:
    """``MIS#482-QV``: a value format used by none of the earlier sets."""
    return (f"{P[:3].upper()}#{rnd.randint(100, 999)}-{rnd.choice(CODE_LETTERS)}"
            f"{rnd.choice(CODE_LETTERS)}")


def code_file_ho4(rnd: random.Random, module: str, lines: int) -> list[str]:
    """Plausible Python source in the ho4 word banks: a stage registry with functions."""
    cls = "".join(p.title() for p in module.split("_"))
    out = [f'"""{module.replace("_", " ")}: registered stages."""', "",
           "from dataclasses import dataclass, field", "", "STAGES = {}", "", "",
           "def stage(name):", "    def wrap(fn):", "        STAGES[name] = fn",
           "        return fn", "    return wrap", "", "",
           "@dataclass", f"class {cls}Row:", "    key: str", "    weight: int = 0",
           "    tags: list = field(default_factory=list)", "", ""]
    while len(out) < lines:
        v, n, a = rnd.choice(VERBS_HO4), rnd.choice(NOUNS_HO4), rnd.choice(ADJS_HO4)
        out.append(f'@stage("{v}-{n}")')
        out.append(f"def {v}_{n}_{a}(rows, budget={rnd.choice([16, 32, 48, 64, 96])}):")
        for _ in range(rnd.randint(2, 6)):
            out.append(rnd.choice([
                f"    rows = [r for r in rows if r.weight > {rnd.randint(1, 40)}]",
                f"    rows.sort(key=lambda r: (r.key, -r.weight))",
                f"    budget -= {rnd.randint(1, 9)}",
                f"    rows = rows[:budget]",
                f"    for r in rows:\n        r.tags.append('{a}-{n}')",
                f"    # {v} each {a} {n} before the {rnd.choice(NOUNS_HO4)} is handed on",
            ]))
        out.append("    return rows")
        out.append("")
        out.append("")
    return "\n".join(out).split("\n")[:lines]


def const_module_ho4(rnd: random.Random, module: str, const: str, value: int) -> str:
    """An importable module defining ``const`` (the mid-task check imports it)."""
    lines = [f'"""{module.replace("_", " ")}: limits."""', "", f"{const} = {value}", ""]
    for _ in range(4):
        v, n = rnd.choice(VERBS_HO4), rnd.choice(NOUNS_HO4)
        lines += ["", f"def {v}_within_limit({n}_rows):",
                  f"    # {v} at most {const} {n} rows in one pass",
                  f"    return list({n}_rows)[:{const}]", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def hexs(rnd: random.Random, n: int) -> str:
    return "".join(rnd.choice("0123456789abcdef") for _ in range(n))


def iso_ms(rnd: random.Random) -> str:
    return (f"2027-03-{rnd.randint(9, 12):02d}T{rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:"
            f"{rnd.randint(0, 59):02d}.{rnd.randint(0, 999):03d}Z")


def rollout_events(rnd: random.Random, n: int, svc: str) -> list[str]:
    """Rollout controller events, one JSON object per line (own fields and templates)."""
    out = []
    for _ in range(n):
        ev = rnd.choice([
            {"ev": "probe", "pod": f"{svc}-{hexs(rnd, 6)}", "ok": rnd.random() < 0.9,
             "rtt_ms": rnd.randint(2, 400)},
            {"ev": "shift", "traffic_pct": rnd.randint(1, 60), "stage": f"{rnd.randint(1, 6)}/6"},
            {"ev": "slo", "burn": round(rnd.uniform(0, 3), 2), "window": rnd.choice(["10m", "2h", "1d"])},
            {"ev": "secret_sync", "digest": hexs(rnd, 10)},
            {"ev": "latency", "p95_ms": rnd.randint(15, 2400), "path": f"/{rnd.choice(NOUNS_HO4)}"},
            {"ev": "backlog", "depth": rnd.randint(0, 1200), "lane": rnd.choice(VERBS_HO4)},
        ])
        out.append(json.dumps({"at": iso_ms(rnd), **ev}, separators=(",", ":")))
    return out


def _build(index: int, seed: int) -> tuple[dict, dict]:
    """One ho4 history and the planted values the independence check looks at."""
    rnd = random.Random(seed)
    th = THEMES_HO4[index]
    P, mods = th["project"], list(th["modules"])
    rnd.shuffle(mods)
    mod_a = mods[0]
    b = Builder(rnd)

    def cls_of(mod: str) -> str:
        return "".join(p.title() for p in mod.split("_")) + "Cases"

    def ut_cmd(mod: str) -> str:
        return f"python -m unittest tests.test_{mod}"

    # ---- planted values (ho4 formats; answer types as in build_history) ----
    err_a = err_code(rnd, P)
    err_distractors = [err_code(rnd, P) for _ in range(3)]
    ticket = rnd.randint(100000, 999999)
    slug = "-".join(th["topic"].split()[:2])
    branch = f"patch/{ticket}-{P}-{slug}"
    branch_docs = f"{P}-writeup-{ticket}"
    port_old, port_new, port_admin = (rnd.randint(3410, 3489), rnd.randint(8110, 8189),
                                      rnd.randint(3510, 3589))
    clients = list(th["clients"])
    rnd.shuffle(clients)
    target_client = clients[0]

    def conn_t() -> str:
        return f"{rnd.randint(1, 4)}s{rnd.randrange(105, 995, 10)}ms"

    def resp_t() -> str:
        return f"{rnd.randint(1, 3)}m{rnd.randint(11, 59)}s"

    timeouts = {c: (conn_t(), resp_t()) for c in clients}
    used_c = {v[0] for c, v in timeouts.items() if c != target_client}
    used_r = {v[1] for c, v in timeouts.items() if c != target_client}
    cn, rp = timeouts[target_client]
    while cn in used_c:
        cn = conn_t()
    while rp in used_r:
        rp = resp_t()
    timeouts[target_client] = (cn, rp)
    fixture_timeouts = {c: (f"0s{rnd.randrange(15, 95, 10)}ms", f"{rnd.randint(7, 9)}m{rnd.randint(11, 59)}s")
                        for c in clients}
    req_id, req_other = f"CN-{rnd.randint(10000, 99999)}", f"CN-{rnd.randint(10000, 99999)}"
    while req_other == req_id:
        req_other = f"CN-{rnd.randint(10000, 99999)}"
    const_val = rnd.choice(th["const_values"])
    const_cur = const_val * 2 // 3
    host = f"pgx-perf-{rnd.randint(11, 69)}.east.lan"
    db_port = rnd.choice([5436, 6634, 7438, 8632])
    db_name = th["db"]
    old_helper, new_helper = th["helper"]
    n_tag = rnd.randint(2000, 8999)
    tag_new = f"bld-{n_tag}-{hexs(rnd, 3)}"
    tag_old = f"bld-{n_tag - rnd.randint(3, 40)}-{hexs(rnd, 3)}"
    integ = names_ho4(rnd, 412)
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
    lines = code_file_ho4(rnd, mod_a, rnd.randint(120, 170))
    b.tool("read", {"path": f"src/{P}/{mod_a}.py"}, read_result(f"src/{P}/{mod_a}.py", lines))
    say("a_open", nfun=sum(1 for l in lines if l.startswith("@stage(")))

    user("u_tests")
    cases = names_ho4(rnd, 34)
    fail = cases[rnd.randrange(len(cases))]
    tb = [f'  File "tests/test_{mod_a}.py", line {rnd.randint(30, 280)}, in {fail}',
          f"    self.store.shift_column('{th['column']}')",
          f"{P}.errors.SchemaShiftError: [{err_a}] shifting '{th['column']}' left the table "
          "unchanged"]
    b.tool("shell", {"command": ut_cmd(mod_a)},
           unittest_output(rnd, f"tests.test_{mod_a}", cls_of(mod_a), cases, {fail: tb}))
    say("a_tests", fail=fail)

    user("u_spec")
    say("a_spec")
    user("u_port")
    say("a_port")

    cfg = ["# Upstream dependencies in production (read by conf.upstreams)", ""]
    for c in clients:
        cfg += [f"[upstreams.{c}]", f'url = "https://{c.replace("_", "-")}.{P}.svc.example"',
                f'connect_timeout = "{timeouts[c][0]}"', f'response_timeout = "{timeouts[c][1]}"',
                f"max_attempts = {rnd.randint(1, 7)}", f"max_connections = {rnd.randint(3, 80)}", ""]
    user("u_clients")
    b.tool("read", {"path": "conf/upstreams.toml"}, read_result("conf/upstreams.toml", cfg))
    say("a_clients")

    for m in mods[1:3]:
        user("u_module", m=m)
        lines = code_file_ho4(rnd, m, rnd.randint(110, 160))
        b.tool("read", {"path": f"src/{P}/{m}.py"}, read_result(f"src/{P}/{m}.py", lines))
        say("a_module", m=m, noun=rnd.choice(NOUNS_HO4))

    env = [f"PERF_BROKER_HOST=mq-perf-{rnd.randint(11, 69)}.east.lan",
           f"PERF_CACHE_HOST=kv-perf-{rnd.randint(11, 69)}.east.lan",
           f"PERF_DB_HOST={host}", f"PERF_DB_USER={P}_svc", "PERF_DB_TLS=require",
           f"PERF_FLAGS={rnd.choice(NOUNS_HO4)}+{rnd.choice(NOUNS_HO4)}"]
    user("u_env")
    b.tool("read", {"path": "conf/perf.env"}, read_result("conf/perf.env", env))
    say("a_env")

    user("u_pooler")
    say("a_pooler")

    m = mods[3]
    user("u_tests2", m=m)
    cases = names_ho4(rnd, 27)
    f2 = cases[rnd.randrange(len(cases))]
    b.tool("shell", {"command": ut_cmd(m)},
           unittest_output(rnd, f"tests.test_{m}", cls_of(m), cases, {f2: [
               f'  File "tests/test_{m}.py", line {rnd.randint(20, 200)}, in {f2}',
               "    self.upstream.call()",
               f"{P}.errors.AttemptsExhausted: [{err_distractors[0]}] no attempts left"]}))
    say("a_tests2", f2=f2)

    user("u_helper")
    b.tool("edit", {"path": f"src/{P}/{mod_a}.py", "oldString": f"def {old_helper}(",
                    "newString": f"def {new_helper}("},
           f"Edited src/{P}/{mod_a}.py (1 replacement)")
    say("a_helper")

    user("u_newport")
    say("a_newport")

    user("u_db")
    b.tool("grep", {"pattern": "_perf", "path": "conf"},
           f"Found 1 matches\nconf\\databases.toml:\n  Line {rnd.randint(3, 30)}:   replay = \"{db_name}\"")
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

    fx = ["# Test-data upstreams: tiny connects, huge responses", ""]
    for c in clients:
        fx += [f"[upstreams.{c}]", f'connect_timeout = "{fixture_timeouts[c][0]}"',
               f'response_timeout = "{fixture_timeouts[c][1]}"', ""]
    user("u_fixture")
    b.tool("read", {"path": "tests/data/upstreams.toml"},
           read_result("tests/data/upstreams.toml", fx))
    say("a_fixture")

    user("u_two", m=mods[5], m2=mods[6])
    for mm, e in ((mods[5], err_distractors[1]), (mods[6], err_distractors[2])):
        cases = names_ho4(rnd, 22)
        ff = cases[rnd.randrange(len(cases))]
        b.tool("shell", {"command": ut_cmd(mm)},
               unittest_output(rnd, f"tests.test_{mm}", cls_of(mm), cases, {ff: [
                   f'  File "tests/test_{mm}.py", line {rnd.randint(20, 200)}, in {ff}',
                   "    self.seed_rows()",
                   f"{P}.errors.ColumnMismatch: [{e}] seed row names a column the table lacks"]}))
    say("a_two")

    for m in mods[1:] + mods[1:4]:
        b.user(rnd.choice(ph["u_filler"]).format(P=P, m=m))
        path = f"src/{P}/{m}.py"
        lines = code_file_ho4(rnd, m, rnd.randint(130, 200))
        b.tool("read", {"path": path}, read_result(path, lines))
        b.say(rnd.choice(ph["a_filler"]).format(m=m))

    import_messages = b.messages

    # ---- steps: the shared skeleton ----
    sid = f"ho4h{index + 1}"

    def q(qid, category, answer, parts=None, restart=False, evidence=None, **kw):
        return {"kind": "question", "id": f"{sid}{qid.lower()}", "qid": qid,
                "category": category, "text": ph[qid].format(**v, **kw), "answer": answer,
                "parts": parts or [answer], "evidence": evidence or parts or [answer],
                "restart_before": restart}

    def paste(pid, what, body):
        return {"kind": "paste", "id": f"{sid}{pid.lower()}",
                "text": ph["paste"].format(what=ph[what], body="\n".join(body))}

    deploy = rollout_events(rnd, 140, th["svc"])
    deploy.insert(rnd.randint(40, 100), json.dumps(
        {"at": iso_ms(rnd), "ev": "activated", "build": tag_new, "replaces": tag_old,
         "scope": "all-zones"}, separators=(",", ":")))
    msgs = [("W0612", "Unused variable '{x}'", "unused-variable"),
            ("C0103", "Variable name \"{x}\" doesn't conform to snake_case naming style", "invalid-name"),
            ("R0913", "Too many arguments (7/5)", "too-many-arguments"),
            ("W0718", "Catching too general exception Exception", "broad-exception-caught"),
            ("C0301", "Line too long (131/100)", "line-too-long"),
            ("R1705", "Unnecessary \"else\" after \"return\"", "no-else-return")]
    lint = []
    cur = None
    for _ in range(230):
        mm = rnd.choice(mods)
        if mm != cur:
            lint.append(f"************* Module {P}.{mm}")
            cur = mm
        code, text, sym = rnd.choice(msgs)
        lint.append(f"src/{P}/{mm}.py:{rnd.randint(1, 400)}:{rnd.randint(0, 24)}: {code}: "
                    f"{text.format(x=rnd.choice(NOUNS_HO4))} ({sym})")
    lint += ["", "-" * 66,
             f"Your code has been rated at {rnd.uniform(4, 9):.2f}/10", ""]
    prof = [f"Timer unit: 1e-06 s", "", f"Total time: {rnd.uniform(20, 90):.4f} s",
            f"File: src/{P}/{mods[4]}.py", f"Function: reconcile at line {rnd.randint(20, 90)}", "",
            "Line #      Hits         Time  Per Hit   % Time  Line Contents",
            "=" * 62]
    for k in range(140):
        hits = rnd.randint(1, 90000)
        t = rnd.randint(hits, hits * 40)
        prof.append(f"{100 + k:>6} {hits:>10} {t:>12} {t / hits:>8.1f} {rnd.uniform(0, 9):>8.1f}"
                    f"      {rnd.choice(VERBS_HO4)}_{rnd.choice(NOUNS_HO4)}(rows)")
    cm = th["const_mod"]
    mid_cmd = ut_cmd(cm)
    mid_case = names_ho4(rnd, 1)[0]
    message = f"{th['const']} is {const_cur}, contrary to change notice {req_id}"
    mid_out = unittest_output(rnd, f"tests.test_{cm}", cls_of(cm), [mid_case], {mid_case: [
        f'  File "tests/test_{cm}.py", line 16, in {mid_case}',
        f"    self.assertEqual({th['const']}, REQUIRED, REASON)",
        f"AssertionError: {const_cur} != None : {message}"]}, kind="FAIL")

    steps = [
        q("Q1", "identifier", err_a),
        paste("P1", "paste_deploy", deploy),
        q("Q2", "identifier", branch),
        q("Q3", "superseded", str(port_new), evidence=[f"move it to {port_new}"]),
        paste("P2", "paste_lint", lint),
        q("Q4", "irrelevant_matches", timeouts[target_client][0],
          evidence=[f'connect_timeout = "{timeouts[target_client][0]}"']),
        q("Q5", "vague", timeouts[target_client][1],
          evidence=[f'response_timeout = "{timeouts[target_client][1]}"']),
        paste("P3", "paste_prof", prof),
        q("Q6", "oversized_read", q6_after),
        dict(q("Q7", "mid_task", str(const_val), mid_cmd=mid_cmd,
               evidence=[f"{req_id}: {th['const']} must be exactly {const_val}"]),
             mid_task={"command": mid_cmd, "output": mid_out}),
        q("Q8", "multi_fact", f"{host}:{db_port}/{db_name}", parts=[host, str(db_port), db_name],
          evidence=[f"PERF_DB_HOST={host}", f"pgcat listens on {db_port}", db_name]),
        q("Q9", "restart_multi_eviction", tag_new, restart=True),
        q("Q10", "vague", new_helper),
    ]
    import_messages.append({"role": "user", "content": steps[0]["text"]})
    const = th["const"]
    test_file = "\n".join([
        "import sys", "import unittest", "from pathlib import Path", "",
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))', "",
        f"from {P}.{cm} import {const}  # noqa: E402", "",
        "REQUIRED = None  # the value the change notice requires",
        f'REASON = f"{const} is {{{const}}}, contrary to change notice {req_id}"', "", "",
        f"class {cls_of(cm)}(unittest.TestCase):",
        "    maxDiff = None", "",
        f"    def {mid_case}(self):",
        f"        self.assertEqual({const}, REQUIRED, REASON)", ""])
    workspace = {
        f"tests/test_{cm}.py": test_file,
        f"src/{P}/{cm}.py": const_module_ho4(rnd, cm, const, const_cur),
    }
    h = {"id": f"ho4-h{index + 1}", "seed": seed, "project": P, "set": SET,
         "generator": GENERATOR, "import": import_messages, "steps": steps,
         "workspace": workspace,
         "shell": [{"match": f"unittest tests.test_{cm}", "output": mid_out}]}
    planted = {
        "theme": [P, th["svc"], th["db"], th["const"], *th["helper"], *th["modules"],
                  *th["clients"], th["column"]],
        "values": [err_a, *err_distractors, f"CT-{ticket}", branch, branch_docs, req_id,
                   req_other, host, tag_new, tag_old, q6_before, q6_after, mid_case, fail, f2,
                   timeouts[target_client][0], timeouts[target_client][1]],
        "numeric": [str(port_old), str(port_new), str(port_admin), str(db_port), str(const_val),
                    str(const_cur)],
    }
    return h, planted


def build_heldout4(index: int, seed: int) -> dict:
    return _build(index, seed)[0]


# ---------------------------------------------------------------- independence check

def _grams(h: dict) -> set:
    """Four-word runs of the wording: user turns, assistant summaries, questions and paste
    wrappers (not tool output or paste bodies), as in ``needle_gen_ho3``; inline code spans
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
    """Problems with the committed ho4 set; empty when it is independent and well formed."""
    import needle_gen as ng
    import needle_gen_ho2 as ng2
    import needle_gen_ho3 as ng3

    problems = []
    earlier = {}
    for folder in EARLIER_FOLDERS:
        for f in sorted((ROOT / "eval" / "needles" / folder).glob("*.json")):
            earlier[f.name] = f.read_text(encoding="utf-8")
    for folder in EARLIER_FOLDERS:
        if not any((ROOT / "eval" / "needles" / folder).glob("*.json")):
            problems.append(f"the {folder} needle files are missing")
    corpus = "\n".join(earlier.values()).casefold()
    earlier_answers = set()
    for text in earlier.values():
        for s in json.loads(text)["steps"]:
            if s["kind"] == "question":
                earlier_answers |= {s["answer"].casefold(), *(p.casefold() for p in s["parts"])}

    def word_in(tok: str, text: str) -> bool:
        return re.search(rf"(?<![a-z0-9_]){re.escape(tok.casefold())}(?![a-z0-9_])", text) is not None

    # 1. Seeds, themes and word banks.
    seeds = set(range(SEED_BASE, SEED_BASE + len(THEMES_HO4)))
    if seeds & EARLIER_SEEDS:
        problems.append("seed overlap")
    ours = _theme_tokens(THEMES_HO4)
    theirs = (_theme_tokens(ng.THEMES) | _theme_tokens(ng.THEMES_HO) | _theme_tokens(ng2.THEMES_HO2)
              | _theme_tokens(ng3.THEMES_HO3))
    if ours & theirs:
        problems.append(f"theme tokens shared: {sorted(ours & theirs)}")
    for bank, others in ((VERBS_HO4, ng.VERBS + ng.VERBS_HO + ng2.VERBS_HO2 + ng3.VERBS_HO3),
                         (NOUNS_HO4, ng.NOUNS + ng.NOUNS_HO + ng2.NOUNS_HO2 + ng3.NOUNS_HO3),
                         (ADJS_HO4, ng.ADJS + ng.ADJS_HO + ng2.ADJS_HO2 + ng3.ADJS_HO3)):
        allbanks = set(ng.VERBS + ng.VERBS_HO + ng2.VERBS_HO2 + ng3.VERBS_HO3 + ng.NOUNS
                       + ng.NOUNS_HO + ng2.NOUNS_HO2 + ng3.NOUNS_HO3 + ng.ADJS + ng.ADJS_HO
                       + ng2.ADJS_HO2 + ng3.ADJS_HO3)
        if set(bank) & allbanks:
            problems.append(f"word bank shared: {sorted(set(bank) & allbanks)}")
    for tok in sorted(ours):
        if word_in(tok, corpus):
            problems.append(f"theme identifier {tok!r} occurs in an earlier needle file")
    for t in THEMES_HO4:
        for cv in t["const_values"]:
            if str(cv) in earlier_answers:
                problems.append(f"const value {cv} is an earlier answer")

    earlier_grams = set()
    for text in earlier.values():
        earlier_grams |= _grams(json.loads(text))
    dev_skeleton = _skeleton(json.loads(earlier["dev-h1.json"]))

    for i in range(len(THEMES_HO4)):
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
        for s in qs:
            if s["qid"] in ("Q4", "Q5", "Q9") and text.count(s["answer"]) != 1:
                problems.append(f"{h['id']} {s['qid']}: answer occurs {text.count(s['answer'])} times")
        if h["import"][-1] != {"role": "user", "content": qs[0]["text"]}:
            problems.append(f"{h['id']}: import does not end with Q1")
    # 6. Question wording: no question text shared verbatim with an earlier set.
    earlier_q = {s["text"].casefold() for t in earlier.values() for s in json.loads(t)["steps"]
                 if s["kind"] == "question"}
    for i in range(len(THEMES_HO4)):
        for s in _build(i, SEED_BASE + i)[0]["steps"]:
            if s["kind"] == "question" and s["text"].casefold() in earlier_q:
                problems.append(f"ho4-h{i + 1} {s['qid']}: question text equals an earlier one")
    # 7. The ho4 coding tasks' identifiers: not in an earlier task module or needle file.
    task_srcs = [p for p in (ROOT / "eval" / "tasks").glob("*.py")
                 if p.stem.startswith(("dev_", "ho_", "ho2_", "ho3_"))]
    task_corpus = corpus + "\n".join(p.read_text(encoding="utf-8") for p in task_srcs).casefold()
    for tok in TASK_IDENTIFIERS:
        if word_in(tok, task_corpus):
            problems.append(f"task identifier {tok!r} occurs in an earlier task or needle file")
    for tok in list(ng2.TASK_IDENTIFIERS) + list(ng3.TASK_IDENTIFIERS):
        if tok in TASK_IDENTIFIERS:
            problems.append(f"task identifier {tok!r} is an earlier task identifier")
    return problems


# Package, module, function, error, error-code and file names of eval/tasks/ho4_t1.py ..
# ho4_t5.py.
TASK_IDENTIFIERS = [
    "romanum", "NumeralError", "to_roman", "from_roman", "split_regnal", "century_of",
    "RN-70", "RN-71", "RN-72", "RN-73", "RN-74", "numeral_rules",
    "sizewise", "SizeError", "parse_size", "format_size", "rewrite_quota", "pad_label",
    "quota_style",
    "pinlint", "PinIssue", "scan_requirements", "PN1", "PN2", "PN3", "PN4", "PN5",
    "wheel_tag", "pin_rules",
    "tenpin", "GameError", "frame_scores", "score_game", "handicap", "with_handicap",
    "parse_sheet", "lane_pair", "league_handbook",
    "jpatch", "PatchError", "resolve_pointer", "apply_patch", "make_patch", "json_kind",
    "patch_rules",
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
        print(f"ho4 independence check: {'ok' if not problems else f'{len(problems)} problems'}")
        return 1 if problems else 0
    out = a.out or OUT
    out.mkdir(parents=True, exist_ok=True)
    for i in range(len(THEMES_HO4)):
        h = build_heldout4(i, SEED_BASE + i)
        (out / f"{h['id']}.json").write_text(json.dumps(h, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8", newline="\n")
        chars = sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or ""))
                    for m in h["import"])
        print(f"{h['id']}: {len(h['import'])} import messages, ~{chars} chars, {len(h['steps'])} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
