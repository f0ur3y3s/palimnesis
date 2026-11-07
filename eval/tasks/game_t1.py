"""game-t1: TINY TANK WAR, a single-file canvas game from one prompt (user's test, 2026-11-06).

One turn, the user's prompt verbatim, in an empty workspace. Unlike the other tasks there is
no stub and no unit-test suite to grow: the hidden check reads ``index.html`` and

- statically: the title, a canvas, WASD, mouse aim, click to fire, R to restart, three
  lives, a best score in ``localStorage`` (``test_f_*``);
- syntax: every inline script passes ``node --check``;
- at run time: ``SMOKE`` (written to a temp file by the check) runs the page's scripts in Node against a stub canvas,
  DOM, ``localStorage`` and Web Audio, fires load events, then drives 900 animation frames
  with WASD, mouse movement, clicks, Space and Enter, and R, and fails on any exception, on
  a game loop that never runs, or on frames that draw nothing;
- the constraint ``C1`` (``test_c1_*``): one self-contained file, with no script, style,
  image or font loaded from anywhere, no network API, and no other asset files.

How good the game is to play is not scored. The workspace's ``index.html`` is kept with the
run's records for a person to open.
"""

from __future__ import annotations

import random

ID = "game-t1"
SET = "development"
TITLE = "TINY TANK WAR: a single-file HTML5 canvas game"
RESTART_BEFORE = None
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "everything in one index.html: no external files or network",
}

TURNS = [
    "Build a complete single-file HTML5 canvas game in index.html called TINY TANK WAR. "
    "Requirements: player controls a tank with WASD; mouse aims turret; click fires shells; "
    "destructible walls; enemy tanks with basic AI; explosions and screen shake; health bars; "
    "increasingly difficult levels; score; three lives; R restarts; best score stored in "
    "localStorage. Everything in one index.html, no external files or network. Make it "
    "polished and arcade-like.",
]


def files(rnd: random.Random) -> dict[str, str]:
    return {}


