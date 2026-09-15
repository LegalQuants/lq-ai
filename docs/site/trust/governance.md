---
title: Governance
description: Who decides, how routine work differs from architectural and scope decisions, and where the meeting record lives.
audience: [evaluator, partner, contributor]
status: draft
sources:
  - GOVERNANCE.md
  - docs/adr/0022-committee-governance-and-meeting-records.md
sidebar:
  order: 8
---

"Who decides" is the question a partner or an evaluator asks once "does it work" is settled. ADR
0022 answers it by pointing at a public record with dates on it: committee minutes published per
meeting in [`LegalQuants/lq-ai-community`](https://github.com/LegalQuants/lq-ai-community). The
document below is the project's own account of that process, written by the people who run it.

<!-- include: GOVERNANCE.md -->

## Where the record actually lives

Per [ADR 0022](../../adr/0022-committee-governance-and-meeting-records.md), meeting minutes are
published — not this repository, deliberately, so that reading the product's source code and
following its governance are two different clone weights — in a separate
[`LegalQuants/lq-ai-community`](https://github.com/LegalQuants/lq-ai-community) repository, one
folder per meeting (`meetings/YYYY-MM-DD-<topic>/notes.md`). Raw transcripts are not published; the
minutes are the record, and a committee member absent from a call has seven days to object before
silence counts as assent (ADR 0022 decisions 4 and 5). ADR 0022 records that the 2026-07-19 and
2026-07-26 calls are published there and that seeding the earlier calls (2026-06-28, 07-05, 07-12)
is outstanding. A public decisions log in the same repository is not named in `GOVERNANCE.md` or
ADR 0022 as of the checked commit.

## An honest status note

`GOVERNANCE.md`'s own header still marks the document **"Proposed."** ADR 0022 — itself
**Accepted** by the committee on 2026-07-26 and merged as PR #311 — records `GOVERNANCE.md` as
adopted alongside it. The file has not been updated to reflect its own adoption as of the commit
this page was checked against; treat the document's substance as current practice per ADR 0022, and
its self-reported "Proposed" header as a drift this site did not correct on the source's behalf.

Read this against [Continuity](continuity.md) rather than in isolation: the two facts that matter
most for a partner deciding how much weight to put on this project's roadmap are who currently
authors most of the code (concentrated) and who is authorized to decide what the project does next
(a committee, per the document above). Those are different questions with different answers, and
conflating them either overstates or understates the project's resilience depending on which way
you round.

## Next

- [Continuity](continuity.md) — what the maintainer and contributor structure this page describes means if the current maintainer steps back.
- [Published gaps](published-gaps.md) — the honest-state inventory this governance process maintains.
