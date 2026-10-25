# Palimnesis: Lossless Context Proxy — Implementation Plan

Oct 24, 2026 · @Daniel · Revised after design review and implementation notes

> **Amended.** Read with `docs/amendments/A1-proactive-recall.md` (from Phase 2 on), which makes proactive recall plus transcript files the primary recall mechanism and defers hidden recall tools to optional Phase 3B. Decisions D15 (amended) and D17–D19 apply.

## Overview

Palimnesis is a local proxy between an agent harness and Strata. It archives accepted conversation content, presents a bounded view to the model, and provides exact, addressable retrieval of content removed from that view.

ARC motivates observation masking and addressable recall; LCM motivates immutable history and optional summary DAGs; The Complexity Trap supports deterministic masking; RaMem informs contextual retrieval. The implementation contracts below are the specification. Papers motivate mechanisms; they do not resolve proxy protocol or lifecycle decisions.

**Goals**

- Support a documented subset of OpenAI Chat Completions and Anthropic Messages against named harness versions.
- Preserve accepted messages and content blocks exactly under stable addresses with provenance.
- Bound every upstream input while reserving generation capacity.
- Preserve rendered token prefixes where practical and measure actual cache reuse.
- Keep deterministic compaction free of LLM calls. Optional summaries run as background work.
- Recover committed state and reconcile identifiable retries without duplicating logical events; handle ambiguous keyless retries through the documented recovery/conflict policy.

**Scope and limits**

One local user and one Strata instance, with isolated concurrent sessions. No cross-session personal memory or autonomous execution of harness tools. Exact archival availability does not guarantee correct model recall or task success. Content discarded before transmission cannot be recovered. Disable native harness compaction using verified, version-specific settings where possible.

Responses API, multimodal input, signed reasoning, and provider extensions are supported only when explicitly listed in the capability matrix. Unsupported features receive documented errors, never silent content loss. Universal automatic session identification is not a release claim.

## Architecture and stack

Harness → protocol adapter → session/branch reconciliation → durable archive → bounded view → Strata.

Strata → internal transcript ledger → recall interception or external delivery → harness.

Maintain a harness-visible transcript and an internal model transcript. Hidden recall calls/results appear only in the latter. A durable mapping connects them for subsequent requests, forks, retries, and recovery.

Python 3.12; FastAPI/uvicorn; pooled async httpx; SQLite in WAL mode with synchronous=FULL by default; google-re2 for regex matching; pytest/pytest-asyncio; pinned dependencies. Count with the actual model tokenizer and chat template, preferably using an upstream counting interface where available. FTS5 provides full-text search, not general regex. Optional CPU embeddings and sqlite-vec arrive after core evaluation.

Suggested modules: api, sessions, store, transcript, view, recall, state, summaries, semantic. Documentation: PLAN.md, contracts.md, capabilities.md, decisions.md, papers.md, harnesses.md, results.md. Tests include a deterministic fake upstream and versioned harness fixtures. Create eval/needle.py, eval/replay.py, eval/tasks/ and eval/report.py early enough for each phase's checks.

## Required implementation contracts

Write these contracts in docs/contracts.md and encode them in fake-upstream tests before enabling rewriting.

### Protocol preservation

Maintain a matrix of endpoints, harness versions, fields, headers, streaming events, and behavior. Begin with one harness/endpoint. Keep unmodified passthrough independent from normalization. Rewriting uses a typed internal representation with an opaque extension envelope where safe, preserving supported tool IDs, content order, stop conditions and metadata. Reject unsupported requests before acceptance.

### Client timeouts and automatic retries

For each pinned harness/SDK version, record connect timeout, read-idle timeout, any total request deadline, retryable failures/status codes, retry count/backoff, and whether retries occur after partial streaming delivery. Record whether an idempotency key or retry-attempt header is actually sent; use captured fixtures rather than assumed SDK defaults.

Set the proxy's request-wide deadline below any verified client total deadline with a cleanup/error-delivery margin. Read-idle timeouts are a separate constraint: keep supported SSE traffic within the read-idle interval during prefill and recall, and test whether that client recognizes comments/pings as activity. Keepalives do not extend a total deadline or create visible progress. For non-streaming clients, ensure the configured client wait/read allowance covers the proxy deadline plus response margin. Unknown or unchangeable limits require a conservative documented setting and a timeout/retry test.

A retry-count header is only a reconciliation hint, never an identity or idempotency guarantee; accept only a bounded parsed value and exclude transport retry metadata from the semantic request fingerprint. For keyless duplicates, use explicit session, visible parent and fingerprint to detect a matching outstanding request and return the documented in-progress/recovery response instead of starting concurrent generation. A matching completed request whose response is absent from the resend remains potentially ambiguous; require the documented recovery action rather than silently generate again or claim exactly-once behavior. Do not deduplicate a new identical user occurrence that explicitly extends a later visible parent.

Test client timeouts during prefill, recall and after partial visible text, using the actual SDK retry policy and no idempotency key. Cancellation must reach the old upstream attempt and duplicate attempts must not silently mutate the same branch. Document which failures the SDK retries so a proxy error does not trigger an uncontrolled retry loop.

### Session identity, branches and reconciliation