SMOKE = r'''// Runs the inline scripts of index.html in Node against stubs and drives the game.
"use strict";
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc\s*=)([^>]*)>([\s\S]*?)<\/script>/gi)]
  .filter(m => !/type\s*=\s*["']?(?!text\/javascript|module|application\/javascript)[\w\/+-]+/i.test(m[1]))
  .map(m => m[2]);
if (!scripts.length) { console.error("no inline script"); process.exit(2); }

const noop = () => {};
let draws = 0;
// Anything: callable, constructible, every property is itself; numbers coerce to 0.
const any = new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => 0 : (typeof k === "symbol" || k === "then") ? undefined : any,
  apply: () => any, construct: () => any, set: () => true,
});
function context(canvas) {
  const grad = { addColorStop: noop };
  const t = {
    canvas, measureText: s => ({ width: String(s).length * 7, actualBoundingBoxAscent: 8, actualBoundingBoxDescent: 2 }),
    createLinearGradient: () => grad, createRadialGradient: () => grad, createConicGradient: () => grad,
    createPattern: () => ({ setTransform: noop }),
    getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(Math.max(0, (w | 0) * (h | 0) * 4)), width: w, height: h }),
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(Math.max(0, (w | 0) * (h | 0) * 4)), width: w, height: h }),
    isPointInPath: () => false, isPointInStroke: () => false, getLineDash: () => [],
    getTransform: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0, invertSelf() { return this; } }),
  };
  return new Proxy(t, {
    get: (o, k) => {
      if (k in o) return o[k];
      if (typeof k === "string" && /^(fill|stroke|draw|put|clear)/.test(k)) return () => { draws++; };
      if (typeof k === "string" && /^[a-z]/.test(k)) return noop;
      return undefined;
    },
    set: (o, k, v) => { o[k] = v; return true; },
  });
}
const listeners = new Map();
function on(type, fn) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn); }
const elements = new Map();
function element(tag, id) {
  const base = {
    tagName: String(tag).toUpperCase(), id: id || "", style: {}, dataset: {}, width: 960, height: 640,
    clientWidth: 960, clientHeight: 640, offsetWidth: 960, offsetHeight: 640, offsetLeft: 0, offsetTop: 0,
    children: [], childNodes: [], textContent: "", innerHTML: "", innerText: "", value: "",
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    addEventListener: on, removeEventListener: noop, dispatchEvent: () => true,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 960, bottom: 640, width: 960, height: 640, x: 0, y: 0 }),
    appendChild: c => c, removeChild: c => c, insertBefore: c => c, append: noop, prepend: noop, remove: noop,
    setAttribute: noop, getAttribute: () => null, hasAttribute: () => false, focus: noop, blur: noop,
    requestPointerLock: noop, requestFullscreen: () => Promise.resolve(), querySelector: () => element("div"),
    querySelectorAll: () => [], closest: () => null, contains: () => true, toDataURL: () => "data:,",
  };
  base.getContext = () => context(proxy);
  base.parentNode = base.parentElement = null;
  const proxy = new Proxy(base, {
    get: (o, k) => (k in o ? o[k] : (typeof k === "string" && /^on/.test(k)) ? null : undefined),
    set: (o, k, v) => { if (typeof k === "string" && /^on[a-z]+$/.test(k) && typeof v === "function") on(k.slice(2), v); o[k] = v; return true; },
  });
  return proxy;
}
function byId(id) { if (!elements.has(id)) elements.set(id, element(/canvas|cv|game|screen/i.test(id) ? "canvas" : "div", id)); return elements.get(id); }
const body = element("body");
const store = new Map();
const frames = [];
const document = {
  body, documentElement: element("html"), head: element("head"), hidden: false, visibilityState: "visible",
  readyState: "complete", fonts: { ready: Promise.resolve(), load: () => Promise.resolve([]), add: noop },
  getElementById: byId, querySelector: s => (/canvas/i.test(s) ? byId("canvas") : s.startsWith("#") ? byId(s.slice(1)) : element("div")),
  querySelectorAll: s => (/canvas/i.test(s) ? [byId("canvas")] : []), getElementsByTagName: t => (/canvas/i.test(t) ? [byId("canvas")] : []),
  createElement: t => element(t), createTextNode: () => element("text"), addEventListener: on, removeEventListener: noop,
  exitPointerLock: noop, pointerLockElement: null, hasFocus: () => true, activeElement: body,
};
const g = {
  document, console, Math, Date, JSON, Number, String, Boolean, Array, Object, Symbol, Map, Set, WeakMap, WeakSet,
  Promise, Error, TypeError, RangeError, parseInt, parseFloat, isNaN, isFinite, Float32Array, Float64Array,
  Uint8Array, Uint8ClampedArray, Int32Array, Uint16Array, Int16Array, ArrayBuffer, DataView, Proxy, Reflect, BigInt,
  innerWidth: 1280, innerHeight: 720, devicePixelRatio: 1, screen: { width: 1280, height: 720 },
  addEventListener: on, removeEventListener: noop, dispatchEvent: () => true,
  localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(String(k), String(v)); },
                  removeItem: k => store.delete(k), clear: () => store.clear(), key: i => [...store.keys()][i] ?? null,
                  get length() { return store.size; } },
  requestAnimationFrame: cb => { frames.push(cb); return frames.length; }, cancelAnimationFrame: noop,
  setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask, performance: { now: () => now },
  AudioContext: any, webkitAudioContext: any, Audio: any, Image: function () { return element("img"); },
  Path2D: function () { return new Proxy({}, { get: () => noop }); }, OffscreenCanvas: function () { return element("canvas"); },
  matchMedia: () => ({ matches: false, addEventListener: noop, addListener: noop }), navigator: { userAgent: "node", getGamepads: () => [] },
  location: { reload: noop, href: "file:///index.html", search: "" }, alert: noop, confirm: () => true, prompt: () => null,
  getComputedStyle: () => new Proxy({}, { get: () => "" }), ResizeObserver: function () { return { observe: noop, disconnect: noop }; },
  FontFace: function () { return { load: () => Promise.resolve() }; },
};
let now = 0;
g.window = g; g.self = g; g.globalThis = g; g.top = g; g.parent = g;
const ctx = vm.createContext(g);
let failed = null;
process.on("uncaughtException", e => { failed = e; });
process.on("unhandledRejection", e => { failed = e; });
try {
  for (const s of scripts) vm.runInContext(s, ctx, { filename: "index.html" });
} catch (e) { console.error("script error at load:", e && e.stack || e); process.exit(1); }

function fire(type, extra) {
  const ev = Object.assign({ type, preventDefault: noop, stopPropagation: noop, stopImmediatePropagation: noop,
    target: byId("canvas"), currentTarget: byId("canvas"), button: 0, buttons: 1, clientX: 480, clientY: 320,
    offsetX: 480, offsetY: 320, pageX: 480, pageY: 320, movementX: 0, movementY: 0, repeat: false,
    shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, timeStamp: now }, extra);
  for (const fn of listeners.get(type) || []) fn.call(g, ev);
}
const key = (k, code, kc) => ({ key: k, code, keyCode: kc, which: kc });
const KEYS = { w: key("w", "KeyW", 87), a: key("a", "KeyA", 65), s: key("s", "KeyS", 83), d: key("d", "KeyD", 68),
               r: key("r", "KeyR", 82), space: key(" ", "Space", 32), enter: key("Enter", "Enter", 13) };
let ran = 0;
(async () => {
  try {
    for (const t of ["DOMContentLoaded", "load", "resize", "focus"]) fire(t, {});
    await new Promise(r => setTimeout(r, 50));
    for (let i = 0; i < 900 && !failed; i++) {
      now += 1000 / 60;
      const plan = i % 120;
      if (plan === 0) { fire("keydown", KEYS.enter); fire("keyup", KEYS.enter); fire("keydown", KEYS.space); fire("keyup", KEYS.space); }
      if (plan === 5) fire("keydown", KEYS.w);
      if (plan === 30) { fire("keyup", KEYS.w); fire("keydown", KEYS.d); }
      if (plan === 50) { fire("keyup", KEYS.d); fire("keydown", KEYS.s); fire("keydown", KEYS.a); }
      if (plan === 70) { fire("keyup", KEYS.s); fire("keyup", KEYS.a); }
      const x = 480 + 300 * Math.cos(i / 20), y = 320 + 200 * Math.sin(i / 20);
      fire("mousemove", { clientX: x, clientY: y, offsetX: x, offsetY: y, pageX: x, pageY: y });
      fire("pointermove", { clientX: x, clientY: y, offsetX: x, offsetY: y, pageX: x, pageY: y });
      if (i % 9 === 0) { for (const t of ["pointerdown", "mousedown"]) fire(t, {}); for (const t of ["pointerup", "mouseup", "click"]) fire(t, {}); }
      if (i === 600) { fire("keydown", KEYS.r); fire("keyup", KEYS.r); }
      const due = frames.splice(0);
      for (const cb of due) { cb(now); ran++; }
      await new Promise(r => setImmediate(r));
    }
  } catch (e) { failed = e; }
  if (failed) { console.error("runtime error:", failed && failed.stack || failed); process.exit(1); }
  if (ran < 300) { console.error(`game loop ran ${ran} animation frames of 900`); process.exit(3); }
  if (draws === 0) { console.error("nothing was drawn"); process.exit(4); }
  console.log(`ok: ${ran} frames, ${draws} draw calls, localStorage keys ${[...store.keys()].join(",")}`);
  process.exit(0);
})();
'''

