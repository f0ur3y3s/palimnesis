# ho2: the fresh Phase 3B held-out set

The Phase 3 held-out set (`eval/needles/heldout/`, `eval/tasks/ho_t*.py`) was seen before
Phase 3B was designed, so the 3B gate is judged on this set alone (docs/plans/phase3b.md,
O-B1). It was generated and committed before any Phase 3B run.

## Contents

- `ho2-h1.json` … `ho2-h12.json`: 12 needle histories with 10 questions each, 120 needles.
  The layout and step skeleton are the same as `eval/needles/heldout/`:
  Q1, P1, Q2, Q3, P2, Q4, Q5, P3, Q6, Q7, Q8, [proxy restart], Q9, Q10.
- The category mix per history is the same as the earlier sets: identifier ×2, superseded,
  irrelevant matches, vague ×2, oversized read, mid-task need, several distant facts, and a
  restart with multiple evictions (Q9, `restart_before`).
- Coding tasks: `eval/tasks/ho2_t1.py` … `ho2_t5.py`. `ho2-t3` is the restart task, and
  its key constraint is C2. The task modules carry `SET = "heldout2"`.

## Generator and seeds

- Generator: `eval/needle_gen_ho2.py` (`GENERATOR = "eval/needle_gen_ho2.py v1"`).
- Seeds 6400–6411: history `ho2-hN` uses seed 6399 + N. The earlier sets used 3100–3105
  (dev) and 5200–5211 (heldout).
- Regenerate with `uv run python eval/needle_gen_ho2.py`. The output is byte-identical to
  the committed files, and `--check` verifies this.
- The generator imports only format helpers from `eval/needle_gen.py`: the OpenCode 2.1.4
  read-result shape, the `python -m unittest` output shape and the message builder.
- Everything else is new:
  - the themes, the word banks and the phrasing bank;
  - the file names (`conf/peers.toml`, `conf/preprod.env`, `tests/data/peers_test.toml`);
  - the log, lint and profile bodies;
  - the value formats: error codes, branch names, ticket ids, timeouts in milliseconds,
    port ranges, pooler ports, hosts and release tags.
- The coding tasks' workspaces are seeded by `run.task_seed(task id)`, as before.

## Independence check

`uv run python eval/needle_gen_ho2.py --check` exits non-zero on any of the following:

1. **Seeds** overlap the dev or heldout seeds.
2. **Theme identifiers** are shared with the earlier sets. The identifiers are the project,
   service, database, constant, helper names, modules, clients and column.
   - The check also fails when any of them occurs as a whole word anywhere in the dev or
     heldout needle files.
   - The verb, noun and adjective banks must also be disjoint.
3. **Planted strings** containing a letter occur anywhere in the dev or heldout needle files
   (case-insensitive substring). These are every answer, part and evidence string, and every
   planted identifier: the error codes and their distractors, ticket, branch, requirement
   ids, host, both release tags, the test names around Q6, and the failing test names.
4. **Purely numeric values** (ports, pooler port, constant values) equal any earlier answer
   or answer part. They are not substring-checked, because short numbers occur by chance in
   any long tool output. Their evidence strings carry words, so those are substring-checked
   under 3.
5. **Wording** shares a four-word run with the dev or heldout wording. Wording means user
   turns, assistant summaries, questions and paste wrappers. Inline code spans are left out:
   Q7's `python -m unittest tests.test_<module>` command has the same shape as Phase 3's.
6. **Structure** breaks: the step skeleton must match dev, every history has 10 questions,
   every evidence string is in its history, and the import ends with Q1.
7. **Task identifiers** of the ho2 coding tasks occur as whole words in any dev or ho task
   module or needle file. These are the package, function, error class, error code and
   document names.

The task domains were chosen to differ from the dev-t1…t5 and ho-t1…t5 domains:

| Task | Domain |
|---|---|
| ho2-t1 | grid locators |
| ho2-t2 | chord transposition |
| ho2-t3 | shift rosters |
| ho2-t4 | recipe scaling |
| ho2-t5 | ignore patterns |

The earlier sets were read for format only.

## Task checks

`run.check_reference(["ho2-t1", …, "ho2-t5"])` (`eval/tasks/run.py`) gave these results:

- Every reference solution passes all `test_f_*` methods and C1–C3.
- Every stub fails every `test_f_*` method.
