# Glossary

The labels used across `docs/results.md`, `docs/decisions.md` and `eval/`.

## Configurations

Configuration names read `a<arm>-<variant>`: `a4-d77` is arm 4, the configuration frozen by decision D77. They are defined in `eval/needle.py` (`CONFIGS`).

| Arm | What it tests |
| --- | --- |
| 1 | Native OpenCode compaction; Palimnesis only relays (`serve --passthrough`). The baseline. |
| 2 | Bounded view and transcript files, no proactive recall |
| 3 | Bounded view plus proactive recall, no transcript files |
| 4 | Full Palimnesis: bounded view, proactive recall, transcript files |
| 5 | Arm 4 plus hidden recall tools (Phase 3B) |

The variant is either a decision number or a development name.

- **Frozen for a held-out run:**
  - `a4-d43`: Phase 3, frozen by D43;
  - `a5-d64`: Phase 3B, frozen by D64;
  - `a4-d77`: the ho3 run, frozen by D77; `serve`'s default since D78.
- **Development variants**, built up a letter at a time:
  - `a4-tr`: `a4-d43` plus the current **t**urn collapsed last (D70) and **r**etrieval r2 (D71);
  - `a4-trn`: plus working **n**otes (D72);
  - `a4-trn2`: with notes format n2 (D74);
  - `a4-trn2h`: plus notes **h**eader h2 (D75).

  A variant sent to a held-out set is renamed by its decision, so `a4-d77` is `a4-trn2h`.
- **Other names:**
  - `a5-A` … `a5-D` are the Phase 3B matrix arms, and a trailing `p` adds pinned instructions (D65);
  - `a1-native` is arm 1 in task records.

## Setting codes

Version 1 of each setting is the original; 2 is the later choice.

| Code | Setting | `serve` default |
| --- | --- | --- |
| q1 / q2 | Recall query policy | q1 |
| x1 / x2 | Excerpt rendering | x2 |
| r1 / r2 | Retrieval; r2 never quotes the model's own reasoning | r2 |
| n1 / n2 | Working-notes format; n2 keeps every section when cut | n2 |
| h1 / h2 | Notes header; h2 asks for values quoted in full | h2 |
| s0–s3 | Stub format for masked content | s1 |
| t1 / t2 | Hidden recall tool descriptions (arm 5) | off |
| a0–a4 | Model-facing addendum (unrelated to the arm's "a") | a3 |

## Other labels

- **D** numbers are entries in `docs/decisions.md`; **R** numbers are entries in `docs/results.md`. **A** numbers are plan amendments (`docs/amendments/`).
- **Sets:**
  - `dev` is development data;
  - `ho`, `ho2` and `ho3` are the first, second and third held-out sets;
  - `ho3-t1` is task 1 of ho3; `ho3-h1` is needle history 1, and `ho3h1q2` is its question 2.
- **Needles** are planted facts the model is later asked about.
  - **Loose exact** forgives formatting such as backticks around the value; **strict exact** does not.
  - An **early stop** is an empty or cut-short answer.
- **Turn kill:** a turn stopped at the 30-minute wall-time limit (D44, D45).
- **Gate inputs** (D44.6) are the checks every judged archive must pass: 0 over-budget inputs, 0 excerpt text visible to the client, `--explain` with 0 unexplained cache changes, and `transcripts verify` passing.
- **Hosts:**
  - **pythia** is the Strata host since D76;
  - **Zeus** was the host before it (D49).

  Results stay per host and build.