HIDDEN = {
    "_check/test_hidden.py": "SMOKE = " + repr(SMOKE) + "\n" + r'''import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path.cwd()
PAGE = ROOT / "index.html"
HTML = PAGE.read_text(encoding="utf-8", errors="replace") if PAGE.exists() else ""
SCRIPTS = re.findall(r"<script(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)</script>", HTML, re.I)
CODE = "\n".join(SCRIPTS)
NODE = shutil.which("node")


def keyed(letter):
    """The key appears as a key name or code a handler could compare with."""
    lo, up, kc = letter.lower(), letter.upper(), ord(letter.upper())
    return re.search(r"""['"`](?:Key)?[%s%s]['"`]|\bKey%s\b|\bkeys?\s*\.\s*[%s%s]\b|keyCode\s*===?\s*%d\b|\b%d\s*:"""
                     % (lo, up, up, lo, up, kc, kc), CODE)


class Game(unittest.TestCase):
    def test_f_page_exists(self):
        self.assertTrue(PAGE.exists(), "no index.html")
        self.assertGreater(len(HTML), 2000, "index.html is too small to be the game")

    def test_f_title(self):
        self.assertRegex(HTML, re.compile(r"tiny\s+tank\s+war", re.I))

    def test_f_canvas(self):
        self.assertTrue(re.search(r"<canvas\b", HTML, re.I) or re.search(r"createElement\(\s*['\"]canvas", CODE))
        self.assertTrue(re.search(r"getContext\(\s*['\"]2d", CODE), "no 2d context")

    def test_f_wasd_mouse_click(self):
        for letter in "WASD":
            self.assertTrue(keyed(letter), f"no handling of {letter}")
        self.assertRegex(CODE, r"mousemove|pointermove")
        self.assertRegex(CODE, r"mousedown|pointerdown|['\"]click['\"]")

    def test_f_restart_with_r(self):
        self.assertTrue(keyed("R"), "no handling of R")

    def test_f_lives_and_best_score(self):
        self.assertRegex(CODE, re.compile(r"lives?\w*\s*[:=]\s*3\b|LIVES\s*[:=]\s*3\b", re.I))
        self.assertRegex(CODE, r"localStorage\s*\.\s*setItem|localStorage\s*\[")
        self.assertRegex(CODE, r"localStorage\s*\.\s*getItem|localStorage\s*\[")

    def test_f_scripts_parse(self):
        self.assertTrue(SCRIPTS, "no inline script")
        self.assertIsNotNone(NODE, "node is not on PATH")
        with tempfile.TemporaryDirectory() as d:
            for i, text in enumerate(SCRIPTS):
                p = Path(d) / f"s{i}.js"
                p.write_text(text, encoding="utf-8")
                r = subprocess.run([NODE, "--check", str(p)], capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_f_runs_900_frames(self):
        self.assertIsNotNone(NODE, "node is not on PATH")
        with tempfile.TemporaryDirectory() as d:
            smoke = Path(d) / "smoke.js"
            smoke.write_text(SMOKE, encoding="utf-8")
            r = subprocess.run([NODE, str(smoke), str(PAGE)], capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-1200:])

    def test_c1_no_network_or_external_files(self):
        self.assertTrue(PAGE.exists())
        self.assertIsNone(re.search(r"<script[^>]*\bsrc\s*=", HTML, re.I), "loads a script file")
        self.assertIsNone(re.search(r"<link[^>]*\bhref\s*=\s*['\"](?!data:|#)", HTML, re.I), "links a file")
        self.assertIsNone(re.search(r"url\(\s*['\"]?(?!data:|#)[\w./-]", HTML, re.I), "css url() to a file")
        self.assertIsNone(re.search(r"\.src\s*=\s*['\"`](?!data:)", CODE), "loads an image or sound file")
        self.assertIsNone(re.search(r"\bfetch\s*\(|XMLHttpRequest|new\s+WebSocket|EventSource|\bimport\s*\(|navigator\.sendBeacon", CODE),
                          "uses the network")

    def test_c1_no_other_asset_files(self):
        assets = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                  if p.is_file() and p.suffix.lower() in {".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                                                          ".wav", ".mp3", ".ogg", ".woff", ".woff2", ".ttf", ".json"}
                  and not p.relative_to(ROOT).as_posix().startswith(("_check/", ".pi/"))]
        self.assertEqual(assets, [], "assets outside index.html")
''',
}

