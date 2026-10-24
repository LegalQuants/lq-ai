# Annex A — Quality rules and failure tests

**Status:** Core rule set filed. The twelve ranked rules, each with a failure test, the
sixteen house-style rules and the two publication conditions are by Iris
([@iris-ng](https://github.com/iris-ng)). They come from her comparative review of three
self-hosted AI agent documentation sites (Hermes Agent, OpenClaw and nanoclaw), dated
2026-07-30 and circulated to the committee as a mini-PRD on 2026-08-01. Her text is below
as she wrote it. Her rules name the site "lq-website", its working name at the time. The
parent PRD uses the set by reference as its acceptance tests; no separate committee
adoption is sought. The rest of this annex is what the parent PRD adds around it.

## The twelve rules (Iris)

Twelve rules for lq-website, ranked by failure cost, each with a test that says when the
rule has been broken. All twelve come from watching three comparable documentation sites
fail the same reader.

Three self-hosted AI agent documentation sites were read the way an installer reads them —
Hermes Agent, OpenClaw and nanoclaw. The finding is not that any of them is bad. Install
works on all three. The finding is that the same reader gets stranded in the same places
on all three, and those places are predictable enough to write rules against.

Each is a rule about lq-website, not an observation about somebody else's site. The
measurements behind them are in the review itself; its own caveat applies to every number
quoted here: "Treat every number here as approximate; the quotes are reliable."

### 1 — Say what LQ.AI is, what it touches, and what the reader must bring — before any command appears

Two of three sites show a command before explaining the product. nanoclaw does the
opposite and has zero undefined words on its front page. LQ.AI also needs data boundary,
outbound data, and limits up front.

> **Failed when:** a first-time reader sees a command before LQ.AI is defined, its data
> boundary stated, and prerequisites named.

### 2 — Document backing up and restoring before launch

No site in this sample does it. All three treat backup as a reference-table command; two
have no restore instructions; nanoclaw's six uses of "backup" mean tagging source code.
Our readers hold client data.

> **Failed when:** install is documented but protect/recover is not.

### 3 — Answer "what leaves my deployment, and who sees it" on one findable page

nanoclaw never states that user messages go to a model provider; its only outbound-data
statement is on a commercial partner's page. OpenClaw spreads the answer across five
pages; Hermes uses two pages plus a proxy page.

> **Failed when:** the answer to "what leaves my deployment" requires more than one page.

### 4 — State every default as behaviour, not as a value

Pattern: what happens if you do nothing, posture name, then the opt-in verb.

> If the allowlist file doesn't exist, all additional mounts are blocked. That's the
> default posture; you opt in by creating the file.

OpenClaw's best instance — "If you do nothing, OpenClaw uses the bundled agent runtime…" —
is inconsistent. Hermes uses that phrasing once in 473,000 words. Keep the setting name
nearby.

> **Failed when:** a default and its setting are not findable together.

### 5 — Put recovery inside the quickstart, not on a page the reader has to find

Hermes has the model: a gate, a "what success looks like" checklist, symptom-cause-fix in
reader language, and ordered recovery. One diagnostic command appears 41 times. Add
OpenClaw's good output and nanoclaw's literal error heading.

> **Failed when:** a stuck reader has no next command or observable success check.

### 6 — End every admission of a limit with a decision

nanoclaw states the gap, lists consequences, then assigns responsibility. LQ.AI endings
include "get a reviewer" and "do not use this for that matter". A hard stop is an answer.

> **Failed when:** a risk paragraph does not end in proceed, configure, escalate or stop.

### 7 — Define the load-bearing words before they spread, and gloss each one in place on first use

None of the three sites has a glossary. Hermes has zero uses of the word across 473,260
words and reuses "gateway" for a paid service and a local process. nanoclaw uses a central
term as a getting-started heading, then defines it only on an optional page. Review
correction: this is not a taxonomy project. Define in place first; use the glossary for
backup.

> **Failed when:** a term appears before definition or carries two meanings.

### 8 — Publish which install paths, integrations and capabilities are actually supported

Hermes does this: "Termux (Android) is a Tier 2 platform. The installer script and
documentation here are maintained on a best-effort basis only." Readers need supported,
works-but-you-are-on-your-own, not built, and safe-for-matters labels.

> **Failed when:** a reader picks an install path, integration or capability without
> knowing whether anyone maintains it.

### 9 — Route after orientation, by goal, in the reader's words — and say when to skip

Hermes has the best routing page and buries it after uninstalling. OpenClaw writes routing
into metadata that never renders. Review correction: route after orientation, not before
it; keep a straight path to quickstart.

> **Failed when:** readers pick the wrong path, reach an advanced page too early, or get
> routinely wrong time estimates.

### 10 — Give every page an onward route, and make each link say what is on the other end

68% of Hermes's written pages end nowhere. nanoclaw's onward links are best, but appear on
only half its pages and miss search landings. Copy the gloss that lets a reader choose
without clicking. For paired walkthrough/reference pages, state the difference in line two
and link each way.

> **Failed when:** a search landing page has no exit, or a paired page does not explain
> why the other exists.

### 11 — Keep one grouping. The sidebar, the address and any index must agree

Hermes has four groupings, eight sidebar/address contradictions, one breadcrumb/URL
mismatch, and two pages in two top-level groups. OpenClaw has four tab/address mismatches,
and 203 of 776 pages sit in no menu. Use page length as a review trigger, not a hard
limit; review killed the cap because nanoclaw's smallness cost readers five needed pages.
Add question headings and alphabetical lookup.

> **Failed when:** address, menu and lookup disagree.

### 12 — No selling inside instructions, and no assumed tools

Hermes carries 39 upsell callouts across 29 pages, including Docker and Windows setup.
nanoclaw's debugging route, channel installation and extension path require a third-party
coding tool, while page one offers stranded alternatives. The dependency is never a
prerequisite.

> **Failed when:** a reader meets an advert mid-task, or a page assumes an unnamed tool,
> account or service.

### Two rules need a second reader

Two of the twelve cannot be checked by the person who wrote the page. Rule 1 and rule 7
both turn on whether a reader already knew a word, and the author always did. Those two
need a second reader who has not seen the LQ.AI source, and until that reader exists the
rules are unverified rather than met.

## The house-style rules (Iris)

Sixteen rules the three sites earned the hard way. These are authoring guidance, not
gates — the twelve above are the gates.

1. Open a page with its conclusion in one sentence.
2. State the governing idea in bold near the top.
3. Say what does not exist.
4. Give the zero-configuration behaviour before the setting that changes it.
5. When a default is off, say why it is off.
6. Gate ambition, and define success before the reader proceeds.
7. Put commands before theory on troubleshooting pages, and show good output.
8. Organise troubleshooting by visible symptom.
9. Answer the obvious objection in the same paragraph that raises it.
10. Keep a rule and its exception together.
11. Exercise authority through consequence, not command.
12. Give limitations their own heading and enumerate them.
13. Correct docs in public, and say which version fixed it.
14. Do not hedge. If a qualification is needed, put it inside dashes.
15. Do not put jokes where people arrive broken.
16. Never write "the user" on a page the user is reading.

On earning the right to say "don't": nanoclaw earns it because mechanism comes first —
"NanoClaw refuses to spawn at all if lockdown is on but can't be established" — and it
hands duty back: "The defense against all four is the same and it's yours, not the
software's: scoping." Hermes pairs prohibition with consequence or substitute. OpenClaw
gives flat instructions, and without a reason "do not" is easy to work around.

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
