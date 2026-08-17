# Annex B — User journeys as acceptance criteria

Twenty-five journeys. Each one is a route a real reader takes through the site, and each
ends in a **failed-when** test that someone who did not build the site can run against it.
Read each journey as a person arriving with a worry or a task: it passes when they leave
with it handled.

The journeys are three things:

- **Acceptance tests** — the launch gate runs the P0 tests; later phases run theirs.
- **Contribution units** — most journeys are claimable by one person (Annex C maps them).
- **Entry-point cards** — the site's landing hub routes by these goals, in reader language.

**How this annex is organised.** By theme first, then by maturity within each theme. Seven
themes group the journeys by what the reader came to do. Inside each theme, the journeys run
in maturity order, from launch to later phases, so related journeys sit together instead of
being spread across phases. J5 sits above the themes: it is not a place a reader goes but a
rule for how every page is served. See "The two front doors".

**On navigation.** Role still drives the sidebar. Each journey has one page, reached through the reader's role. Theme is a second lens, not a second sidebar: it groups the landing hub's cards and
the machine index an agent reads. Both point at the same pages, so no page has two homes.
This relaxes the old rule of one grouping only, and keeps the rule that no journey gets two
homes.

**Status vocabulary.** *Evidence-derived*: someone took or demanded this path, on the
record. *Synthetic (likely / plausible)*: extrapolated from evidenced personas and
contexts; confidence per the evidence pass that adjudicated every synthetic journey
against the community record, issue tracker, and published minutes. Two journeys found no
evidence for reasons of project age, are marked so, and should be re-tested once the site
has lived long enough to produce readers.

**Phase** proposes when the journey's pages ship; committee sign-off is parent decision 2.

| Theme | # | Journey | Reader | Status | Phase |
|---|---|---|---|---|---|
| Cross-cutting | J5 | Point my coding agent at it | a coding agent | evidence | **Launch** (build req.) |
| Is this for me? | J1 | Am I the person this is for? | anyone; often a legal function of one | evidence | **Launch** |
| Is this for me? | J21 | Can it do litigation? | disputes practitioner | evidence | Launch-with |
| Is this for me? | J15 | Why not just buy it / use the alternative? | budget-holder, contributor | evidence | Fast-follow |
| Getting it running | J2 | Get it running | operator | evidence | **Launch** |
| Getting it running | J20 | Air-gapped install | isolated-network operator | evidence | **Launch** (inventory) |
| Getting it running | J22 | Which hosting combination is mine? | operator with a fixed topology | evidence | **Launch** (index) |
| Getting it running | J19 | Will it run on what I have? | resource-constrained reader | synthetic · likely | Launch-with |
| Keeping data safe | J3 | What leaves my deployment? | operator, evaluator | evidence | **Launch** ⚠ blocked |
| Keeping data safe | J4 | Hand this to our security team | evaluator | evidence | **Launch** |
| Keeping data safe | J9 | A provider key leaked, 11pm | operator | synthetic · likely | Launch-with |
| Keeping data safe | J24 | I found a security problem | outside reporter | evidence | Fast-follow |
| Running it day to day | J11 | It broke — triage and recover | operator | evidence | **Launch** (min. set) |
| Running it day to day | J6 | Week two: back up, upgrade, watch | operator | evidence | Launch-with |
| Proving what happened | J10 | The output was wrong — reconstruct | practising lawyer | evidence | Launch-with |
| Proving what happened | J25 | Compare techniques on my matter | benchmarking practitioner | evidence | Fast-follow |
| Proving what happened | J16 | The insurer asks what you deployed | accountability reader | synthetic · plausible | Post-launch re-test |
| Proving what happened | J14 | The annual re-review | evaluator, a year on | synthetic · plausible | Post-launch re-test |
| Making it your own | J7 | Bring my own workflow in | lawyer-author | evidence | Launch-with |
| Making it your own | J18 | Should I trust this skill? | skill consumer | synthetic · likely | Launch-with |
| Making it your own | J23 | My language, my law — fork or contribute? | non-anglophone practitioner | evidence | Launch-with |
| Making it your own | J17 | What survives the next release? | fork/frontend builder | evidence | Fast-follow |
| As you grow | J8 | Can it carry our branding? | deployer, firm | evidence | **Ships independently** |
| As you grow | J12 | We just crossed fifty users | deployer mid-engagement | synthetic · likely | Fast-follow |
| As you grow | J13 | The pilot becomes a programme | prototyper + IT | synthetic · likely | Fast-follow |

