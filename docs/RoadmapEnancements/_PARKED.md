# Roadmap-enhancement analysis — PARKED

> **Status (2026-05-21):** parked until M3-A6 PR (#57) merges and Phase 7 work closes — possibly until all of M3 wraps. Kevin's call: better to do this work fresh in a focused session against a clean branch state than to interleave it with active M3 work.

---

## What's in this subfolder

- **`HANDOFFlavernevaluation.md`** — handoff from a prior CC web session that drafted DE-265 (Lavern as design reference for §3.10 Autonomous Layer M4, §3.8 ensemble extension, §8.5 MCP catalog).
- **`de265.patch`** — the commit that the web session couldn't push (container was ephemeral). **STALE**: the patch's line context targets a PRD state where DE-264 was the latest entry; in current PRD, DE-265 through DE-285 are all already claimed. The patch will not apply cleanly and the DE number needs to change.
- **`HANDOFFboundaryregistersroadmap.md`** — proposal for adopting Dazza Greenwood's 6-register boundary catalog as the framework for LQ.AI's restraint work. Proposes a §1.8 posture addition, a posture document (`docs/security/boundary-registers.md`), R1 codification with golden tests, §3.7 Playbook updates (declared tool grants + schema-validated handoffs), §3.10 autonomous-layer updates, and 4 new DE entries (the doc calls them DE-266–269, but those numbers are all already taken — see "stale" above).
- **`draft_051.docx`** — Dazza Greenwood's May 2026 article that's the source of the 6-register framework. **Read this first when resuming.**

## When we resume, the suggested order

1. **Read `draft_051.docx` first**, independently. Don't import the handoff documents' summary of it without verifying the framing against the source. The handoff docs may be accurate; they may also have selective emphasis the source doesn't carry.
2. **Re-evaluate the "honest count"** of where LQ.AI sits on the 6 registers — the prior CC counted 2/2/2 (fully / partial / deferred-with-architectural-commitment) against `main`, before M3-A6 shipped. Confirm the count against current branch state.
3. **Adjudicate the two framing meta-questions** before any PRD text gets drafted:
   - Vocabulary attribution for "registers of restraint" (Greenwood's coinage) — cite once and use, or don't adopt the term?
   - Treat the catalog as a living artifact ("expected to grow as community practice matures") vs. commit to "six registers" as a fixed enumeration?
4. **Renumber.** The handoff docs propose DE-265 through DE-269; all of those numbers are taken. The next free number when resuming is likely DE-286+ (DE-285 was filed 2026-05-20).
5. **Reclassify the `§2.4` Playbook updates** in `HANDOFFboundaryregistersroadmap.md`. They were drafted as "land before M3 Playbook executor merges" — but the executor shipped in M3-A2 and M3-A6 is in PR. Those changes are post-merge follow-ons now, not in-PR edits.
6. **Independently verify the 5 normative rules** the handoff doc cites for R1 codification (refuse-flag-or-gate / severity floor / no silent supplement / retrieved-content-trust / destination check) against the source article + LQ.AI's existing skill-authoring guide. The handoff doc summarizes them; the article is what authorizes them.
7. **Then draft.** PRD edits + new DE entries on a new branch off `main`, separate from any M3-A6 follow-on work.

## Carry-forward observation worth not losing

The prior CC's response to Dazza (reproduced in the handoff conversation) made an insight worth preserving when we write the §1.8 posture text:

> **The Inference Tier model is a separate axis, not a 7th register.** "Lawyer + agent vs. third-party-processor" runs along a different dimension than Greenwood's "lawyer vs. agent" registers — it restrains *where the data goes during inference*, not *what the model may decide, spend, run, or touch*. Worth naming explicitly in any posture text so a reader doesn't conflate the two boundaries.

## Why the work is high-value despite being parked

The boundary-register framing is genuinely good prior art for restraint design, and DE-265 (Lavern reference) is the right discipline for the M4 autonomous-layer work — concrete prior art instead of a blank page. Both should land before M4 design starts. M4 hasn't started yet, so parking through M3-close still leaves comfortable runway.

---

*This file is a parking marker, not part of the PRD. Delete when the analysis resumes and the resume-ordering above starts executing.*
