# Decisions

Material choices, their reasons and rejected alternatives. Newest last.

## D1 — Python 3.12 via uv, dependencies pinned by `uv.lock` (Phase 0)

The machine's default Python is 3.14; the plan targets 3.12, so the project pins `.python-version` to 3.12 and uv provides it. Exact versions live in `uv.lock`. Verified on Windows 11 / Python 3.12: `google-re2 1.1.20251105` installs from a wheel and matches; bundled SQLite 3.53.1 has FTS5. The Phase 3 risk "RE2 may not install on Windows" is cleared for this target.

## D2 — Harness-neutral core; first harness chosen from evidence (Phase 0)

Pi, OpenCode and Claude Code are evaluated on equal criteria (`docs/probes/harnesses.md`). No harness is favored for being already configured locally. Core code keys off protocol, not harness.

## D3 — Passthrough is a byte relay independent of normalization (Phase 0)

The passthrough forwards request bytes and streams `aiter_raw()` response bytes unchanged, including content-encoding; it never parses or re-serializes JSON. Normalization (Phase 1+) is a separate path, per "Keep unmodified passthrough independent from normalization."

## D4 — Session routing: `/s/<id>/…` prefix and/or `X-Palimnesis-Session` (Phase 0)

The prefix is stripped before forwarding; one route serves both API styles (`/s/<id>/v1` OpenAI base, `/s/<id>` Anthropic base) because both append `/v1/...`. Header-only requests on unprefixed paths are accepted for clients that cannot preserve a path prefix. Missing identity is rejected (`session_required`) even in passthrough, so later archiving phases never inherit unsessioned traffic. Path/header disagreement is rejected (`session_mismatch`).

Identifier grammar: 1–128 chars of `[A-Za-z0-9._-]`, starting alphanumeric, no `..`, no trailing `.`. Rejected alternative: accepting any URL-safe string, which would let traversal-looking IDs into future file and DB keys. The trailing-dot rule exists because Windows strips trailing dots, so `abc.` and `abc` would alias as capture directories. Windows device names (`CON`, `NUL`) remain valid IDs; capture fails open for them, and the archive keys sessions in SQLite, not on the filesystem.

The session segment is parsed from the raw request target, so `/s/a%2Fb/...` is rejected rather than decoded into a different route. `/s/` is reserved: upstream paths under it are unreachable through the proxy.

## D5 — Proxy-originated errors use the endpoint's error shape (Phase 0)

`/v1/messages*` gets Anthropic's `{"type":"error","error":{...}}` with the Palimnesis code in the message; everything else gets OpenAI's `{"error":{"message","type","code","param"}}`. Status 400 for identity errors: neither the OpenAI nor the Anthropic SDK retries 400 (to be confirmed against each pinned SDK in `docs/harnesses.md`).

## D6 — Opt-in raw capture as the baseline/fixture pipeline (Phase 0)

`--capture-dir` writes each exchange's exact request/response bytes (credentials redacted) so any harness pointed at the proxy produces replayable fixtures. Request is written on arrival, response on completion or cancellation (marked `complete: false`); writes run off the event loop and the final write is shielded from cancellation. Captures buffer each response in memory: acceptable for an opt-in diagnostic, not for the archive path.

## D7 — First harness: OpenCode 2.1.4 over Chat Completions (Phase 0)

User's choice after the equal comparison in `docs/probes/harnesses.md`. OpenCode sends an exact `x-opencode-session-id` and can route per-session base URLs via its `model.request` plugin hook. Its non-linear defaults (title generation, `subagent` tool) are disabled by config; undo/revert/fork have no switch and fall to Phase 1 divergence rejection. Pi and Claude Code follow in Phase 4B.

## D8 — Contracts are parametric over runtime capacity (Phase 0)

Strata changed `n_ctx` from 32768 to 65536 mid-probe, so contracts state budgets as formulas over values read from `/props` (`input_budget = min(configured, n_ctx − R − M)`), with a startup floor check (`F + min_recent + R + M ≤ n_ctx`) that disables rewriting rather than failing every request. Measured numbers live in `results.md`. At 32K with `R = 8192`, `M = 256` the input budget is 24,320; whether OpenCode's fixed overhead `F` leaves a useful recent window at 32K is measured from live captures, not assumed.

## D9 — The proxy is a raw ASGI application (Phase 0 review)

The Phase 0 protocol review found four fidelity bugs that all came from framework layers between the client and the bytes:

- FastAPI routing returned 405 for `HEAD` and `OPTIONS` and decoded `%2F` into the route.
- httpx `params=` re-encoded the query (`%7e` became `~`, a bare `flag` became `flag=`).
- `client.build_request` injected `accept`, `accept-encoding` and `user-agent`.
- Starlette only watched for disconnect once a `StreamingResponse` started, so a client leaving before upstream headers kept Strata's single slot busy.

`palimnesis.api.Proxy` now handles the ASGI scope directly. It works on `raw_path`, `query_string` and the raw header list, builds an `httpx.Request` without client defaults, and runs a disconnect watcher in a task group for the whole relay. uvicorn runs with its own `Server` and `Date` headers off (`palimnesis.server`), so the upstream's are relayed once. Paired p95 overhead dropped from 3.1–4.3 ms to 1.9–3.8 ms.

## D10 — Phase 1 lifecycle and storage decisions (user, 2026-10-24)

Resolved from `docs/plans/phase1.md` §Decisions. The user chose items 1–3 and 11 explicitly and accepted the planner's recommendations for the rest.

1. **Divergence:** `409 history_divergence` with `x-should-retry: false`. The message gives the message index and says to start a new session. It includes no content.
2. **Conflicting concurrent request:** `409 session_busy` with `x-should-retry: false`.
3. **Continue-after-partial resend:** accepted as an extension. The flattened text maps back to the archived partial and the acknowledged extent is recorded. The upstream view renders reasoning and text split at that extent.
4. **Resend omitting an incomplete partial:** *Amended twice; current rule in D13.1.*
   - The slice-0 probe showed OpenCode never omits a partial after a *server-side* failure, so the omission was first made divergence.
   - The live run (R9) then showed OpenCode *does* omit a reply interrupted from the *client* side, which bricked the session.
   - D13.1 restores the user's original choice, superseded-partial acceptance, for client-cancelled attempts only.
