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
