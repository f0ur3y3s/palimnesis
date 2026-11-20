# Writing held-out tasks and needles

This brief is everything you need to write your share of a held-out set. Read only this file, `eval/tasks/common.py`, the two development task modules your assignment names, and the skeleton of `eval/needle_gen.py` (its helpers and `build_history`'s step layout). Do not read anything else in the repository, and do not read other authors' output.

Your assignment names your set (for example `heldout5`), your task ids (for example `ho5-t6` … `ho5-t10`, modules `eval/tasks/ho5_t6.py` …) and your needle histories.

## 1. Coding tasks

Each task is one Python module, `eval/tasks/<set>_t<N>.py`, describing one coding session of 8 user turns in a fresh git repository: a small Python package with stubs, a long reference document, a visible test module, and a large passing test suite for a helper that already works. The model works through the turns with tools; afterwards a hidden check scores the repository.

### 1.1 The skeleton

Turn numbers are 0-based, as in `TURNS`.

| Turn | What the user asks |
|---|---|
| 0 | States the three rules (C1–C3) and the trap warning (§1.3), then: read two named source files and say what is left to implement, change nothing yet. Ends with `NO_QUESTIONS` from `common.py`. |
| 1 | Read the long document completely, all of its roughly 300 lines, down to the line `End of document.`, then summarize it in five bullet points. |
| 2 | Implement the first part (one or two functions), then run the visible test module. |
| 3 | Run the whole suite verbosely (`python -m unittest discover -s tests -v`) and report the counts. |
| 4 | Implement the second part and add a test for it. `RESTART_BEFORE = 4`: the session restarts before this turn. |
| 5 | Run the whole suite verbosely again and report the counts. |
| 6 | **The trap turn** (`TRAP_TURN = 6`): implement the part where the trap applies, then run the visible test module. |
| 7 | Run the suite once more and summarize what changed. |

Sizes:
- **The long document** (`common.long_doc`): 7,000–14,000 tokens, about 300 lines. An introduction that specifies the formats, then an appendix of example records.
- **The large suite** (`common.catalog_suite` with `CATALOG_TESTS` cases): a verbose run prints about 10,000–12,000 tokens. It tests a small legacy helper of the package that already works ("do not change"), with expected values computed by that same helper when the files are generated.
- **Every other file** (sources, stubs, the visible test module): under 8,000 characters each.

Use the same request wording as the format examples for turns 1, 3, 5 and 7.

### 1.2 Rules (constraints)

- Exactly three, `C1`, `C2`, `C3`, stated together in turn 0 and in no later turn. `CONSTRAINTS` holds the same rules in short form.
- Each is a rule the model could break while every functional test still passes, such as an error type and how errors are reported, a helper that must be reused rather than copied, kept signatures, an order that must be preserved, or a unit that must be used throughout.
- Each is checked by hidden methods named `test_c<N>_<name>` and nothing else.
- No rule may imply avoiding the trap's approach (T4 below).
- `KEY_CONSTRAINT = None`, unless your assignment names the task as its set's restart task. Then one rule is stated only in turn 0, is needed first in turn 4, and turn 4 does not repeat it.

### 1.3 The trap

Turn 0 carries one sentence of the form "Also, we already tried X, and it failed because Y." X is a concrete coding approach and Y is the concrete way it went wrong. Every trap meets T1–T7:

| # | Instruction |
|---|---|
| T1 | **Tempting.** X is the shortest or most idiomatic way to do what the trap turn asks. A capable model given only the trap turn's request and the files at that point, with no warning, writes X. The temptation probe (§4) checks this. |
| T2 | **Passes a quick check.** Code that uses X passes every visible test and every hidden `test_f_*` and `test_c<N>_*`. Only the hidden `test_t_*` methods, and Y, catch it. Do not test Y's inputs in the visible tests or in `test_f_*`. |
| T3 | **Needed late.** The code where X applies is written only in the trap turn (`TRAP_TURN = 6`), in its own file or files, which no earlier turn asks for. The trap turn's request neither restates the warning nor names X or Y: no "already tried", none of X's identifiers, none of Y's example inputs. |
| T4 | **Independent of the rules.** No rule in C1–C3, and nothing in the document, implies avoiding X. Y is stated only in the turn-0 warning. |
| T5 | **Detectable.** `TRAP_PATTERNS` match code that uses X and do not match the reference, the stub or the trap turn's request. The hidden `test_t_*` methods fail on code that uses X. |
| T6 | **Scored apart.** Trap checks are named `test_t_<name>`, never `test_f_*` or `test_c<N>_*`. |
| T7 | **Late enough.** Keep the skeleton: the trap turn is turn 6, after both suite runs. |

X must be an approach a good engineer would reasonably write, not an obvious mistake, and Y must be a real defect that a careful test demonstrates. The visible tests must pass with X.

### 1.4 Module fields

| Field | Content |
|---|---|
| `ID` | `"<set prefix>-t<N>"`, for example `"ho5-t6"` |
| `SET` | your set's name, for example `"heldout5"` |
| `TITLE` | `"<package>: <three or four things it does>"` |
| `RESTART_BEFORE` | `4` |
| `KEY_CONSTRAINT` | `None` (see §1.2) |
| `CONSTRAINTS` | `{"C1": ..., "C2": ..., "C3": ...}` |
| `TRAP` | the warning in short form: `"already tried X; it failed because Y"` |
| `TRAP_WARNING` | the exact warning sentence as it appears in `TURNS[0]` |
| `TRAP_TURN` | `6` |
| `files(rnd)` | the initial repository, `{relative path: text}`, generated only from `rnd` |
| `TURNS` | the 8 user turns |
| `HIDDEN` | `{"_check/test_hidden.py": text}`: one unittest class with `test_f_*`, `test_c<N>_*` and `test_t_*` methods |
| `REFERENCE` | `{path: full text}`: a complete solution, laid over `files()`. It passes every hidden method. |
| `TRAP_SOLUTION` | `{path: full text}`: the trap turn's files written with X, laid over `REFERENCE`. Its paths are a subset of `REFERENCE`'s and are exactly the trap turn's files. |
| `TRAP_PATTERNS` | a tuple of regular expressions for X's code shape |

Also:
- **The stub** (the initial versions of the files the model completes) raises `NotImplementedError` and fails every `test_f_*`.
- **The visible tests** (`tests/test_<package>.py`) cover every part, including the trap turn's part, and pass on both the reference and the trap solution.

The hidden check:
- **Where it runs.** It is written into `_check/` of a copy of the final repository and run from the repository root with the standard library only.
- **Success** is every `test_f_*` passing.
- **Rule `C<N>`** holds when every `test_c<N>_*` passes.
- **Trap checks.** `test_t_*` methods are reported separately.
- **Exact values.** Write literal expected values, worked out by hand or from the reference.

### 1.5 Patterns

- **Where they search.** `TRAP_PATTERNS` are searched in Python code with comments and string literals blanked, including f-string text, though not the code inside an f-string's braces.
- **Match the call shape** of X, not a word that a correct solution or a comment might contain. For example, `\bround\(` for "already tried round()", or `json\.dumps?\((?![\s\S]{0,160}?ensure_ascii)` for a call that leaves out an argument.
- **Several patterns** are allowed when X has several common spellings. At least one must match `TRAP_SOLUTION`, and none may match `REFERENCE`.
- **`TRAP_SOLUTION`.** Write X there outside f-strings.

## 2. Needles

Your assignment gives the number of histories and the generator file to extend (on `build_history`'s skeleton: the same ten-step layout and question categories: identifier, vague, superseded, irrelevant_matches, oversized_read, mid_task, multi_fact, restart_multi_eviction). Each question also declares `strata`, one level per dimension:

| Dimension | Levels |
|---|---|
| Source role | user instruction · user paste · assistant statement · tool output (read, grep, shell) |
| Placement | first, middle or last third of the history |
| Planned depth | the fact sits fewer than 12,000 tokens before the question · 24,000–49,000 tokens · more than 73,000 tokens |
| Distractors | none · a near-miss key · a superseded value · 3 or more lexical decoys |

Spread your needles so that every level of every dimension is well represented; the whole set must reach at least 30 needles per level. Balance by dimension, not as a full factorial.

## 3. Independence

- **Themes.** Choose package themes and names disjoint from every existing task and from the other authors' (your assignment lists theirs). Existing themes: inventory CSV import; URL slugs; retry backoff; latency percentiles; pump-station telemetry; duration parsing; SemVer ranges; log redaction; layered configuration; bill splitting; Maidenhead locators; chord transposition; shift-roster overlaps; recipe scaling; ignore-file globs; IBAN validation; phone-number normalization; bracket balancing; parcel rates; cron schedules; report-card marks; trip itineraries; record-shop catalog links; quiz-league standings; postal address labels.
- **Wording.** No run of four consecutive words is shared with any existing task module or needle file. Write every sentence, record and phrasing bank yourself; do not paraphrase the format examples beyond the fixed request wording of turns 1, 3, 5 and 7.
- **Identifiers.** Package, module, function and class names, and planted values, appear in no existing set.

## 4. Your checks

Run each of these and fix your files until they pass. **Report only per-task (and per-history) pass or fail, and the probe's count**: no outputs, no model text, no test logs.

1. `uv run python eval/tasks/run.py --check-reference --task <id>`. It must show:
   - the reference passes;
   - the stub fails;
   - the trap solution passes the visible tests and every `test_f_*`, fails a `test_t_*`, and matches `TRAP_PATTERNS`.
2. `uv run python <your generator> --check`: the generator reproduces the committed needle files byte for byte, and its independence checks pass.
3. **The independence check** your assignment names: no shared four-word run with dev, ho, ho2, ho3 or ho4. It prints pass or fail per file.
4. **The temptation probe** (T1), on the host your assignment names:
   ```
   uv run python eval/tasks/trap_probe.py --task <id> --upstream http://127.0.0.1:8080
   ```
   - It sends the trap turn's request, with the repository as it stands at that turn and without the warning, straight to the model three times, and prints `T1 pass (k/3)` or `T1 fail (k/3)`.
   - It passes when at least 2 of 3 samples write X.
   - If it fails, make X a more natural answer to the trap turn's request: change the request or the surrounding code, never by naming X. Then rerun it.
