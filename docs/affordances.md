# Affordances

Versioned model-facing text: stub formats, the system addendum and recall tool descriptions (v1_plan "Model-facing recall affordances", D14.5). The texts live in `src/palimnesis/affordances.py` (`REGISTRY`, `ACTIVE`), and every id there has an entry here (`tests/test_affordances.py`).

Rules:
- A version's text is frozen once it renders anywhere. A wording change is a new id.
- Switching versions is a one-time, recorded prefix invalidation (contracts §10, "view policy/format version change").
- Addresses are `§ALIAS.N` (block N of an occurrence) or `§ALIAS` (the whole occurrence). The database stores aliases without `§`.
- Placeholders in braces are filled by `palimnesis.stubs`. Previews are exact substrings of the archived text, cut on safe Unicode boundaries.

**Active in Phase 2:** stub `s1`, addendum `a0`, no tool descriptions (recall tools arrive in Phase 3).

## Stub formats

### `s1`

Phase 2's format, rendered by `palimnesis.stubs`. Caps: 192/96 tokens for tool results, 64/32 for reasoning.

```
[palimnesis s1 §{alias}.{block} {kind} · {tokens} tok · {lines} lines · sha {sha6}]
{head preview}
…[{omitted} tok not shown]…
{tail preview}
[archived exactly; not shown]
```

Example: `[palimnesis s1 §K7Q2MX.0 tool_result · 18,432 tok · 412 lines · sha 3f9a1c]`.

Details:
- `kind` is `tool_result` or `reasoning`.
- `tokens` is the count of the whole text, with thousands separators.
- `lines` counts newlines, plus one for an unterminated last line. The singular is `1 line`.
- `sha6` is the first six hex digits of the text's SHA-256 (WTF-8 bytes when the text has lone surrogates).
- `omitted` is the count of the hidden middle.
- Previews snap to whole lines when a line break falls inside them. A preview that does not end a line gets a separator newline.
- A text that fits both caps is shown whole, after the header, with no marker or hint. Empty text is the header alone.
- The hint means the omitted part is archived exactly but is not shown. Phase 2 has no recall.

Collapsed forms:
- Bare reference: `§K7Q2MX.0`.
- Span note, one proxy-authored user-role message (D14.13): `[palimnesis s1 span §AAAAAA–§BBBBBB · 37 messages · 12,345 tok · archived exactly; not shown]`.

### `s2`

Phase 3 draft. Same layout as `s1`, with the hint `[archived exactly]`: content is recallable, but the stub does not say how.

### `s3`

Phase 3 draft: `s2` plus an inline recall hint naming the call that returns the omitted part.

```
[archived exactly · omitted part: palimnesis_recall(id="§{alias}.{block}", offset={head_length}, limit={omitted_length})]
```

`offset` is in code points. The unit of `limit` follows the Phase 3 `palimnesis_recall` contract (unresolved).

## System addenda

### `a0`

None: no addendum is rendered. Phase 2's active choice, because no recall tool exists yet.

### `a1`

The plan's starting addendum:

> Older content may appear as address stubs; use palimnesis_recall for exact details and catalog or search tools when the needed address is unknown.

### `a2`

Guided draft:

> Older content may appear as address stubs like §K7Q2MX.0; an address never changes meaning. When a stub's preview is not enough to act correctly, call palimnesis_recall with its address. When you need something old but have no address, page palimnesis_catalog or search with palimnesis_grep. Do not recall what the preview already shows.

## Tool descriptions

Drafts for the Phase 3 tools. The signatures follow v1_plan Phase 3. The full text of each version is in `affordances.py`.

### `t1`

Terse: one sentence per tool.

- `palimnesis_recall(id, offset?, limit?)`: Exact archived content for an address such as §K7Q2MX.0. Long items continue from next_offset.
- `palimnesis_catalog(cursor?, page?)`: Archived messages, 20 per page, oldest first; each line is §alias seq role kind tokens flags preview.
- `palimnesis_grep(query, mode, scope?, cursor?)`: Search archived content; mode is text (full-text) or regex (RE2). Results carry addresses.

### `t2`

Guided: what each tool returns, when to use it, how to continue, and what errors look like (an unknown address gets suggestions, never other content; regex is RE2 without backreferences or lookaround).

## Phase 3 A/B matrix

Copied from `docs/plans/phase2.md`. Defined in Phase 2 and run in Phase 3.

Arms:

| Arm | Stub | Addendum | Tool description |
| --- | --- | --- | --- |
| A | s2 head/tail | a1 | t1 terse |
| B | s3 (s2 plus inline recall hint) | a1 | t1 |
| C | s2 | a0 (none) | t2 guided |
| D | s1 (alias and size only) | a1 | t2 |

- **Data:** stratified development needles, labeled recall-needed and recall-unneeded situations, and 5 development coding tasks. Runs are paired, with prompts fixed per arm.
- **Metrics:** retention, appropriate recall, unnecessary calls, invalid ids, task success, added tokens, latency.
- **Selection rule:**
  1. Reject arms with an invalid-id rate above 5%.
  2. Rank by retention.
  3. Break ties by fewest unnecessary calls, then by tokens.
- **Freeze** the selected arm before held-out runs.

**Plan inconsistency, open for Phase 3 planning.** Arm D calls `s1` "alias and size only", but the Phase 2 module spec and golden test (`test_stub_s1_golden_text`) give `s1` head/tail previews. The format as built is `s1`, and the matrix above is kept verbatim. Before the A/B runs, either:
- give arm D a separate header-only version (a new id), or
- accept that D differs from A only in its hint and tool description.
