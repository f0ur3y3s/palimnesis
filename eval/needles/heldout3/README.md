# ho3: the third held-out set

`ho2` (`eval/needles/heldout2/`, `eval/tasks/ho2_t*.py`) has been retired into development
data (D69), so later designs need a fresh held-out set. `ho3` is that set.

It was written by an author separate from the development work. The author read the
earlier sets and generators for format only. They did not read the run results, the
decisions after D68, the amendments, or the proxy's view, notes and recall code. The set
tests general long-context recall and multi-turn coding, not any particular design. It
was generated and committed before any run.

## Contents

- `ho3-h1.json` … `ho3-h12.json`: 12 needle histories with 10 questions each, 120 needles.
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
- Coding tasks: `eval/tasks/ho3_t1.py` … `ho3_t5.py`.
  - `ho3-t3` is the restart task, and its key constraint is C2.
  - `ho3-t5` is the hardest task, as `ho2-t5` was in its set.
  - The task modules carry `SET = "heldout3"`.

## Generator and seeds

- Generator: `eval/needle_gen_ho3.py` (`GENERATOR = "eval/needle_gen_ho3.py v1"`).
- Seeds 7400–7411: history `ho3-hN` uses seed 7399 + N. The earlier sets used 3100–3105
  (dev), 5200–5211 (heldout) and 6400–6411 (heldout2).
- Regenerate with `uv run python eval/needle_gen_ho3.py`. The output is byte-identical to
  the committed files, and `--check` verifies this.
- The generator imports only format helpers from `eval/needle_gen.py`: the OpenCode 2.1.4
  read-result shape, the `python -m unittest` output shape and the message builder. The
  check also imports `eval/needle_gen_ho2.py`, but only to compare against its themes,
  word banks and task identifiers.
- Everything else is new:
  - the themes, the word banks and the phrasing bank;
  - the code-file template (one pipeline class with methods);
  - the file names: `etc/backends.ini`, `etc/uat.vars`, `etc/schemas.yaml` and
    `tests/fixtures/backends.ini`;
  - the bodies of the three pastes: a logfmt canary-controller log (P1), a mypy report
    (P2) and a tracemalloc snapshot (P3);
  - the value formats, listed below.

  | Value | Format |
  |---|---|
  | error codes | `VINT-417MT` |
  | branches | `topic/<project>-<ticket>-<slug>` |
  | job and decision-record ids | `JOB-nnnnn`, `DR-nnnn` |
  | timeouts | ISO 8601 durations (`PT3.47S`, `PT1M25S`) |
  | ports | new ranges |
  | pooler ports | `6435`, `7643`, `8433`, `9532` |
  | hosts | `pgw-uat-N.corp.internal` |
  | environment | UAT, database suffix `_uat` |
  | release tags | `ship-NNNx` |
- The coding tasks' workspaces are seeded by `run.task_seed(task id)`, as before.

## Independence check

`uv run python eval/needle_gen_ho3.py --check` exits non-zero on any of the following:

1. **Seeds** overlap the dev, heldout or heldout2 seeds.
2. **Theme identifiers** are shared with any earlier set. The identifiers are the project,
   service, database, constant, helper names, modules, clients and column.
   - The check also fails when any of them occurs as a whole word anywhere in the dev,
     heldout or heldout2 needle files.
   - The verb, noun and adjective banks must also be disjoint from all three earlier banks.
   - Each theme's constant values must not equal any earlier answer.
3. **Planted strings** containing a letter occur anywhere in the earlier needle files
   (case-insensitive substring). These are every answer, part and evidence string, and every
   planted identifier: the error codes and their distractors, the job id, both branches,
   both decision-record ids, the host, both release tags, the test names around Q6, the
   failing test names and both target timeouts.
4. **Purely numeric values** (ports, pooler port, required and current constant values)
   equal any earlier answer or answer part.
5. **Wording** shares a four-word run with the dev, heldout or heldout2 wording. Wording
   means user turns, assistant summaries, questions and paste wrappers. Inline code spans
   are left out, so Q7's `python -m unittest tests.test_<module>` command is not counted.
   No question text may equal an earlier one either.
6. **Structure** breaks: the step skeleton must match dev, every history has 10 questions,
   every evidence string is in its history, and the import ends with Q1.
7. **Task identifiers** of the ho3 coding tasks occur as whole words in any dev, ho or ho2
   task module or in any earlier needle file. These are the package, function, error class,
   error code and document names.

Each history's Q7 workspace was also run for real (`python -m unittest tests.test_<module>`
in a scratch copy). It fails with the same `AssertionError` line as the canned shell output.
That line names the constant and the decision record, but not the required value.

The task domains differ from the dev-t1…t5, ho-t1…t5 and ho2-t1…t5 domains:

| Task | Domain | Restart rule / hardest |
|---|---|---|
| ho3-t1 | IBAN formats, validation codes, check digits | |
| ho3-t2 | phone numbers to E.164, contact sheets | |
| ho3-t3 | unbalanced brackets in source text, with a CLI | restart task, key C2 |
| ho3-t4 | parcel rates: chargeable weight, oversize and fuel surcharges | |
| ho3-t5 | cron expressions: names, @ shortcuts, next run | hardest |

## Task checks

`run.check_reference(["ho3-t1", …, "ho3-t5"])` (`eval/tasks/run.py`) gave these results:

- Every reference solution passes all `test_f_*` methods and C1–C3.
- Every stub fails every `test_f_*` method. Two stubs hold one constraint each, as ho2-t5's
  did: ho3-t1's C3 (standard library only) and ho3-t5's C1 (no banned imports).
- The legacy catalog suite of every task passes on the untouched workspace.

The visible tests of ho3-t2 (`test_house_style_extension`) and ho3-t5
(`test_sunday_is_zero`) encode the superseded rule on purpose. A model must update them
after turn 5, as with ho2-t2's sharps test.
