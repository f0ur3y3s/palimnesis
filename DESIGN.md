---
name: Palimnesis
description: A code-review diff of what a coding agent sends against the bounded view the model receives.
colors:
  ground: "#eef0ea"
  sheet: "#fbfbf8"
  ink: "#161914"
  ink-2: "#454b40"
  ink-3: "#6a7064"
  rule: "#d6dacf"
  del: "#fadbd4"
  del-gutter: "#e9a395"
  del-ink: "#8a2414"
  add: "#d6f0d8"
  add-gutter: "#8ccd95"
  add-ink: "#155a24"
  fold: "#f1e3b8"
  fold-ink: "#5f4709"
  quiet: "#e6e9e1"
  model: "#2456b8"
  cache: "#7b9bd6"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "36px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.02em"
    fontFeature: "tnum"
  lede:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.55
  body:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  body-sm:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 400
  button:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 600
  code:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 600
  label-sm:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
  code-label:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "12.5px"
    fontWeight: 600
rounded:
  pill: "999px"
  shell: "14px"
  button: "9px"
  button-small: "8px"
  control: "7px"
  bar: "3px"
spacing:
  page-x: "20px"
  page-top: "32px"
  page-bottom: "56px"
  stack: "26px"
  inset: "26px"
  inset-compact: "16px"
  row-x: "8px"
components:
  review-shell:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.shell}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "9px 16px"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "9px 16px"
  button-small:
    rounded: "{rounded.button-small}"
    padding: "6px 12px"
  segmented-option:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink-2}"
    typography: "{typography.label-sm}"
    padding: "4px 11px"
  segmented-option-pressed:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
  step-entry:
    textColor: "{colors.ink-2}"
    typography: "{typography.body-sm}"
    padding: "10px 16px"
  step-entry-current:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
  tag:
    backgroundColor: "{colors.quiet}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "1px 8px"
  status-ok:
    backgroundColor: "{colors.add}"
    textColor: "{colors.add-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "5px 11px"
  status-move:
    backgroundColor: "{colors.fold}"
    textColor: "{colors.fold-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "5px 11px"
  diff-row-del:
    backgroundColor: "{colors.del}"
    textColor: "{colors.ink}"
    typography: "{typography.code}"
    padding: "2px 8px"
  diff-sign-del:
    backgroundColor: "{colors.del-gutter}"
    textColor: "{colors.del-ink}"
    width: "22px"
  diff-row-add:
    backgroundColor: "{colors.add}"
    textColor: "{colors.ink}"
    typography: "{typography.code}"
    padding: "2px 8px"
  diff-sign-add:
    backgroundColor: "{colors.add-gutter}"
    textColor: "{colors.add-ink}"
    width: "22px"
  fold-span:
    backgroundColor: "{colors.fold}"
    textColor: "{colors.fold-ink}"
    typography: "{typography.code-label}"
    padding: "5px 12px 5px 22px"
  fold-same:
    backgroundColor: "{colors.quiet}"
    textColor: "{colors.ink-2}"
    typography: "{typography.code-label}"
    padding: "5px 12px 5px 22px"
---

# Design System: Palimnesis

## Overview

**Creative North Star: "The Review Diff"**

Palimnesis explains itself the way a developer already reads change. The session is a commit log, and each step is a diff with the agent's history on the left and the model's view on the right. The visual world is a code-review tool set on a pale green-grey sheet. Monospace hunks carry the content. Red removals, green additions and ochre folds carry the meaning. A single blue marks whatever belongs to the model.

Density is that of a review tool, not a landing page. Text is set at reading sizes, the diff is set in a mono at 13.5px, and the one large element on any step is the readout of two token counts. Changes show by default and unchanged runs fold away, so the eye goes to what moved. Surfaces are flat. Depth comes from two paper tones and 1px hairlines.

The system ships a light theme and a dark theme with the same token names. The page follows `prefers-color-scheme` and honours `data-theme="light"` or `data-theme="dark"` on the root element.

**Key Characteristics:**
- Review-tool grammar with split and unified diffs, sign gutters, line numbers and folds.
- Token counts sit where line numbers sit in a code diff.
- One accent (`--model`), reserved for the model's side.
- Diff colours always carry diff meaning and always come as a tint plus an ink.
- Flat surfaces, hairline rules, no shadows.
- One typeface family in two cuts, Atkinson Hyperlegible Next and Mono.