---

## The two front doors

Every page has two readers, and they do not want the same thing. A person comes to
understand the project and judge whether it is safe to proceed: they need to know why it
matters, what is safe, and what to expect. A coding agent comes because its human pointed it here: it needs the
exact steps, the rules, and what to do and not do. The community's stated way in is an
agent reading the project, so this split is live, not hypothetical.

The floor is the same for both: every page retrievable as plain markdown, `/llms.txt`
present, no scraping of rendered HTML. Above the floor they diverge. The agent does not
want the human's guided tour through the role sidebar; it wants a flat, complete index of
goals, served as text. That index is the theme lens. So the theme grouping is not only for
people: it is the shape the agent needs, and the shape the human hub already uses.

### J5 — Point my coding agent at it
The community's publicly stated onboarding route is an agent reading the project. The
machine surface (`/llms.txt`; `.md` served for every page URL) is a build requirement, not
a page — cheap specified up front, expensive retrofitted.
> **Failed when:** any page cannot be retrieved as plain text/markdown, or an agent must
> scrape rendered HTML to read the docs.

---

## Is this for me?
*Deciding whether to spend any more time here.*

### J1 — Am I the person this is for?
The highest-traffic page on the site, and it does not exist. A practitioner inside the
project's own community deferred engagement for weeks unsure he was an intended user; a
practising litigator initially dismissed the repo as in-house-only
([2026-07-19 minutes](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-07-19-weekly/notes.md)).
The model is a considerations page with disqualifiers the reader can check themselves
against — not an audience description.
> **Failed when:** a reader cannot determine within one page whether the software is
> intended for them; or discovers only after installing that their use case is out of
> scope; or can conclude they are in scope when the PRD's non-goals say they are not.

