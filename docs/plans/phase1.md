# Phase 1 plan: Durable archive and transcript reconciliation

Planner output from 2026-10-24, after `phase-0`. The R4 carry-overs (lifespan guard, capture tests, live cancel through the proxy) were closed in `f3b4373` and R5. Decisions are recorded at the end as the user resolves them.

## Constraints found while planning

- Fault fixtures store request bodies already parsed into JSON objects. Byte-exact raw-archive tests use `eval/fixtures/opencode-2.1.4/live/exchanges/*/request.body`: 10 real bodies, 20–45 KB each.
- OpenCode's system prompt contains today's date and an `<env>` block. Under strict reconciliation, resuming a session on a later day would change message 0 (decision 5).
- `tools` (about 10.8 KB) follows `messages`, so every transition has about 10.9 KB of common suffix (decision 7).

## Modules

Two test seams: HTTP through the fake upstream, and pure or store-level functions.

**`palimnesis.store`**
- `Store.open(path, synchronous="FULL")`. Each connection sets WAL, `synchronous`, `foreign_keys`, `recursive_triggers` and `busy_timeout`, and reads them back; any mismatch refuses startup.
- Migrations are versioned with `PRAGMA user_version`.
- One writer thread runs bounded `BEGIN IMMEDIATE` transactions (`await store.write(fn)`); there is a separate read connection.
- An authorizer denies DDL outside migrations, and a lock file allows one process per database.
- `diagnostics()` reports the active modes.

**`palimnesis.rawdelta` + `RawArchive`**
- Pure codec: `encode(parent, body, variant)` and `decode(delta, parent)`.
  - v1 stores prefix length and suffix bytes.
  - v2 stores prefix length, the changed middle and the suffix length.
  - Bounds, total length and SHA-256 are verified on decode.
- Snapshots are taken when there is no usable parent, at depth 32, on a system or tool change, and when the delta is not smaller than a snapshot.

**`palimnesis.chat`**
- `parse(body) -> ChatRequest` produces typed messages with blocks (`text`, `reasoning`, `tool_call`, `tool_result`) and an envelope holding key order, `content` form and top-level fields. It raises `Unsupported(code, field)` or `InvalidBody`.
- `render(view, client_messages)` splices internal occurrences into the client's own message objects.

**`palimnesis.transcript`**
- Pure `reconcile(resend, visible)` returns one of: `Extend`, `Prefix`, `ContinueAfterPartial`, `SupersededPartial` or `Divergence(index, reason)`.
- `model_view(branch)` returns the visible and internal occurrences.

**`palimnesis.ledger`**
- `fingerprint_v1`.
- `accept(...)` is one transaction covering the raw body, request row, occurrences and blocks, aliases, the idempotency binding and the attempt.
- Duplicate classification.
- `parse_retry_hint`.
- Startup recovery appends `attempt_abandoned(restart)`.

**`palimnesis.relay`**
- An incremental OpenAI SSE parser that keeps the exact bytes of each event.
- A batcher flushes at ≥ 25 ms, ≥ 16 KiB or a terminal event, over a bounded queue. It commits each batch before forwarding its original bytes.
- Comments are forwarded promptly; the finish chunk is held until `[DONE]`.
- A failure after the 200 sends an in-stream error event, and every streaming 200 carries `x-should-retry: false`.
- Non-streaming responses are committed as `prepared_responses` before delivery.

**`palimnesis.addresses`**
- `issue` assigns a stored alias that is never reassigned.
- `resolve` returns `Hit`, `Ambiguous(candidates)` or `Unknown(suggestions)`.

`api.Proxy` routes `POST …/chat/completions` to the archive path unless `--passthrough` is set; metadata GETs pass through.

### Schema sketch

**Immutable tables** (insert-only; `BEFORE UPDATE` and `BEFORE DELETE` triggers abort):
- `sessions`, `branches`
- `raw_bodies(format, base_raw_id, depth, prefix_len, suffix_len, payload, total_len, sha256)`
- `requests(…, raw_id, fp_version, fingerprint, stream, idem_key, visible_parent_occ, retry_hint, envelope)`
- `idempotency_bindings` (PK session, branch, key)
- `occurrences(branch_id, seq, parent_occ_id, role, view ∈ {both, visible, internal}, source ∈ {client, generated, client_import, internal_tool}, request_id, generation_id, envelope, content_sha256)`
- `blocks(occ_id, idx, kind, encoding, meta)`, `segments(block_id, seq, bytes)`
- `attempts`, `generations`, `visible_map`
- `events(kind ∈ accepted_input, attempt_started, upstream_headers, batch_committed, delivery_started, delivery_progress, delivery_completed, delivery_failed, cancelled, attempt_failed, attempt_abandoned, turn_complete, response_prepared, context_version, partial_acknowledged)`
- `prepared_responses`, `aliases`