## Colors

A low-chroma green-grey neutral range carries the page, and four diff pairs plus one blue carry all the meaning.

### Primary
- **Model Blue** (`--model`): the only accent. It colours the "Model receives" figure, the current step number in the log, the model segment of the ruler, the token count on rows new to a step, links, text selection, the caret, the focus ring and the arrival flash on new rows.
- **Cache Blue** (`--cache`): a paler partner to Model Blue, used only for the cached part of the model's ruler bar. It reads as "the model's tokens, but already paid for".

### Secondary
- **Removal Rose** (`--del`), **Removal Gutter** (`--del-gutter`), **Removal Ink** (`--del-ink`): what the agent sends that the model's view leaves out. The tint fills the left cell, the gutter fills the sign column, and the ink colours the minus sign.
- **Addition Mint** (`--add`), **Addition Gutter** (`--add-gutter`), **Addition Ink** (`--add-ink`): lines only Palimnesis writes into the model's view, such as the addendum, notes, span line and excerpts. The same pair fills the "below H" status pill.

### Tertiary
- **Span Ochre** (`--fold`) and **Span Ink** (`--fold-ink`): a run of old turns collapsed into one span line. The same pair fills a status pill when the view changes ("past H", "below T").

### Neutral
- **Ground** (`--ground`): the page background, the toolbar band, the diff header row, section dividers, the reply row and the selected step in the log.
- **Sheet** (`--sheet`): the review panel and button faces. It sits one step lighter than Ground in both themes.
- **Ink** (`--ink`): headings, primary text, the filled face of primary buttons and pressed segmented options.
- **Ink 2** (`--ink-2`): secondary prose, unselected log entries, list items and context rows in the diff.
- **Ink 3** (`--ink-3`): labels, line numbers, role names in the diff, the agent bar on the ruler and the footer.
- **Rule** (`--rule`): every hairline border and the scrollbar thumb.
- **Quiet** (`--quiet`): unchanged and cache-read content. It fills unchanged-run folds, the empty side of a one-sided diff row, the ruler track, neutral pills and the log tag.

### Dark theme
The dark theme redefines every token. Ground `#101210`, Sheet `#181b17`, Ink `#eceee8`, Ink 2 `#bcc2b4`, Ink 3 `#8e9587`, Rule `#2c312a`, Removal Rose `#3f1d18`, Removal Gutter `#8c3a2c`, Removal Ink `#ffb3a6`, Addition Mint `#17331c`, Addition Gutter `#2f7a3c`, Addition Ink `#9fe0a8`, Span Ochre `#3a3018`, Span Ink `#f0d27e`, Quiet `#22261f`, Model Blue `#8fb3f5`, Cache Blue `#5675b0`. In dark mode the tints go deep and the inks go pale, so each pair keeps its contrast.

### Named Rules
**The One Blue Rule.** `--model` is the only accent, and it always means the model's side. The agent's side is never blue. Decoration is never blue.

**The Diff Meaning Rule.** Red means left out of the model's view. Green means written by Palimnesis. Ochre means collapsed into a span. Quiet grey means unchanged and read from cache. The status pill is the one other place the pairs appear. There green marks a steady view and ochre a view that changes.

**The Paired Tint Rule.** A tinted fill never appears without its ink. `--del` goes with `--del-ink`, `--add` with `--add-ink`, `--fold` with `--fold-ink`. Both themes redefine the pair together.

## Typography

**Display Font:** Atkinson Hyperlegible Next (with system-ui, -apple-system, Segoe UI, sans-serif)
**Body Font:** Atkinson Hyperlegible Next (same stack)
**Label/Mono Font:** Atkinson Hyperlegible Mono (with ui-monospace, Cascadia Mono, Consolas, monospace)

**Character:** One family in two cuts. The proportional cut does the explaining and the mono cut holds everything a developer would read in a terminal or a diff, such as messages, token counts, the repo name and ruler labels. Both are built for legibility, so letterforms like 0 and O stay distinct in counts.