Prefer explicit identity in the configured base URL: OpenAI-style base http://127.0.0.1:9000/s/<session>/v1 and Anthropic-style base http://127.0.0.1:9000/s/<session>, producing session-prefixed API routes. Verify path preservation and endpoint joining for each pinned harness; do not assume all clients preserve arbitrary prefixes. Strip the session prefix before forwarding upstream.

Also accept X-Palimnesis-Session. If path and header identifiers disagree, reject the request rather than silently choosing one. Validate opaque identifiers, limit their length, and treat path IDs as routing identifiers rather than authentication secrets; avoid unnecessary URL logging. Define branch identity and optional idempotency keys separately.

Provide session creation/resume commands that print the appropriate base URL. Starting an unrelated chat requires a fresh session URL; deliberately resuming uses the existing one. Do not configure one permanent session URL for all new chats. A system-prompt/first-message hash is only a lookup hint, never proof of identity: independent sessions can start identically.

Each unchanged-harness adapter needs a documented association strategy. If identity is ambiguous, require an explicit identifier or return a clear ambiguity error; never silently merge histories. Do not bind sessions to transport connections as a general solution.

Represent ordered occurrences and parent relationships. Identical messages repeated later are distinct occurrences. Extensions append; edits/divergence create a branch or a documented conflict. Native compaction creates an explicit discontinuity rather than replacing archived originals. Serialize branch mutations; concurrent divergence must not silently interleave.

### Visible/internal transcript and delivery

Persist accepted-input, upstream-attempt, generated-content, internal-call/result, view-version and response-preparation events. Map every visible response to its internal generation chain and visible parent. Reconcile client resends against visible history, then reconstruct model views from mapped internal events. Never mistake hidden events for missing client input or append them twice.

Record preparation, attempted delivery, completed server write, cancellation and failure separately. A completed write does not prove client receipt. Scope each idempotency key to a session/branch and bind it atomically to a versioned request fingerprint before inference. The fingerprint includes the visible parent/history, model, supported generation settings, tool definitions/choice, content and semantic extension fields; exclude transport-only details using an explicit canonicalization policy. Same key with a different fingerprint returns a conflict, never a previous response. Concurrent matching requests attach to the existing logical attempt only where supported, otherwise receive a defined in-progress response.

For a completed matching non-streaming request, replay the committed visible result without inference or tool execution. Streaming idempotent replay is deferred to Phase 8. Until supported, a repeated key for a streaming result receives a documented non-reexecuting recovery/conflict response, not a newly generated stream. When enabled, streaming replay reconstructs ordered client-visible events and final usage/stop metadata; timing need not match. Incomplete streams follow the documented recovery/error path rather than silently restarting generation. Retain key bindings at least as long as their replayable logical results; explicit deletion invalidates both, and unknown/expired bindings must not claim deduplication. Without a key, document ambiguity. Do not promise exactly-once network delivery. Harness tool execution and its retries remain the harness's responsibility.

### Archival exactness and stable addresses

Keep raw accepted request bodies separately from normalized records. Exact retrieval means original decoded UTF-8 content, or original bytes for explicitly supported binary content. Raw export preserves request serialization; normalized retrieval does not promise original JSON formatting.

Use a simple lossless raw-body delta as the Phase 1 default. Against a prior raw request in the same session/branch, store its identifier, the longest common byte-prefix length, and the new body's remaining suffix. Reconstruct as parent_bytes[:prefix_length] + suffix, verified against the complete body's byte length and content hash. This does not assume the complete parent body is a literal prefix: closing JSON delimiters and changed request options commonly break that assumption. The raw-storage parent is distinct from the logical conversation parent.

Optional measured optimization: record a common suffix length as well as the prefix and store only the changed middle. Benchmark captured requests from the first harness before adopting this variant; it is useful when large unchanged fields such as tools follow messages in serialized bodies. Keep prefix-only deltas as the default unless physical byte savings justify the added format. For the optional variant, compute the suffix from the bytes remaining after the common prefix so reused regions cannot overlap in either body. Reconstruct as parent_bytes[:prefix_length] + middle + the final suffix_length bytes of parent_bytes; a zero suffix length contributes empty bytes explicitly. Validate both lengths against parent and reconstructed-body sizes and verify the complete byte length/hash. Version the delta record format and retain the same snapshot/depth policy. If adopted, cover unchanged bodies, empty prefixes/suffixes, insertions/deletions, non-overlap and multibyte boundary reconstruction in the existing round-trip checks.

Take a full snapshot at most every N requests (default N=32) to bound delta-chain depth. Also snapshot on a system/tool-schema change, an unsuitable parent, or when the delta is not smaller than a snapshot. A byte-prefix boundary may split UTF-8 because reconstruction is on bytes; decode only the reconstructed body. Validate parent references and prefix bounds, preserve ancestors required by retained deltas, and materialize a snapshot before deleting such ancestors. Test corrupt/missing bases, backup/restore and exact reconstruction of formatting/opaque fields. Content-addressed chunk manifests are a later optimization only if measured storage cost justifies the extra machinery.

Measure physical archive bytes, manifests/index overhead and reconstruction cost separately from logical history size. Replay increasing turn counts with repetitive and incompressible content to expose duplicated history and metadata growth; do not assume deduplicating normalized messages solves raw-request storage. If the first usable implementation temporarily stores independent bodies, make this an explicit documented mode with measured disk budgets and admission limits rather than claiming linear physical growth. Do not claim a universal linear bound for arbitrary changing request bodies.

