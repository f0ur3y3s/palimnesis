# OpenCode 2.1.4 transcript-directory access probe (A1 harness capability gate)

Oct 25, 2026, 02:58–03:10 UTC.

**Question.** Can OpenCode 2.1.4, as configured for Palimnesis (`integrations/opencode/opencode.json`, `plugins/palimnesis.ts`), have the model search and read files in a directory outside its working directory and outside any git repo, without unexpected permission prompts or denial? A1 "Harness capability gate", `docs/plans/phase3.md` §4.

**Setup:**

- OpenCode `v2.1.4` (`opencode --version`), the Bun binary at `%APPDATA%\npm\node_modules\@opencode\cli\bin\opencode.exe`.
- Palimnesis `serve --passthrough --capture-dir` on `127.0.0.1:9051`. The repo was at `8428f48` (phase-2 + D25) when the proxy started. `394cd32`, a docs-only plan commit, landed during the runs. The working tree also held uncommitted `src/` changes from concurrent work (`search.py`, `store.py`, `recall.py`). Passthrough mode does not archive or rewrite, so those changes should not affect this probe [unverified].
- Strata `0.1.48` at `192.168.1.173:8080`, model `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536, default temperature 1.0. Runs were strictly sequential, and `/status` showed idle after each one. The prompt cache was warm across runs: every run used a new session but the same system prefix.
- Isolation was the same as R9/R10 (`eval/fixtures/opencode-2.1.4/view-live/scripts/oc_turn.py`):
  - isolated `HOME`/`USERPROFILE`/`OPENCODE_TEST_HOME`, XDG, `TEMP`/`TMP` and `OPENCODE_CONFIG_DIR`;
  - `OPENCODE_DISABLE_PROJECT_CONFIG` and the other `OPENCODE_DISABLE_*` flags;
  - `opencode run --standalone --format json`, plus `service.json` `{"disabled": true}`;
  - a fresh git repo as cwd and `PWD`;
  - stdin at EOF.
  - The user's `~/.config|.local/share|.local/state|.cache/opencode` kept their Oct 23 mtimes. Only the user's own pre-existing `opencode serve --service` (PID 17040, started 2026-10-23) was running afterwards.
- Script: `eval/probes/opencode_transcript_probe.py`.
  - A probe-only observer plugin, `eval/probes/opencode_transcript_observer.ts`, logs every permission evaluation from the `permission` `evaluate` hook. The hook fires after the rules are evaluated and before `opencode run` answers an ask, so asks are visible even under `--auto`, which approves them silently.
  - The observer never changes `effect`.
- Raw logs, captures and `summary.json` are in the session scratchpad: `…\scratchpad\oc-transcripts\` and `…\scratchpad\oc transcripts é\`.

**Fixture.** A stand-in for `%LOCALAPPDATA%\palimnesis\transcripts\<session>`: `<ROOT>\localappdata\palimnesis\transcripts\ses_probe0001\`. It is a sibling of the cwd repo `<ROOT>\work`, outside every git repo (`git rev-parse` fails there), and outside `TEMP`.

- `index.md`: 20 one-line entries. Entry 7 says `turn-0007.md | 80 lines | topic: HELIOTROPE`.
- `turn-0001..0020.md` (80 lines each). Line 42 of `turn-0007.md` is `NEEDLE: vault combination 7-31-4-19, token QX-5521-VIOLET`.
- `turn-0013.md`: 3,000 lines, 202 KB. Line 2417 is `ANCHOR-OSPREY…`; line 2418, `ANSWER: copper-kestrel-8812`, does not contain the grep term.
- All files are LF. A first run with CRLF files (a0) showed `\r` leaking into grep previews.

**Labels:** as in `opencode_live.md`. **[verified]** means observed in these runs. **[source]** means read from the `v2.1.4` source tarball, which was treated as data and not executed. **[unverified]** means inferred. Source paths are relative to `packages/`.

## 1. How the tools gate paths outside the project [source]

**`external_directory` permission.**
- `core/src/file-access.ts` `resolve` classifies a target as internal when it is inside the Location directory, or inside the project worktree when the worktree is not a drive root.
- Anything else carries an `external_directory` authorization. Its resource is `<target dir>/*` with forward slashes: the file's parent, or the directory itself.
- `authorizeExternal` asserts it once per tool call, deduplicated by directory.

**Which tools call it:**

| Tool | external_directory check | Own permission (action → resource) |
| --- | --- | --- |
| `read` | `authorizeRead` checks the target first | `read` → the absolute path (forward slashes) |
| `grep` | its `path`, absolute paths accepted (`RelativePath` is only a brand) | `grep` → the **pattern**, not the path |
| `glob` | its `path`, as a directory | `glob` → the **pattern** |
| `shell` | **only the cwd and `cd`/`pushd`/`Set-Location` targets** (`core/src/shell/parse.ts` `CWD`, `tool/plugin/shell.ts` `prepare`) | `shell` → the command text |
| `edit`/`write`/`patch` | yes | `edit` |

So `external_directory` and `read` are the only path-keyed actions for reading. `grep`/`glob`/`shell` rules match patterns or command text, so a path-scoped rule for them is meaningless.

**Default effect is allow for the primary agent.**
- `schema/src/agent.ts` `Info.default` gives every agent created through the editor `[{*,*,allow}, {read,*.env,ask}, {read,*.env.*,ask}, {read,*.env.example,allow}]`.
- `core/src/plugin/agent.ts` gives `build` (the default) only an extra `question` allow.
- So `external_directory`, `read`, `grep`, `glob` and `shell` all evaluate to **allow**.
- The built-in "ask" fallback in `core/src/permission.ts` `evaluate` applies only when no rule matches, and `*` always matches.
- Exceptions: `explore` adds an explicit external_directory allow. `title`/`summary` deny everything.

**Rule evaluation** (`core/src/permission.ts`):
- Rules are `agent defaults + config permissions (in document load order) + per-agent config permissions + session rules`, then "always" approvals saved in the DB per project.
- The **last** matching rule wins (`findLast`). A deny anywhere among the configured rules short-circuits before saved approvals.
- Config `permissions` are appended to every agent (`core/src/config/plugin/agent.ts`), so a later rule in the user's own config can override an earlier Palimnesis rule.

**Glob syntax** (`core/src/util/wildcard.ts`):
- Both sides have `\` turned into `/`.
- `*` becomes `.*`, which crosses `/`, so `<root>/*` already covers every depth and `<root>/**` is equivalent. `?` matches one character.
- Everything else is literal. The match is anchored, and the `i` flag is set **on win32 only**, so matching is case-insensitive there.
- `~`, `~/…` and `$HOME/…` are expanded against `Global.Path.home` (`OPENCODE_TEST_HOME ?? os.homedir()`), but only for the `external_directory`, `read` and `edit` actions (`expandHome`).
- `%LOCALAPPDATA%` and `$LOCALAPPDATA` are **not** expanded.

**Asks without a human** (`cli/src/run/noninteractive.ts` `replyPermission`):
- Without `--auto`, `opencode run` prints `! permission requested: <action> (<resources>); auto-rejecting` to **stderr**.
- It then rejects with feedback ("This non-interactive run cannot ask the user for permission… Continue without this action."). The tool fails as model-visible output and the run continues; only `--compatibility v1` aborts.
- With `--auto` (also `--yolo`, `--dangerously-skip-permissions`), the reply is `once`: approved, with nothing printed.
- The JSON event stream carries no permission events in either case.

**TUI** (`tui/src/util/permission.ts`). The TUI uses the same Permission service, so with the default rules it shows nothing. Under an ask rule it shows `← Access external directory <dir>`, lists the resources, and offers once/always/reject. "Always" stores `<git root of that dir, else the dir>/*` per project (`file-access.ts` `save`, `permission.ts` `reply`). Not exercised live.

**Tool limits:**
- `read` (`core/src/tool/read-filesystem.ts`):
  - At most 2,000 lines and 50 KB per page, and 2,000 characters per line.
  - Pages end with `[Output truncated. Continue reading with offset: N]`.
  - External reads skip `AGENTS.md` discovery (`tool/plugin/read.ts`), so a transcript dir cannot inject instructions that way.
- `grep`:
  - Ripgrep with `--hidden --no-config --glob=!**/.git/**`, 100 matches by default, and a 30 s timeout.
  - The model sees absolute paths in Windows form, even when it passed forward slashes.
  - Because of `--hidden`, grepping the transcript **root** would also search a `.staging\` directory there. Ripgrep's `.ignore` files are still honoured, since there is no `--no-ignore` [unverified live].

## 2. Live runs [verified]

Each run was one fresh session asked to do one lookup.
- **Index task:** "Search `<dir>/index.md` for HELIOTROPE, then read only lines 40-44 of the matching turn file … quote the line that starts with NEEDLE."
- **Oversize task:** "… use grep to find ANCHOR-OSPREY in `turn-0013.md`, then read at most 5 lines with offset/limit and quote the line after the anchor."
- **Paginate task:** read only, without grep.

Model round trips are proxy captures; a lookup takes 3 (grep, read, answer).

| Run | Permissions added | `--auto` | Tools (args) | Asks (observer / stderr) | Needle | Round trips, time |
| --- | --- | --- | --- | --- | --- | --- |
| a1 | none (shipped config) | no | grep(path=index.md), read(turn-0007, offset 40, limit 5) | 0 / 0 | yes | 3, 22 s |
| a2 | none | yes | same | 0 / 0 | yes | 3, 18 s |
| a3 oversize | none | no | grep(path=turn-0013.md) → line 2417; read(offset 2417, limit 5) | 0 / 0 | yes | 3, 19 s |
| a4 backslash prompt | none | no | same as a1, paths with `\` | 0 / 0 | yes | 3, 26 s |
| b1 | allow `external_directory` + `read` on `<transcripts>/*` | no | same as a1 | 0 / 0 | yes | 3, 18 s |
| b2 | same as b1 | yes | same as a1 | 0 / 0 | yes | 3, 18 s |
| c1 **control** | `external_directory * ask` | no | grep ✗, glob ✗, read ✗ (rejected); then shell `grep -n … index.md`, `sed -n '40,44p' …turn-0007.md` | **3 / 3** | yes (via shell) | 7, 42 s |
| c2 control | `external_directory * ask` | yes | grep, read | **2 / 0** (approved silently) | yes | 3, 23 s |
| d1 | c + allow `C:\USERS\…\TRANSCRIPTS\*` (upper case, backslashes) | no | same as a1 | 0 / 0 | yes | 3, 21 s |
| d2 oversize | same as d1 | no | same as a3 | 0 / 0 | yes | 3, 18 s |
| d3 backslash prompt | same as d1 | no | same as a4 | 0 / 0 | yes | 3, 23 s |
| e1 | c + allow `~/../localappdata/palimnesis/transcripts/*` | no | same as a1 | 0 / 0 | yes | 3, 19 s |
| f1 | d, root `…\oc transcripts é\…` (space, non-ASCII; the rule has `É`) | no | same as a1 | 0 / 0 | yes | 3, 40 s |
| f2 | none, same root as f1 | no | same as a1 | 0 / 0 | yes | 3, 19 s |
| a5 paginate | none | no | read ×3, no limit: pages at 1, 779, 1547 | 0 / 0 | **no**: Strata 400 | 4, 142 s |

What the runs show:

- **Default access.** The observer logged `external_directory`, then `grep` or `read`, all `allow`, on every non-control run. No JSON error events occurred, and no tool had `status: error` outside c1.
- **Prompt and rule forms.** Forward-slash and backslash prompts both worked. The rule forms that matched were upper-case with backslashes, `~` with a `..` segment, and a path with a space and `é`/`É`. This confirms the win32 case-folding, slash normalization and `~` expansion from §1.
- **The controls prove the detector.** In c1 an ask produced both the observer record and the stderr line, and the rejection reached the model as a tool error. The model then **routed around it with the `shell` tool** (Git Bash `grep`/`sed` on absolute paths). The `shell` action was allowed because shell path arguments are not `external_directory`-checked. In c2, `--auto` approved the asks with no visible trace except the observer.
- **Pagination cost.** In a5 the model paged correctly from the truncation notice. Each 50 KB page (about 778 lines of hex-dense rows) cost about 28k prompt tokens (5,095 → 33,003 → 61,914). The fourth request was 91,134 tokens, over `n_ctx` 65,536, and Strata rejected it (the passthrough does no budgeting). Whole-file reads of large turn files are not a viable recall path at this context size.

## 3. Findings

1. **No permission prompt or denial occurs with the shipped config** [verified a1–a5, f2; source §1]. OpenCode 2.1.4's `build` agent allows `external_directory`, `read`, `grep`, `glob` and `shell` by default, with or without `--auto`.
2. **The minimal config needed is none.** For robustness against stricter user rules, ship explicit allow rules **last** in `permissions`. Only two actions take path resources:

   ```json
   { "action": "external_directory", "resource": "<root>/*", "effect": "allow" },
   { "action": "read", "resource": "<root>/*", "effect": "allow" }
   ```

   - `<root>` should be the absolute transcripts root written by `palimnesis opencode-config`, e.g. `C:/Users/<user>/AppData/Local/palimnesis/transcripts`.
   - Forward or back slashes and any case work on Windows. `/**` is equivalent to `/*`.
   - `~/AppData/Local/palimnesis/transcripts/*` also works, but only when `%LOCALAPPDATA%` is the default under the profile, so prefer the absolute path.
   - Do not add path rules for `grep`/`glob`/`shell`; their resources are patterns and commands. Do not allow `edit`.
   - These rules do not override a later user rule (last match wins) or a user deny. Saved "always" approvals cannot override a configured deny.
3. **Recommended location:** keep `%LOCALAPPDATA%\palimnesis\transcripts\<session-dir>\` as planned (phase3 §3). It is outside every repo and every cwd, works with spaces and non-ASCII, and needs no rule by default. Point the addendum at the **session directory**, not the root, so grep's `--hidden` does not reach `<root>\.staging\`. Write LF.
4. **The bounded recipe works.** The exact line came back in 15 of 15 non-paginate lookups: the table, plus a0 (the CRLF run, same as a1). In 14 of them the model used grep → `read(offset, limit)` with 2 tool round trips; c1 used shell. Unbounded paging overflowed the 64K context in 3 pages. The addendum must require grep first and a `limit`, and `index.md` must stay small.
5. **Execution environment caveat** (from `opencode_live.md` §1). If the user's OpenCode attaches to the shared background service (no `--standalone`, no `service.json` disable), that service's config and permissions apply, not the Palimnesis config directory's. The default allow still holds unless the user's own config adds `external_directory`/`read` ask or deny rules [source; not exercised].
6. **Security note.** `external_directory` is not a confinement boundary for reads: shell commands with absolute path arguments bypass it (c1). That does not affect this gate, but the projection's privacy rests on filesystem ACLs (phase3 §3), not on OpenCode rules.

## 4. Verdict

**PASS** for OpenCode 2.1.4 with the shipped Palimnesis config (`opencode run` with or without `--auto`). The two explicit allow rules above are recommended defence-in-depth, ordered last. The O5 fallback is not needed.

Remaining for the phase 3 §4 probe, not covered here:
- the TUI path, live;
- the real `%LOCALAPPDATA%` path;
- the t1 projection format and the a3 addendum;
- the deterministic fake-upstream run (step 3);
- view-on (non-passthrough) Palimnesis.
