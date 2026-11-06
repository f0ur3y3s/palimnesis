# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers who run coding agents (OpenCode 2.1.4, Pi 1.5.0) against a local model, usually at a 32K–64K context on one GPU. They want long coding sessions without the agent losing the exact file paths, error messages and values it saw earlier. The walkthrough page is written for them.

## Product Purpose

Palimnesis is a local proxy between an agent harness and a Strata server. It archives every accepted message exactly, sends the model a bounded view of the conversation, and gives back what the view removed: a working-notes block, excerpts matched to each new message, and transcript files the model can grep. Success for the walkthrough page: a reader can explain how the harness keeps the whole conversation while the model sees a bounded view, and how hidden details come back.

## Positioning

It never summarizes away or deletes history. Native compaction rewrites old turns into a lossy summary; Palimnesis masks them in the model's copy only and keeps exact, addressable originals. Measured on held-out data at 32K (R41): 5/5 coding tasks against native compaction's 4/5, with about half the prompt tokens; the speed difference is the summaries native compaction writes and the redone work (R46).

## Operating Context

The harness runs on the developer's machine and talks to the proxy on 127.0.0.1:9000; Strata may run on another host. The harness is configured with a 1,000,000-token context and its own compaction off, so it always sends the whole conversation. Results and decisions are numbered entries in docs/results (R) and docs/decisions (D).

## Capabilities and Constraints

- Archive mode for OpenAI Chat Completions and Anthropic Messages; bounded views with an exact token budget (24,320 at 32K); watermarks H = F + 0.9·C and T = F + 0.5·C.
- Supported harnesses: OpenCode 2.1.4, Pi 1.5.0. Claude Code is backlogged.
- The walkthrough is static HTML on GitHub Pages (site/, deployed by .github/workflows/pages.yml); no build step.
- Token counts in the walkthrough are illustrative; the mechanisms must stay accurate to docs/contracts.md.

## Evidence on Hand

docs/results R41 (held-out OpenCode), R46 (where the wall-clock gain comes from), R47 (Pi coding tasks), R45/R48 (Pi needles). README figure from eval/readme_figures.py. No users, testimonials or adoption figures exist; none may be invented.

## Product Principles

- Exact over approximate: show real mechanisms and real numbers, label anything illustrative.
- The harness's copy is never touched; only the model's copy is bounded.
- Every claim traces to a contract, decision or result entry.
- Plain, precise language, as in the docs.