Address every retained message/block, including user instructions and assistant decisions. Use full collision-resistant IDs internally. Issued short aliases must never change meaning; ambiguous aliases require disambiguation. Unknown IDs return errors with suggestions, never another record's content. Scope retrieval to the authorized session/branch.

Chunks carry offsets, total length, encoding, content hash and continuation metadata. Reassembly must preserve Unicode, whitespace and empty content exactly. Token sizing must not corrupt encoding. External files/attachments are recoverable only if their bytes were accepted and archived.

### Reasoning carryover and template behavior

Record reasoning serialization per exact model, tokenizer/chat-template revision and serving parser. Distinguish prior completed user turns from multiple assistant/tool steps inside the current user turn. State whether earlier reasoning is retained, removed or transformed on each internal recall continuation; never apply a blanket history-stripping policy across Qwen-family templates.

On the OpenAI-compatible path, explicitly list reasoning_content and any reasoning deltas as vendor extensions, with tested input/output/round-trip behavior. Archive emitted reasoning separately from visible answer content where the parser distinguishes them. Whether reasoning is shown to the harness is separate from whether the next upstream model input must carry it. Do not drop it merely because the client does not resend it; reconstruct current-turn carryover from the internal transcript where the template requires it. Do not reinsert it where the pinned template excludes it.

Use golden rendered-token fixtures for an internal recall/tool result followed by continuation, the next user turn, and restart reconstruction. Include retained reasoning in input accounting and previously generated reasoning in cumulative output accounting without charging its generation twice. Record any template-driven prefix change as an explicit invalidation cause. Qwen documentation warns that dropping reasoning_content can affect multi-step tool use; this motivates testing the installed template/parser, not imposing one policy on every model.

### Complete budgets and overflow

Before EVERY upstream invocation, enforce:

- rendered input ≤ configured input budget;
- rendered input + reserved generation + safety margin ≤ actual context capacity.

Count the actual template, system instructions, tool schemas, state, history, delimiters, catalog, recall payloads and generation preamble. Pin tokenizer/template versions and cross-check upstream usage. Drift increases the margin or triggers safe rejection.

Allocate bounded state, recent-history, catalog and recall components. Archive oversized tool output before masking it, including newest output. Preserve valid tool-call/result groups. If non-evictable system instructions, tool schemas or current user input cannot fit, return a structured pre-inference budget error; never silently truncate them. Explicit opt-in input offloading may be added later.

Removed user/assistant spans retain retrievable addresses and catalog coverage. The external catalog grows with history; only bounded pages enter the prompt. Provide first/next/page navigation with bounded cursor cost. Keeping every bare historical ID visible forever is not bounded.

### Request-wide generation and time limits

Treat all internal generations producing one visible response as one logical request. Establish a cumulative generation-token allowance from the client's supported output-limit field, capped by proxy policy, and a request-wide monotonic deadline. Record each adapter's mapping in the capability matrix. Count text, generated reasoning and hidden tool-call arguments against this shared allowance using upstream generation usage or conservative tokenizer accounting. Tool-result payloads consume input/recall budgets, not generated-output tokens. Report visible output and total internal consumption separately.

Before each continuation, subtract prior consumption and cap upstream generation by both the remaining request allowance and available context capacity. Enforce the deadline during reads, tool resolution, queued work and continuation scheduling, not only between calls. Persist consumption with the logical attempt; replaying a completed result does not trigger generation or reset its counters. Independent background jobs have separate explicit budgets and are still included in total serving cost.

On token exhaustion, do not start another continuation. Terminate the visible response with the endpoint's length/max-token stop condition if its emitted structure can be completed validly; never emit an incomplete external tool call as executable. If valid completion is impossible, return the defined partial-stream or non-streaming error. Deadline expiry cancels upstream work and uses the documented timeout/error response. Never label exhausted or failed work as a normal successful stop. Test exhaustion before recall, during tool arguments and after several continuations.

### Streaming and mixed calls

Implement an adapter-specific stream assembler. Forward supported text and reasoning deltas promptly; buffer tool-call blocks until their names and arguments are complete and classified. Keep one proxy-owned visible message/stream open across internal recall continuations, suppressing intermediate completion events and remapping block indices and identifiers. A continuation can append a new content block within that visible message.

Already-emitted text is accompanying text and remains in the visible transcript even if recall later leads to a correction. Never retract it. Preserve the mapping between concatenated visible content and its separate internal generations. Signed reasoning or other blocks that cannot safely be combined require explicitly tested handling or a capability error. Buffering a whole generation is an optional diagnostic/compatibility mode, not the default.

Emit one valid final termination sequence, or the endpoint's defined partial-stream error if an internal continuation fails. Do not emit a successful terminal event and then attempt to reopen the same message. Measure time to first visible text/reasoning, silent intervals during recall, and end-to-end latency on the actual model; keepalives do not count as visible progress.

Persist and resolve internal-only calls before another inference, suppressing their events externally. For mixed internal/external calls, resolve internal calls locally, emit only external calls through a valid client response, and wait for harness results before continuing inference. Preserve the complete internal call set and supply all results before continuation. Reject untested mixed forms; never execute or discard external calls.

