"""The README's results figure, from the numbers published in R41 (``docs/results/phase3-acceptance.md``).

R41 is the held-out gate Phase 3 was accepted on: OpenCode 2.1.4 on the fresh set ``ho3``
at 32K on pythia, ``a4-d77`` (Palimnesis as ``serve`` ships it) against arm 1 (OpenCode's
native compaction). The values below are copied from R41-A and R41-B; this script only
draws them. Writes ``docs/images/results-light.svg`` and ``results-dark.svg``.

    uv run python eval/readme_figures.py
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"

# R41-B, one attempt per task and arm: (task, wall minutes, upstream calls, passed).
TASKS = ["ho3-t1", "ho3-t2", "ho3-t3", "ho3-t4", "ho3-t5"]
PALIMNESIS = {"ho3-t1": (42, 64, True), "ho3-t2": (36, 56, True), "ho3-t3": (61, 103, True),
              "ho3-t4": (33, 53, True), "ho3-t5": (60, 84, True)}
NATIVE = {"ho3-t1": (150, 207, False), "ho3-t2": (42, 67, True), "ho3-t3": (79, 161, True),
          "ho3-t4": (98, 175, True), "ho3-t5": (156, 249, True)}
# R41-A and R41-B totals.
HEADLINE = [
    ("5/5", "coding tasks passed", "native compaction: 4/5"),
    ("53%", "of the prompt tokens", "6.0M against native's 11.4M"),
    ("42%", "of the upstream calls", "360 against native's 859"),
    ("115/120", "needles recalled exactly", "95.8%, against an 85% bar"),
]

# The dataviz reference palette: categorical slots 1 (blue) and 2 (orange), validated
# for both modes (adjacent CVD ΔE 24.7 light / 26.8 dark), and its chart chrome.
THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "axis": "#c3c2b7", "s1": "#2a78d6", "s2": "#eb6834"},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
             "grid": "#2c2c2a", "axis": "#383835", "s1": "#3987e5", "s2": "#d95926"},
}
SERIES = [("Palimnesis (a4-d77)", "s1", PALIMNESIS), ("OpenCode native compaction", "s2", NATIVE)]

W = 880
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
BAR = 12      # bar thickness, under the 24px cap
GAP = 2       # surface gap between the two bars of a task
ROW = 44      # one task's band


def _bar(x0: float, y: float, length: float, fill: str, surface: str, title: str) -> str:
    """A horizontal bar: square at the baseline, 4px rounded data end."""
    r = min(4.0, length / 2, BAR / 2)
    x1 = x0 + length
    d = (f"M{x0:.1f},{y:.1f} H{x1 - r:.1f} Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f} "
         f"V{y + BAR - r:.1f} Q{x1:.1f},{y + BAR:.1f} {x1 - r:.1f},{y + BAR:.1f} H{x0:.1f} Z")
    return f'<path d="{d}" fill="{fill}"><title>{escape(title)}</title></path>'


def _panel(t: dict, x: float, y: float, w: float, title: str, idx: int, unit: str,
           ticks: list[int]) -> tuple[str, float]:
    label_w = 70
    plot_x, plot_w = x + label_w, w - label_w - 64
    top = y + 30
    vmax = ticks[-1]
    sx = plot_w / vmax
    parts = [f'<text x="{x}" y="{y + 12}" font-size="14" font-weight="600" fill="{t["ink"]}">'
             f'{escape(title)}</text>']
    height = ROW * len(TASKS)
    for v in ticks:
        gx = plot_x + v * sx
        parts.append(f'<line x1="{gx:.1f}" y1="{top - 4}" x2="{gx:.1f}" y2="{top + height - 6}" '
                     f'stroke="{t["grid"] if v else t["axis"]}" stroke-width="1"/>')
        parts.append(f'<text x="{gx:.1f}" y="{top + height + 10}" font-size="11" fill="{t["muted"]}" '
                     f'text-anchor="middle">{v}</text>')
    for row, task in enumerate(TASKS):
        ry = top + row * ROW
        parts.append(f'<text x="{x}" y="{ry + BAR + 5}" font-size="12" fill="{t["ink2"]}">{task}</text>')
        for k, (name, slot, data) in enumerate(SERIES):
            value, passed = data[task][idx], data[task][2]
            by = ry + k * (BAR + GAP)
            length = value * sx
            parts.append(_bar(plot_x, by, length, t[slot], t["surface"],
                              f"{name}, {task}: {value} {unit}" + ("" if passed else ", failed")))
            note = f"{value}" + ("" if passed else "  · failed")
            parts.append(f'<text x="{plot_x + length + 6:.1f}" y="{by + BAR - 2}" font-size="11" '
                         f'fill="{t["ink2"]}">{note}</text>')
    return "\n".join(parts), top + height + 14 - y


def figure(mode: str) -> str:
    t = THEMES[mode]
    out = []
    y = 28
    out.append(f'<text x="24" y="{y}" font-size="17" font-weight="600" fill="{t["ink"]}">'
               "Held-out coding and recall at a 32K context</text>")
    y += 20
    out.append(f'<text x="24" y="{y}" font-size="12" fill="{t["ink2"]}">OpenCode 2.1.4 on the '
               "fresh set ho3, Strata on one host, one attempt per task and arm (results R41)</text>")
    # Headline figures.
    y += 22
    col = (W - 48) / len(HEADLINE)
    for i, (big, what, sub) in enumerate(HEADLINE):
        cx = 24 + i * col
        out.append(f'<text x="{cx:.1f}" y="{y + 30}" font-size="30" font-weight="600" '
                   f'fill="{t["ink"]}">{escape(big)}</text>')
        out.append(f'<text x="{cx:.1f}" y="{y + 50}" font-size="12" fill="{t["ink2"]}">{escape(what)}</text>')
        out.append(f'<text x="{cx:.1f}" y="{y + 66}" font-size="11" fill="{t["muted"]}">{escape(sub)}</text>')
    y += 104
    # Legend: two series, both always named.
    lx = 24
    for name, slot, _ in SERIES:
        out.append(f'<rect x="{lx}" y="{y - 10}" width="12" height="12" rx="3" fill="{t[slot]}"/>')
        out.append(f'<text x="{lx + 18}" y="{y}" font-size="12" fill="{t["ink2"]}">{escape(name)}</text>')
        lx += 18 + 7.2 * len(name) + 28
    y += 18
    pw = (W - 48 - 32) / 2
    a, ha = _panel(t, 24, y, pw, "Wall time per task (minutes)", 0, "min", [0, 40, 80, 120, 160])
    b, hb = _panel(t, 24 + pw + 32, y, pw, "Upstream calls per task", 1, "calls",
                   [0, 50, 100, 150, 200, 250])
    out += [a, b]
    h = y + max(ha, hb) + 12
    body = "\n".join(out)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h:.0f}" '
            f'viewBox="0 0 {W} {h:.0f}" font-family="{FONT}" role="img" '
            f'aria-label="Held-out results R41: Palimnesis passed 5 of 5 coding tasks against 4 of 5 '
            f'for native compaction, using 53% of the prompt tokens and 42% of the upstream calls; '
            f'needles 115 of 120.">\n'
            f'<rect width="100%" height="100%" rx="8" fill="{t["surface"]}"/>\n{body}\n</svg>\n')


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for mode in THEMES:
        (OUT / f"results-{mode}.svg").write_text(figure(mode), encoding="utf-8", newline="\n")
        print(OUT / f"results-{mode}.svg")


if __name__ == "__main__":
    main()
