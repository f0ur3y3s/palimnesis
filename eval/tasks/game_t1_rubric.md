# TINY TANK WAR rubric (game-t1)

How to score one `index.html` from a `game-t1` run. The hidden check (`game_t1.py`) only shows that the features are wired up and that the page runs 900 frames without an error. This rubric scores what a player gets.

## Rules

1. **Blind.** Copy both games of a pair to `A.html` and `B.html` in a random order, and keep the key apart. Score both before opening the key.
2. **Same setup.** Use one browser, a 1280×800 window, with sound on. Play each game for 5 minutes, or until it ends. Then press R and play 1 more minute.
3. **As written first.** Score the page exactly as the run left it.
4. **Then patched, if it does not run.** If the page fails to start or crashes, make the smallest change that lets it run: define a missing name, or call an existing setup function. Mark every change `/* PATCH */`, list them, then score again. Never add features or fix behaviour that runs but is wrong. Report both scores. The as-written score is the result, and the patched score shows what the model built.
5. **Evidence.** For every item below 2, write one line saying what you saw.

## Gate: does it run?

| Score | Meaning |
|---|---|
| 2 | Opens, starts, and plays with no console errors. |
| 1 | Plays, but console errors appear, or it crashes after 1 minute or more. |
| 0 | Blank page, or a crash within the first minute. |

A gate of 0 makes the as-written total 0. Then score the patched copy.

## Requirements (0–2 each, 24 points)

Score each requirement the prompt names: 2 means present and works as a player would expect, 1 means present but broken or awkward, 0 means missing.

| # | Requirement | 2 means |
|---|---|---|
| R1 | WASD moves the tank | The tank moves in all four directions and stops at walls. |
| R2 | The mouse aims the turret | The turret follows the cursor everywhere on the playfield, including after the window resizes. |
| R3 | Click fires shells | Each click fires a visible shell from the barrel along the aim. Holding the button or clicking fast is rate-limited. |
| R4 | Destructible walls | Shells damage walls and break them, with visible damage stages or debris. Other walls block movement and shells. |
| R5 | Enemy tanks with basic AI | Enemies move with purpose (approach, aim, fire, avoid walls) and do not freeze or pass through walls. |
| R6 | Explosions | Hits and kills show an explosion that grows and fades. |
| R7 | Screen shake | Big hits shake the screen briefly, and the shake settles. |
| R8 | Health bars | The player and every enemy show health that drops on hits. |
| R9 | Levels get harder | Clearing a level starts the next one, and it is noticeably harder (more, faster or tougher enemies, or different maps). |
| R10 | Score | The score rises for kills and is always visible. |
| R11 | Three lives and R restarts | Three lives are shown and lost one at a time. Game over appears after the third. R restarts a fresh game at any time. |
| R12 | Best score kept | The best score shows on screen and survives a page reload (`localStorage`). |

## Constraint (pass or fail)

**C1: one self-contained file.** Everything is in `index.html`: no other files, no network requests (check the browser's network panel), no fonts, images or sounds loaded from anywhere. A fail is reported beside the score, and halves the as-written total.

## Polish and arcade feel (0–3 each, 18 points)

| # | Quality | 3 means | 1 means |
|---|---|---|---|
| P1 | Game feel | Movement and aiming are responsive. Shots have recoil or kick. Hits feel weighty. | Movement is floaty or sticky, and shots feel weightless. |
| P2 | Visual clarity | The player, the enemies, shells, walls and pickups can be told apart at a glance. Nothing important is hidden under the HUD. | Things blend together, text overlaps, or the HUD covers play. |
| P3 | Arcade presentation | A title screen, a level banner, a game-over screen with score and best, and a consistent style. | Plain text on a blank canvas. |
| P4 | Difficulty curve | Level 1 can be cleared by a new player. Later levels ramp steadily. | Unwinnable at the start, or no change between levels. |
| P5 | Feedback | Damage, kills, low health, level clear and a new best score are each signalled by sound, flash or text. | Events pass without any signal. |
| P6 | Stability | 5 minutes of play show no slowdown, stuck state, runaway particles or broken restart. | Visible slowdown, or a state the player cannot leave. |

A score of 2 is between the 3 and 1 descriptions, and 0 means the quality is absent.

## Totals

- **As written:** the gate (0–2), then R1–R12 (24) plus P1–P6 (18), out of 42. The total is 0 if the gate is 0, and halved if C1 fails.
- **Patched:** the same items scored on the patched copy, reported with the list of patches. The patched total never replaces the as-written total.

Report a pair like this:

| | Arm | Gate | Requirements /24 | Polish /18 | C1 | Total /42 | Patches |
|---|---|---|---|---|---|---|---|
| A | (from the key) | | | | | | |
| B | (from the key) | | | | | | |

Also note, from the run record: calls, compactions, wall time, whether the turn ended or was killed, and the hidden-check result.