Define accompanying text, parallel calls, tool-choice restrictions, malformed arguments, reserved-name collisions and limit exhaustion. Reassemble arguments before execution. Map internal generations to valid visible message IDs, content-block indices, finish reasons and terminal events. Specify cancellation and partial-response errors per endpoint. On harness disconnect or cancellation, cancel the active internal loop and promptly close the active upstream request/stream; prevent subsequent recall or fallback invocations. Use request-scoped cancellation and deterministic cleanup, including races between cancellation, tool resolution and continuation. Record partial delivery without treating it as complete.

Do not assume socket closure immediately releases the installed Strata engine's slot. Test cancellation during prefill, decode and internal continuation, for streaming and non-streaming clients. Measure time until the next request can start and set a release threshold in Phase 0; document engine/version limitations. Document visible-response usage semantics and expose aggregate internal work separately.

Bound every queue between upstream reads, archival commit batches and client writes by bytes/items. Backpressure must pause upstream reads instead of accumulating unbounded memory. Configure archive-commit and client-write/no-progress deadlines plus the request-wide deadline. A connected client that stops reading is a failure case even without a disconnect. Run blocking database work outside the event-loop thread so a stalled writer cannot prevent timeout/cancellation handling. Read flow control alone is not proof that Strata stops computing.

If storage cannot commit, do not forward uncommitted batches. If either storage or client delivery cannot progress within its deadline, stop scheduling continuations, cancel/close the active upstream request and record the outcome if storage permits. Do not claim an event was durably recorded when storage failed. Release resources in all paths; test bounded memory, commit-before-forward ordering and slot release under slow readers, stalled writers, disk-full and upstream stalls. Declare queue sizes and timeout defaults in configuration and reports.

### Cache behavior and scheduling

For the default single-slot upstream, admit foreground requests through a bounded FIFO at the proxy and dispatch at most one logical request to Strata at a time. Start the request-wide deadline on arrival, before queueing; queue time consumes that deadline. Configure and report the queue capacity. Reject excess arrivals immediately with the documented overload response (HTTP 429), matched to the verified SDK retry policy. Remove queued requests on cancellation or expiry without starting inference. Resolve idempotent duplicates and branch conflicts before creating a second queue entry.

The active request retains its scheduling slot across internal recall continuations until it completes, fails, is cancelled, or returns external tool calls to the harness. Never retain the slot while waiting for harness execution or later user input; the next client request queues normally. Release the slot only after upstream completion or cancellation cleanup under the verified slot-release contract. Background jobs use the same single-slot scheduler and start only when no foreground request is active or queued; an already-running bounded job must not be overlapped with foreground inference. Report foreground queue wait separately from inference latency and cache reuse; serialization prevents parallel dispatch, not all cross-session cache eviction.

The invariant concerns rendered token prefixes, not HTTP JSON bytes. Preserve prior tokens and append where possible. Record longest-common-prefix tokens for consecutive upstream calls.

Allowed invalidations include watermark moves, state commits, catalog navigation, recall-buffer eviction, summary activation, system/tool changes, branches and model/template changes. Restart and upstream cache eviction can reduce reuse despite identical input. Do not claim rereads happen only at watermark moves.

Place mutable state after the largest practical stable prefix and measure placement cost. Version state commits. Measure reused tokens directly where available; label latency-based estimates.

Background inference can occupy the model and displace cache state even when asynchronous. With one upstream slot, admit background inference while idle, bound work and measure contention. Prefer model-driven state updates. Fallback refresh is optional queued work and never required for deterministic compaction to terminate.

### Durability and isolation

Commit accepted input and branch assignment before inference. For incremental streaming, commit each bounded batch of generated content and its transcript mapping before forwarding that batch; do not wait for the entire generation. Tune batch size/flush interval against measured write cost and visible latency. Persist turn-completion markers separately so a crash leaves an explicit incomplete turn. Non-streaming responses are committed before delivery. Partial streamed output must remain reconstructible without being mistaken for a complete assistant turn.

Set journal_mode=WAL and synchronous=FULL explicitly by default, applying and reading back the settings on relevant connections. FULL adds WAL synchronization at commit and supports power-loss durability when the filesystem and hardware honor synchronization. Offer synchronous=NORMAL only as an explicit performance option: it preserves committed transactions across application-process crashes but may roll them back after an OS crash or power loss. Record the selected mode in diagnostics and evaluation reports; never attach the FULL durability claim to NORMAL.

Specify transactions, busy handling and archive/index consistency. Separate process-crash and power-loss tests. WAL checkpointing is maintenance, not the durability contract. Use bounded transactions and per-branch ordering; never hold a write transaction throughout inference. Measure FULL-mode commit latency and visible flush delay on the target Windows filesystem; per-batch WAL synchronization is an early tuning candidate. Tune batch size/interval before considering a weaker durability option.

Archive messages/blocks/events are immutable. Derived indexes and delivery projections may change and be rebuilt. Enforce immutability through database protections and behavioral tests, not source grep. User-invoked deletion is the explicit exception, covering associated indexes under a retention policy.

Bind to loopback by default. Preserve role/provenance during recall; do not promote historical tool output into system authority. Default operational logs exclude raw conversation bodies and secrets.