### J21 — Can it do litigation?
Confirmed end-to-end: a practising litigator inferred litigation support from the shipped
research capability, filed a scope proposal
([#287](https://github.com/LegalQuants/lq-ai/issues/287), escalated), and the committee
narrowed the carve-in to research and drafting
([decision log](https://github.com/LegalQuants/lq-ai-community/blob/main/decisions/README.md))
— while PRD §1.6 still excludes litigation flatly. Three public surfaces, three answers.
The failure mode is a *confident wrong answer*, in either direction.
> **Failed when:** a page presents case-law or research capability without stating on that
> same page that litigation and e-discovery workflows are v1 non-goals; or the non-goals
> are listed without telling the reader what to do instead; or two published project
> surfaces answer the scope question differently.

### J15 — Why not just buy it — or use the open-source alternative?
Confirmed in the variant that matters: a community member could not say why the project
should exist alongside the visible open-source alternative, and was resolved only by an
answer posted in chat — unretrievable. The page includes a "where the commercial products
win" column and treats the open-source alternative as a first-class comparison, plus the
test-bench answer to "why not just use Claude directly."
> **Failed when:** the comparison page names no case in which a commercial product is the
> better choice — a comparison with no losses is marketing — or the page does not
> distinguish LQ.AI from the visible open-source alternatives.

---

## Getting it running
*The setup path: mostly day-one work, because readers cannot start without it.*

### J2 — Get it running
The strongest existing journey — the quickstart works. The fixes are ordering (prereqs and
data boundary before the first command) and recovery inlined rather than on a page the
stuck reader must find. Day-zero failures on the documented path are on record
([#92](https://github.com/LegalQuants/lq-ai/issues/92)).
> **Failed when:** a first-time reader meets a command before the software is defined, its
> data boundary stated, and prerequisites named — or a stuck reader has no next command
> and no observable success check.

### J20 — Air-gapped install *(launch: egress inventory)*
An air-gapped install on the documented path has already failed on an unpublished image
([#99](https://github.com/LegalQuants/lq-ai/issues/99)), and first boot performs ~30
undeclared model downloads from an upstream component (DE-353). The egress inventory is a
test artifact to publish, not a document to write: the air-gap CI records real phone-home
attempts (#366 / #427). The machine surface doubles as the offline documentation bundle.
> **Failed when:** an install step assumes network access not named in the egress
> inventory — or the documentation cannot be read on a machine with no route to the
> internet.

### J22 — Which of these hosting combinations is mine? *(launch: supported-shapes index)*
The demand that produced the docs-site idea. Recipes exist or are filed for Caddy +
Tailscale, reverse-proxy TLS (#370), tailnet Ollama
([#495](https://github.com/LegalQuants/lq-ai/issues/495) — filed precisely because the
egress guard refuses the obvious configuration), Windows (#259), Azure (#154–#157, fed
back by a production deployment's IT team). No index exists, and the guard rails now
refuse configurations no page explains.
> **Failed when:** an operator on a common topology — remote inference host, corporate
> cloud endpoint, Windows, behind a reverse proxy — cannot determine from the site whether
> it is supported, or hits a fail-closed refusal that no page explains.

### J19 — Will it run on what I have? *(synthetic · likely)*
Named reference configurations known to work span a very large workstation to a modest
VPS — a spread wide enough that readers conclude either "server room" or "anything," both
wrong. For the law-school clinic, legal-aid org, or solo practitioner, this page decides
whether they try at all.
> **Failed when:** the site states no minimum hardware, or states a minimum without saying
> what degrades below the recommended configuration.

---

## Keeping data safe
*The risk surface, and who is responsible for it.*

### J3 — What leaves my deployment, and who sees it?
The highest-severity journey: this reader's failure mode is a client-confidentiality
incident. The honest answer exists in [docs/security/anonymization.md](../../../security/anonymization.md)
and is several clicks deep; the committee's
[published minutes](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-07-26-weekly/notes.md)
record the layer's reliability as an open item. **Blocked** on parent decision 1; whatever
the outcome, this page states measured behaviour and ends in a decision (route privileged
matters to Tier 1). No benchmarked site in any regulated field passes this test — it is
genuinely differentiating.
> **Failed when:** the answer to "what leaves my deployment" requires more than one page —
> or a risk paragraph ends without telling the reader to proceed, configure, escalate, or
> stop.

### J4 — Hand this to our security team
The richest content in the repo (threat model, audit logging, supply chain, SIG Lite,
HONEST-STATE) with no information architecture over it. The trust-centre index is the
deliverable; stable URLs are the commitment; the public governance record
([lq-ai-community](https://github.com/LegalQuants/lq-ai-community)) is linked as a
first-class artifact — it is the only public surface that answers "who decides" with dates.
> **Failed when:** a URL cited externally stops resolving; or an evaluator must read more
> than the trust-centre index to find any of its artifacts (threat model, data flow, audit
> and evidence, supply chain, gaps catalogue, governance and continuity, questionnaires).

### J9 — A provider key leaked, and it is 11pm *(synthetic · likely)*
The trigger is unevidenced (searched; clean negative). The hard half — the blast-radius
statement and the audit query — already exists in security-audit findings and a measured
leak-rate PR, in places no operator will look at 11pm. Note: v0.7.0's gateway-key
requirement (#396) changed the rotation procedure — this page and the per-release surface
ship together.
> **Failed when:** a reader searching for how to revoke a leaked credential lands on a page
> that explains how keys are stored but does not give the revocation command, the
> blast-radius statement, and the audit query — or gives them across more than one page.

### J24 — I found a security problem — what do I do with it?
The project's only full audit to date was disclosed publicly, deliberately, by a reporter
who read the coordinated-disclosure policy and applied an exploitability test the policy
does not contain (findings not externally exploitable by default → public review is safer
and faster). The reasoning is sound and lives in a chat message.
> **Failed when:** a reporter with findings has to invent the public/private test
> themselves — or the policy is stated without the exploitability distinction that decides
> real cases.

---

## Running it day to day
*Keep it alive, and fix it when it breaks.*

### J11 — It broke — triage and recover *(launch: minimum set)*
Confirmed five times over, one instance per triage branch: a clean-install failure on the
documented path ([#92](https://github.com/LegalQuants/lq-ai/issues/92)); three fail-closed
operator-visible changes in one release (v0.7.0 — #396, #399, #400); a hardening change
that would have refused the documented default configuration (caught in review); silent
empty-but-running states ([#503](https://github.com/LegalQuants/lq-ai/issues/503),
[#207](https://github.com/LegalQuants/lq-ai/issues/207)); an upgrade that silently didn't
take ([#277](https://github.com/LegalQuants/lq-ai/pull/277)). Launch carries the minimum:
symptom-first entry, the day-zero branch, and the upgrade branch; full runbooks follow
with J6.
> **Failed when:** a reader can find how to upgrade but cannot find whether a release's
> migrations are reversible, or what to do when one fails halfway — or no page can be
> reached by searching a symptom rather than a task name.

### J6 — Week two: back it up, upgrade it, watch it
No runbooks directory exists; rollback is answered nowhere at any level. The regulated-field
benchmark reclassified this from "cheap differentiation" to **the floor for the category**
— sites holding real records document backup and restore.
> **Failed when:** install is documented and protect/recover is not.

---

## Proving what happened
*Show your work after the fact. No hosted competitor can offer this to a regulated
professional.*

### J10 — The output was wrong — what did the flag promise, and what happened?
Confirmed in generalised form: a user relied on output, was wrong, and had to reconstruct
what the system did by hand ([#503](https://github.com/LegalQuants/lq-ai/issues/503) —
"this defect caused me to publish a wrong conclusion"). The page must state, in the
negative, what a green citation flag does not assert — including *currency of the law*, a
limit a committee member independently proposed flagging
([2026-07-19 minutes](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-07-19-weekly/notes.md),
temporal currency flags) — and how to tell "the system broke" from "the analysis is thin."
Crosses the in-app Learn boundary deliberately: this reader may no longer have deployment
access.
> **Failed when:** the page describing citation verification does not state, in the
> negative, what a verified citation does not assert; or the reader cannot find a
> documented procedure for retrieving the receipt and ledger entry for a past answer; or
> the page does not tell the reader how to distinguish a system failure from a poor answer.

### J25 — I want to compare techniques on my own matter
The test-bench reader, now real: a controlled five-model benchmark run through the full
stack ([#503](https://github.com/LegalQuants/lq-ai/issues/503)), in which a platform
default silently zeroed one model's results — a platform failure that would have been
scored as a model failure. The page documents what the platform's defaults do to results
and how to read routing metadata so attribution survives.
> **Failed when:** a reader varying one thing at a time cannot tell from the response
> whether the platform or the model produced the outcome — or the defaults that shape
> their results are not documented on the page that invites the comparison.

### J16 — The insurer wants to know what you deployed *(synthetic · plausible)*
No member has faced an inquiry. The capability is real — signed, provenanced releases
pinned to a commit; matter-scoped audit and citation records — and a contributor has
already described the air-gap test's phone-home log as "evidence for procurement
conversations instead of an assertion." The assembled story (*you can prove what you ran*)
is a selling point no SaaS competitor can offer a regulated professional.
> **Failed when:** there is no page a firm can cite that describes what a specific
> released version did, or no documented query that produces a matter-scoped record of
> model calls and citation verifications.

### J14 — The annual re-review, one year on *(synthetic · plausible)*
Procurement re-review is a calendar event; the project has not lived a calendar yet. The
discipline it tests has already failed once in the opposite direction — six files pointed
at a community channel that was never created
([#490](https://github.com/LegalQuants/lq-ai/issues/490)). The version-stamp mechanism the
journey requires already runs in the
[decisions log](https://github.com/LegalQuants/lq-ai-community/blob/main/decisions/README.md).
> **Failed when:** any URL published in the trust-centre tree stops resolving, or an
> evaluator cannot determine from the site what changed between two named releases in the
> artifacts they relied on.

---

## Making it your own
*Adapt it, extend it, and know what to trust.*

### J7 — Bring my own workflow in
The best-covered audience in the repo; the missing piece is the entry point — nothing tells
a reader their existing prompt files are close to skill-shaped — plus the frontmatter
schema as a table and a skills index.
> **Failed when:** a reader with working prompt files cannot tell what would have to change
> to make them a skill.

### J18 — Should I trust this skill? *(synthetic · likely)*
A third-party legal-substance skill has been offered to the community and volunteers
offered to test it — before any index, trust card, or stated attestation meaning exists.
The trust card states: author, attesting attorney, jurisdiction and practice-area scope,
version, and what the attestation covers (a maintainer-of-record commitment that decays
with the law — not a warranty).
> **Failed when:** a skill can be discovered and installed from the site without its
> author, attesting attorney, jurisdiction scope, and version visible on the same page —
> or the attestation's meaning is not stated where a consumer will read it.

### J23 — It needs to be in my language and my law — do I fork or contribute?
In one June fortnight, four community members reached for forks (two language versions, a
practice-area hard fork, deployment forks) while the routing rule went unstated — the
record is in [PR #313](https://github.com/LegalQuants/lq-ai/pull/313)'s discussion.
ADR 0024 has since decided the routes; the coverage map is open
([#506](https://github.com/LegalQuants/lq-ai/issues/506)). The coverage index (parent PRD,
"Designed to expand") is this journey's page.
> **Failed when:** a reader with jurisdiction-specific substance cannot determine where it
> goes without asking a human — or forks because they could not find out.

### J17 — What can I build on that will survive the next release?
Confirmed: a fork-builder built against a moving target and had to redo the work, asking
in as many words when the platform would be "finished." Multiple real builds run on this
backend; a first-party downstream product broke on an undocumented compose-level contract
([#278](https://github.com/LegalQuants/lq-ai/pull/278)). The page ranks extension points
by stability and states plainly what compatibility is and is not promised before 1.0.
> **Failed when:** the site names an extension point without stating its stability, or a
> reader cannot find a single statement of what compatibility the project does and does
> not promise before 1.0.

---

## As you grow
*The commercial path, from first promise to full programme.*

### J8 — Can it carry our branding?
The constraint (alter/remove upstream branding only under 50 end-users per rolling 30
days, written permission, or an enterprise licence) is recorded in exactly one file —
[ADR 0001](../../../adr/0001-openwebui-fork-pin.md), which itself assigns the missing
"Branding obligations" section. Parent PRD spawned item 1; the upstream fork refresh
(#498) is the natural moment. The page defines "end user," gives a method to determine the
current count (and states honestly if none exists), and names the three lawful positions
above the line.
> **Failed when:** a reader can plan a rebranded deployment without meeting the threshold
> and the dual-branding requirement.

### J12 — We just crossed fifty users *(synthetic · likely)*
J8 is *before you promise*; this is *after you promised and grew* — and the count is
currently unmonitorable (no end-user definition, no rolling-window count: a product gap
the page must state honestly).
> **Failed when:** the branding page states the fifty-user threshold without defining "end
> user" and without giving a method to determine the current count.

### J13 — The pilot has to become a programme *(synthetic · likely)*
A prototyper with a live corporate-sandbox opportunity and an ROI condition is on the
record; the requirements half is a production-readiness matrix with support-tier labels —
*supported / operator-provided / not yet*, each row linked to its page or DE. The honest
matrix is mixed, which is exactly why publishing it is credible.
> **Failed when:** a production requirement an enterprise IT function routinely asks about
> has no page stating whether it is supported, operator-provided, or not yet built — or a
> reader cannot find how to extract usage and cost data for a given period.

---

## Running the tests

- **The launch gate** (parent PRD, "How we'd know it's done"): J1–J4 pass, run by a
  non-author; J1 and J3 additionally pass with a second reader who has not read the
  source — until that reader exists they are *unverified*, not passed. J5's machine
  surface, J11's minimum set, J20's egress inventory, and J22's supported-shapes index are
  verified as build artifacts.
- **Each later phase** runs its own journeys' tests on shipping.
- **A journey's test failing after launch is a bug**, filed like any other, against the
  page that fails it.
