# Phase 7 decisions

## D111: Phase 7 scope, hosts and the user's protocol choices (2026-11-19)

The Phase 7 plan (`docs/plan/phases/phase7.md`) left five questions to the user (U1–U5). This entry records their answers, the scope they set, and the consequences. D115, the frozen held-out protocol, inherits all of it.

1. **Phases 5 and 6 are skipped for now** (user decision).
   - **Why.**
     - The pinned state already retains decisions and constraints well (R61) and beat native compaction on ho3 (R41).
     - Phase 5's own green light asks that its cost be justified against Phase 4A, and nothing shows a gap a summary DAG would close.
     - Phase 6's paraphrased retrieval has no evidence of need.
   - **Reversible.** Either phase can return before Phase 8. Its gates then become mandatory, and the affected comparisons are rerun.
   - **Phase 7 rows they own** (paraphrased needles, summary cost) are deferrals, not passes.
2. **Candidate and baseline.**
   - The candidate is `a4-d77`, `serve`'s defaults (D78), frozen at the freeze commit F.
   - The baseline is arm 1, OpenCode's own compaction (D44.1).
   - `--hidden-tools` is experimental and not claimed for release. R32 failed both of its gates.
3. **Harness scope (U4).**
   - **OpenCode 2.1.4 is the confirmatory harness.**
   - **Pi 1.5.0** runs ho4's 5 tasks on Chat, `a4-d77` against its own compaction, reported only. This needs a held-out unlock in `pi_task.py`.
   - **OMP** gets no held-out quality claim.
   - `docs/capabilities.md` says so for OMP and hidden tools.
4. **Held-out size (U2).**
   - 20 new tasks and 180 new needles form `heldout5`. With ho4's 5 tasks and 120 needles, that makes 25 tasks and 300 needles.
   - A sealed 10-task reserve (`heldout6`) is kept for Phase 8's reruns.
   - Four separate author sessions write them under the plan's §1.1 process.
5. **Needle scoring (U5).** The 95% gate uses loose exact (R19), as D44.4 and D77 did. Strict exact is reported.
6. **Hosts (U1, U3): pythia and Zeus, split by task.**
   - **Context.** Both run Strata at a real `n_ctx` of 32,768 for the pilot and the held-out runs. There is no emulated budget (O2). pythia goes back to 64K afterwards, and 64K is a reported run only.
   - **Split.** Tasks are allocated to hosts by a seeded draw, fixed in D115. Both arms of a task run on the same host, back to back, in seeded order. A McNemar pair never spans hosts.
   - **One build.** D48, D76 and D103 do not allow a comparison to span builds, and Zeus runs 0.1.57 while pythia runs 0.1.58.
     - Before the pilot, Zeus is moved to 0.1.58, accepted by its counts (D102: `palimnesis check` and the counting cases).
     - If that cannot be done, host becomes a stratum. The 2×2 table and McNemar are reported per host and pooled, and the pooled result is labelled as spanning two builds.
   - **Host stability.**
     - **Zeus:** Windows Update is paused for the whole run window, and active hours are set to cover it (D108).
     - **pythia:** automatic reboots are off.
     - **Both:** every run records the host epoch (plan S3).
   - **Timing.** The hosts differ in speed, so latency and prompt time are compared within a host only.
   - **Cost.** About 5 days of slot time, spread over two hosts.