### Model-facing recall affordances

Make recall behavior an explicit workstream in Phases 2–3. Design and version stub previews, address syntax, tool descriptions, error/continuation hints and a short system addendum. A starting addendum is: "Older content may appear as address stubs; use palimnesis_recall for exact details and catalog or search tools when the needed address is unknown."

A/B a small predeclared set of variants on development needles and coding tasks. Measure exact-answer retention, appropriate recall, unnecessary calls, invalid IDs, task success, added tokens and latency. Use labeled situations where recall is needed and where it is unnecessary. Keep prompts and tools fixed within each paired run, since wording changes affect both behavior and the cached prefix. Select variants on development data, then freeze them before held-out evaluation. Do not tune on the final test set.

## Development workflow

CLAUDE.md requires these contracts, meaningful behavioral tests and material decision records. Link papers for modules implementing research mechanisms; protocol plumbing does not require artificial citations. Document justified adaptations rather than forcing literal fidelity.

Retain planner, test-writer, protocol-reviewer, cache-auditor, paper-fidelity-reviewer and eval-runner roles. Reviewers are read-only. The paper reviewer distinguishes fidelity bugs from documented adaptations; local contracts and protocol correctness prevail.

Per phase: plan → failing tests → implement → independent review → applicable checks → results → commit/tag. Phases 4A (state) and 4B (harness expansion) are independent workstreams with separate tags and acceptance gates; neither blocks the other. Optional phases may be skipped explicitly. Every reviewer command must exist before its phase depends on it. Cache review reports token-prefix changes and documented invalidation causes, not only watermark moves.

## Phase 0 — Contracts and one-harness passthrough

Deliver contracts, capability matrix, pinned versions, one endpoint adapter, passthrough, fake upstream, baseline capture and replay scripts. Define request-wide generation accounting, deadlines, queue limits and idempotency fingerprint fields. Select a first harness whose normal supported workflow is linear; document edit/rewind, session-tree forks, concurrent subagents and other features to avoid until their lifecycle behavior is supported. Record actual SDK timeout/retry behavior and template-specific reasoning carryover. Capture direct live baselines before rewriting. Probe template/tokenizer, capacity, counting, cache metrics, cancellation-to-slot-release latency and concurrency. Verify session-prefixed base URLs for the first harness and establish its cancellation release threshold.

**Green lights**

- [ ] First harness completes a scripted task through supported streaming/non-streaming paths.
- [ ] Fake-upstream fixtures prove fields, errors, event ordering, tool deltas and cancellation are preserved.
- [ ] Live direct/proxy behavior is comparable; exact generated-text equality is diagnostic, not a gate.
- [ ] Measure passthrough overhead separately; target p95 under 5 ms on documented hardware/workload, with deviations recorded.
- [ ] Protocol reviewer approves the declared subset.
- [ ] Real-SDK no-key timeout/retry fixtures establish safe deadline/idle settings and keyless duplicate handling. Any retry-attempt header is documented as a hint only.
- [ ] First-harness setup lists unsupported branching/rewind/concurrency features, and the normal linear workflow does not require them.

## Phase 1 — Durable archive and transcript reconciliation

Deliver the minimum correct lifecycle slice: raw archive, immutable message/block/event tables, explicit session URL, stable addresses, visible/internal mapping, and a minimal request/delivery ledger. Support one serialized active branch per session. Recognize divergence and concurrent conflicting requests and reject them clearly; full automatic branching is deferred. With a supplied idempotency key, support completed non-streaming-result replay or a defined in-progress/conflict response. Streaming replay is deferred; duplicate streaming keys and ambiguous partial delivery return a clear non-reexecuting recovery/conflict response rather than automatic resume.

Commit input before inference and output batches before delivery, with basic process-crash recovery tests. FTS is derived and rebuildable. Advanced branching, automatic retry resumption, delivery recovery and the full crash/fault matrix belong in Phase 8; record these limits in the first-usable release. Do not defer committed archival writes or hidden-event reconciliation.

**Green lights**

- [ ] Explicit retries do not duplicate logical events; repeated identical occurrences remain distinct. Same key/different payload or settings conflicts, concurrent matching keys follow the defined policy, and completed non-streaming replay performs no inference; repeated streaming keys get the defined recovery/conflict response.
- [ ] Raw requests reconstruct byte-for-byte through the chosen storage representation. Increasing-length replay reports physical data/metadata growth; any temporary independent-body mode has explicit budgets and limits.
- [ ] Distinct explicit session URLs never merge; mismatched identity sources, divergent edits/forks and conflicting concurrent requests receive defined errors in this initial subset.
- [ ] Every supported block round-trips exactly; aliases survive forced collisions.
- [ ] Database tests reject unauthorized archive mutation.
- [ ] Crashes around input commit and response preparation preserve committed data/mappings.
- [ ] Follow-up requests reconstruct fixtures containing hidden internal events without duplication or loss.

## Phase 2 — Bounded view, catalog and cache instrumentation

Deliver deterministic masking, complete counting, component budgets, bounded catalog navigation, protocol-valid view construction and watermark hysteresis. Use a 48K input default only when capacity and generation reservation permit it. Specify threshold units and the post-compaction target explicitly.

**Green lights**