REFERENCE = {"index.html": r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TINY TANK WAR</title>
<style>
  html, body { margin: 0; height: 100%; background: #111; display: grid; place-items: center; }
  canvas { background: #2b2b22; image-rendering: pixelated; cursor: crosshair; }
</style>
</head>
<body>
<canvas id="game" width="960" height="640"></canvas>
<script>
"use strict";
// Reference for the hidden check (game-t1): small, but every requirement is present.
const canvas = document.getElementById("game");
const ctx = canvas.getContext("2d");
const W = canvas.width, H = canvas.height, TILE = 40;
const BEST_KEY = "tinyTankWar.best";
const keys = {};
const mouse = { x: W / 2, y: H / 2, down: false };
let state, shake = 0, last = 0;

function newGame() {
  state = { level: 1, score: 0, lives: 3, best: Number(localStorage.getItem(BEST_KEY) || 0),
            shells: [], blasts: [], over: false };
  startLevel();
}
function startLevel() {
  const s = state;
  s.player = { x: 80, y: H / 2, a: 0, turret: 0, hp: 100, cool: 0 };
  s.walls = [];
  for (let i = 0; i < 18 + s.level * 2; i++) {
    const x = 160 + Math.floor(Math.random() * 18) * TILE, y = Math.floor(Math.random() * 16) * TILE;
    s.walls.push({ x, y, hp: 3 });
  }
  s.enemies = [];
  for (let i = 0; i < 2 + s.level; i++) {
    s.enemies.push({ x: W - 80 - Math.random() * 200, y: 60 + Math.random() * (H - 120), a: Math.PI,
                     hp: 40 + s.level * 10, max: 40 + s.level * 10, cool: 60 + Math.random() * 60 });
  }
}
function hitsWall(x, y, r) {
  return state.walls.find(w => x + r > w.x && x - r < w.x + TILE && y + r > w.y && y - r < w.y + TILE);
}
function fire(from, angle, enemy) {
  state.shells.push({ x: from.x + Math.cos(angle) * 22, y: from.y + Math.sin(angle) * 22,
                      vx: Math.cos(angle) * 7, vy: Math.sin(angle) * 7, enemy, life: 120 });
}
function boom(x, y, size) {
  state.blasts.push({ x, y, r: 4, max: size, t: 0 });
  shake = Math.min(18, shake + size / 4);
}
function update() {
  const s = state;
  if (s.over) return;
  const p = s.player;
  const speed = 2.4;
  let dx = (keys.KeyD ? 1 : 0) - (keys.KeyA ? 1 : 0), dy = (keys.KeyS ? 1 : 0) - (keys.KeyW ? 1 : 0);
  if (dx || dy) {
    p.a = Math.atan2(dy, dx);
    const nx = p.x + Math.cos(p.a) * speed, ny = p.y + Math.sin(p.a) * speed;
    if (!hitsWall(nx, ny, 14) && nx > 14 && nx < W - 14 && ny > 14 && ny < H - 14) { p.x = nx; p.y = ny; }
  }
  p.turret = Math.atan2(mouse.y - p.y, mouse.x - p.x);
  if (p.cool > 0) p.cool--;
  if (mouse.down && p.cool === 0) { fire(p, p.turret, false); p.cool = 18; }
  for (const e of s.enemies) {
    const toP = Math.atan2(p.y - e.y, p.x - e.x);
    e.a += Math.sign(toP - e.a) * 0.03;
    const nx = e.x + Math.cos(e.a) * (0.8 + s.level * 0.15), ny = e.y + Math.sin(e.a) * (0.8 + s.level * 0.15);
    if (!hitsWall(nx, ny, 14) && nx > 14 && nx < W - 14 && ny > 14 && ny < H - 14) { e.x = nx; e.y = ny; }
    if (--e.cool <= 0) { fire(e, toP + (Math.random() - 0.5) * 0.3, true); e.cool = Math.max(30, 110 - s.level * 10); }
  }
  for (const sh of s.shells) {
    sh.x += sh.vx; sh.y += sh.vy; sh.life--;
    const wall = hitsWall(sh.x, sh.y, 3);
    if (wall) { wall.hp--; sh.life = 0; boom(sh.x, sh.y, 14); if (wall.hp <= 0) s.walls.splice(s.walls.indexOf(wall), 1); }
    const targets = sh.enemy ? [p] : s.enemies;
    for (const t of targets) {
      if (sh.life > 0 && Math.hypot(t.x - sh.x, t.y - sh.y) < 16) {
        sh.life = 0; t.hp -= 20; boom(sh.x, sh.y, 22);
        if (t !== p && t.hp <= 0) { s.score += 100 * s.level; boom(t.x, t.y, 50); }
      }
    }
  }
  s.shells = s.shells.filter(sh => sh.life > 0 && sh.x > 0 && sh.x < W && sh.y > 0 && sh.y < H);
  s.enemies = s.enemies.filter(e => e.hp > 0);
  for (const b of s.blasts) { b.t++; b.r += (b.max - b.r) * 0.25; }
  s.blasts = s.blasts.filter(b => b.t < 24);
  if (p.hp <= 0) {
    boom(p.x, p.y, 60);
    s.lives--;
    if (s.lives <= 0) { s.over = true; saveBest(); } else { p.hp = 100; p.x = 80; p.y = H / 2; }
  }
  if (!s.enemies.length) { s.level++; s.score += 500; startLevel(); }
  if (s.score > s.best) { s.best = s.score; saveBest(); }
  shake *= 0.85;
}
function saveBest() { localStorage.setItem(BEST_KEY, String(state.best)); }
function tank(t, body, gun, turret) {
  ctx.save(); ctx.translate(t.x, t.y);
  ctx.save(); ctx.rotate(t.a); ctx.fillStyle = body; ctx.fillRect(-16, -12, 32, 24); ctx.restore();
  ctx.rotate(turret); ctx.fillStyle = gun; ctx.fillRect(0, -3, 24, 6); ctx.beginPath(); ctx.arc(0, 0, 8, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}
function bar(x, y, frac, color) {
  ctx.fillStyle = "#000"; ctx.fillRect(x - 18, y, 36, 5);
  ctx.fillStyle = color; ctx.fillRect(x - 18, y, 36 * Math.max(0, frac), 5);
}
function draw() {
  const s = state;
  ctx.save();
  ctx.translate((Math.random() - 0.5) * shake, (Math.random() - 0.5) * shake);
  ctx.fillStyle = "#2b2b22"; ctx.fillRect(-20, -20, W + 40, H + 40);
  for (const w of s.walls) { ctx.fillStyle = ["#5a3b22", "#7a5230", "#9c6b3d"][w.hp - 1] || "#9c6b3d"; ctx.fillRect(w.x, w.y, TILE - 2, TILE - 2); }
  tank(s.player, "#4caf50", "#9ccc65", s.player.turret);
  bar(s.player.x, s.player.y - 26, s.player.hp / 100, "#7cfc00");
  for (const e of s.enemies) {
    tank(e, "#c0392b", "#e57373", Math.atan2(s.player.y - e.y, s.player.x - e.x));
    bar(e.x, e.y - 26, e.hp / e.max, "#ff5252");
  }
  ctx.fillStyle = "#ffeb3b";
  for (const sh of s.shells) { ctx.beginPath(); ctx.arc(sh.x, sh.y, 3, 0, Math.PI * 2); ctx.fill(); }
  for (const b of s.blasts) {
    ctx.fillStyle = `rgba(255,${120 + b.t * 5},0,${1 - b.t / 24})`;
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
  ctx.fillStyle = "#fff"; ctx.font = "bold 18px monospace";
  ctx.fillText(`TINY TANK WAR   LEVEL ${s.level}   SCORE ${s.score}   BEST ${s.best}   LIVES ${s.lives}`, 16, 26);
  if (s.over) {
    ctx.fillStyle = "rgba(0,0,0,0.6)"; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#fff"; ctx.font = "bold 48px monospace"; ctx.fillText("GAME OVER", W / 2 - 130, H / 2);
    ctx.font = "20px monospace"; ctx.fillText("press R to restart", W / 2 - 105, H / 2 + 40);
  }
}
function frame(t) {
  if (t - last > 8) { update(); last = t; }
  draw();
  requestAnimationFrame(frame);
}
addEventListener("keydown", e => { keys[e.code] = true; if (e.code === "KeyR") newGame(); });
addEventListener("keyup", e => { keys[e.code] = false; });
canvas.addEventListener("mousemove", e => {
  const r = canvas.getBoundingClientRect();
  mouse.x = (e.clientX - r.left) * W / r.width; mouse.y = (e.clientY - r.top) * H / r.height;
});
canvas.addEventListener("mousedown", () => { mouse.down = true; });
addEventListener("mouseup", () => { mouse.down = false; });
newGame();
requestAnimationFrame(frame);
</script>
</body>
</html>
'''}