### Hierarchy
- **Display** (700, 36px, 1.1, -0.025em): the page title only. It drops to 29px below 820px.
- **Headline** (700, 26px, 1.2, -0.02em): the selected step's title.
- **Figure** (Mono 600, 34px, 1, -0.02em, tabular figures): the two readout counts, "Agent sends" and "Model receives". It drops to 27px below 820px. It is deliberately larger than the step title because it is where the eye should land.
- **Lede** (400, 17px, 1.55, max 70–72ch): the setup paragraphs and the one sentence per step.
- **Body** (400, 16px, 1.55): the page default.
- **Body small** (400, 15px): log entries, the step's bullet list and the term definitions (max 60–70ch).
- **Code** (Mono 400, 13.5px, 1.55): every diff row, wrapping anywhere so long paths never overflow.
- **Label** (600, 13px): figure labels, column headers, status pills, section dividers inside the diff.
- **Label small** (600, 12.5px): segmented options. The mono cut at the same size and weight sets fold rows.

### Named Rules
**The Numbers Are Code Rule.** Every token count is set in the mono cut with `font-variant-numeric: tabular-nums`, right-aligned where it sits in a column, so counts line up the way line numbers do.

**The Readout Outranks the Title Rule.** On each step the two figures are the largest type in the panel. Nothing else in the panel goes above 26px.

## Layout

The page is a single centred column, max 1320px wide, with 32px top, 20px side and 56px bottom padding, and a 26px gap between the masthead, the review panel, the terms and the footer.

The review panel is a two-column grid. The step log takes 280px on the left and the selected step fills the rest. Inside the step, every band (readout, toolbar, diff divider, legend, bottom nav) uses a 26px horizontal inset, so their left edges align. The readout stacks its title row, figures, lede, bullets and ruler with a 14px gap.

The split diff is a six-column grid, `62px 22px 1fr 62px 22px 1fr`, that is count, sign and text for each side. The unified diff keeps the first three. The ruler is a two-column grid with a 64px label column and the tracks.

Terms below the panel flow into an auto-fit grid of columns at least 270px wide.

Below 820px the panel becomes one column. The step log turns into a horizontal scroller with snap points and entries 190px to 64% wide. The diff switches to unified at `54px 20px 1fr`. The split/unified control and the keyboard hint are hidden. Band insets tighten from 26px to 16px.

### Named Rules
**The Shared Edge Rule.** Every band inside the step uses the same horizontal inset (26px, 16px on narrow screens), so the title, figures, toolbar, divider text and legend share one left edge.

## Elevation & Depth

The system is flat. No surface casts a shadow. Depth comes from two paper tones and hairlines. The page sits on `--ground`, the review panel is `--sheet` with a 1px `--rule` border, and bands inside the panel (the toolbar, the diff header, section dividers, the selected log entry) drop back to `--ground` to read as recessed strips.

The only `box-shadow` in the build is motion, not depth. Rows that are new to a step arrive under a full inset wash of `--model` at 24% and settle to transparent over 900ms on `cubic-bezier(.16, 1, .3, 1)`. It runs only under `prefers-reduced-motion: no-preference`.

### Named Rules
**The Hairline Rule.** Separation is a 1px `--rule` line or a change of paper tone. Never a shadow.

**The One Motion Rule.** The arrival flash on new rows is the only authored motion. State changes elsewhere are instant.

## Shapes

Corners are soft on containers and controls and absent inside the diff. The review panel is 14px round and clips its contents. Buttons are 9px (8px for the compact pair), segmented controls 7px, ruler bars 3px. Status pills and the log tag are full pills (999px). Diff rows, sign gutters and fold rows are square and run edge to edge, as they do in a review tool.

## Components

### Buttons
Plain and firm. They look like the controls of a review tool, not like marketing calls to action.
- **Shape:** gently rounded (9px), 1px `--rule` border.
- **Primary:** `--ink` face with `--sheet` text, used for Next, the forward action.
- **Secondary:** `--sheet` face with `--ink` text, used for Previous.
- **Small:** the compact Previous/Next pair beside the step title, 13.5px text, 6px 12px padding, 8px radius.
- **Disabled:** `aria-disabled="true"` at 40% opacity with a default cursor.
- **Focus:** a 2px `--model` outline at 2px offset. There is no hover treatment.