- [ ] Every invocation fits or receives a structured pre-inference error.
- [ ] Cover oversized newest output, user/system input, schemas, Unicode and many small messages.
- [ ] Version stub formats, tool descriptions and the short recall addendum; define the Phase 3 affordance A/B matrix.
- [ ] Bounded catalog pages can reach every archived span.
- [ ] Builder makes zero upstream calls.
- [ ] Replay explains every prefix invalidation; unexplained changes fail.
- [ ] Report watermark frequency against token ingress/workload size; no universal moves-per-100-turn gate.
- [ ] Report measured cache reuse and prefill latency by invalidation cause; label estimates.

## Phase 3 — Exact recall and end-to-end streaming

Deliver palimnesis_recall(id, offset?, limit?), bounded catalog tools, palimnesis_grep(query, mode, scope?, cursor?), interception and per-turn iteration/materialization caps. Reserve palimnesis\_ names and reject collisions.

Full-text mode uses FTS5. Regex mode defaults to google-re2, with RE2 syntax documented and unsupported constructs rejected explicitly. Verify package installation on supported Python/Windows targets early. RE2 avoids catastrophic backtracking through linear-time matching, but still cap pattern length, compilation memory, scanned bytes, results and total request work; check cancellation between bounded scan units.

If backreferences or other extended syntax are required, offer a separately selected regex-module compatibility mode with explicit per-operation timeout and total request limits. Never silently fall back from RE2 to a different dialect, and never use unbounded Python re for model-supplied patterns. Arbitrary regex cannot use an incomplete FTS prefilter. Results carry addresses/provenance. Recall eviction preserves protocol groups.

At limit exhaustion, disable internal tools for a final continuation where supported, or return the documented error. Check budgets before every continuation. Multi-chunk exact reconstruction is an API guarantee, not a promise that a model can read an arbitrary object in one turn.

**Green lights**

- [ ] Internal calls/results never appear externally.
- [ ] Mixed/parallel calls, accompanying text, malformed arguments, disconnect, retry, cancellation and limit exhaustion pass deterministic fixtures.
- [ ] Exact reconstruction covers messages and observations, including empty/multibyte content.
- [ ] Invalid IDs never substitute records; aliases remain stable.
- [ ] Full-text/regex tests cover code punctuation and multiline patterns.
- [ ] Continuations fit and terminate within both request-wide token and time limits; successive internal calls cannot reset the client's output allowance. Token exhaustion maps to a valid length stop or documented partial-stream error.
- [ ] Slow-client and stalled-writer fixtures prove bounded memory, enforced deadlines, commit-before-forward ordering and upstream cancellation/slot release. Queue/time limits are recorded.
- [ ] Concurrent foreground-session fixtures prove bounded FIFO admission, one active upstream request across internal continuations, overload rejection, queue-time deadline accounting and removal of cancelled/expired entries without inference. Background work cannot bypass queued foreground requests.
- [ ] Until Phase 8 replay support, repeated streaming keys receive the defined recovery/conflict response without inference. Actual-SDK keyless retries after timeouts and partial text never start a silent duplicate generation.
- [ ] Golden rendered-token fixtures prove template-specific reasoning carryover through internal calls and the next user turn, including restart reconstruction.
- [ ] Early needle evaluation and a recall/restart coding task pass on the first harness.
- [ ] Supported text/reasoning deltas arrive before upstream generation completes; tool blocks remain hidden until classified and internal-only terminal events never leak.
- [ ] Cancellation closes the upstream request, prevents continuation and meets the measured slot-release threshold, or the installed-engine limitation is an explicit blocker for the declared capability.
- [ ] Run the affordance A/B matrix on development data, report recall precision/necessity and latency as well as accuracy, then freeze the selected variant.

### First usable milestone — end of Phase 3

One documented harness can start/resume through a session URL, stream visible progress, cross the budget, retrieve exact hidden content and recover committed history after a process restart. Publish a runnable setup example and known limits, including which edit/rewind, branching and concurrent-agent features must remain disabled. Require explicit sessions, serialized single-branch operation, bounded input, durable writes and visible/internal reconciliation. Automatic branching, broad harness coverage and advanced delivery recovery are not prerequisites. Reject unsupported lifecycle cases clearly; a live interrupted turn may require user-directed recovery. This milestone provides real use before the complete Phase 8 hardening matrix.

## Phase 4A — Pinned state

Deliver versioned goal, constraints, decisions, current step, dead ends and useful addresses; palimnesis_state_update; default 800-token cap. Archive state versions and supporting addresses. Define conflicts/provenance. Drop low-priority entries deterministically while originals remain retrievable. State aids navigation rather than replacing authoritative instructions.

Optional fallback refresh follows background scheduling rules. This workstream depends on Phase 3 and is independently releasable from Phase 4B.

**Green lights**

- [ ] State commits are explicit invalidations with measured prefix impact.
- [ ] Early constraints and already-tried tasks are evaluated over several watermark moves.

## Phase 4B — Harness expansion

Expand to both endpoints and Pi, OpenCode and Claude Code, recording exact versions, extensions and native-compaction settings. This workstream depends on Phase 3 and does not require pinned state. Provide protocol-specific session-URL setup and explicit new-session/resume instructions for every harness.

**Green lights**

