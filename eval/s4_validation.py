"""Phase 8 S4: validate the needle instrument on retired heldout5 (plan §1.2, R70).

    python eval/s4_validation.py spec --root DIR --python PY --out SPEC.json [--samples 3]
        [--generators a,b] [--variants original,format] [--histories-per-generator N]
    python eval/s4_validation.py report ROOT [--json]

**Steps** (``make_spec``, for ``eval/headless.py plan --spec``): one per generator and
variant, original phrasing first. Each runs ``eval/needle_shape_probe.py`` on that
generator's heldout5 histories, writing ``ROOT/<variant>-<generator>.json`` (counts only).

**Expectation (plan §1.2):** under the original phrasing the probe flags generators a, c
and d and passes b; under the format rule (each question's stem plus the fixed sentence
for its inferred kind) the questions pass.

**Report** (``report``): passing questions over all questions per generator and variant,
from the JSON records, with ``unscored`` and ``missing attempts:`` lines that
``eval/run_ready.py`` reads (a question with no record is missing).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SET_DIR = ROOT / "eval" / "needles" / "heldout5"
GENERATORS = ("a", "b", "c", "d")
VARIANTS = ("original", "format")
UPSTREAM = "http://127.0.0.1:8080"


def histories() -> dict[str, list[Path]]:
    """{generator letter: heldout5 history files}, in name order."""
    out: dict[str, list[Path]] = {g: [] for g in GENERATORS}
    for f in sorted(SET_DIR.glob("*.json")):
        g = Path(json.loads(f.read_text(encoding="utf-8"))["generator"]).stem.rsplit("_", 1)[-1]
        out[g].append(f)
    return out


def make_spec(*, root: str, python: str, samples: int = 3, generators=GENERATORS,
              variants=VARIANTS, per_generator: int | None = None) -> dict:
    hs = histories()
    steps = []
    for v in variants:
        for g in generators:
            files = [f.relative_to(ROOT).as_posix() for f in hs[g]][:per_generator]
            steps.append({"name": f"{v} {g}", "argv": [
                python, "eval/needle_shape_probe.py", *files, "--upstream", UPSTREAM,
                "--samples", str(samples), "--variant", v, "--out", f"{root}/{v}-{g}.json"]})
    name = f"s4-probe-s{samples}" + ("" if per_generator is None else f"-h{per_generator}") \
        + ("" if tuple(generators) == GENERATORS else "-" + "".join(generators)) \
        + ("" if tuple(variants) == VARIANTS else "-" + "+".join(variants))
    return {"config": name, "steps": steps,
            "server": {"props": f"{UPSTREAM}/props", "n_ctx": 32768, "slots": 1,
                       "build": "Strata 0.1.58", "temperature": 1.0, "top_p": 0.95, "top_k": 20},
            "env": {}}


def report(root: Path, spec: dict | None = None) -> dict:
    """Counts per (variant, generator) from the step outputs; ``spec`` (the plan) names
    the expected outputs and their histories, so a missing record is reported."""
    rows, missing = {}, []
    for st in (spec or {}).get("steps", []):
        v, g = st["name"].split()
        argv = st["argv"]
        out = Path(argv[argv.index("--out") + 1])
        out = out if out.is_absolute() else ROOT / out
        files = [a for a in argv if a.endswith(".json") and "/needles/" in a]
        want = []
        for f in files:
            h = json.loads((ROOT / f).read_text(encoding="utf-8"))
            want += [s["id"] for s in h["steps"] if s.get("kind") == "question"]
        got = json.loads(out.read_text(encoding="utf-8"))["questions"] if out.exists() else {}
        missing += [f"{v}:{q}" for q in want if q not in got]
        ok = sum(1 for q in want if q in got and got[q]["passes"] == got[q]["samples"])
        rows[(v, g)] = {"pass": ok, "total": len(want),
                        "by_category": _by_category(got, want)}
    return {"rows": rows, "missing": missing}


def _by_category(got: dict, want: list[str]) -> dict:
    out: dict[str, list[int]] = {}
    for q in want:
        if q in got:
            c = out.setdefault(got[q]["category"], [0, 0])
            c[0] += got[q]["passes"] == got[q]["samples"]
            c[1] += 1
    return out


def format_report(rep: dict) -> list[str]:
    out = ["S4 needle instrument on retired heldout5 (plan §1.2, R70)", "",
           f"{'variant':9} {'generator':9} {'pass':>9}"]
    for (v, g), r in rep["rows"].items():
        out.append(f"{v:9} {g:9} {r['pass']:>4}/{r['total']:<4}")
    out.append("")
    for (v, g), r in rep["rows"].items():
        cats = ", ".join(f"{c} {a}/{b}" for c, (a, b) in sorted(r["by_category"].items()))
        out.append(f"{v} {g}: {cats or 'none'}")
    out.append("unscored none")  # every probed question has a count (run_ready.py reads this form)
    out.append(f"missing attempts: {', '.join(rep['missing']) or 'none'}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("spec")
    s.add_argument("--root", required=True)
    s.add_argument("--python", default=sys.executable)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--samples", type=int, default=3)
    s.add_argument("--generators", default=",".join(GENERATORS))
    s.add_argument("--variants", default=",".join(VARIANTS))
    s.add_argument("--histories-per-generator", type=int)
    r = sub.add_parser("report")
    r.add_argument("run_dir", type=Path, help="the headless run directory (its plan.json names the outputs)")
    r.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "spec":
        spec = make_spec(root=a.root, python=a.python, samples=a.samples,
                         generators=tuple(a.generators.split(",")),
                         variants=tuple(a.variants.split(",")),
                         per_generator=a.histories_per_generator)
        a.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
        for i, st in enumerate(spec["steps"], 1):
            print(f"{i:3}: {st['name']}")
        print(f"{len(spec['steps'])} steps -> {a.out}")
        return 0
    plan = json.loads((a.run_dir / "plan.json").read_text(encoding="utf-8"))
    rep = report(a.run_dir, plan)
    if a.json:
        print(json.dumps({"rows": {f"{v} {g}": r for (v, g), r in rep["rows"].items()},
                          "missing": rep["missing"]}, indent=1))
    else:
        print("\n".join(format_report(rep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