### Segmented controls
- **Style:** a `--sheet` capsule with a 1px `--rule` border and 7px radius, holding text options at 12.5px 600 in `--ink-2`.
- **State:** the pressed option (`aria-pressed="true"`) fills with `--ink` and its text turns `--sheet`. Two sit in the toolbar, Changes / All lines and Split / Unified.

### Chips
- **Status pill:** 13px 600 text on a full pill, 5px 11px padding. The neutral pill is `--quiet` on `--ink-2`. The steady state uses the addition pair and a changing view uses the span pair.
- **Log tag:** 11.5px 600 text on `--quiet` in `--ink-2`, 1px 8px padding, under a log entry whose view changes. It stays neutral grey.

### Navigation
- **Step log:** a list of buttons with a right-aligned mono step number (13px 600, `--ink-3`) in a 28px column and the step name at 15px in `--ink-2`. Hover darkens the name to `--ink`. The current step gets a `--ground` fill, a 600 name in `--ink` and a `--model` number. Focus is an inset 2px `--model` outline. On narrow screens the log scrolls sideways.
- **Bottom nav:** Previous step and Next step buttons at either end, the keyboard hint ("Arrow keys or j and k") between them at 13px in `--ink-3`. Arrow keys and j/k step through, and the URL hash records the step.

### Diff
The signature component.
- **Header row:** 13px 600 `--ink-2` labels on `--ground` with a `--rule` bottom line, "Agent sends" over the left half and "Model receives" over the right.
- **Context row:** mono text in `--ink-2`, role name in `--ink-3`, count in `--ink-3`. Rows new to the step set their text in `--ink` at 500 and their count in `--model` at 600.
- **Removal row:** the left cell in `--del`, the sign cell in `--del-gutter` with a `−` in `--del-ink`, the empty right side in `--quiet`.
- **Addition row:** the mirror on the right with `--add`, `--add-gutter`, `--add-ink` and a `+`.
- **Span fold:** a full-width `--fold` button row in the mono at 12.5px 600 and `--fold-ink`, stating the message count and tokens, with an underlined Show/Hide action in the UI face.
- **Unchanged fold:** the same row on `--quiet` in `--ink-2`, for a run of unchanged messages.
- **Section divider:** 13px 600 `--ink-2` text on `--ground` with a `--rule` top line, introducing the model's reply.
- **Legend:** small swatches for the four diff meanings under the diff, in 13px `--ink-2`.

### Readout
The two figures sit side by side, agent first, with a 13px 600 `--ink-3` label above each, and a status pill follows them. The ruler below shows the agent and model as 10px bars on a `--quiet` track against a 28,000-token scale, with thin `--ink-2` ticks at T and H and a 2px `--ink` tick at the budget. The model bar splits into `--cache` and `--model`. A one-line cache note in 13px `--ink-2` sits under it.

## Do's and Don'ts

### Do:
- **Do** keep `--model` for the model's side only, the figure, the current step, the ruler, focus and links.
- **Do** use the diff pairs only for their diff meaning and always with their ink (`--del`/`--del-ink`, `--add`/`--add-ink`, `--fold`/`--fold-ink`).
- **Do** set every token count in Atkinson Hyperlegible Mono with tabular figures.
- **Do** make the step's figures the largest type in the panel (34px against a 26px title).
- **Do** separate surfaces with 1px `--rule` hairlines and the `--ground`/`--sheet` step.
- **Do** align every band inside the panel on the 26px inset (16px below 820px).
- **Do** define any new colour in both themes as a pair under one token name.
- **Do** gate the arrival flash behind `prefers-reduced-motion: no-preference`.

### Don't:
- **Don't** introduce a second accent hue. A new emphasis uses weight, `--ink`, or an existing diff pair with the same meaning.
- **Don't** use the red, green or ochre pairs anywhere outside the diff, its legend and the status pill.
- **Don't** add drop shadows or glows to cards, buttons or the panel.
- **Don't** round diff rows or gutters. The diff runs square and edge to edge.
- **Don't** set prose in the mono cut or counts in the proportional cut.
- **Don't** add hover lifts or transitions to controls. The only authored motion is the arrival flash.