- [ ] Every advertised harness passes archive, recall, streaming, cancellation and recovery contracts for its subset.
- [ ] Each adapter verifies session-path preservation, endpoint joining and conflicting path/header rejection.
- [ ] Native-compaction configuration is verified; discontinuity detection does not rely only on summary-shaped text.
- [ ] State-independent fixtures allow this workstream to pass even if Phase 4A remains unfinished.

## Phase 5 — Summary DAG (optional)

Deliver asynchronous summaries over immutable spans, hierarchical nodes, proxy-assigned coverage, palimnesis_describe and durable resumable jobs. Activate at explicit view-version boundaries. Failed/stale jobs leave deterministic masking usable.

Escalate detailed summary → smaller bullets → deterministic bounded representation. Bound attempts and validate serialized size/coverage. Summaries remain fallible navigation aids; originals remain exact.

**Green lights**

- [ ] Coverage addresses resolve and every source span has navigable coverage.
- [ ] Adversarial summaries terminate within attempt/token limits.
- [ ] Foreground latency/cache impact meet a recorded contention budget.
- [ ] Restart resumes or abandons jobs without duplicate activation.
- [ ] Paired decision-recall results justify cost versus Phase 4A.

## Phase 6 — Semantic retrieval and reinstatement (optional)

Deliver CPU embeddings, rebuildable incremental index, hybrid ranking and palimnesis_search(query, scope?, cursor?). Bounded results include role, branch, sequence, address, neighboring turns and summary coverage. Index off the request path; expose freshness and lexical fallback while catching up.

This adapts RaMem's contextual evidence principles, rather than implementing its complete long-term-memory framework.

**Green lights**

- [ ] GPU memory remains unchanged within measurement noise.
- [ ] Measure enqueue overhead separately from index lag; target enqueue p95 under 50 ms on documented hardware.
- [ ] Held-out paraphrased needles achieve ≥90% top-5 recall.
- [ ] Context-mismatch errors decrease on a defined labeled test.
- [ ] Results remain scoped/bounded with stale or unavailable indexes.

## Phase 7 — Candidate evaluation

Evaluate a release candidate using infrastructure started in Phase 0 and focused evaluation throughout Phases 3–6. This is a provisional evidence checkpoint, not the final release decision: deferred Phase 8 lifecycle behavior and its fault matrix are not yet required to be implemented. Mark those checks pending rather than passing them or blocking Phase 7 on future work. Keep existing contract failures blocking for capabilities already claimed. Compare native compaction with Palimnesis using the same model, actual capacity, output reservation, tasks, initial repo and available seeds. Isolate stores/reset repositories. Record commit, versions, hardware, cache warmness and all proxy-side calls. Temperature zero alone does not guarantee reproducibility.

**Test families**

1. At least 300 exact-needle trials stratified by source role, placement, masking depth and distractors, with a held-out set. Add paraphrased retrieval for Phase 6.
1. At least 20 coding tasks crossing the budget, with executable outcomes, early constraints and already-tried traps.
1. Serving metrics: first visible content, task latency, prefill/decode time, internal iterations, all input/output tokens, background work and cache reuse.
1. Lifecycle tests: identity ambiguity, forks, repetition, oversized input, mixed calls, cancellation, retries, stale indexes and boundary-targeted crashes.

The table distinguishes mandatory final release gates from informational objectives. Apply it to every capability actually advertised, including optional upgrades when enabled. Record counts and uncertainty even where the gate uses an observed rate. Freeze criteria before held-out results; do not waive a failed gate after seeing them. Phase 7 records provisional results, and Phase 8 confirms the final decision.

| Metric | Final gate or objective |
| --- | --- |
| Needle exact match | Mandatory: observed held-out exact match ≥95%; report count and confidence interval, without claiming the lower confidence bound exceeds 95% |
| Coding task success | Mandatory: observed paired task success rate ≥ native baseline on the predeclared suite; report discordant outcomes/uncertainty without claiming equivalence |
| Early constraint honored | Mandatory: observed rate ≥90%; report absolute failures |
| Repeated dead ends | Mandatory: 0/20 on the declared trap suite; report uncertainty |
| Upstream input over budget | Mandatory: 0; report expected structured rejections separately |
| Internal tools exposed | Mandatory: 0 across declared fixtures |
| Prefix changes | Mandatory: every change attributed to an allowed event |
| Serving efficiency | Informational objective: lower total tokens/latency; include recalls, state refresh and summaries. Report regressions |
| Durability/reconciliation | Mandatory after Phase 8: all deterministic tests for declared capabilities pass; deferred checks remain pending during Phase 7 |
| Output/time/backpressure limits | Mandatory: request-wide allowance, deadline and bounded-buffer fixtures pass |
| Physical storage growth | Mandatory: measured scaling and enforced admission limits; minimizing physical size is an informational objective |

Predeclare a two-sided exact McNemar test for paired binary success/failure outcomes, using the discordant-pair counts; this follows ARC's paired-outcome analysis. Set the significance level (default 0.05), primary comparison and treatment of multiple confirmatory comparisons before final results. Report the full paired contingency table, paired success-rate difference and uncertainty alongside the p-value. State the exact test's power floor: with d discordant pairs all favoring one system, the minimum two-sided p-value is 2^(1-d). Five discordant pairs yield p=0.0625 and six yield p=0.03125; at least six are needed for p\<0.05, even in the most favorable split. More balanced splits require more discordant pairs. A 20-task suite with a strong baseline may therefore be unable to demonstrate significance. With few discordant pairs, emphasize limited power; significance is not an additional release gate. A nonsignificant result does not establish equivalence or noninferiority; any such claim requires a predeclared margin and suitable interval-based analysis.

