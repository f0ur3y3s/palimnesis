# Docs

Where each document lives and when to read it. Labels such as `a4-d77`, `ho3`, `R41` or `D78` are explained in [glossary.md](glossary.md).

## The spec: what is true now

| Document | What it holds | Read it when |
| --- | --- | --- |
| [contracts.md](contracts.md) | The proxy's behavior, clause by clause; it overrides everything else | Changing behavior: a red test first, then the code, then this text |
| [capabilities.md](capabilities.md) | What each endpoint, harness and request feature gets, and the known limits | Answering "is X supported?" |
| [harnesses.md](harnesses.md) | Per-harness setup and what to avoid | Setting up or adding a harness |
| [affordances.md](affordances.md) | Model-facing presentation: stubs, excerpt blocks, addenda, the 3B matrix | Changing what the model sees |
| [papers.md](papers.md) | The research behind each mechanism and how Palimnesis adapts it | Writing or reviewing a mechanism's docstring |
| [glossary.md](glossary.md) | Configuration names, setting codes, set and result labels | Reading results or decisions |

## The plan

| Document | What it holds |
| --- | --- |
| [plan/v1_plan.md](plan/v1_plan.md) | The v1 plan: phases, green lights, open decisions |
| [plan/amendments/](plan/amendments/) | Amendments to the plan (A1: proactive recall and transcript files) |
| [plan/phases/](plan/phases/) | Each phase's planner output: seams, slices and tests |

## The record: append-only

| Document | What it holds |
| --- | --- |
| [decisions/](decisions/README.md) | Material choices, reasons and rejected alternatives (D1…), one file per phase, with an index |
| [results/](results/README.md) | Measured results (R1…), bound to commit, configuration and host, one file per phase, with an index |
| [probes/](probes/) | Captured evidence about Strata and the harnesses that the contracts rely on |

New decisions and results go at the end of the newest file in their folder, and get a row in that folder's index. Entries are cited by number (`D44`, `R41-B`), never by file.
