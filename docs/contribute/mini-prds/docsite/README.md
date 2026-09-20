# A public documentation site for LQ.AI · mini-PRD

| | |
|---|---|
| **Status** | **Ready for implementation.** ADR 0028 (stack and hosting) was accepted by the committee on 2026-09-20. The remaining items are listed under [Open questions](#open-questions) with the default the site proceeds on. |
| **Effort** | **L overall, deliberately divisible** — 22 independently claimable S/M items across six contributor profiles (Annex C). The launch-gating subset is ~26 pages, of which ~15 are curation of existing repo files. |
| **Contributor profile** | Varies by section: DevOps (operations), compliance/security professional (trust centre), practising lawyer (skills, licensing), technical writer (contribute, orientation), frontend engineer (site infrastructure). Per-item profiles in Annex C. |
| **Review** | Maintainer review by default. Content stays in this repository, so CODEOWNERS routing for security, compliance and skills paths applies as it does today. |
| **Depends on / relates to** | ADR [0001](../../../adr/0001-openwebui-fork-pin.md) (branding clause — spawned item 1), ADR [0022](../../../adr/0022-committee-governance-and-meeting-records.md), ADR [0024](../../../adr/0024-jurisdiction-and-practice-area-expansion.md) (contribution routing), ADR [0025](../../../adr/0025-release-versioning-and-pipeline-ordering.md) (upgrade classes); **ADR 0031** (headless / API-only use: acknowledged, not supported — PR #564) sets what the site does not document; **ADR 0028** (documentation-site generator and hosting — accepted 2026-09-20) sets the stack; the open anonymization item ([2026-07-26 minutes](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-07-26-weekly/notes.md), PR #439) — **holds one trust-centre page**; mini-PRDs [#1](../procurement-readiness-pack.md), [#3](../skill-acceptance-tests.md), [#5](../air-gap-install-verification.md), [#7](../reverse-proxy-tls-deployment-recipes.md), [#8](../community-skill-installer-ui.md); DE-386; issues #490, #495, #503. |

**Annexes** (siblings of this file):
[**A — Quality rules and failure tests**](annex-a-quality-rules.md) *(core rules are community-authored and land under their author's name)* ·
[**B — User journeys as acceptance criteria**](annex-b-journeys.md) ·
[**C — Page trees, sizing, and claimable work items**](annex-c-work-plan.md)

---

## What this is

A public documentation site for LQ.AI: an audience-indexed façade over canonical repo files, built with **Astro/Starlight and hosted on GitHub Pages** (ADR 0028, accepted 2026-09-20), with **content living in this repository** and the site building from the same tree — so every page's "checked against" stamp is the file's own git history. Latest-version-only until 1.0, with per-page status badges. It curates and routes; it does not fork content the repo already holds.

## The goal

LQ.AI's promise is that every claim it makes can be checked — read the skill that produced the answer, check the citation against the source, inspect the gap catalogue, verify where data goes. The docs site is how that promise reaches people who have not cloned the repo. Its goal is to grow the four things the project runs on:

- **Deployments** — operators who succeed alone, and whose deployments survive week two.
- **Approvals** — evaluators who can say yes from their desk, citing stable URLs.
- **Legal substance** — practising lawyers who become skill authors, the project's canonical value.
- **Contributors** — humans and their coding agents, for whom a material contribution is a recognised route into LegalQuants membership.

## Who we are building it for

Priority-ordered; the full audience matrix and journeys are in Annexes B–C.

1. **The self-hosting legal team, often a legal function of one (P0).** The same person is operator, author and evaluator across months. What the site gives them: from *"is this for me?"* to a verified running deployment without asking a human — and the week-two pages (backup, upgrade, key rotation) that keep the deployment alive once real matters are in it. Every other audience depends on this reader succeeding.
2. **The security / procurement evaluator (P0).** Spends 45 minutes, never installs, holds the veto. What the site gives them: a trust centre with stable, citable URLs — the artifacts outside commentators already praise unprompted (threat model, signed releases, HONEST-STATE), organised so an evaluator completes their questionnaire without a meeting. The public framing this earns the project: *procurement delays measured in days, not months*.
3. **The practising lawyer with substance to encode (P1).** The open-skills thesis made usable: "your prompt files are already skill-shaped", a clear attestation path, and a skill catalogue browsable by **practice area and jurisdiction** — an axis no comparable project's documentation offers and ours can populate today.
4. **The contributor and their coding agent (P1).** The community's actual onboarding advice, stated publicly, is *point your agent at the repo*. The machine surface (`/llms.txt`, `.md` on every URL) makes the site's most common first reader first-class — and because contribution doubles as the admissions route into LegalQuants, the contributor pages are also the community's front door.
5. **The deployment partner (P2).** LQs want to deliver branded deployments to clients — the commercial layer the founder publicly invited. What the site gives them: the licence obligations, stated as obligations, and a documented way to deliver a branded deployment within the upstream licence instead of folklore — enabling that layer on terms nobody can breach by accident.

**Not an audience: people building against LQ.AI.** Under ADR 0031, headless and API-only use is acknowledged, not supported. The site carries exactly one page on it (see scope cuts).

## What the project gets

- **Answers become assets instead of favours.** The two costliest questions in the community record — *"why LQ.AI when the open-source alternative exists?"* and *"how do I deploy this on my company's cloud?"* — were each answered once, in chat, by whoever happened to be online, and neither answer is retrievable. The site converts recurring questions from a person's availability into a permanent, versioned answer.
- **The honesty discipline becomes the public brand.** HONEST-STATE surfaced proudly; every page stamped with the commit it was checked against; every admitted limit ending in a decision. This is the differentiator outsiders already cite — the site makes it the first thing a stranger sees rather than something they excavate.
- **Contribution scales with the community, not the maintainer.** The site itself ships as 22 claimable S/M items with per-item acceptance tests (Annex C): a lawyer can own the skills pages, a DevOps contributor the operations pages, a compliance professional the trust centre — each reviewed, each independently mergeable.
- **The evaluation and deployment funnel compounds.** Most of the P0 content already exists in the repo — the launch is ~60% curation. The site is the highest-leverage packaging of work already done.

**The gap this closes, in one paragraph.** None of this requires invention — it requires organising what exists, and closing four documented failures on the way: a licence obligation recorded only inside ADR 0001 while the community plans white-label deployments (spawned item 1); a public pseudonymization claim the committee's own [published minutes](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-07-26-weekly/notes.md) describe as non-functional (open question 1); silent failure modes that have already cost one user a published wrong conclusion ([#503](https://github.com/LegalQuants/lq-ai/issues/503)); and public surfaces drifting out of agreement with the repo and each other (marketing at v0.4.x against a v0.7.0 repo; PRD §1.6 against the decision log on litigation scope). Each is handled in the open questions and spawned items below rather than argued here.

## What we'd ship

**The tree** — eight namespaces, role-based navigation with a goal-based entry hub (full trees, sizing and rationale in Annex C):

```
/            entry hub: one-sentence definition, data boundary, goal cards, "not for" link
/start/      orientation — "Is LQ.AI for you?", what it touches, quickstart, routing     (5 pages)
/operate/    install ×5, hardware sizing, backup/restore, upgrade, key rotation,
             troubleshooting, headless boot (unsupported — ADR 0031) + recipes/ — an
             EXTENSIBLE catalogue of short, agent-readable topology guides (Tailscale,
             Azure, remote Ollama…) behind a supported-shapes index                     (~16+)
/trust/      TRUST CENTRE — data-flow, threat model, anonymization, audit, supply chain,
             HONEST-STATE, governance, continuity, disclosure, questionnaires            (~13)
/skills/     authoring, testing, attestation, playbooks + generated skill catalogue,
             and a GENERATED coverage index by jurisdiction × practice area: pages
             listing attested skills, research sources/MCP connectors, scope notes,
             and coverage gaps                                                          (~10+)
/deliver/    branding & licensing obligations, theming, branded-deployment guide,
             multi-deployment ops                                                        (~8)
/contribute/ two tracks, live board (generated), per-profile on-ramps, dev-env guide     (~9)
/reference/  GENERATED — config reference, schemas, ADR index, error vocabulary,
             release versioning policy
/changelog/  one page per release: upgrade class (ADR 0025), operator actions, migrations
+ machine surface: /llms.txt and .md for every page URL — a coding agent is the most
  common first reader, and this is a build step now or a rewrite later
```

**The launch (P0):** `/` + `/start/` + the install spine of `/operate/` + `/trust/` (the data-flow page joins when #439 closes) — **~26 pages, ~15 of them curation**. Order: OPS + EVAL launch-gating; AUTHOR + CONTRIB launch-with; PRODUCT fast-follow, with the branding page shipping independently. The order is the working plan and changes by PR.

**The rules it is built under:** the community-authored twelve ranked rules (from the three-site documentation benchmark), sixteen house-style rules, and two conditions — every page states the commit it was checked against; nothing publishes orphaned — plus three regulated-field additions (silent-failure disclosure, professional-duty language at the point of decision, licence obligations as obligations). All with failure tests, all in Annex A. One cross-surface rule joins them: **every page stating a scope or capability names its canonical artifact and check date — failed when two published surfaces answer the same question differently.**

**Structural commitments:** the `/trust/` subtree carries a URL-stability commitment (procurement memos cite these URLs; GitHub Pages cannot configure redirects between a site's own pages, so stability is a naming discipline plus canonical-stub pages for unavoidable moves). Reference pages are generated, never hand-written — their sources (Pydantic config models, skill frontmatter, the ADR directory) already exist. No API reference is published (ADR 0031). The skill catalogue carries **practice area and jurisdiction as first-class axes**, which no comparable project's documentation offers and our skills can populate today.

**Designed to expand.** Two namespaces are catalogues that grow by contribution, not by restructuring:

- **Deployment recipes** (`/operate/recipes/`): short problem-shaped guides in a fixed house format — problem, context, steps, verify, *and the refusal errors explained* (the egress guard refusing plaintext-to-tailnet is a security feature that reads as a wall until a page explains it, issue [#495](https://github.com/LegalQuants/lq-ai/issues/495)). Each recipe is an S-sized claimable item; the Caddy + Tailscale recipe and mini-PRD [#7](../reverse-proxy-tls-deployment-recipes.md) are the precedent. A supported-shapes index fronts the catalogue: one row per topology, marked *recipe published / known to work / not tried*.
- **The coverage index** (`/skills/coverage/`), by **jurisdiction × practice area**: generated from skill frontmatter and the content-source registry (ADR [0021](../../../adr/0021-content-source-registry-and-free-source-expansion.md)) — a page per jurisdiction and per practice area, listing the attested skills, the research sources and MCP connectors relevant to it, the coverage gaps, and the ADR 0024 route for filling them. Each page carries canon's scope decisions in place (e.g. litigation: research and drafting only), which is the cross-surface rule doing its job. A lawyer browses by practice area within their jurisdiction; both axes are already in skill frontmatter.

Both catalogues are agent-readable page-by-page via the machine surface: **a coding agent should be able to fetch "remote Ollama over Tailscale" or "Singapore law resources" as a single `.md` and act on it.** That is the growth model — the site's most common first reader is an agent, and these are the two page types an agent most often acts on.

## What we would not ship (scope cuts)

- **Building against LQ.AI.** ADR 0031: headless and API-only use is acknowledged, not supported. The site carries one page, under `/operate/`, that describes the headless boot and states that no compatibility is promised. No API reference, frontend or fork guide, "gateway as a drop-in" page, streaming guide, or cookbook. Revisit when ADR 0031's triggers fire.
- **End-user help.** The in-app Learn surface owns the daily-user audience — it is version-locked to the deployment and present at the moment of the question. Stated as policy, with one deliberate exception: incident procedures with professional-conduct consequences (a wrong citation, evidence reconstruction) belong on the site, because that reader may no longer have deployment access.
- **Versioned documentation** before 1.0. Latest-only with per-page status badges; revisit at 1.0.
- **A skill registry.** The catalogue is an index with provenance, not a distribution mechanism; registry ambitions route to mini-PRD #8 and the `lq-skills` repo.
- **Journeys as navigation.** Journeys (Annex B) are acceptance tests and contribution units. The nav stays role-based; one grouping only — sidebar, address, and index must agree.
- **A hosted status page.** Not in scope.

## How we'd know it's done

The journeys in Annex B each carry a *failed-when* test runnable by someone who did not write the site. **Launch gate:**

1. The P0 journeys (*Is this for me · Get it running · Hand this to our security team*) pass, run by a non-author; the first additionally passes with a **second reader who has not read the source** — until that reader exists it is unverified, not passed. *What leaves my deployment* joins the gate, with its own second reader, when its page ships (#439).
2. The twelve community-authored failure tests (Annex A): none fires against the built site.
3. Machine surface verified: `/llms.txt` present; every page URL serves `.md`; an agent can orient from one fetch.
4. Accessibility gate in CI (WCAG 2.1 AA) passes — including on generated reference pages, which is where it usually fails.
5. Zero orphan pages; every page stamped with the commit it was checked against; the link checker (`docs/audits/check_doc_links.py`) passes.

## Open questions

None of these blocks a demo or the launch. Each carries the default the site proceeds on until someone decides otherwise.

1. **The anonymization layer** (PR #439; open item in the 2026-07-26 minutes). *Default:* the data-flow page ("what leaves my deployment") waits for #439, and the trust centre launches with the existing anonymization page, which already states the layer's limits. Whatever the outcome, the data-flow page states measured behaviour and ends in a decision ("route privileged matters to Tier 1").
2. **Custom domain.** *Default:* launch at `legalquants.github.io/lq-ai/`. One later move to a custom domain is safe: GitHub permanently redirects every `github.io` path to the same path on the new domain. A second move is not, because Pages cannot redirect one custom domain to another. So pick the final domain once, before the trust centre is offered as a citable reference, and verify it at the organization level first (ADR 0028).
3. **Preview hosting for docs PRs.** *Default:* CI builds each PR and attaches the site as a build artifact; Pages deploys from `main` only.
4. **The deployment-partner framing.** *Default:* only the branding-obligations page ships (spawned item 1); the rest of `/deliver/` waits. The proposed framing is "deliver branded client deployments" (dual-branding, threshold-aware), with fork-based multi-tenant SaaS marked unsupported-but-legal — not "build your own Harvey".

Earlier drafts asked the committee for four more decisions. They are withdrawn, not deferred:

- **Priority order** — the phases above are the working plan and change by PR.
- **Quality rules** — Annex A's failure tests are this PRD's acceptance tests; no separate adoption is sought. The core set still lands under its author's name.
- **Mentors per section** — maintainer review by default; CODEOWNERS routing applies because content stays in the repo.
- **Hosting ownership** — Pages is already enabled on `LegalQuants/lq-ai` and deploys from `main`; the repository's maintainers operate it as they do CI (ADR 0028).

## Spawned, not absorbed

Pre-existing obligations this PRD names as dependencies and refuses to swallow:

1. **Branding-obligations page — ship now, independent of the site** (Effort M). Assigned by ADR 0001 itself; the 50-user threshold appears nowhere else in the repo; the upstream fork refresh (#498) is the natural moment. The single highest-cost gap in the research.
2. **Status-drift fix**: `GOVERNANCE.md` still says Proposed while ADR 0022 is Accepted; the `lq-ai-community` status notes are frozen at 2026-08-02. Two small human-merged PRs.
3. **Scoped API tokens**: PRD §5.1 promises them; the code has JWT session auth only. File the DE and the HONEST-STATE row — the one currently unregistered PRD-vs-code divergence.
4. **Release-notes backfill**: 7 of 12 version tags have no GitHub Release (against PRD §7.8's "full changelog" commitment — second HONEST-STATE row); source material exists for all seven; Effort M. Plus a five-minute edit: v0.4.0's published Release still carries its DRAFT banner.
5. **The founder loop-in.** The committee already decided it (2026-07-26, decision 4: bring Kevin up to date before any public release). A docs-site launch plausibly triggers it; there are two heavier items to bundle (the Apple signing identity SPOF named in ADR 0025; the standing CallDonna.ai transfer offer). Human task, not an agent's.
6. **Machine-actionable jurisdiction / practice-area packs (file as a DE).** The coverage index above is *readable* by agents; the further step — a manifest an agent can *apply* ("for Singapore data-protection work: enable these skills, allowlist this MCP connector, set this tier floor") — crosses into product configuration and legal-substance governance (who attests a pack, and what does the attestation cover?). Too consequential to absorb here; the index is designed so a manifest can be generated from it once the DE lands.

## Where this proposal is weak

The journey evidence skews toward the issue tracker — readers who file issues are not typical readers. Two journeys (annual re-review; insurer inquiry) have no evidence because the project is too young for calendars, not because they are wrong. The sizing in Annex C is one researcher's estimate; every contributor who claims a section should re-size it. And the whole plan inherits a single point of external dependence: the quality layer is one community member's work, and the right response to that is to credit and land it, not to rewrite it.

---

*Drafted 2026-08-12 against `main` @ `e9d57763` (v0.7.0). Revised 2026-09-14: scope aligned to ADR 0031 (one headless page, no `/build/`); stack recorded in ADR 0028; committee decisions reduced to open questions with defaults. Revised 2026-09-20: ADR 0028 accepted and the implementation gate cleared.*