Repeat selected trials to quantify variability, but do not count correlated seeds/runs of the same task as independent pairs. Predeclare the independent task-level outcome used for McNemar; analyze repeat-level variability with task-cluster-aware intervals or a separate descriptive report. One task changes a 20-task rate by five percentage points; remove the one-point agreement requirement. Keep any exploratory practical regression tolerances separate from the mandatory observed-rate gate above. Increase samples when the final decision remains inconclusive, using a sampling/stopping rule fixed before confirmatory results. Keep affordance selection separate from held-out confirmatory runs.

## Phase 8 — Operational hardening and final release decision

Complete deferred lifecycle support here: defined branching/fork behavior, streaming idempotent replay, advanced retry/delivery recovery and the full concurrency/crash matrix. Automatic interrupted-turn resume is optional and must not imply exactly-once network delivery. Deliver passthrough flag, diagnostics, inspection/export CLI, explicit deletion, backup/restore, migrations, resource limits and clean-machine guides. Export exact content/provenance. Explain deletion and backup retention limits. Validate archive/index integrity after recovery.

After hardening, rerun the full deterministic contract suite and assess the change set against the Phase 7 candidate. Repeat affected live evaluations whenever lifecycle, streaming, budget, prompt, retrieval or scheduling changes can alter behavior or cost. Changes to model-facing behavior require the relevant held-out recall/coding comparisons; documentation-only changes do not require blanket reruns. Bind every result to its commit and configuration, and explain which earlier results remain applicable. Final release requires all mandatory gates and enabled optional-phase gates to pass, with no pending checks for advertised capabilities. Report unmet informational objectives as limitations rather than relabeling them as passed gates.

**Green lights**

- [ ] At least 20 forced process-termination trials at selected boundaries retain committed events and valid transcript mappings.
- [ ] Claim power-loss durability only when separately configured/tested.
- [ ] Disk-full, busy-database, timeout and malformed-stream failures are explicit and do not silently lose accepted history.
- [ ] Each advertised guide works on a clean supported installation.
- [ ] Protocol review approves the full capability matrix.
- [ ] Streaming idempotent replay preserves visible event order/content and terminal metadata without inference or internal-tool reexecution; payload/key conflicts, interruption and unsupported resume paths have fixtures.
- [ ] Complete deferred checks, rerun affected evaluations after hardening, and make the final release decision against every mandatory gate.
- [ ] Publish final results/limitations with commit, configuration and the applicability of any retained candidate measurements.

## Open decisions and residual risks

Resolve in Phase 0: first harness/endpoint; session-path preservation, URL joining and new-session/resume workflow; supported content/extensions; installed Strata counting/template/cancellation/cache capabilities; actual capacity/output reservation/margin; and cache impact of concurrent sessions/background inference.

Model recall remains a behavioral risk. Identity ambiguity, protocol limits, delivery uncertainty, cache eviction, contention and durability also retain limitations; mitigation is not proof of elimination. Publish measured limitations. Unique retained history requires growing storage; repeated raw requests and derived metadata can grow faster unless deduplicated. Report physical scaling and enforce disk admission limits. Export and user-invoked deletion address retention, not a bounded-storage guarantee.

## References

- [ARC](https://arxiv.org/html/2607.25066v1): exact recall, bounded catalog pages and active-view assumptions.
- [LCM](https://arxiv.org/html/2605.04050v1): immutable history, DAG, escalation and memory tools. Zero-cost continuity concerns short-task recursive overhead, not prefix-cache guarantees.
- [The Complexity Trap](https://arxiv.org/abs/2508.21433): masking and scaffold-dependent evaluation.
- [RaMem](https://arxiv.org/abs/2606.22844): contextual evidence and retrieval validity.
- [Anthropic streaming](https://platform.claude.com/docs/en/build-with-claude/streaming): event lifecycles and argument deltas.
- [SQLite FTS5](https://sqlite.org/fts5.html): full-text syntax; regex needs a separate path.
- [SQLite synchronous settings](https://sqlite.org/pragma.html#pragma_synchronous): WAL FULL/NORMAL durability tradeoffs.
- [RE2](https://github.com/google/re2): linear-time matching, memory limits and restricted syntax.
- [regex module](https://github.com/mrabarnett/mrab-regex): explicit timeout-enabled compatibility mode.
- [Strata cancellation report](https://github.com/Niko1221/Strata/issues/431): verified historical report of delayed streaming cancellation during long prefill on v0.1.32; the maintainer reports a fix in v0.1.34. It supports installed-version regression testing, not a claim that current releases still have the bug.
- [Qwen3 serving/tool-use notes](https://github.com/QwenLM/Qwen3): reasoning_content handling can affect multi-step tool use; verify the installed model/template/parser.
- [Strata](https://github.com/Niko1221/Strata): setup/API entry points; verify installed behavior directly.
- [Anthropic context-engineering cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools): structured note-taking.