`recursive_triggers=ON` stops `INSERT OR REPLACE` from deleting rows silently.

**Derived and mutable:** `branch_heads(branch_id, tip_occ_id, active_request_id, version)`, the delivery projection, and `fts_blocks` (FTS5 external content, rebuildable).

## Requirement → test

Seams:

| Code | Seam |
| --- | --- |
| H | HTTP through the fake upstream, with the DB in `tmp_path` |
| P | Pure function |
| S | Store against a real SQLite file |
| X | Subprocess with crash points |
| E | `eval/` measurement |
| D | Docs |

Fixtures:

| Code | Fixture |
| --- | --- |
| L | Live exchanges |
| Fb | Fault-run shapes |
| SSE | `sse_oa_*.sse` |
| NS | `nonstream_oa_*.json` |
| HID | New hidden-event fixtures |
| SYN | Literal test values |

| Requirement | Tests | Seam / fixture |
| --- | --- | --- |
| GL1: retries don't duplicate logical events | `test_failed_no_output_resend_adds_attempt_not_occurrences`, `test_idempotent_retry_adds_no_occurrences` | H / L0, SYN |
| GL1: identical occurrences stay distinct | `test_identical_user_text_in_two_turns_gets_two_addresses`, `test_identical_tool_results_in_one_request_are_distinct` | H / SYN |
| GL1: same key with different payload, settings or mode conflicts | `test_same_key_different_messages_409_idempotency_conflict`, `…_different_temperature_…`, `test_same_key_different_stream_mode_conflicts` | H / SYN |
| GL1: concurrent matching keys | `test_concurrent_same_key_gets_409_in_progress_single_upstream_call` | H |
| GL1: completed non-streaming replay makes no inference | `test_completed_nonstream_key_replays_exact_bytes_without_upstream` | H / NS |
| GL1: repeated streaming key | `test_repeated_streaming_key_409_streaming_replay_unsupported_no_upstream` | H / SSE |
| GL2: byte-for-byte reconstruction | `test_live_bodies_round_trip_through_archive`, `test_delta_unchanged_empty_prefix_insert_delete_utf8_split` (both variants), `test_corrupt_base_raises_not_wrong_bytes`, `test_missing_parent_raises`, `test_snapshot_every_32`, `test_snapshot_on_tool_change`, `test_snapshot_when_delta_not_smaller`, `test_backup_api_copy_reconstructs` | P+S / L, SYN |
| GL2: growth report | `eval/bench_archive.py` (10 → 200 turns, repetitive and random, per-table bytes, FTS and index overhead, reconstruction time by depth, v1 vs v2) | E |
| GL2: admission limit | `test_oversized_body_rejected` (413); disk budget deferred to Ph8 | H |
| GL3: no merging | `test_identical_first_requests_in_two_sessions_stay_separate`, `test_archive_path_rejects_mismatch_before_archiving` | H / L0 |
| GL3: divergence | `test_edited_earlier_user_message_409_history_divergence`, `test_truncated_history_resend_with_new_user_409`, `test_assistant_not_generated_by_palimnesis_409` | H / L mutated |
| GL3: conflicting concurrent requests | `test_second_different_request_while_active_409_session_busy` | H |
| GL4: exact block round-trip | `test_blocks_round_trip` (empty, null vs absent, multibyte, CRLF, lone surrogate, tool args, reasoning), `test_live_messages_round_trip_json_equal` | P+S |
| GL4: aliases | `test_forced_hash_collision_extends_second_alias_first_unchanged`, `test_ambiguous_prefix_returns_candidates`, `test_unknown_alias_suggests_never_substitutes`, `test_alias_scoped_to_session` | S |
| GL5: immutability | `test_update_delete_rejected_on_each_immutable_table`, `test_insert_or_replace_and_upsert_rejected`, `test_raw_sqlite_connection_without_authorizer_still_blocked`, `test_drop_denied_by_authorizer` | S |
| GL6: crash after input commit | `test_crash_after_input_commit_then_restart` | X / L0 |
| GL6: crash around response preparation | `test_crash_after_nonstream_prepared_before_delivery`, `test_crash_after_batch_k_commit_before_forward` | X |
| GL7: hidden events | `test_reconcile_with_hidden_chain_extends_without_dup` (P), `test_followup_upstream_body_contains_hidden_events_once_in_order` (H) | HID |
| §3: unsupported rejected before acceptance | `test_unsupported_feature_rejected_nothing_archived` | H |
| §3: EOF without terminal is a failure | `test_passthrough_truncated_stream_closes_abruptly`, `test_archive_eof_without_done_ends_with_error_event_turn_incomplete`, `test_finish_then_eof_without_done_is_failure` | H / SSE truncated |
| §4: one serialized branch | `test_branch_mutations_serialized_per_session` | H |
| §5: retry hints | `test_retry_hint_parsed_0_100_else_ignored`, `test_retry_header_does_not_change_fingerprint` | P+H |
| §5: rewritten streams | `test_streaming_200_has_should_retry_false`, `test_upstream_reset_mid_stream_yields_error_event`, `test_client_receives_upstream_bytes_unchanged_for_complete_streams` | H |
| §5: status rows for Ph1 | `test_keyless_outstanding_409`, `test_keyless_completed_absent_409_ambiguous_retry`, `test_upstream_5xx_before_headers_should_retry_false`, `test_input_commit_failure_503_archive_unavailable`; 429 and 504 deferred to Ph3 | H |
| §6: binding scope and timing | `test_same_key_in_other_session_is_independent`, `test_binding_committed_before_upstream_called`, `test_unknown_key_treated_as_new` | H |
| §6: fingerprint canonicalization | `test_fingerprint_key_order_insensitive`, `test_1_vs_1_0_differ`, `test_no_unicode_normalization`, `test_stream_and_stream_options_excluded`, golden hex for L0 | P |
| §6: new identical user turn | `test_same_user_text_after_new_parent_is_new_occurrence` | H |
| §11: pragmas | `test_pragmas_read_back_on_writer_and_reader`, `test_normal_mode_reported_in_diagnostics`, `test_mismatched_pragma_refuses_start` | S |
| §11: commit order | `test_input_committed_before_upstream_sees_request`, `test_batch_committed_before_client_receives_it`, `test_partial_not_marked_complete` | H |
| §11: off the event loop | `test_db_locked_by_other_connection_does_not_block_event_loop` | H+S |
| §11: storage failure | `test_commit_failure_mid_stream_stops_forwarding_closes_upstream` | H |
| §11: provenance | `test_occurrence_role_source_recorded`; recall deferred to Ph3 | S |
| FTS derived | `test_fts_indexes_inserted_blocks`, `test_fts_delete_and_rebuild_restores_results` | S |
| Delivery ledger | `test_delivery_events_sequence_stream`, `test_client_disconnect_records_cancelled_and_closes_upstream` | H |
| Continue and length | `test_continue_flattened_partial_maps_to_archive`, `test_length_followups_extend` | P+H / Fb |
| FULL commit latency | `eval/bench_commit.py` | E |
| Keepalive relay (R4) | `test_upstream_comments_forwarded_promptly_on_archive_path` | H |
| Docs | contracts §5 rows, capabilities, harnesses, decisions, results | D |

