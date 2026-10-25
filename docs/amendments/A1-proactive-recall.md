# Plan amendment A1: proactive recall and transcript files

Adopted 2026-10-24 (D19). The user's text follows, with two reading notes:
- **Name.** References to Mnemon read as Palimnesis (D17), and `mnemon_*` tool names become `palimnesis_*`.
- **Backends.** "Strata or llama.cpp" is governed by D15 as amended: v1 builds a backend-neutral upstream-profile seam but ships and evaluates only the Strata profile.

---

Applies from Phase 2. Replaces hidden-tool recall as the primary mechanism for the first usable milestone.

## Purpose and guarantees

Palimnesis helps local models served by Strata or llama.cpp operate within a small, bounded context while preserving the complete accepted session outside it. Relevant historical excerpts return automatically; exact originals remain searchable through the harness's normal tools.

This provides **bounded working context with lossless external history**. It does not guarantee unlimited model attention, correct retrieval, or correct interpretation of every archived fact.

Eunoe motivates this approach through proactive retrieval, pinned excerpts and readable transcripts. Its reported results are encouraging, but its approximately 110K-token prompt size does not establish equivalent performance at 32–64K. Record the mechanism, evidence limits and Palimnesis's adaptations in `decisions.md` and `papers.md`. [Eunoe](https://github.com/chroxify/eunoe)

Existing archival, durability, session identity, streaming, cancellation, admission and complete-budget contracts remain in force unless explicitly amended below.

## Phase 2 — budget and deterministic presentation

### Recall excerpts

Add a `recall_excerpts` component to complete input accounting.

Define both:

- A maximum excerpt allocation per accepted user message.
- A maximum total allocation across all excerpt blocks in the active view.

Excerpts must never displace non-evictable input or consume reserved generation capacity. Their allocation may fall to zero when necessary.

Render excerpts after the original user text in the internal copy of that message, inside a delimited block. The original archived message remains unchanged. Excerpts never enter the harness-visible transcript.

Each excerpt includes its source address, turn number, original role, applicable tool name and verbatim payload. Escape presentation delimiters unambiguously. Treat payloads as historical evidence, not new instructions; preserve provenance and do not promote tool output to system authority.

### Immutable content, budgeted inclusion

An accepted message's excerpt set and rendering are immutable. Never recompute them on later requests or after restart.

The view builder may omit an entire excerpt block under a deterministic budget policy. Omission does not modify its stored contents. Record inclusion changes as view invalidations and avoid repeatedly removing and reinserting blocks between threshold events.

Pinned excerpts do not make historical user messages permanently non-evictable. Older spans may leave the active view under the existing addressability and catalog policy.

### Catalog

Retain the catalog as a bounded index over archived spans and as the source for the transcript index.

Do not build model-facing catalog navigation tools in Phase 2. Catalog paging can remain an internal or inspection capability until optional Phase 3B.

## Phase 3 — proactive recall

When a genuine new user message is accepted:

1. Reconcile it against the visible transcript. Distinguish new instructions from tool-result messages and retries.
2. Determine the base view and any eviction triggered by this request.
3. Search archived spans absent from that resulting view, including spans about to be evicted.
4. Select excerpts within the available allocation.
5. Persist the selection before inference.

Use a deterministic, bounded query-construction policy for FTS5/BM25. Do not pass arbitrary user text directly as FTS query syntax. Define behavior for long messages, code punctuation, empty queries and messages such as "continue."

Rank candidates by relevance, merge overlapping excerpts, apply the token cap, then render the selected evidence in chronological order. Chronological ordering must not determine which candidates survive selection.

Retain provenance for conflicting or superseded statements. A high retrieval score does not establish that a statement is current.

Persist:

- Source addresses and exact excerpt boundaries.
- The frozen rendered block.
- Archive cutoff and base-view version.
- Query, retrieval and renderer versions.
- The selection's token charge under the pinned tokenizer.

Retries and subsequent requests reuse the stored selection. Do not search the injected excerpt text as though it were new user input.

Proactive retrieval runs on new user messages. It does not solve every information need discovered during an autonomous tool loop; transcript fallback covers those cases.

## Phase 3 — transcript-file fallback

Render a per-session directory outside project repositories containing:

- `index.md`: a concise entry per turn, with stable addresses and filenames.
- `turn-NNNN.md`: user content, assistant content, tool calls and tool outputs, with explicit boundaries and provenance.