5. **Leading system message changes** (OpenCode's date and `<env>`): recorded as an immutable context version, an allowed invalidation cause. Edits to user, assistant or tool history remain divergence.
6. **First request with prior turns:** imported with `source=client_import`.
7. **Raw delta format:** v1 (prefix plus suffix) and v2 (prefix, middle and suffix length) are both implemented. Adopt v2 only if it saves ≥ 25% raw bytes on the live replay plus a synthetic 200-turn replay.
8. **Aliases:** stored, hash-derived Crockford base32, at least 6 characters, extended on collision, never reassigned. Blocks are `alias.N`.
9. **Upstream body in Ph1:** the client's verbatim message objects with internal occurrences spliced in. Full re-render from the archive comes in Ph2.
10. **Passthrough:** a global `--passthrough` flag only. In archive mode, `/v1/messages` and `/v1/responses` return `unsupported_feature`.
11. **DB location:** `%LOCALAPPDATA%\palimnesis\palimnesis.db` (XDG data dir elsewhere), overridable with `--db`, plus a single-process lock file.
12. **Incomplete turn after a crash:** marked abandoned on restart. Then:
    - an identical resend with no committed output gets a new attempt;
    - a Continue shape is accepted (3);
    - anything else gets `409 ambiguous_retry`;
    - there is no automatic resume.
13. **Finish chunk without `[DONE]`:** the finish chunk is held. EOF before `[DONE]` produces an in-stream error event (contracts §3).
14. **Top-level allowlist:** `temperature`, `top_p`, `seed`, `stop`, `presence_penalty`, `frequency_penalty`, `reasoning_effort` and `chat_template_kwargs.enable_thinking` are forwarded and fingerprinted. `developer` role and text-part arrays are rejected until a harness sends them.
15. **Lone surrogates:** stored as WTF-8 with an encoding tag.
16. **Input-commit failure:** `503 archive_unavailable`, `retry-after: 2`, retry allowed because nothing was accepted.
17. **Fingerprint parent:** the full visible message list stands for the visible parent. The parent occurrence ID is stored on the binding.

## D11 — Chat Completions parsing is allowlist-strict (Phase 1 slice 3)

`palimnesis.chat` rejects whatever falls outside the declared subset, at every level. Rejection happens before acceptance, so nothing is archived or silently dropped (contracts §3).

- **Unknown keys** are rejected per message role (e.g. `user.name`, `reasoning_content` on a non-assistant message), inside each tool call, inside its `function`, and inside each `tools[i].function` (allowed: name, description, parameters, strict).
- **Content.** System, user and tool messages need string content; only assistant content may be null or absent. A tool message needs a string `tool_call_id`.
- **Types and counts.** An empty `messages` array is `InvalidBody`. `stream` must be a bool and `stream_options` an object. `n` is off the allowlist, so even `n: 1` is rejected.
- **Block order.** Assistant blocks are always reasoning, then text, then tool calls. The envelope keeps the client's key order for verbatim re-emission.
- **Hashing.** `content_sha256` covers role and blocks only, so key order and null-versus-absent content don't change it.
- **Error paths.** For duplicate keys and NaN/Infinity, the error names the path of the first occurrence in document order.

Loosening any of these is a capability change: add a test and a `capabilities.md` row.

## D12 — Tuning from the Phase 1 measurements (R6, R7 → R8)

1. **v2 raw deltas are the default.** They meet D10.7's bar on both required replays: 68.6% smaller on the live chain, 56.3% / 58.0% on 200-request synthetic chains. The saving is the ~11 KB tools array that follows `messages` in OpenCode bodies. Existing v1 rows stay readable: the format is per row.
2. **The stream relay flushes when its read queue drains**, not on a 25 ms age timer, still capped at 16 KiB per batch. On Windows the timer's 15.6 ms granularity made each paced token wait ~34 ms, while a FULL commit takes ~1 ms at p95. Paced tokens now commit and forward individually; bursts coalesce. Commit-before-forward is unchanged. Rejected: shortening the timer, because granularity makes any sub-16 ms age unreliable on Windows.
3. **Consecutive parts of one block in a batch are merged into one segment row**, cutting segment rows ~16× on recorded-shape streams. Under paced decoding each token is still its own batch and segment; that is the price of commit-before-forward and is reported, not hidden.
4. **`put_raw` reuses recently written or verified bodies** (64-entry cache, used only when the row's SHA-256 matches) instead of rebuilding the parent chain per insert.

## D13 — Phase 1 review and live-run fixes

From the independent review (REJECT, 7 confirmed findings) and the live archive run (R9). Every fix has a regression test (`tests/test_review_fixes.py`, `tests/test_transcript.py`, `tests/test_crash_recovery.py`).

1. **Client-cancelled partials may be omitted (R9).** A partial whose attempt ended `cancelled` (client disconnect) may be absent from the resend. It stays archived, is recorded as `partial_superseded`, and alignment continues past it. That includes a later answer sitting where the partial was. Server-failed partials still must be resent flattened (probe rules); omitting one is divergence. A keyless retry may reuse a request whose only output the client cancelled.
2. **Reconciliation reports its alignment.** The ledger addresses archived occurrences through `aligned` (client message → occurrence), not by position, for context versions, partial acknowledgements and upstream splicing.
3. **A complete turn whose delivery never completed may come back flattened.** A crash after the final commit, before forwarding, leaves the client holding a prefix; D10.3's partial rule applies.
4. **Stale retries are history divergence.** A keyless or keyed retry matching an older request is rejected with `409 history_divergence` once other turns follow that request. Previously its answer was appended after the later turns.
5. **An upstream error event is terminal.** Nothing after it, not even `[DONE]` in the same read, is relayed or can mark the turn complete.
6. **Every relay failure after the 200 ends with an error event**, including malformed but valid-JSON chunks. At most 32 events may follow the finish chunk.
7. **The accept transaction is shielded from client cancellation**, so its outcome is always cleaned up. `ledger.interrupt` records a disconnect after any queued terminal write and never adds a second terminal event.
8. **Failure codes.**
   - A non-streaming response that cannot be archived gets `502 upstream_failed`, `x-should-retry: false`.
   - Input-commit failures offer a retry (`503`, `retry-after: 2`) only for transient `sqlite3.OperationalError`.
9. **Encoding.** Generated blocks are tagged WTF-8, since lone `\uD83D` escapes occur in streamed text. The FTS index stores a `?`-replaced copy. The archive upstream request asks for `accept-encoding: identity`.
10. **Migration and capture.**
    - Migration 2 backfills the full-text index from existing blocks.
    - `--capture-dir` requires `--passthrough` instead of being silently ignored in archive mode.

Follow-ups from the re-review, fixed:
- Alignment prefers a complete answer that follows a cancelled partial over reading the client message as that partial flattened.
- `partial_superseded` is recorded once per partial.

**Carried to Phase 3:** internal occurrences that belong to a superseded (cancelled) attempt must not be spliced into the upstream body. Phase 1 creates no internal occurrences.

Not changed: an FTS rowid can shift under `VACUUM`. Palimnesis never runs `VACUUM`, and `search.rebuild` restores the index if a user does.

## D14 — Phase 2 design decisions (user, 2026-10-24)

From `docs/plans/phase2.md` §Decisions. The user chose items 1–3 and accepted the planner's recommendations for the rest.

1. **Masking is overflow-triggered, before Phase 3 recall exists.** The view is always built and counted. The client body is forwarded byte-identical until the view would cross the high watermark. Past it, masking is deterministic and oldest-first with stubs and stable aliases, under hysteresis. `--view off` disables masking but keeps budgets. Masked detail beyond the stub previews is not model-recallable until Phase 3; this is a known limit.
2. **Pins are vendored.** The Qwen `tokenizer.json` and the chat template live in `pins/strata-0.1.48/` with SHA-256s and are verified on load.
3. **Input budget cap is 48K.** `input_budget = min(48000, n_ctx − R − M)`: 24,320 at 32K capacity, 48,000 at 64K.
4. **Catalog and recall slots are reserved now:** P = min(1024, 5%·B_in) and Q = min(4096, 10%·B_in), rendered empty in Phase 2.
5. **Stubs.** Addresses are `§ALIAS.N`. Stub format `s1` is versioned, and a format change is a recorded, one-time invalidation.
6. **Watermarks:** H = 0.90, T = 0.50 of maskable capacity, with `min_recent` = 4,096 tokens. Revisit after `bench_view`.
7. **Catalog pages:** p = 20 entries of at most c = 48 tokens each.
8. **Cache accounting** lives in `events` rows. Token sequences are held in memory and re-rendered deterministically after a restart.
9. **Pin mismatch or floor failure** puts the proxy in view-disabled mode: archive and forward as in Phase 1, with diagnostics.
10. **Budget-rejected input** is rejected before acceptance; nothing is archived.
11. **Generation reserve:** `R_req = min(client limit, 8192)`. The upstream limit is rewritten when it is absent or above the cap, so Strata's silent clamp never fires.
12. **Masked reasoning** becomes a reasoning stub, a declared §9 view transform.
13. **Collapsed spans** become one proxy-authored user-role note. The template forbids non-leading system messages.
14. **Contracts §10 allowed causes** gain "view policy/format version change" and "capacity/budget change".

## D15 — Other model backends (llama.cpp and others) are a v2 item (user, 2026-10-24)

v1 keeps the plan's scope: one Strata instance. No upstream-profile abstraction is built in v1. `palimnesis.pins`, `palimnesis.upstream_facts` and the Phase 2 cache accounting stay Strata-specific.

**What v1 already offers another OpenAI-compatible server:** `--passthrough` works against any OpenAI-compatible server. Archive mode's session routing, reconciliation, archive and SSE relay key off the Chat Completions protocol, not the backend.

**What v2 needs for a new backend:** an upstream profile per backend and version, built from the profile's own probe suite (`eval/probes/` style), never from assumed defaults. It bundles:
- **Pins:** the chat template, tokenizer and preprocessing rules for the served model.
- **Facts reader:** context size, build and template identity. llama.cpp's `/props` is similar to Strata's, but each field needs verifying.
- **Counting cross-check:** e.g. llama.cpp `/tokenize` in place of Strata's `count_tokens`.
- **Cache-reuse model:** llama.cpp prefix reuse, not Strata's 6-checkpoint model. This feeds the expected-reuse estimates and the reuse classes.
- **Measured behavior:** error shapes, output-limit clamping, cancellation and slot release, keepalive cadence, reasoning carryover.

Rejected for v1: adding the profile seam during Phase 2. It is cheap but outside the v1 scope, and the user chose to defer it.

## D16 — Stub, chunk and catalog details (Phase 2 slices 6, 8, 11)

Choices made while implementing `palimnesis.stubs`, `palimnesis.catalog` and `palimnesis.affordances` that the plan left open.

1. **Stub s1 layout.**
   - A header, a head preview and a tail preview cut at safe character boundaries (snapped to whole lines when a line break falls inside a preview), then the closing hint `[archived exactly; not shown]`.
   - Text that fits within both preview caps is shown whole with no marker; empty text gets the header alone.
   - Reasoning stubs use 64/32-token caps.
2. **Arm D of the Phase 3 matrix gets its own format.** The matrix describes arm D's stub as "alias and size only", but s1 has previews. Arm D will use a header-only format `s0`, registered before Phase 3 runs. s1 is unchanged.
3. **Chunks.**
   - `sha256` covers the whole text, not the chunk.
   - Offsets count code points.
   - If not even one whole character fits the budget, the cut falls mid-character. The result is still exact on reassembly but is flagged; `ValueError` if not one code point fits.
4. **Catalog cursors.**
   - A cursor must sit on a page boundary, match the page size and belong to the branch.
   - Pages read at most p+1 rows through the `(branch_id, seq)` index.
   - `page(k)` relies on per-branch seqs being dense from 1 and raises if that breaks.
   - "Superseded" covers replaced context versions as well as `partial_superseded` partials.
5. **Masking must pay.** Texts within the preview caps (about 65–288 tokens) produce stubs no smaller than the original. The watermark logic stubs an item only when the stub is smaller.
6. **ARC's bare-id tier is skipped** (paper-fidelity review, Phase 2). ARC first collapses older stubs to bare `§id` references, then further. Palimnesis goes from s1 stubs straight to one span note naming the first and last alias of the run. Per-message bare references grow without bound, and that growth is what span collapse exists to stop. The middle aliases remain addressable and listed in the internal catalog, and the Phase 3 transcript files will expose them. `stubs.bare_ref` stays available for that.

## D17 — The project is named Palimnesis (user amendment 1, 2026-10-24)

*Palin* ("again") + *mnēsis* ("remembering"). The name echoes a palimpsest, a manuscript scraped and overwritten, and inverts it: in Palimnesis nothing is ever overwritten, and the original can always be read again.

The rename reaches the package and CLI (`palimnesis`), the headers `X-Palimnesis-Session` and `X-Palimnesis-Kind` (all `x-palimnesis-*` headers are stripped before forwarding), the env vars `PALIMNESIS_*`, the default archive `%LOCALAPPDATA%\palimnesis\palimnesis.db`, the OpenCode provider and plugin, docs and agent roles. Model-facing text follows: stubs read `[palimnesis s1 …]` and future tools are `palimnesis_*`.

Unchanged: the repo folder, git history, and recorded evidence (`eval/fixtures/`, `eval/probes/fixtures/`, the vendored pins), which must stay byte-exact. The release is pre-1.0, so there are no compatibility aliases.

## D18 — MIT license (user, 2026-10-24)

Palimnesis is MIT-licensed (`LICENSE`), matching Eunoe, the MIT project behind amendment A1. Vendored third-party files keep their own licenses: the Qwen tokenizer and chat template are Apache-2.0 per the model repository (`THIRD_PARTY_NOTICES.md`). Eunoe is credited as a design influence; if any of its code is ever incorporated, its MIT notice must be reproduced.

## D15 amended — upstream-profile seam in v1, llama.cpp profile later (user, 2026-10-24)

Supersedes D15's "no seam in v1" because amendment A1 names Strata *or* llama.cpp.
- Phase 2 builds a backend-neutral upstream profile, so budgeting, views and the A1 retrieval code do not depend on Strata specifics. The profile covers pins, facts reader, counting cross-check, cache-reuse model and error mapping.
- v1 ships and evaluates only the Strata 0.1.48 profile.
- A llama.cpp profile, with its own probe suite, remains later work. Until it exists, capabilities advertise Strata only.

## D19 — Amendment A1 adopted: proactive recall and transcript files (user, 2026-10-24)

`docs/amendments/A1-proactive-recall.md` amends `docs/v1_plan.md` from Phase 2 on. Consequences for work already done or planned:
- **Recall slot.** D14.4's reserved recall slot Q becomes the `recall_excerpts` allocation, with a per-message cap and an active-view total cap. It may fall to zero, never displaces non-evictable input, and never touches the generation reserve.
- **Excerpt blocks** are immutable per accepted user message. They render after the user text in the internal copy only, never in the harness-visible transcript. The view builder may omit a whole block deterministically; each change is a recorded invalidation with hysteresis.
- **Catalog stays internal.** `palimnesis.catalog` remains a bounded index and the transcript index's source. There are no model-facing catalog tools in Phase 2 (none were built).
- **Phase 3** becomes proactive recall plus transcript-file fallback, with a harness capability gate: the first harness must demonstrably read the transcript directory.
- **Hidden recall tools** (`palimnesis_recall`, `palimnesis_grep`, catalog navigation, internal interception, hidden continuations) move to optional Phase 3B. `docs/affordances.md`'s A/B matrix of hidden-tool variants is a Phase 3B matrix. Phase 3 selects query policy, excerpt format, caps and the transcript-search addendum on development data instead.
- **Evaluation** runs at 32K, then 64K, with the five arms A1 lists.
- **Eunoe's evidence** (`docs/papers.md`) motivates but does not establish results at 32–64K.

## D20 — Phase 2 excerpt policy and slots (user, 2026-10-24)

From the Phase 2 delta plan, `docs/plans/phase2.md` §Delta.

1. **Old excerpt blocks are dropped only at threshold events** (watermark or collapse moves, budget changes), where the prefix is invalidated anyway. Between events a new user message may get a reduced or zero allocation. `bench_view` measures this starvation, and Phase 3 may change the policy on development data.
2. **Excerpt caps, Phase 2 defaults:**
   - per message `q_msg = min(2048, 4%·B_in)`;
   - active-view total `Q = min(4096, 10%·B_in)`, D14.4's formula;
   - effective total `Q_eff = min(Q, max(0, B_in − P − F − min_recent))`.

   That is 972 / 2,432 tokens at 32K and 1,920 / 4,096 at 64K. Excerpts never count in F, never touch R or M, never trigger a watermark move, and never cause a BudgetError: their allocation shrinks to zero first. Phase 3 selects the final caps on development data.
3. **The catalog slot is P = 0 until Phase 3B.** A1 removed model-facing catalog navigation, so the component stays in the budget but reserves nothing. Existing views see a one-time recorded budget change.

## D21 — Upstream-profile seam layout (Phase 2 slice A; implements D15 amended)

- **Core interface.** `palimnesis/profile.py` holds the backend-neutral Protocols (`runtime_checkable`):
  - `Counter`: `added_token_strings`, `count`, `count_cached`, `count_messages`, `render_args`;
  - `FactsReader`: `facts`, `stale`, `pinned_ok`, `refresh`, `mark_stale`, `observe`, `diagnostics`;
  - `CrossCheck`: `canary`, `usage → Usage(prompt_tokens, cached_tokens, prompt_ms)`;
  - `CacheReuseModel`: `expected`;
  - `ErrorMap`: `staleness_reason`, `is_context_overflow`.

  These are bundled with `TemplateRules` in a frozen `UpstreamProfile`, alongside the neutral `UpstreamFacts(n_ctx, identity)`.
- **Strata profile.** Everything Strata-specific lives in `palimnesis/upstreams/strata/`:
  - `pins.py` and `pins_data/` (bytes unchanged);
  - `tokens.py`;
  - `facts.py` (formerly `upstream_facts.py`; the `/props` record is `Props`);
  - `errors.py`;
  - `cache.py` (`StrataCacheModel`, filled in by slice 9).
- **Loading.** `profile.load(name, base_url)` resolves names through a string registry. `Settings.profile` defaults to `strata-0.1.48`; there is no CLI flag while only one profile exists. An unknown name fails before the server starts.
- **Template rules.** A profile declaring rules the core does not implement runs view-disabled (contracts §9: a template revision is a pinned-value change, not a runtime branch).
- **Boundary.** `tests/test_profile.py` walks every core module's imports and fails on any Strata import. A toy profile (character counter) drives the full view path end to end.
- **Note.** Earlier decision and plan entries name the pre-move module paths; they are historical records and are left as written.

## D22 — Cache accounting, reuse model and drift (Phase 2 slices 9–10)

1. **Every dispatched upstream call is recorded.** Each gets an immutable `upstream_call` event, written after delivery. Failed calls (503s, transport errors) are recorded too, with their `outcome` and null usage.
2. **Strata reuse model** (`StrataCacheModel`, always labeled an estimate):
   - The expected reuse is the latest checkpoint of the previous render at or before `min(LCP, generation start)`.
   - The candidate checkpoints are the six latest of: assistant-turn starts, the generation-prompt start, and multiples of 16,384 tokens. A system root is added when the system prompt is ≥ 2,048 tokens.
   - It reproduces the probe table (docs/probes/strata.md §7).
   - **Limit:** it sees only the previous call. When the server still holds an older checkpoint from an earlier call, the estimate is a lower bound, as in the probe's turn-4 edit: estimate 1,043, measured 2,656.
3. **Reuse classes, in order:**
   - `full`: cached ≥ `min(LCP, generation start)`.
   - `checkpoint_limited`: cached ≥ the estimate.
   - `restart_or_eviction`: anything lower.
   - `unexplained`: an unexplained cause always gets this class.

   Causes are attributed from the first differing manifest segment (contracts §10). `eval/replay.py --explain` fails on any `unexplained`.
4. **Drift.**
   - "Recent" means the last 8 calls, and `M_eff = M + 2·max drift`, capped at 2,048.
   - Three consecutive drifts, or one drift over 1,024, disables bounded views until the process restarts. A miscounting renderer is a pin problem, not a transient one.
5. **Context versions keep their position.** A context version, such as OpenCode's daily date change in the system message, takes the view position (seq) of the occurrence it supersedes. Before this fix, view boundaries resolved to the start of history after a date change, and masked sessions failed with `context_budget_exceeded`.

## D23 — Phase 2 protocol-review fixes

1. **Escalation before a budget error.** After masking, collapse and excerpt omission, the view also stubs oversized reasoning in the recent window, not only tool output. If still over budget, it lets the window shrink below `min_recent` to the newest group and collapses everything older.
   - **What it prevents:** a session with a large fixed input (e.g. a 15K-token system prompt at 32K) whose reasoning-heavy recent window failed with `context_budget_exceeded` after acceptance, on every later turn.
   - **What remains:** a budget error after acceptance only when the newest group alone cannot fit. The next turn makes that group older and collapsible, so the session recovers.
2. **Known limit of `--view off`.** Its pre-acceptance check counts the client's messages. The upstream view also restores archived reasoning (§9), so an over-budget history can still be rejected after acceptance. `--view off` is a diagnostic mode.
3. **Startup canary.** An inconclusive canary (`count_tokens` unavailable) is re-run on the next refresh instead of disabling views for the process lifetime.
4. **CLI read-only opens** use a proper file URI, so `#`, `%` or `?` in a path cannot drop `mode=ro` or open another file.
5. **Excerpt path hardening.**
   - Excerpt header fields (alias, role, tool name) are reduced to a safe character set, so a client-chosen tool name cannot inject delimiters or special tokens.
   - An excerpt-source or rebuild failure falls back to answering without excerpts. A move caused by the rebuild is recorded.

## D24 — Phase 2 cache-audit fixes and logged policy limits

The independent cache audit re-rendered 789 consecutive upstream-call pairs across 17 scenarios, including restarts, date changes, effort, tool and `n_ctx` changes, drift and excerpts. It found no unexplained or misattributed pair.

1. **Fixed: excerpt churn under a moving per-message cap.** A budget change that shrinks `q_msg` (client `max_tokens` changes, `n_ctx` changes, drift margin at 32K) is a threshold event. Blocks then over the cap are added to `omitted_excerpts` and the view version is recorded with cause `excerpt_omitted`. Previously the cap was re-checked on every build, so a block flipped in and out as the client limit alternated, re-reading everything after it each call. With omission monotone (D20 R2), re-including an older block cannot happen.
2. **Logged for `bench_view`, not fixed: moves can come almost every turn.** When `min_recent` holds the watermark back, the view lands above T. At small budgets with large outputs it then crosses H nearly every turn: 21 of 24 calls moved at a 12K budget. The hysteresis parameters (D14.6) are revisited with `bench_view` data.
3. **Logged, not fixed: an oversized newest output over-collapses.** The watermark and collapse searches run while the oversized newest output is still verbatim, so they take the last candidate before that output is stubbed. This discards more context and cache than needed. The ordering fix (stub the newest output first when it alone exceeds the window) is a Phase 2 follow-up tracked with `bench_view`.
4. **Disabled-mode audit gap.** `view_disabled` and `first_call` are recorded causes; contracts §10 now lists them. Calls in disabled mode record no LCP, so their prefix changes are not audited.

## D25 — Builder latency: off-path stub warm-up; Phase 2 latency gates

R12 measured warm builds at 48K that do not move the view at p95 ≤ 22.6 ms. Builds that move it reached p95 95–175 ms, so all builds together missed the 30 ms target. Profiling located the cost:

- **Not rendering.** Moves made 14 template renders each; cutting them to 8 changed the time by under 10%.
- **Cold stubs and fragments.** Most of the cost was fitting s1 stub previews for newly masked messages, a bisection over uncached prefix counts at about 4.5 ms per stub. The rest was counting each masked message's rendered fragment for the first time.

Changes. All are exact: views, counts and every R12 count are unchanged.

1. **Stub cache across builds.** Stubs are memoized process-wide, keyed by kind, alias, block, the SHA-256 of the text, preview caps and counter. The bounded LRU holds 4,096 stubs, not texts.
2. **Off-path warm-up.** After each build, `ViewEngine` hands the request's items to one background worker while the upstream generates. The worker renders the session once with every unfixed message masked (`view.warm`), which fills the stub and fragment caches for any later move.
   - A newer request supersedes a pending warm-up rather than queueing behind it.
   - Failures are logged and builds compute on demand.
   - `--view off` skips it.
3. **Per-build measurement memo.** The searches and the final view no longer re-render states already counted.
4. **Sandbox check memo.** The jinja sandbox's attribute check is memoized by (type, attribute). The check depends on nothing else, so this is exact.
5. **Rejected: an estimate-guided search.** It cut renders from 14 to 8 per move with identical results but gained under 10%, which did not justify the extra search logic.

**Gate dispositions (Phase 2).**

- **Builder latency** (plan: build + count p95 ≤ 30 ms at 48K, warm). Met on `tool_heavy` (24.8–26.6 ms) and `chatty` (3.9–4.5 ms). Missed on `big_single` (37.4–38.6 ms), which is accepted:
  - Its moves are triggered by a 3K–15K-token output that arrives in the same request, so that output's stub cannot be prepared beforehand.
  - A move precedes a re-read of ~19K tokens, about 60 s of prefill at 48K (R14, scaled). A 45 ms build adds under 0.1% to that request.
  - Incremental rendering would remove the remainder. It is not scheduled.
- **R8 "bench_archive TTFB flat"** is reinterpreted as *no per-request history reload*.
  - **Met.** The statement count is constant over 200 turns (`test_accept_sql_statements_constant_over_200_turns`).
  - **What still grows** (R13, R16), from first-10 to last-10 over 50 turns, is CPU linear in the client body:
    - JSON parse, 0.7 → 3.7 ms;
    - transcript alignment in accept, 2.0 → 5.2 ms;
    - view render and count, bounded by the input budget.
  - **Why the original wording is dropped:** a parser cannot be flat in the size of its input.
  - **Phase 3 candidate:** incremental alignment against the BranchCache, so that accept is O(new messages).

## D26 — Recall candidates: only what the base view dropped

Candidates for a new instruction's excerpts are the blocks the base view no longer shows: every block of a collapsed message, and the replaced block of a stubbed one (a tool result, or reasoning). The base view already includes this request's moves, so spans evicted by this very request are candidates (A1).

- **Excluded:** text still verbatim anywhere in the view, system messages and replaced context versions, superseded partials (they are not view items), ranges already quoted by an included excerpt block, and anything at or after the instruction.
- **Excerpt text is never a candidate.** It is never archived as a block, so it is never indexed.
- **Unmasked sessions** have no candidates and record `nothing_absent` without searching. Their upstream bodies stay byte-identical to the client's.

## D27 — Chunk-level full-text index

Migration 5 adds `fts_chunks` (contentless FTS5) and `chunk_map`. Every archived block is indexed in contiguous chunks of at most 24 lines and 1,536 code points, cut at a line end, else whitespace, else a safe cut. Chunks are indexed where blocks are, and existing archives are backfilled during the migration, which is the first migration that runs Python.

Rejected: ranking whole blocks. BM25's length normalization buries one dense hit inside a long tool output (`test_a_dense_hit_inside_a_long_block_outranks_a_sparse_hit`).

Adapted from Eunoe, which indexes 6-line windows of tool results with the tool call's description folded into each. Palimnesis's chunks are larger, so a hit keeps more of its context before the ±4 lines are added. They cover every block kind, including user text and reasoning, because A1 retrieves any absent span. Call arguments are indexed as their own blocks rather than folded into results. These sizes are development-selectable.

## D28 — Query policy q1

The query is built from the instruction's own text and never passed through as FTS5 syntax.

- Runs of `[\w.\-/:#@]` become terms of `unicode61` sub-tokens. A run that splits becomes a phrase.
- Code-like terms come first: runs that split, or contain digits, internal capitals or backticks. Plain words follow in order of first occurrence.
- Dropped: one-character words and a frozen stopword and filler list. "fix" and similar verbs stay, because IDF discounts common words.
- At most 32 terms. Long messages contribute their first 12,000 and last 4,000 code points.
- Each term is emitted as an FTS5 string joined by `OR`, so operators, prefixes, column filters and quotes in the text are only ever searched as words. A 2,000-case fuzz test against FTS5 confirms that.
- An empty query records `empty_query`. This covers "continue", "ok" and punctuation only.
- q2 (adding the previous instruction's terms for very short messages) is a development variant, not built yet.

## D29 — Retrieval r1

1. **Hits.** The top 64 chunks by BM25 among the candidate blocks. Ties break by newest source, then block index, start offset and chunk rowid, so the order is total.
2. **Relevance floor.** A chunk must contain one code-like term or two distinct terms (`below_floor`).
3. **Focus and context.** An item is focused on the chunk's matching lines, or its best line when those exceed the cap. It then grows by up to 4 context lines a side, alternately, within its block. Overlapping or touching ranges in one block merge, keeping the best rank.
4. **Item cap.** `min(512, allocation − block overhead)`. The overhead is the rendered block header, item header and footer, plus room for the longest provenance. Below 32 tokens the reason is `zero_allocation`.
5. **Packing.** Greedy in rank order: at most 8 items, 2 per source occurrence, at most 16 exact renders. An item that overshoots shrinks once by the measured excess and keeps at least 32 tokens; otherwise it is skipped. The charge never exceeds the allocation. If nothing fits, the reason is `no_fit`.
6. **Rendering.** Chronological by source seq (D30). `source_sha256` is the SHA-256 of the excerpt's exact text, so an item can be checked against the archive range `[start, end)`.

## D30 — Excerpt order within a block

Items render in the order (source seq, source block, start). Phase 2 sorted by turn, then occurrence id; ids are random, so items within one turn were unordered. No stored rendering changes, since Phase 2 never stored a block with more than one item.

## D31 — Retries select when no excerpt row exists

A retried or keyed request hosts excerpts when its last new client message is a genuine instruction with no `excerpt_blocks` row. This happens when a crash fell between acceptance and the excerpt commit, or when the source failed. Either no upstream call was made for it, or the call failed without output, so nothing the model saw depended on a selection and selecting then is safe. An existing row is always reused (`test_a_retry_after_a_crash_before_the_excerpt_commit_selects_once`).

## D37 — Transcript capability gate for OpenCode 2.1.4: passed

`docs/probes/opencode_transcripts.md` records the result.

- **What passed.** With the shipped config and no extra rule, OpenCode's read, grep, glob and shell tools reached a transcript directory outside the working tree and outside any repository, without prompts or denials, with and without `--auto`. The exact needle was returned in 15 of 15 lookups.
- **Why.** Every OpenCode agent starts from allow-all rules, including `external_directory`.
- **Fallback (O5) not needed.**

Consequences for the design:

1. **Bounded lookups only.** The model addendum must require a search followed by a bounded read. Unbounded `read` pages up to 2,000 lines or 50 KB, and it overflowed a 64K context in the probe.
2. **Point at the session directory.** The addendum names the session's own directory, never the transcripts root. OpenCode's grep searches hidden folders such as `.staging`.
3. **LF only.** Projection files use LF line endings. CRLF leaks `\r` into grep previews.
4. **Filesystem permissions are the only confinement.** OpenCode's shell tool bypasses `external_directory`, so permission rules confine nothing. Transcript privacy rests on filesystem permissions alone.
5. **The allow rule is optional.** Adding one (`external_directory` and `read` on `<root>/*`, placed last) changes nothing under the default agents. It matters only for agents configured with ask or deny.

## D32 — Transcript location and directory names

The root is `<db dir>/transcripts` by default, overridden with `--transcripts DIR`; `--no-transcripts` disables projection.

- **Git work trees.** A default root inside a git work tree disables projection with a warning. An explicit root inside one refuses startup.
- **Session directory names.** Each session's directory is `safe(id[:40]).lower() + "-" + sha256(id)[:12]`. Here `safe` maps anything outside `[A-Za-z0-9_-]`, dots included, to `_`, since Windows is case-insensitive and D4 allows device names.
- **What the model is pointed at.** `projector.session_dir(root, id)` is the only path the addendum names. Staging lives at `<root>/.staging`, outside every session directory (D37.2).

## D33 — Transcript format t1

**Turn files.** `turn-NNNN.md` holds one turn:
- a header line with turn, status, seq range and format;
- then each archived block once, between `[[§ALIAS.N · seq S · role · tool NAME (call_id) · kind]]` and `[[/§ALIAS.N]]`, escaped with the x1 payload escaping (reversible).

**Linked payloads.** A payload goes to `payloads/ALIAS.N.txt` when it is over 64 KiB or contains NUL, and to `.bin` when it is not valid UTF-8. The file holds its exact bytes. The turn file then shows a head/tail preview, the line count and the SHA-256.

**Index and manifest.**
- `index.md` has one line per turn (at most about 60 tokens, with a 100-character preview) and a header saying "search; do not read whole".
- `manifest.json` lists every published file with its SHA-256.
- Files are written as bytes, LF only (D37.3).

**Adaptations from the plan:**
- **`incomplete: failed`.** This status is added, since `attempt_failed` is neither complete nor cancelled.
- **Context versions.** A context version renders in the turn of its seq, flagged `replaces §X`, rather than linked from `turn-0000.md`. The link would have rewritten a write-once file.
- **When a turn is sealed.** A turn becomes write-once only once a later turn exists. Until then it is `turn-NNNN.pK.md`, and its unfinished linked payloads are `.pK` too. K counts the archive rows it renders, so it only grows and is deterministic.
- **Branch revision.** The generation is the cutoff seq. The index and manifest also carry a branch revision, because content can change at the same seq, for example when an attempt ends.

## D34 — Publication protocol

1. **Write each file safely.** Write to `.staging`, fsync, then `os.replace`.
2. **Order.** Write-once files first (sealed turns, sealed payloads), then the newest `.pK` files, then `manifest.json`, then `index.md`. Superseded `.p` files are removed best-effort afterwards.
3. **What a reader sees.** `index.md` names only complete files, so a reader always sees one consistent generation. After a crash, or a refused index replace, the manifest may lead the index by one generation. The manifest does not list `index.md`.
4. **Windows locking.** A `PermissionError`, as when a reader holds the index open, is retried 3 times at 50 ms. If it persists, the previous generation stays published and the next trigger retries.
5. **Rebuild.** `palimnesis transcripts rebuild SESSION` reproduces the projection byte for byte from the archive without inference, and repairs any write-once file whose bytes are wrong. It is unsupported while the proxy is writing the same session.
6. **Verify.** `palimnesis transcripts verify SESSION` checks every payload against the archive.

## D35 — Projector scheduling

- **One worker.** A single background thread on a read-only store connection. It coalesces per session, with the newest trigger winning.
- **Triggers.** It is triggered after acceptance and after each attempt ends, from the request's `finally`. It never blocks a response and holds no write lock.
- **Startup and shutdown.** At startup it re-projects the sessions that recovery touched. At shutdown it drains.
- **Logs.** Only counts and directory hashes.
- **Not built yet:** `eval/bench_projection.py` (publication latency and bytes per request) and the Phase 8 deletion cascade.

## D36 — The transcript-search addendum (a3)

- **Where it goes.** The proxy appends `a3`, which names the session's transcript directory, to the upstream copy of the first system message. When there is no system message, it prepends one. The archive and the client never see it, and it counts in F.
- **When it is fixed.** At the session's first view that hides anything (a watermark, collapse or oversized stub), stored as an immutable `addendum_fixed` event, and reused unchanged from then on, even if the transcript root moves. Cache-accounting rebuilds after a restart apply the stored text.
- **Before acceptance.** The budget check counts the addendum's tokens, so it cannot turn into a budget error after acceptance.
- **Deviation from the plan.** The plan fixed the addendum at the first bounded request; it is fixed at the first masked one instead.
  - Unmasked sessions stay byte-identical to the client, as Phase 2 promises. The addendum's claim that content may be hidden is only made once it is true.
  - The cost is one extra re-read of the whole head, system prompt and tool schemas (about 5K tokens for OpenCode), once per session. The pinned template renders the tools before the system text, so the addendum lands just before the system-root checkpoint and that checkpoint is lost. A watermark move already falls back to that checkpoint (R14), so this is the only extra cost. Measured by the Phase 3 cache audit: LCP 4,958 versus 4,976 for the move alone; estimated reuse 0 versus about 4,975 tokens.
- **Cache accounting.** A change of the addendum, including its first appearance or a later removal, is recorded as `view_format_change`. On the first masked request that is the first token difference, ahead of the move itself.
- **Disabling it.** `--no-transcripts` drops the addendum, recorded as `view_format_change`. Rejected: injecting it through harness configuration, which is harness-specific and would be archived as client content.

## D38 — Phase 3 review fixes

1. **Excerpts of text with lone surrogates.** JSON allows lone surrogates, and the archive keeps them as WTF-8. An excerpt now quotes each one as U+FFFD, which keeps offsets because it is one code point each. `source_sha256` still covers the exact archived range.
   - **Bug fixed:** the rendering could not be stored, and the request failed with a 500 on every retry.
   - **Fallback:** if an excerpt row still cannot be stored, the view move is committed alone and the request proceeds without excerpts (§13).
2. **Counted before acceptance:**
   - the addendum the session actually uses, i.e. the stored text when one is fixed, not the current root's;
   - the residue of any older history, as one worst-case span note.

   A request that cannot fit is refused before acceptance rather than failing after it, with the in-build check as the safety net. A sweep test drives requests near the budget edge and confirms it.
3. **A move made by the rebuild with a new excerpt block** (an R3 omission) is recorded and becomes the view the upstream call is attributed to.
   - **Bug fixed:** calls kept the base view number and were recorded `unexplained`, so `--explain` failed. The auditor's `long12b` scenario is now a regression test.
4. **Code-like terms narrowed (D28 amended).** A term is code-like when it has digits, `_`, `/`, `::`, internal capitals, a dot between two parts of 2+ characters, or backticks. Hyphenated and abbreviated prose (`follow-up`, `e.g.`) is plain, and a phrase of only one-character parts is dropped. A single code-like term can therefore clear the r1 floor alone only for a real identifier. Eunoe requires `min(2, wanted)` matched terms. r1 also admits one code-like term, because an error code or identifier is the strongest single signal in a coding session (papers.md).
5. **Packing counts the real rendering (D29.5 amended).** The block is counted with real provenance (alias, turn, role, tool name), so the charge is exact. A placeholder had let a long tool name throw away a whole selection. `over_allocation` remains as the defensive reason when a source returns more than its allocation.
6. **Never re-quote included text (D26).** Already-quoted ranges are compared with each item's span after context is added, not with the hit chunk.
7. **One decode per block.** `search_chunks` decodes each block once, however many of its chunks hit. A 4 MB tool output had cost 1.2 s.
8. **Warm-up sees the addendum.** Warm-up runs on the items the build used, addendum included.
9. **Carriage returns in transcripts (D33 amended).** File structure is LF only. A CR inside a payload is payload text and is kept, so lines of CRLF tool output end in CR inside their block, and `extract` splits on LF only. Linked payload files hold exact bytes, special tokens included; only inline payloads are escaped.
10. **"Byte-identical" means "except restored reasoning" (§9).** Unmasked sessions forward the client's body unchanged unless archived reasoning is restored for a client that omits it, as OpenCode does.

## D39 — The upstream is shared with another application

The user advised on 2026-10-25 that the Strata server on bazzite also serves another application.

- **Pacing.** Evaluation and live runs never saturate the slot. Each request waits for an idle slot (`/slots` or `/status`) and backs off rather than queueing behind foreign work. Runs are sequential and small.
- **Labelling.** Foreign traffic during a run is recorded. Latency, prefill and prompt-cache figures from such runs are labelled as possibly affected by it, not reported as clean. Foreign requests can evict cached prefixes, so measured reuse is a lower bound.
- **No restarts without asking.** The held-out step's restart with `n_ctx` 32768 (O2) would disrupt the other application, so it needs the user's go-ahead first. The fallback is emulating 32K with `--input-budget 24320` at 64K capacity, with native compaction (arm 1) given a matching `limit.context`, labelled as emulated.
- **Update (2026-10-25).** The user reports the other application has been stopped. Runs after this notice are labelled unaffected unless foreign activity is actually observed. The idle-slot check stays in place, and so does the rule against restarting Strata without asking.

## D40 — Restarting Strata at 32K for held-out runs

The user granted SSH access to bazzite (alias `bazzite`) on 2026-10-25 and asked for the server to be restarted at 32K for the held-out runs (O2).

- **How Strata runs.** Its own launcher (`~/.local/share/strata/terminal/0.1.49/strata.py launch`) serves the saved preset "IQ3_XXS 64K" (`~/.local/state/strata/launch/iq3_xxs-64k.json`): engine 0.1.48, `--max-context 65536`, `--kv int8`, MTP, `--expert-cache auto`, vision off, parallel 1, port 8080.
- **Restart command:** `strata.py launch --preset "IQ3_XXS 64K" --context 32k --parallel 1 --restart --no-tui --yes`. Its `--plan` dry run shows the running configuration in every respect except the context.
  - The override applies to that start only; the saved preset stays 64K.
  - `--parallel 1` is pinned because the launcher's default, "fit to card", could fit a second slot at the smaller context.
- **Rejected: the old `iq3_xxs-32k` profile** from 2026-10-23. It has vision on (CPU reader), no expert cache and, per `docs/probes/strata.md` §0, different defaults with the conversation cache off. Those differences would confound held-out latency and cache reuse with more than the context size.
- **Sequence.**
  1. Wait for the development evaluation, which runs on the 64K server, to finish. Nothing is restarted mid-run.
  2. Restart with the command above.
  3. Check that `/props` and `/v1/status` report `n_ctx` 32768, and that the build, template hash and canary still match the pinned profile. Bounded views turn off otherwise.
  4. Run the held-out evaluation.
  5. Restore with `strata.py launch --preset "IQ3_XXS 64K" --restart --no-tui --yes` and check that `n_ctx` is 65536.
- **Launch outside the SSH login.** bazzite sets logind `KillUserProcesses=true`, so anything started from an SSH login is killed when the login closes, even under `setsid nohup`. That is what stopped the 64K server at 06:07 EDT on 2026-10-25, during the development evaluation. Every launch is therefore wrapped in its own systemd user scope, so it outlives the login: `systemd-run --user --scope --unit=strata-<ctx> python/bin/python3 strata.py launch ...`. Stop with `strata.py launch --stop --preset "IQ3_XXS 64K"` before starting the next unit.
- **Observed and not changed:** the launcher warns that the server runs on the LAN with no API key ("anyone who can reach this port can use the model and its tools"). This is the user's existing configuration.

## D41 — The counter follows Strata's message normalization (R21-A, R21-B)

The development evaluation (R21) found two places where the pinned counter rendered something other than what Strata renders. Strata's `serve/frontend.py` is the evidence; `eval/probes/p12_strata_normalization.py` recorded live counts for both.

1. **Reasoning-only assistant turns.** Strata drops a completed assistant turn that has no text, no image and no tool calls, reasoning included (#843); the final message is kept. The counter now drops the same turns.
   - **Effect before the fix:** whenever the model answered only in its reasoning, every later request in the session drifted, by 83 and 16 tokens live. Three drifts in a row disabled bounded views for the whole process (D22.4).
   - OpenCode 2.1.4 sends "" for such turns, so this hits real sessions, not only the emulator.
   - In `layout` a dropped turn is a zero-length segment. The kept messages around it group as Strata renders them, so a tool run continues across it.
2. **Malformed tool-call arguments.** Strata keeps arguments that are not a JSON object as text under `"arguments"`, and maps empty arguments to `{}` (#510). The counter used to leave them as strings, which the pinned template refuses.
   - **Effect before the fix:** a call cut off by `finish_reason: "length"`, resent by the client, made every view build fail. The proxy then forwarded the whole history (D14.9), and Strata answered 400 on every later request in the session.
3. **D14.9 is unchanged.** A view defect still forwards unbounded. With the counter matching Strata, these two inputs no longer reach that path. Making the fallback refuse rather than forward would turn a counter defect into a hard failure for the user, so it is not done here.
4. **R21-C (upstream early stops) is not a proxy defect.** Answers that end mid-value or arrive empty match the raw upstream stream. With item 1 fixed they no longer cascade, so they now count as ordinary model misses. Their cause in Strata 0.1.48 is unknown.

## D42 — Turns the upstream renders as nothing, in the core (cache audit of D41)

D41 made the counter drop empty assistant turns. The cache audit of that change found that the core still treated those turns as rendered.

1. **A template rule, not a Strata branch.** `TemplateRules.drops_empty_assistant` declares that the upstream renders nothing for a completed assistant turn matching `profile.empty_assistant`: no text, no image, no tool calls; reasoning does not count. The core implements both values, and Strata declares `True`. The Strata counter uses the same predicate, so there is one definition.
2. **The view's recent window counts rendered tokens.** `min_recent` used to count a dropped turn's reasoning. A long reasoning-only answer could therefore fill the window by itself and leave the newest tool result stubbed, even though the window then rendered almost nothing. Dropped turns now count zero, so the view equals the one built without the turn.
3. **Dropped turns are never masked.** Stubbing their reasoning changed no tokens, yet it marked them `stub` or oversized and reported them in `evicted_now`. Their manifest form is now `verbatim`.
4. **Checkpoints.** The Strata cache model took every assistant segment start as a resume point, including zero-length ones, and they crowded the 6 slots. It now takes only segments that render tokens. Two message lists that render identical ids get identical checkpoints.
5. **`--explain` alignment.** When a collapse absorbs a dropped turn at the start of its run, the first differing token lies in the next segment, and the pair was compared at the wrong turn (`unexplained`). `_changed_segment` steps back to a zero-length segment just before that one only when its turn changed, so an edit of the next turn is still attributed there.
6. **Canary.** `prior_turn_thinking_only` (Strata: 61 tokens, recorded 2026-10-25) makes a server that renders empty turns (for example `STRATA_KEEP_EMPTY_TURNS=1`) fail the pin check at startup, instead of drifting per call.
7. **Accepted: a dropped turn's reasoning is not a recall candidate.** Recall covers what the view removed (D26), and the view never removes these turns. The model never sees them either, but that is the upstream's rendering, not the proxy's. A reasoning-only answer is still archived and projected into transcripts.

## D43 — Phase 3 variants frozen: q1, r1, x2, a3 (S10)

Selected on development data only (R20, R22); the held-out set has not been run.

1. **x2 replaces x1 as the excerpt renderer.** In R22, on the fixed proxy, x2 scored 58/60 in both runs and x1 scored 51 and 53. Pooled, x2 alone was right on 14 needle pairs and x1 alone on 2.
   - **The evidence is narrow.** 12 of the 14 are one history (dev-h6), where x1 sets off a cascade of early stops (R21-C) in both runs. Without dev-h6 the two are level (96 / 2 / 2 / 0). What R22 shows is that x2 avoids a reproducible failure; it does not show better retrieval or answers in general.
   - **Why choose x2 anyway.** The early stops are upstream behavior with an unknown cause, and x2 is the renderer under which they stayed rare (1 in 120, against 14 in 120). A1 also asks that retrieval scores not be read as currency, and x2's header says so: the current turn, and that a later turn supersedes an earlier one.
   - **Cost:** more lookups (37–39 against 19–32 per run) and a higher time to first visible content (p50 10.2–10.4 s against 6.8–7.2 s). The held-out report includes both.
   - x1 stays registered and selectable with `--excerpt-renderer x1`. Stored blocks keep their own rendering and `renderer_version`, so archives written under x1 replay unchanged.
2. **q1 stays.** In R20, q2 scored 46/60 against q1's 44, with bugs A and B still present. That is no evidence for the change, so the simpler policy stays.
3. **a3 stays.** a4 scored 37/60 in R20, against 44 for a3.
4. **q2 and a4 were not re-run after D41.** Their R20 results include bugs A and B. They stay selectable for later phases but are not part of the held-out configuration.
5. **The held-out configuration** is the default `serve`: q1, r1, x2, a3, transcripts t1, s1 stubs. The emulated 32K (`--input-budget 24320`) is development-only; held-out runs use Strata restarted at 32K (O2, D40).

## D44 — Held-out protocol for S11, fixed before any held-out run

Written on 2026-10-25, after D43 froze the variants and before any held-out history was generated or run. Nothing here changes after held-out results are seen (plan §7: "Freeze criteria before held-out results; do not waive a failed gate after seeing them").

1. **Configuration.** Arm 4 is `a4-d43`: the default `serve` at commit `ac87c8f` or a later commit that changes only `eval/` and docs. Strata runs at `n_ctx` 32768 (D40), and the pin and canary passed at 32K (4/4 cases, 2026-10-25). Arm 1 is native OpenCode compaction through `--passthrough`, with `limit.context` 32768.
2. **Driver.** Held-out needles and coding tasks run through real OpenCode 2.1.4 (O3), never the emulator. A generated history enters OpenCode through `opencode session import`; each question is then a real `opencode run --session` turn. OpenCode therefore builds and resends every request itself.
3. **Held-out set.** 12 histories × 10 questions (120 needles). Themes, seeds and question wording are disjoint from dev-h1..h6. The category skeleton is the same, so A1's coverage holds. The set is generated once and committed before its first run.
4. **Needle gate (O1).** Loose exact match (R19's definition) on arm 4 at 32K is at least 85%, observed over all 120 needles.
   - **What is reported:** the count, a 95% Wilson interval, strict exact, and a history-clustered bootstrap interval. Questions in one history are not independent.
   - **What counts as a miss:** every needle with no correct answer, including errors, early stops and timeouts.
5. **Coding gate (O1).** 5 held-out tasks (plus 3 development tasks, used only to check the harness), run once per arm.
   - **The gate:** arm 4's successes are at least arm 1's, and the restart task passes under arm 4.
   - **Task success** is the task's executable check, run after the session.
6. **Other gates for the tag:** on every held-out archive, 0 over-budget inputs, 0 excerpt text visible to the client, `--explain` with 0 unexplained pairs, and `transcripts verify` passing.
7. **Reruns.** A history or task is rerun from scratch only for an infrastructure failure outside the proxy: Strata down, foreign traffic seen by the D39 gate, or an OpenCode or driver crash not caused by a proxy response. Each rerun and its reason is recorded, and the first attempt's data is kept. A failure caused by the proxy counts.
8. **A defect found during held-out runs.** The run stops. After the fix, the whole held-out needle set and every coding task rerun on the fixed commit. Both results are reported, and the gate is judged on the rerun.
9. **64K (reported only).** After the 32K runs, Strata goes back to 65536. Arm 4 runs 60 needles (held-out histories h1..h6) and the same 5 tasks under both arms.

## D45 — S11 tooling: real OpenCode for needles and coding tasks

Written on 2026-10-25 while building the S11 tools, on development data only. No held-out history or task has run. D44 is unchanged; this entry records how the tools implement it.

1. **Needle driver** (`eval/needle.py run --driver opencode`, `eval/needle_opencode.py`).
   - Each history's import, up to but not including the Q1 text, becomes an `opencode session export` document. It enters an isolated OpenCode home through `opencode session import`. Every step is then one `opencode run --session` turn.
   - Records keep the emulator's per-needle fields, so `eval/report.py` reads both. They are labelled `driver: "opencode"`.
   - There is no tool cap; the emulator's 8 calls per question do not apply. A turn is killed after 30 minutes and counts as an error.
   - Each run also checks that the first client body equals the history and that its prior turns are archived as `client_import`.
2. **Messages go to `opencode run` on stdin.** As one argument, 2.1.4 on Windows keeps the quotes `CreateProcess` adds (`docs/harnesses.md`, OpenCode). Rejected: one argument per word. It works for short text, but pastes exceed the command-line limit.
3. **Session identity without the plugin.** The provider's `baseURL` is `palimnesis session url <history|task>-<config>-<tag>`. One OpenCode session therefore maps to one named Palimnesis session, which `transcripts verify` and `--explain` can address. Requests carry no `X-Palimnesis-Kind`; the proxy does not read it.
4. **Proxy settings.** The child runs the `serve` app with `serve`'s defaults (no `--input-budget`), except `deadline_s` 3600, as in the development runs. The reason: the D39 gate between the proxy and Strata holds a request while the slot is busy, and that wait counts against the deadline. This is the only difference from the `serve` defaults, and it is open for confirmation before the held-out run.
5. **The model's environment.** The model's shell gets PATH without the project's virtual environment, so it runs the system Python. The hidden checks use the same interpreter.
6. **Held-out histories** (`needle_gen.py --set heldout`, `build_heldout`). A separate builder with its own themes, word banks, file names, value formats and phrasing bank, on `build_history`'s skeleton.

**Not everything is disjoint**:
- The P1 deploy-log body comes from the shared `log_lines` templates, including the `2026-10-2x` timestamps and the probe, rollout, queue, reload, HTTP and GC lines.
- Some values are shared or drawn from overlapping ranges: the default pooler port 5432 named in the pooler turn, the 420-test size of the verbose integration run, the fixture read timeouts (`<1–9>.0s`) and write timeouts (60–90 s), and the fallback range for the target read timeout. Four held-out answer values (`15s`, `22s`, `28s`, `2.5s`) also occur as values in the development set, which the model never sees during a held-out run.

None of these is an answer, or the evidence for one. No four-word run of user, assistant, question or paste-wrapper text is shared (tested). `build_history` is untouched, so the dev files regenerate byte-identically (tested).
   - The held-out project tests use stdlib `unittest`, and Q7's command (`python -m unittest tests.test_<module>`) runs for real: it fails naming the constant and the requirement id, but not the required value.
   - The development histories' Q7 command is `pytest`, which the system Python lacks. Under real OpenCode, dev-h1 Q7 therefore failed in the smoke run. That affects development data only.
7. **Coding tasks** (`eval/tasks/`, `run.py`).
   - Each task is one OpenCode session of 8 turns in a fresh git repository. Constraints and an "already tried X, it failed because Y" note come in turn 1. Turn 2 is a full read of a 7–14K-token document; turns 4 and 6 are verbose runs of a ~10–12K-token passing suite. The proxy restarts before turn 5.
   - **Restart task:** ho-t3. Its key constraint C2 (how the command line writes its output) is stated only in turn 1, and is needed only in turn 5, which does not repeat it (tested).
   - **Arms:** arm 4 is `a4-d43` with OpenCode's shipped settings (`compaction.auto` false, `limit.context` 1,000,000). Arm 1 is `serve --passthrough` with `compaction.auto` true and `limit.context` 32768. Both go through the same tap and gate.
   - **Success** means every `test_f_*` method of the hidden check passes. The check is copied in only after the session and run with the system Python. **Constraint `C<N>` holds** when every `test_c<N>_*` method passes. Each check passes on the task's reference solution and fails on the stub (tested).
8. **Gate inputs recorded per run.**
   - `--explain` exit and unexplained pairs, `transcripts verify`, and count drift against the pinned counter.
   - Upstream inputs over 24,320 tokens.
   - Client-visible excerpt text: excerpt markers in any archived client request.
   - The proxy log's "views disabled" and "forwarding unbounded" lines.

9. **Amendments after the independent review (2026-10-25, before any held-out run).**
   1. **Check scoring.**
      - The hidden check runs under a small runner that writes one outcome per test id as JSON, so stderr output cannot break the result.
      - The expected `test_f_*` and `test_c<N>_*` names are read from `HIDDEN`. A test with no outcome counts as failed.
      - A check that outlives 300 s fails with `check_timeout`; `--explain` and `transcripts verify` still run.
   2. **The needle gate's denominator.**
      - Every question that never ran gets a miss row with `not_run` and the reason: an import failure, an unfaithful import, a driver exception, an abort, or a failed Strata check.
      - With `--set heldout`, `report.py` asserts 12 histories × 10 questions, counts any missing needle as a miss, and fails the gate on a duplicate row.
   3. **Attempts** (`eval/attempts.py`).
      - Each driver or runner invocation is a new attempt: `RUN/records/attempt-NNN/` for its records, and `RUN-ws/attempt-NNN/` for its workspaces, OpenCode homes and transcripts root.
      - An attempt directory is never reused or removed. A rerun of an id under the same configuration needs `--reason`. `--resume` is refused by the OpenCode driver.
      - `RUN/attempts.json` records each attempt's number, ids, reason, timestamps, status, and its aborts and infrastructure failures.
      - The report designates the latest attempt per history or task (`--designate` overrides) and lists each superseded attempt with its reason.
      - In the shared proxy and tap code:
        - stop files and proxy logs are unique per start (logs are appended, never truncated);
        - tap bodies are numbered after any already in the directory;
        - an existing `meta.json` is kept under `earlier`.
   4. **History-clustered bootstrap.** 10,000 resamples of histories with replacement, `random.Random(44)`, loose exact over all needles of each resample. The interval is the 2.5th and 97.5th percentiles, with linear interpolation between order statistics. It is reported with the count, the 95% Wilson interval and strict exact.
   5. **Nothing to read the answers from.**
      - Records (`questions.jsonl` with gold, `calls.jsonl`, bodies, streams, `meta.json`, `result.json`, the archive) live only under `RUN/records/`. The transcripts root is given to the proxy explicitly, under `RUN-ws/attempt-NNN/`.
      - A task's workspace is copied into the records tree after the session, and its hidden check is written into the copy only.
      - `import.json` is deleted once imported; its SHA-256 is recorded.
      - Each run lists any record, answer key or hidden-check text found under its workspace tree. A test asserts there is none.
   6. **One task, one session.** A first turn with no session id, or a later turn that reports another session, aborts the task as an infrastructure failure.
   7. **Restart gate.** ho-t3 under arm 4 passes only when every `test_f_*` and every `test_c2_*` passes.
   8. **Gate inputs.**
      - **Over budget:** every arm-4 upstream body is counted with the pinned counter (`tokens.default().count_messages`) against the input budget for the expected `n_ctx` (24,320 at 32K).
      - **`--explain`:** it must exit 0, report 0 unexplained pairs, and report as many pairs as there are upstream calls after each session's first. A crash or a mismatch fails the input.
      - **Excerpt leaks:** scanned in every client request and every proxy response (front tap), the OpenCode export, and the transcript files. A leak is the exact text of a stored block (`excerpt_blocks.rendered`), or of one of its items from `[[excerpt …]]` to `[[/excerpt]]`. Text that only quotes an excerpt marker is counted as an echo, which is reported and is not a gate failure.
   9. **Provenance.**
      - Every run records the git commit and whether the tree is dirty; held-out needles and tasks refuse a dirty tree.
      - Strata's `/props` `n_ctx` and build are read before and after each history and task. A run refuses to start, or aborts, unless `n_ctx` equals `--expect-n-ctx` (default 32768; 65536 for the later 64K runs).
      - Held-out needles refuse any configuration other than `a4-d43`, and refuse `--questions`.
   10. **Import fidelity is enforced.** A first client body that differs from the history (beyond the `reasoning_content: ""` OpenCode adds), or prior turns not all archived as `client_import`, is an infrastructure failure under D44.7, and the history stops there. `needle.py preflight --set heldout` pushes every import through real OpenCode against the fake upstream (no proxy, no model, no Strata) and checks fidelity.
   11. **Aborts** in the task runner are `aborted: <reason>` in `result.json`, with exit code 3, and no check runs.
   12. **`deadline_s` 3600 is confirmed** (D45.4). Each upstream call records its upstream time, from dispatch after the gate to the end of the stream. Calls over 600 s are listed.
   13. **Proxy rejections are visible.** A front tap between OpenCode and the proxy records the proxy's own status and any in-stream error per request. A failed front call while every upstream call succeeded counts as a proxy rejection.
   14. **Reporting.**
      - `a4-d43` is in `report.py`'s `ORDER`.
      - `report.py --coding RUN` prints each run's constraint adherence next to the stub's own check result, followed by the D44.5 verdict: arm 4's successes against arm 1's over ho-t1..t5, plus the restart gate. A missing or aborted run counts as a failure.
   15. **Environment allowlist** (`oc_harness.ENV_ALLOW`, details in `docs/harnesses.md`). `APPDATA` and `LOCALAPPDATA` stay real, because the system `python` (Python install manager) keeps its installs there. The hidden check's interpreter is resolved on the cleaned PATH, because Windows resolves a bare `python` on the parent's PATH.
   16. **The taps pass a client's disconnect along (R24-A, 2026-10-25, before any held-out run).**
       - `needle.Tap` watches `receive()` for `http.disconnect` while it relays. When the client leaves first, it stops relaying and closes the stream it was reading, and records `client_disconnect`. The server does not fail a send to a client that left, so without this the tap read the stream to the end.
       - In the front tap, OpenCode killed at the turn timeout reaches the proxy as a client cancel, so D13.1 lets the next request omit the cut-off turn. In the upstream tap, the proxy's cancel reaches Strata, which releases the slot on disconnect (`docs/probes/strata.md` §9).
       - A disconnected call is a client cancel (`client_cancels` per turn), neither a proxy rejection nor an upstream failure. A non-200 status or an in-stream error still counts.
       - Test: `tests/test_eval_taps.py` (client → front tap → proxy → upstream tap → fake upstream; the cut-off stream closes, the resend gets 200).
       - D44.1: the held-out configuration is `a4-d43` at the commit that carries this fix. It changes `eval/` only.

## D46 — Added-token strings inside messages count as text (R23-A)

The S11 smoke runs found that the counter tokenized `</tool_call>`, `<think>` and the other added-token strings as single tokens when a message quoted them. Strata encodes them as text. OpenCode's `tool.input-json` error quotes the model's unparsable call, `</tool_call>` included, so ordinary sessions hit this. Each request then drifted, and the local count ran low, the unsafe direction for the budget.

1. **The counter mirrors `mark_think_literals`.** `tokens.mark_literals` marks the same strings, fields and exceptions as Strata (`docs/probes/strata.md` §4). It runs after `preprocess_messages`, as Strata marks after `openai_to_messages`. The encoder emits each added token the template wrote as that token, and everything between them as plain text: the marks turn back into the tag text, and that text is encoded with a copy of the pinned tokenizer that has no added tokens.
2. **Evidence.** `eval/probes/p14_literal_tags.py` covers all 33 added tokens in every role, plus the three exceptions, against live Strata. That is 171 cases, and the local count now matches each one (`tests/test_strata_tokens.py`).
   - Rejected: marking only Strata's named literal tags. The probe shows the FIM, audio and TTS tokens are text too, so this GGUF's control tokens are every added token outside those tags.
3. **Layout.** `<|im_start|>` inside a message is text, so it no longer cuts the render. Each template turn is one fragment, and the per-message cut count (`_cuts`) is gone.
4. **Unchanged.**
   - `count`, `count_cached` and `encode` still tokenize the text they are given with the added tokens live. They size previews, the recent window and excerpt charges, and count the probes' golden renders.
   - A message that quotes a tag is therefore estimated a few tokens low there. The assembled request is still counted exactly, so the budget holds.
   - Excerpt payloads are still escaped (contract §11, Delimiters). Strata now makes such text inert anyway; the escaping still keeps a payload from closing its block.
5. **Cost.** On a 150 KB history (dev-h1's import), the marking scan adds about 1.5 ms per count. With a tag present the whole count takes about 6.5 ms cold, against 2.7 ms without.
6. **D44.1 amended before any held-out run.** The held-out configuration is `a4-d43` at the commit that carries this fix and D47. No held-out history or task has run, and the fixes change counting, not anything model-facing.
7. **Fixes from the cache audit of this change.**
   - **Mark before the drop.** Strata marks the whole message list before #843 drops empty turns. A tag that sits only in a dropped turn still switches marking on, and then any private-use mark character elsewhere is turned back into tag text. The counter now does the same (live: 64 tokens, where marking after the drop gave 66).
   - **Dict keys cut.** Strata does not mark keys, so `<|im_start|>` in a tool parameter name or a parsed argument key is a real token and cuts the render. `_key_cuts` counts those, so the layout stays mapped. The counts were already right.
   - **Counter revision.** `tokens.COUNTER_REVISION` ("c3") is part of every call's identity. After a restart, a call recorded by an older revision can fail to re-render to its recorded count; `explain` now classifies such a pair as `model_template_change` instead of `unexplained` (contract §10).
   - **Test oracle.** `test_cacheacct_http.encoded` encodes the marked render, so a future tag case gets the right expected LCP.

## D47 — No Unicode normalization before counting

The cache audit of D46 noticed that Strata's tokenizer (`tools/strata_tokenizer.py`, built from the model pack's vocab and merges) has no normalizer, while the pinned `tokenizer.json` declares NFC. `eval/probes/p15_nfc_count.py` confirmed it live: text whose NFC form differs counted low locally, by 1 for a combining accent and by 8 for decomposed Hangul. That is the unsafe direction for the budget.

1. **The counter loads the pinned tokenizer with its normalizer removed.** The pinned bytes and their hash are unchanged; only the in-memory copy differs. The pre-tokenizer and the model are unchanged, and the counts now match on every probe case.
2. **Canary.** `decomposed_text` (Strata: 69 tokens, recorded 2026-10-25) makes a server that does normalize fail the pin check at startup.
3. **Found before any held-out run.** It is part of the counter revision `c3`.