## Slices

| # | Slice | Depends on |
| --- | --- | --- |
| 0 | Probe: OpenCode's next prompt after a Palimnesis-ended partial stream | — |
| 1 | Store: open, pragmas, writer thread, triggers, authorizer | — |
| 2 | Raw delta v1 and v2 + `RawArchive` | 1 |
| 3 | `chat.parse`/`render`, rejection list, live round-trip | — |
| 4 | Tracer: one streaming live exchange end to end | 1–3 |
| 5 | Multi-turn L0→L9 reconciliation, no-merge, identical occurrences, import | 4 |
| 6 | Divergence, `session_busy`, system-context versions | 5 |
| 7 | Terminal handling: EOF, RST, held finish, non-200, disconnect, commit failure | 4 |
| 8 | Keyless duplicates, retry hint | 5, 7 |
| 9 | Non-streaming path with prepared responses | 4 |
| 10 | Idempotency keys | 8, 9 |
| 11 | Partials: Continue, superseded, length | 7, 0 |
| 12 | Hidden-event fixtures and model-view splice | 5 |
| 13 | Addresses and aliases | 5 |
| 14 | FTS and rebuild | 4 |
| 15 | Subprocess crash points and restart recovery | 7, 9, 11 |
| 16 | Measurements: `bench_archive`, `bench_commit`, live OpenCode two-turn run in archive mode | 2, 4, 15 |
| 17 | Docs | all |

## Risks

- **Next-turn shape after a Palimnesis-ended partial is unverified.** Slice 0 probes it.
- **FULL fsync latency on Windows.** `bench_commit` sets the batch defaults before any weaker durability option is considered.
- **Re-serialization drift.** Mitigated by the verbatim message splice and JSON-equality tests; byte equality is reported as a diagnostic.
- **Trigger bypass.** Raw DDL from outside the app's connections cannot be stopped by triggers; this limit is documented.
- **Keepalives come only from Strata's ~10 s comments until Ph3.** With `x-should-retry: false`, an OpenCode idle timeout becomes final.
- **The hidden-event schema predates recall.** HID fixtures must copy real Strata tool-call and continuation shapes.
- **One writer thread serializes all commits.** Measure it.
- **Reasoning dominates archive size.** Growth reports separate it.
- **Crash tests on Windows** need deterministic `os._exit` points and explicit connection closing.

## Decisions

Resolved as D10 in `docs/decisions.md`.