The directory is a derived, rebuildable projection of the durable archive. Preserve supported content losslessly through documented escaping or linked exact payload files. Verify extracted payloads against archive hashes; readable Markdown need not reproduce raw API request serialization.

Publish files and their index/manifest through a crash-safe protocol. Readers must see a consistent published generation or an explicit archive cutoff, not an index pointing to unfinished files. Mark incomplete turns clearly. Use branch-specific projections when branching becomes supported.

Apply restrictive permissions, exclude contents from operational logs, and include projections in deletion and retention behavior. Rebuilding must not require model inference.

### Harness capability gate

The first supported harness must demonstrably read the directory from its actual execution environment without unexpected prompts or denial.

If it cannot, the profile must provide another verified exact-retrieval mechanism or advertise proactive retrieval only. Documenting inaccessible files is insufficient to claim usable exact-recall fallback.

No harness code changes are required for a supported profile, but session configuration, filesystem access and a model-facing addendum are required.

### Bounded search recipe

A short, versioned system addendum provides the session path and teaches the model to:

1. Search the index or transcript files for relevant terms.
2. Read a specific turn and bounded line range.
3. Narrow or paginate oversized results.

Do not instruct the model to load the entire index or transcript.

Transcript reads pass through the normal tool-output budget policy. Test that an oversized read can be narrowed successfully rather than repeatedly masked before the model sees the needed detail.

## Streaming and reasoning

Ordinary harness tool calls and responses continue to use the baseline streaming adapter.

Template-specific reasoning carryover remains required across ordinary tool steps, including transcript searches. Only reasoning handling specific to hidden proxy continuations moves to Phase 3B.

Excerpts and transcript paths must not introduce uncontrolled prefix churn. Record view invalidations and measure rendered-token prefix reuse on the installed engine.

## Optional Phase 3B — hidden recall tools

Defer:

- `palimnesis_recall`, `palimnesis_grep` and model-facing catalog navigation.
- Internal recall interception and mixed internal/external call handling.
- Stream assembly across hidden continuations.
- Reasoning carryover specific to those hidden continuations.

Keep their contracts documented. Implement them if development evaluation shows that proactive retrieval plus accessible transcript files leaves material failures or excessive lookup cost.

Review later phases that expose additional proxy-owned tools, including pinned-state updates and semantic search. Each requires either an explicitly enabled interception capability or a documented alternative; deferring hidden recall does not automatically implement other hidden tools.

## Evaluation

Start at 32K, then repeat at 64K, reserving generation capacity consistently. Use the actual local model, quantization, template and engine configuration.

Compare:

1. Native harness compaction.
2. Palimnesis's bounded view without proactive excerpts, with transcript fallback.
3. Proactive excerpts without transcript fallback.
4. Proactive excerpts plus transcript fallback.
5. Hidden recall tools later, if implemented.

Use development data to select query policies, excerpt formats, caps and addendum wording. Freeze them before held-out evaluation.

Include exact needles and coding tasks covering:

- Explicit identifiers and error codes.
- Vague references and "continue."
- Superseded decisions and conflicting evidence.
- Information needs discovered mid-task.
- Irrelevant retrieval matches.
- Oversized transcript reads.
- Several distant facts needed together.
- Restarts and multiple eviction events.

Measure task success, constraint adherence, exact-answer retention, appropriate fallback use, unnecessary lookups, total tokens, time to first visible content, total task latency and cache reuse.

Count all harness lookup round trips. Low lookup frequency alone is not success. Measure allocated memory separately; fewer active tokens do not guarantee lower allocated VRAM.

## First usable milestone — green lights

- [ ] Excerpt sets and renderings survive requests and restarts unchanged.
- [ ] Inclusion changes follow the deterministic view policy and have recorded causes.
- [ ] Excerpts never appear in the harness-visible transcript.
- [ ] Per-message and total excerpt allocations fit complete input budgets.
- [ ] Retrieval covers spans evicted by the current request.
- [ ] Transcript payloads reconstruct losslessly and projections rebuild after deletion.
- [ ] Published transcript generations remain consistent across crashes.
- [ ] The first harness can search and read bounded transcript regions.
- [ ] Oversized reads can be narrowed to expose the requested detail.
- [ ] Ordinary tool-step reasoning remains correct for the pinned template.
- [ ] Held-out recall and coding evaluations meet the existing first-usable acceptance criteria.

The milestone demonstrates bounded local inference with durable, retrievable history. "Unlimited context" remains an aspiration, not an acceptance claim.
