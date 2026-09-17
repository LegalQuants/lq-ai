---
title: Security disclosure
description: How to report a vulnerability, what the project commits to, and the test that decides whether a finding is safe to discuss in the open.
audience: [evaluator, operator, contributor]
status: draft
sources:
  - SECURITY.md
  - docs/releases/v0.7.0.md
sidebar:
  order: 10
---

If you found a security problem in LQ.AI, this page tells you where to send it, what response you
can expect, and — the part the policy below does not itself spell out — how the project actually
decides whether a finding belongs in a private report or a public issue.

<!-- include: SECURITY.md -->

## The public-vs-private test in practice

The policy above is clear that vulnerabilities go through coordinated disclosure, not public
issues. It does not state a rule for the harder question a reporter with real findings has to
answer alone: is *this specific* finding safe to work on in the open? The project's only full
security audit to date (#288, 22 findings) answers it by precedent rather than by stating a rule.
Per [`docs/releases/v0.7.0.md`](../../releases/v0.7.0.md), that audit's findings were remediated in
public PRs, and the same notes record that "none is exploitable by a raw external attacker in the
shipped default (every service binds to `127.0.0.1`)." The release notes do not state the second
fact as the reason for the first; the test below is this site's reading of the precedent, not the
project's written rule. Stated generally: **if a finding requires access an
attacker cannot get in the deployment's shipped default configuration — an unexposed local port, a
credential the operator already holds, a network position the shipped topology doesn't grant —
public review is safer and faster than a private report sitting in a queue.** If a finding is
exploitable by an attacker who has only what the shipped default exposes, it goes through the
private, coordinated path above.

:::note[Professional duty]
Applying this test is itself a competence judgment, not a formality — deciding whether your finding
clears the "not externally exploitable in the shipped default" bar before you post it publicly is
the same kind of judgment SECURITY.md's own scope section asks of a reporter ("a demonstrable
exploit path against the project's threat model"). When you are not sure which side of the line a
finding falls on, the private path is the conservative default; nothing above penalizes choosing it.
:::

**Honest gap.** [`SECURITY.md`](../../../SECURITY.md) itself does not yet state this distinction —
the test above is inferred from the one precedent the project has applied it to, not quoted from
the policy. Until the policy is updated to state it directly, treat this page's framing as the
project's practice, not its written rule.

## Next

- [Published gaps](published-gaps.md) — the audit's remaining open findings (#288), tracked honestly alongside everything else.
- [Governance](governance.md) — who reviews a security-relevant PR once a finding is public.
