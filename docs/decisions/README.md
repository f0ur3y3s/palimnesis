# Decisions

Material choices, their reasons and rejected alternatives, newest last. New entries go at the end of the newest file; start a new file when a phase begins. Numbers are global: cite `D44`, not a file.

| File | Entries |
| --- | --- |
| [phase0-1.md](phase0-1.md) | Phases 0 and 1 (D1–D13) |
| [phase2.md](phase2.md) | Phase 2 (D14–D25) |
| [phase3.md](phase3.md) | Phase 3 (D26–D50) |
| [phase3b.md](phase3b.md) | Phase 3B (D51–D68) |
| [phase3-acceptance.md](phase3-acceptance.md) | Working notes and Phase 3 acceptance (D69–D79) |
| [phase4b.md](phase4b.md) | Phase 4B (D80–) |

## Index

| Entry | Title | File |
| --- | --- | --- |
| D1 | Python 3.12 via uv, dependencies pinned by `uv.lock` (Phase 0) | [phase0-1.md](phase0-1.md) |
| D2 | Harness-neutral core; first harness chosen from evidence (Phase 0) | [phase0-1.md](phase0-1.md) |
| D3 | Passthrough is a byte relay independent of normalization (Phase 0) | [phase0-1.md](phase0-1.md) |
| D4 | Session routing: `/s/<id>/…` prefix and/or `X-Palimnesis-Session` (Phase 0) | [phase0-1.md](phase0-1.md) |
| D5 | Proxy-originated errors use the endpoint's error shape (Phase 0) | [phase0-1.md](phase0-1.md) |
| D6 | Opt-in raw capture as the baseline/fixture pipeline (Phase 0) | [phase0-1.md](phase0-1.md) |
| D7 | First harness: OpenCode 2.1.4 over Chat Completions (Phase 0) | [phase0-1.md](phase0-1.md) |
| D8 | Contracts are parametric over runtime capacity (Phase 0) | [phase0-1.md](phase0-1.md) |
| D9 | The proxy is a raw ASGI application (Phase 0 review) | [phase0-1.md](phase0-1.md) |
| D10 | Phase 1 lifecycle and storage decisions (user, 2026-10-24) | [phase0-1.md](phase0-1.md) |
| D11 | Chat Completions parsing is allowlist-strict (Phase 1 slice 3) | [phase0-1.md](phase0-1.md) |
| D12 | Tuning from the Phase 1 measurements (R6, R7 → R8) | [phase0-1.md](phase0-1.md) |
| D13 | Phase 1 review and live-run fixes | [phase0-1.md](phase0-1.md) |
| D14 | Phase 2 design decisions (user, 2026-10-24) | [phase2.md](phase2.md) |
| D15 | Other model backends (llama.cpp and others) are a v2 item (user, 2026-10-24) | [phase2.md](phase2.md) |
| D16 | Stub, chunk and catalog details (Phase 2 slices 6, 8, 11) | [phase2.md](phase2.md) |
| D17 | The project is named Palimnesis (user amendment 1, 2026-10-24) | [phase2.md](phase2.md) |
| D18 | MIT license (user, 2026-10-24) | [phase2.md](phase2.md) |
| D15 amended | upstream-profile seam in v1, llama.cpp profile later (user, 2026-10-24) | [phase2.md](phase2.md) |
| D19 | Amendment A1 adopted: proactive recall and transcript files (user, 2026-10-24) | [phase2.md](phase2.md) |
| D20 | Phase 2 excerpt policy and slots (user, 2026-10-24) | [phase2.md](phase2.md) |
| D21 | Upstream-profile seam layout (Phase 2 slice A; implements D15 amended) | [phase2.md](phase2.md) |
| D22 | Cache accounting, reuse model and drift (Phase 2 slices 9–10) | [phase2.md](phase2.md) |
| D23 | Phase 2 protocol-review fixes | [phase2.md](phase2.md) |
| D24 | Phase 2 cache-audit fixes and logged policy limits | [phase2.md](phase2.md) |
| D25 | Builder latency: off-path stub warm-up; Phase 2 latency gates | [phase2.md](phase2.md) |
| D26 | Recall candidates: only what the base view dropped | [phase3.md](phase3.md) |
| D27 | Chunk-level full-text index | [phase3.md](phase3.md) |
| D28 | Query policy q1 | [phase3.md](phase3.md) |
| D29 | Retrieval r1 | [phase3.md](phase3.md) |
| D30 | Excerpt order within a block | [phase3.md](phase3.md) |
| D31 | Retries select when no excerpt row exists | [phase3.md](phase3.md) |
| D37 | Transcript capability gate for OpenCode 2.1.4: passed | [phase3.md](phase3.md) |
| D32 | Transcript location and directory names | [phase3.md](phase3.md) |
| D33 | Transcript format t1 | [phase3.md](phase3.md) |
| D34 | Publication protocol | [phase3.md](phase3.md) |
| D35 | Projector scheduling | [phase3.md](phase3.md) |
| D36 | The transcript-search addendum (a3) | [phase3.md](phase3.md) |
| D38 | Phase 3 review fixes | [phase3.md](phase3.md) |
| D39 | The upstream is shared with another application | [phase3.md](phase3.md) |
| D40 | Restarting Strata at 32K for held-out runs | [phase3.md](phase3.md) |
| D41 | The counter follows Strata's message normalization (R21-A, R21-B) | [phase3.md](phase3.md) |
| D42 | Turns the upstream renders as nothing, in the core (cache audit of D41) | [phase3.md](phase3.md) |
| D43 | Phase 3 variants frozen: q1, r1, x2, a3 (S10) | [phase3.md](phase3.md) |
| D44 | Held-out protocol for S11, fixed before any held-out run | [phase3.md](phase3.md) |
| D45 | S11 tooling: real OpenCode for needles and coding tasks | [phase3.md](phase3.md) |
| D46 | Added-token strings inside messages count as text (R23-A) | [phase3.md](phase3.md) |
| D47 | No Unicode normalization before counting | [phase3.md](phase3.md) |
| D48 | Held-out ho-t3..t5 and 64K run on a second Strata host | [phase3.md](phase3.md) |
| D49 | Zeus is the only Strata host | [phase3.md](phase3.md) |
| D50 | Phase 3 final review fixes (S12) | [phase3.md](phase3.md) |
| D51 | Composite visible turns (Phase 3B S2) | [phase3b.md](phase3b.md) |
| D52 | Stream assembly (Phase 3B S1) | [phase3b.md](phase3b.md) |
| D53 | Mixed calls | [phase3b.md](phase3b.md) |
| D54 | Hidden tool schemas fixed at the first mask | [phase3b.md](phase3b.md) |
| D55 | Limits, the length stop, and streaming only | [phase3b.md](phase3b.md) |
| D56 | Allowance cap | [phase3b.md](phase3b.md) |
| D57 | Recall by address (`palimnesis_recall`) | [phase3b.md](phase3b.md) |
| D58 | Search (`palimnesis_grep`) | [phase3b.md](phase3b.md) |
| D59 | Catalog pages as tool results | [phase3b.md](phase3b.md) |
| D60 | Hidden results stay out of recall's own inputs | [phase3b.md](phase3b.md) |
| D61 | Visible usage | [phase3b.md](phase3b.md) |
| D63 | Stable in-progress transcript path, turn 0 marked (R25-E, O-B5) | [phase3b.md](phase3b.md) |
| D62 | Held-out protocol for Phase 3B, fixed before any 3B run | [phase3b.md](phase3b.md) |
| D64 | Arm 5 frozen as a5-Dp (S10, R30) | [phase3b.md](phase3b.md) |
| D65 | Short user instructions stay in view (R29, before D64) | [phase3b.md](phase3b.md) |
| D66 | Grep never searches reasoning (R29) | [phase3b.md](phase3b.md) |
| D67 | Lookup budget per instruction; OpenCode's length follow-up is synthetic (R29) | [phase3b.md](phase3b.md) |
| D68 | Unparsable tool arguments resent as `{}` reconcile (S11 defect, R31) | [phase3b.md](phase3b.md) |
| D69 | ho2 becomes development data after its gate (R32, R33) | [phase3-acceptance.md](phase3-acceptance.md) |
| D70 | The current turn is collapsed last (R33-A) | [phase3-acceptance.md](phase3-acceptance.md) |
| D71 | Excerpt retrieval r2: no reasoning (R33-C) | [phase3-acceptance.md](phase3-acceptance.md) |
| D72 | Working notes refreshed by the model at each collapse (R33-D, user choice B) | [phase3-acceptance.md](phase3-acceptance.md) |
| D73 | Empty arguments match any archived arguments (R34 defect) | [phase3-acceptance.md](phase3-acceptance.md) |
| D74 | Working-notes format n2: the cut keeps every section; notes taken from reasoning (R34-C) | [phase3-acceptance.md](phase3-acceptance.md) |
| D75 | Working-notes header h2: values quoted from the notes in full (R36–R38) | [phase3-acceptance.md](phase3-acceptance.md) |
| D76 | pythia is the Strata host; Strata 0.1.54 is an equivalent build of the 0.1.48 pin | [phase3-acceptance.md](phase3-acceptance.md) |
| D77 | Held-out protocol for the working-notes arm on ho3, fixed before any run | [phase3-acceptance.md](phase3-acceptance.md) |
| D78 | `serve` ships `a4-d77` | [phase3-acceptance.md](phase3-acceptance.md) |
| D79 | Phase 3 acceptance review fixes to the shipped configuration (R42) | [phase3-acceptance.md](phase3-acceptance.md) |
| D80 | Source layout: subpackages by subsystem | [phase4b.md](phase4b.md) |
| D81 | Phase 4B scope decisions (user, 2026-11-05) | [phase4b.md](phase4b.md) |
| D82 | Phase 4B decisions settled by the S0 probes (user, 2026-11-05) | [phase4b.md](phase4b.md) |
| D83 | Client-protocol seam (S1); Strata stays at one slot | [phase4b.md](phase4b.md) |
| D84 | Messages subset and neutral mapping (S2) | [phase4b.md](phase4b.md) |
| D85 | Messages emitter (S3) | [phase4b.md](phase4b.md) |
| D86 | Late system messages stay `system`; counter c5 | [phase4b.md](phase4b.md) |
| D87 | Messages archive route (S4) | [phase4b.md](phase4b.md) |
| D88 | Errors on Messages (S5) | [phase4b.md](phase4b.md) |
| D89 | Proxy admission: FIFO, 429, H and K, `/status` guard (S6) | [phase4b.md](phase4b.md) |
| D90 | Harness strings as adapter data; tool-result rule deferred (S7) | [phase4b.md](phase4b.md) |
| D91 | Pi through the proxy; failed partials may be omitted (S8, S9) | [phase4b.md](phase4b.md) |
| D92 | Claude Code is backlogged (user, 2026-11-05) | [phase4b.md](phase4b.md) |
| D93 | Reasoning and accounting on Messages; `state_refresh` for a refresh that hid nothing; Pi live (S11–S13) | [phase4b.md](phase4b.md) |
| D94 | A length-stopped turn may be left out of the resend (S14 finding) | [phase4b.md](phase4b.md) |
| D95 | Phase 4B reviews: fixes and known limits (S15) | [phase4b.md](phase4b.md) |
| D96 | Held-out set `ho4` written, unseen for Phase 7 | [phase4b.md](phase4b.md) |
