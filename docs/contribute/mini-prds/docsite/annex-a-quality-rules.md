# Annex A — Quality rules and failure tests

**Status:** Frame only. The core rule set — twelve ranked rules each with a failure test,
sixteen house-style rules, and two publication conditions — was authored by a community
member from a three-site comparative review of self-hosted-AI documentation sites, and is
adopted by reference pending the committee decision in the parent PRD (decision 4). It
lands here under its author's name, in her own text, when she files it. This annex carries
only what the parent PRD adds around it.

## The two publication conditions (adopted as stated)

1. Nothing publishes orphaned or stubbed.
2. Every page states the upstream release or commit it was checked against.

The second condition already runs in production in this project's ecosystem: the
[`lq-ai-community` decisions log](https://github.com/LegalQuants/lq-ai-community/blob/main/decisions/README.md)
stamps "status checked <date>" on its records and states that canonical artifacts control
on any disagreement. The site copies that mechanism; it does not invent one.

## Proposed regulated-field additions

From a benchmark of documentation for open-source software used in regulated fields
(legal document automation; two medical-records platforms; a core-banking platform
reviewed and set aside as an anti-pattern). Three rules, in the house format — the rule,
the reason, the test that says it has been broken — covering ground the core set does not.
Five further candidates from the same benchmark are held back; the committee can ask for
them if these three earn their place.

### R-A — Every control whose failure is silent must say so, and say what the reader can observe instead

In an unregulated field the question about a control is "can it fail." In a regulated one
the question is **"will I know."** This project's own security documentation states the
finest version of this — for anonymization, a miss is silent, and the lawyer has no in-app
signal — while the public surface states the control flat. The benchmark found the same
divergence-without-signal shape in the closest comparable legal project.

> **Failed when:** a page describes a control that protects client-confidential material
> without stating whether its failure is observable to the user, and — if it is not —
> what the reader should watch, log, or route differently instead.

### R-B — Name the professional duty at the point of the decision that engages it, in the reader's own professional vocabulary

Across four benchmarked sites in three regulated fields, content addressed to the
practitioner's own duties totalled two sentences. Our reader *is* the practitioner —
the solo legal function is operator, author and evaluator in one person. "The gateway logs
every external call" is an engineering fact; "you can evidence, to your client or your
regulator, every occasion on which their material left your control" is the same fact
addressed to the duty it serves.

> **Failed when:** a page describes a technical behaviour that bears on confidentiality,
> privilege, competence or supervision without naming the duty it touches — or the duty
> language appears only in a licence, disclaimer, or PRD section rather than beside the
> decision.

### R-C — Publish the licence obligations the reader can breach as obligations, with the threshold and the compliant pattern

No benchmarked site models this; all three have a licence *link*, which answers "what may
I do with the code." A deployer is asking "what may I promise my client," and only one of
those questions currently has an answer anywhere in this project — inside
[ADR 0001](../../../adr/0001-openwebui-fork-pin.md), which itself assigns the missing page.

> **Failed when:** a reader can plan a rebranded or resold deployment from the deployment
> documentation without encountering the upstream branding clause, the 50-end-user /
> 30-day threshold, and the dual-branding pattern — or the constraint lives only in an
> ADR.

## The cross-surface rule

Added by this PRD on the evidence that two current public surfaces already answer a
product-scope question differently (PRD §1.6 vs the published decision log, on litigation),
with the tie-break buried in a register README.

> **Every page that states a scope, capability, or policy names its canonical artifact and
> the date it was checked against it.**
>
> **Failed when:** two published surfaces answer the same scope question differently.

## How the rules are used

- They are **gates, not style advice**: the launch gate (parent PRD, "How we'd know it's
  done") runs every failure test against the built site, executed by someone who did not
  write it.
- The sixteen house-style rules are **authoring guidance, not gates** — reviewers cite
  them; they do not block merges.
- A rule without a failure test is a preference, and preferences do not survive the second
  week. Any rule proposed for this annex must arrive with its test.
