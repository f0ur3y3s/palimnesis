# ho4: the fourth held-out set

`ho4` is the held-out set for the Phase 7 evaluation on OpenCode 2.1.4 and Pi 1.5.0.

It was written by an author separate from the development work. The author read the
earlier sets and generators for format only. They did not read the run results from R33
on, the decisions from D69 on, the proxy's view, recall, transcripts or working-notes
code, or any development run output. The set tests general long-context recall and
multi-turn coding, not any particular design. It was generated before any run. No turn,
question or task names a harness or a harness tool; files and commands are referred to
generically.

## Contents

- `ho4-h1.json` … `ho4-h12.json`: 12 needle histories with 10 questions each, 120 needles.
  The layout and step skeleton are the same as the earlier sets:
  Q1, P1, Q2, Q3, P2, Q4, Q5, P3, Q6, Q7, Q8, [proxy restart], Q9, Q10.
- The category mix per history is the same as the earlier sets:
  - identifier ×2;
  - superseded;
  - irrelevant matches;
  - vague ×2;
  - oversized read;
  - mid-task need;
  - several distant facts;
  - a restart with multiple evictions (Q9, `restart_before`).
- Coding tasks: `eval/tasks/ho4_t1.py` … `ho4_t5.py`.
  - `ho4-t3` is the restart task, and its key constraint is C2.
  - `ho4-t5` is the hardest task, as `ho3-t5` was in its set.
  - The task modules carry `SET = "heldout4"`.

## Generator and seeds

- Generator: `eval/needle_gen_ho4.py` (`GENERATOR = "eval/needle_gen_ho4.py v1"`).
- Seeds 7500–7511: history `ho4-hN` uses seed 7499 + N. The earlier sets used 3100–3105
  (dev), 5200–5211 (heldout), 6400–6411 (heldout2) and 7400–7411 (heldout3).
- Regenerate with `uv run python eval/needle_gen_ho4.py`. The output is byte-identical to
  the committed files, and `--check` verifies this.
- The generator imports only format helpers from `eval/needle_gen.py`: the read-result
  shape, the `python -m unittest` output shape and the message builder. The check also
  imports `eval/needle_gen_ho2.py` and `eval/needle_gen_ho3.py`, but only to compare
  against their themes, word banks and task identifiers.
- Everything else is new:
  - the themes, the word banks and the phrasing bank;
  - the code-file template (a stage registry with registered functions);
  - the file names: `conf/upstreams.toml`, `conf/perf.env`, `conf/databases.toml` and
    `tests/data/upstreams.toml`;
  - the bodies of the three pastes: a JSON-lines rollout event stream (P1), a pylint
    report (P2) and a line_profiler dump (P3);
  - the value formats, listed below.

  | Value | Format |
  |---|---|
  | error codes | `MIS#482-QV` |
  | branches | `patch/<ticket>-<project>-<slug>` |
  | ticket and change-notice ids | `CT-nnnnnn`, `CN-nnnnn` |
  | timeouts | compound durations (`3s415ms`, `2m37s`) |
  | ports | new ranges |
  | pooler ports | `5436`, `6634`, `7438`, `8632` |
  | hosts | `pgx-perf-N.east.lan` |
  | environment | perf, database suffix `_perf` |
  | release builds | `bld-NNNN-xxx` |
- The coding tasks' workspaces are seeded by `run.task_seed(task id)`, as before.

## Independence check

`uv run python eval/needle_gen_ho4.py --check` exits non-zero on any of the following:

1. **Seeds** overlap the dev, heldout, heldout2 or heldout3 seeds.
2. **Theme identifiers** are shared with any earlier set. The identifiers are the project,
   service, database, constant, helper names, modules, clients and column.
   - The check also fails when any of them occurs as a whole word anywhere in the dev,
     heldout, heldout2 or heldout3 needle files.
   - The verb, noun and adjective banks must be disjoint from every earlier bank.
   - Each theme's constant values must not equal any earlier answer.
3. **Planted strings** containing a letter occur anywhere in the earlier needle files
   (case-insensitive substring): every answer, part and evidence string, and every
   planted identifier.
4. **Purely numeric values** (ports, pooler port, required and current constant values)
   equal any earlier answer or answer part.
5. **Wording** shares a four-word run with the dev, heldout, heldout2 or heldout3 wording
   (user turns, assistant summaries, questions and paste wrappers; inline code spans left
   out). No question text may equal an earlier one either.
6. **Structure** breaks: the step skeleton must match dev, every history has 10 questions,
   every evidence string is in its history, the Q4, Q5 and Q9 answers occur exactly once
   in their history, and the import ends with Q1.
7. **Task identifiers** of the ho4 coding tasks occur as whole words in any dev, ho, ho2 or
   ho3 task module or in any earlier needle file.

Each history's Q7 workspace was also run for real (`python -m unittest tests.test_<module>`
in a scratch copy). It fails with the same `AssertionError` line as the canned shell output.
That line names the constant and the change notice, but not the required value.

The task domains differ from the dev, ho, ho2 and ho3 task domains:

| Task | Domain | Restart rule / hardest |
|---|---|---|
| ho4-t1 | Roman numerals, validation codes, regnal names | |
| ho4-t2 | storage sizes, decimal and binary units, quota sheets | |
| ho4-t3 | pins in requirements files, with a CLI | restart task, key C2 |
| ho4-t4 | ten-pin bowling scores, league handicap, sheet notation | |
| ho4-t5 | JSON Pointer, JSON Patch, patch generation | hardest |

## Task checks

`run.check_reference(["ho4-t1", …, "ho4-t5"])` (`eval/tasks/run.py`) gave these results:

- Every reference solution passes all `test_f_*` methods and C1–C3.
- Every stub fails every `test_f_*` method. Two stubs hold one constraint each:
  ho4-t1's C3 (standard library only) and ho4-t5's C1 (no banned imports).
- The legacy catalog suite of every task passes on the untouched workspace.

The visible tests of ho4-t2 (`test_house_units`) and ho4-t5 (`test_add_replaces_member`)
encode the superseded rule on purpose. A model must update them after turn 5.

## Loading

`eval/needle.py` selects a set through `SETS`; `heldout4` needs an entry there (and in
`HELDOUT_SETS`) before `--set heldout4` works.
