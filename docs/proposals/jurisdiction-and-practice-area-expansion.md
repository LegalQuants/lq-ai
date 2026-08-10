# Mini-PRD: Jurisdiction & practice-area expansion — clearing the acceptance path for community coverage

> **Status:** Accepted (2026-08-09) — committee-accepted at the weekly call, together with its first extraction. Direction paper for the expansion program; accepting it adopts the §Decisions and the §Roadmap's sequencing, not the deferred items, which each still need their own ADR when their trigger fires. Forks resolved with the maintainer 2026-07-20 (see §Decisions). Inventory **reconciled against both repos and a live-docket dry run 2026-07-20** (see §Reconciliation). The first extraction is [ADR 0024 — Routing expansion contributions](../adr/0024-jurisdiction-and-practice-area-expansion.md) (**Accepted** at the same call; filed with this paper); remaining **(ADR needed)** pieces are promoted one at a time as their triggers fire (see §New ADRs this program needs). This paper follows the precedent of [fiduciary-grade-agentic-legal-work.md](fiduciary-grade-agentic-legal-work.md): the big picture lives here; each ADR extracted from it decides one simple thing.
> **Effort:** L for the program's process work (docs + small ADRs, no code beyond CI lints); the coverage itself is community-contributed and open-ended.
> **Contributor profile:** Maintainers and committee for the ADRs; practicing attorneys per jurisdiction for the coverage; no specific engineering profile.
> **Mentor:** Maintainer team; security review wherever a gate touches `gateway/**` or the vetting playbook.

## What this is

LQ.AI ships US-centric authority sources (CourtListener, GovInfo, SEC EDGAR; EUR-Lex as the one EU beachhead, ADR [0021](../adr/0021-content-source-registry-and-free-source-expansion.md)) and ten advisory/transactional starter skills calibrated to US-law defaults. Meanwhile the community is already proposing coverage beyond both axes — EU privacy, EU trademark, a Spanish statutory corpus, litigation research, arbitration, export controls (see §The live docket). The demand is real, credentialed, and **stalling**, because nobody — contributor or maintainer — can point to a written answer for "what happens next and what must be true to merge."

The thesis of this paper: **the answers mostly already exist in canon** — ADR 0021 for sources, the #190→lq-skills#10 redirect for community skills, DE-264 for corpora, the PRD-amendment path for scope, the [vetting playbook](../security/external-contribution-vetting.md) for security. What is missing is not a grand new mechanism but a *sequence of simple precepts, each grounded in an existing document, each ratifiable on its own*. This paper holds the whole picture; the ADRs extracted from it are deliberately small, because a committee ratifying one sentence ratifies it — a committee ratifying nine decisions at once ratifies whichever one they read closest.

## Motivation: how expansion fails today

An incoming jurisdiction or practice-area contribution has — de facto, not by any documented rule — **four possible homes**, each with a different bar:

| Home | Gate | Attestation | Precedent |
|---|---|---|---|
| `lq-ai` `skills/` | [skills/CONTRIBUTING.md](../../skills/CONTRIBUTING.md): claim → draft → attest → attorney + engineer review → merge | Required (practicing attorney) | The 10 starter skills |
| `legalquants/lq-skills` | Quality gate (structure + skills-qa verdict + evals) + one LQ-member approval | **Not required** | The EU compliance suite, redfern-schedule |
| `skills/community/` in `lq-ai` | Undefined (DE-264 sketches it) | Undefined | None — the directory is empty |
| A sibling org repo (+ MCP) | That repo's own governance | That repo's own | PrivacyQuant (DE-264) |

The routing between them is folklore: the one recorded precedent is a PR comment (lq-ai#190, withdrawn with "this belongs in LegalQuants/lq-skills" → lq-skills#10, merged). Nothing in any CONTRIBUTING.md says that. Every failure mode this program addresses has already occurred on the live docket:

- **Contributors guess wrong** (#190 filed a skill in the product repo and had to withdraw it) — or **stall waiting for a steer** (#174 has been open a month, its central question "where should this live?" unanswered; the same question was asked in community chat on 2026-06-12 and never answered either).
- **Unanswered routing questions resolve into forks.** In one June fortnight, members proposed a French and a UAE version of LQ.AI, a hard fork rearranged around practice areas, and deployment forks — while the project's actual rule ("build it into the backend") was being stated in the same channel (see §Community views). Coverage that forks away is coverage the project never gets.
- **Duplication merges past nobody noticing** (lq-skills#18 overlaps merged #6; neither the contributor nor the gate had anywhere to check).
- **The two skill repos' bars diverge silently** — attestation required at one door, absent at the other — so the same trust question gets different answers depending on where a contribution happens to land.
- **Security review is undefined for the new surfaces**: every S1 source proposal is an unknown-author change to the gateway egress boundary, and a contributed SKILL.md is instructions an LLM executes over privileged client documents — yet the vetting playbook has no skill-content row and the de-facto community home has no adversarial content read.

### Community views on record (WhatsApp #LQ AI, 2026-06)

The community asked this program's central questions a **month before** the docket did, and got no durable answer — which is the clearest evidence that the gap is process, not appetite. Recorded here because chat is not a durable public record. Speakers are cited by the community corpus's own pseudonymous member IDs: these were group-chat messages, not statements written for publication, and the argument does not depend on who made it. Committee views in the next section are attributed by name, since committee decisions are minuted publicly by design.

- **The jurisdiction-fork question, asked and never answered** (builder-061, 2026-06-12): *"what's the plan for LQAI. Anyone keen to release **local jurisdictions versions**? Or it makes more sense to wait for the main one to be finished? / contribute to main one first"* — no reply in the channel. Two days later the same member: *"I will probably make a **French version + a UAE version** too."* Absent a routing answer, the default a contributor reaches for is **a fork per jurisdiction** — precisely the outcome §Out of scope rejects, arrived at by silence rather than by decision.
- **The routing precept already exists in the founder's own words** (builder-012, 2026-06-14): *"If you build functionality that others might want, **build it into the backend — LQ-AI**, but build any frontend type you want with any subset of the available functionality"*; and operationally, *"drop it in LQ-AI — start a branch, get it working, file a pull request… then it's available for everyone to use in any new frontend."* ADR 0024's S1 route is this rule, written down. It has been the project's practice since June; it has simply never been citable.
- **A practice-area architecture was built without a home** (builder-008, 2026-06-14): *"I have **hard forked lq-ai**… The idea is to arrange lq-ai **around practice areas (and matters)** by implementing Deep Agents… Each Deep Agent will cover a practice area and accumulate memory at their practice area level and matter level."* A substantial architectural proposal that never became an issue, a PR, or an ADR — it went to a private fork because nothing told the author where practice-area work belongs.
- **The modularity argument for practice-area packaging** (builder-061, 2026-06-24): *"people who do disputes may not need sophisticated redline tabular reviews of funds agreements and people who just do NDAs don't need a chronology and Redfern schedule"* — the substantive case that coverage is modular by practice area, made in the same thread as the chassis framing (*"LQ-AI is a Chassis for the Ferraris of LegalTech"*) and builder-035's *"I'd much prefer it if we had more of a plugin or extension system."*
- **Practice forks are already contemplated at the top** (builder-012, 2026-06-24): a Relativity/Clio-style build *"as a separate PRD that can sequence after this (**or even as a LQ-AI practice fork**)"*.

Taken together: four separate members reached for a **fork** — by jurisdiction, by practice area, by deployment — in a single fortnight, while the founder was stating a build-it-into-the-backend rule in the same channel. That divergence between stated practice and contributor behaviour is the cost of unwritten routing, and it is what ADR 0024 is for.

### Committee views on record (#lqai Slack, 2026-07-12 → 07-18)

The committee then took up the same questions; those views ground the extractions and are likewise recorded here:

- **The maintenance fear that motivates the trust tiers** (Hou Fu, 2026-07-17): *"if I accept this code and I don't understand it… say the law changes in the state of XYZ, will someone be around to update it or we will have a very outdated LQ AI"* — and, channel-wide: *"people have very different ideas of what LQ AI should be."*
- **The tiering/maintainer-of-record answer** (Joel A. Kaufmann, 2026-07-18, in reply): jurisdiction-specific skills accepted only with a licensed attester who becomes maintainer of record; tech review as a separate gate; unattested work in a labeled experimental tier that graduates when a licensed attorney signs on; *"coverage would scale with the network, not raw contributions… the demand [a killer feature] creates is exactly what recruits an XYZ-licensed maintainer."* This exchange is the origin of the companion trust-tiers ADR, and of operating principles 3–4 below.
- **Litigation carve-in demand is committee-side too, not just the contributor's**: Joel's question for the founder (2026-07-17) — *"litigation drafting needs almost nothing new from the architecture… what's actually stopping us from putting it on the roadmap?"* — and Peter Scripps' datapoint (2026-07-17): *"we handle all litigation in-house to the maximum extent possible. So, litigation elements would be helpful for us."* (lq-ai#287's filer is Joel himself.)
- **A recorded counterweight** (Hou Fu, post-call, 2026-07-12): *"wary about US litigation or even shipping dispute tools."* Views on the S4 carve-in genuinely diverge — which is exactly why the S4 route sends it to a committee decision rather than letting a routing response pre-judge it.
- **The chassis/plugin fork intersects this program** (Hou Fu, 2026-07-12: concluding the plugin/chassis issue is *"blocking how we can implement specific jurisdiction or practice area function"*; Alexios × Hou Fu 1:1 note, 2026-07-14: product-vs-chassis, *"the chassis/plugin decision stays the blocker and needs Kevin"*). This paper does not pre-empt that decision. The routing precepts are deliberately compatible with either outcome: skills, sources, and corpora are already the plugin-shaped units of coverage, and if a plugin/chassis architecture is adopted, the D1 homes become distribution channels for the same units — the shapes, gates, and claims survive; only the packaging mechanics move to that program's own ADRs. Until then, routing within the current architecture is what the live docket needs.

Four operating principles follow, and run through every extraction:

1. **The goal is merged PRs, not perfect governance.** Real practitioners are offering real coverage; every week a proposal sits unrouted, the project loses the contributor. Acceptance is the default path, with gates explainable in one issue comment.
2. **Two axes, kept distinct.** *Procedurally* (what happens): where the contribution goes, who acks, in what order. *Substantively* (what must be true): what it must contain and clear to merge. Conflating them is how proposals stall — a maintainer who cannot yet judge the substance still owes the contributor the route. ADR 0024 is deliberately the procedural axis only.
3. **Attestation capacity is the binding constraint, and it varies by proposer** — some claim they can self-attest (#287, #271), some bring an attester (#174), some bring none (#22's is nonconforming). The path must use the attestation that exists rather than demand attestation the project cannot supply; that is the companion trust-tiers ADR's whole design.
4. **Demand recruits maintainers.** A jurisdiction generating proposals is exactly where a licensed maintainer-of-record can be recruited (#18's Spain-qualified author is the live example). The response practice converts proposers into maintainers instead of filtering them out.

## Decisions (forks resolved with the maintainer, 2026-07-20; item 8 added 2026-07-31 on review of PR #313)

1. **Direction-paper-first; ADRs extracted one at a time.** This document replaces a first-draft omnibus ADR that decided routing, gates, security posture, a vocabulary, a coverage map, a playbook, and enforcement in one text. Each precept now promotes to its own small ADR when its trigger fires, exactly as ADRs 0018–0021 were extracted from the fiduciary-grade paper. *(Rejected: the omnibus ADR — consensus-by-bundle; a stack of micro-ADRs filed all at once — same problem in more files.)*

2. **The first extraction is routing (ADR 0024), and only routing.** The single highest-leverage precept: where each shape of contribution goes. Every sentence of it restates something already in canon, so consensus is cheap and the whole live docket unblocks. Claim-recording (one plain table, extending skills/CONTRIBUTING's existing "claim first" step) rides in the same ADR because routing without a recorded claim recreates the duplication failure already observed (lq-skills#18 vs merged #6). *(Rejected: routing and claiming as separate ADRs — the claim step is one sentence and the pair is still "a list of simple things.")*

3. **Security hardening goes through the vetting playbook, not an ADR.** The playbook's own closing rule invites new threat classes; contributed skill content (a SKILL.md is instructions an LLM executes over privileged client documents) becomes a threat-class row via a normal security-routed docs PR. *(Rejected: deciding security posture inside the expansion ADR — wrong review routing, wrong owners.)*

4. **Trust tiers stay in the companion ADR.** The trust-tiers/maintainer-of-record ADR — **not yet written; in progress** — is the substantive-gate half of this program and files separately, after routing lands. It takes the next free ADR number when it is filed, not one reserved now. *(Rejected: merging it into this program's ADRs — it is already a self-contained, well-scoped decision.)*

5. **Accountability artifacts ride ADR 0022's satellite repo, when it lands.** Per-item explainer decks / routing receipts would extend the `LegalQuants/lq-ai-community` repo that ADR 0022 (PR #311) creates for meeting records, filed under issue/PR number — contingent on 0022's acceptance, not decided here. *(Rejected: deciding the records home in this program — it is 0022's decision to make.)*

6. **Maintainer tooling is referenced function-first.** The playbook practice (lane triage, per-item receipt, salvage, human-gated responses) is specified tool-agnostically; [houfu/lq-maintainer-agent](https://github.com/houfu/lq-maintainer-agent) is the current reference implementation. Automated assistants draft and report; **a human maintainer decides and sends every response** — the same floor the vetting playbook sets. *(Rejected: formally adopting the tool — couples project process to an external v0.2 repo.)*

7. **Claims are recorded, then verified — never pre-accepted.** A contributor's statement that their spec "follows ADR 0021," that they hold a bar admission, or that a self-run QA pass was clean is contributor narrative. Responses record it; gates verify it. This posture runs through every precept below and is why the docket descriptions in this paper say "self-described." *(Grounded in the vetting playbook §4's human-only judgments and the attestation process.)*

8. **The coverage map back-fills merged coverage on day one.** Not "starts from the first routed proposal." The realized collision (lq-skills#18 against merged #6) was against *merged* coverage, so a map that starts empty is blind to exactly the failure it exists to prevent; §The live docket is most of the initial table already. *(Rejected: the empty start — cheaper to create, catches nothing already on the books.)*

## The demand, decomposed (the four shapes)

Every expansion proposal observed to date is one of four shapes — this taxonomy is the analytical backbone of the program and of ADR 0024:

| Shape | What it is | Existing anchor |
|---|---|---|
| **S1 — Authority source** | A new citable data source (register, statute DB, court API) | ADR 0021 (registry, honest availability, phased build) — designed for exactly this extensibility |
| **S2 — Skill(s)** | Work-product skills carrying legal substance | skills/CONTRIBUTING.md (attested, lq-ai) vs. lq-skills' quality gate (community) — the #190→#10 redirect chose the home |
| **S3 — Corpus / statutory graph** | A versioned body of law as data, usually with deterministic MCP tools | DE-264 (the PrivacyQuant sibling-repo pattern) |
| **S4 — Scope carve-in** | The practice area is excluded by PRD §1.6 | PRD amendment + committee decision (governance process, PR #311) |

Proposals decompose: lq-ai#271 is S1 with sibling S2 work already filed separately (lq-skills#9/#16/#17); lq-ai#287 is S4 first, then S2; lq-ai#174 is S3 with a latent S1 edge (live external lookups).

## The live docket (evidence, collected 2026-07-20)

Contributor credentials are **as self-described** (Decision 7). Jurisdiction-specific demand is all EU; one proposal is jurisdiction-agnostic.

**New jurisdictions:** lq-ai#174 (GDPR statutory graph + MCP starting with Spain; author explicitly asks *where it should live* and what namespace); lq-ai#271 (EUIPO Trademark Register as a WS-E source; proposed OAuth2 client-credentials auth would be a gateway first); lq-skills#5–#8 merged + #19 open (EU compliance suite); lq-skills#9/#16/#17 (EUIPO trademark trio); lq-skills#18 (a second GDPR Art. 28 skill **overlapping merged #6** — the duplication failure mode, realized; its `jurisdiction: EU-ES` also fits no current vocabulary); lq-ai#309 (jurisdiction-agnostic scoped-web-search catalog).

**New practice areas:** lq-ai#287 (litigation research + drafting carve-in; needs the §1.6 amendment; mini-PRD promised, not yet filed; committee views already on record on both sides — see §Committee views); lq-skills#10 merged + #13 (international arbitration); lq-skills#20 (US regulatory-enforcement analysis); lq-skills#22 (US export controls, first-time external author — within §1.6 scope, no carve-in needed).

The PRD **already invites** much of this: DE-001 (practice-area skill candidates), DE-002 (jurisdiction regimes incl. Singapore PDPA, LGPD, PIPL), DE-264 (the sibling-repo pattern).

## What exists vs. what's missing

| Need | Today | Net-new |
|---|---|---|
| **Routing** | Folklore: four possible homes (lq-ai `skills/`, lq-skills, empty `skills/community/`, sibling repos); the one precedent is a PR comment (#190) | **ADR 0024**: four routing sentences, each restating canon |
| **Claim registry** | skills/CONTRIBUTING requires "claim first" but records claims nowhere visible; #18-vs-#6 collision realized | One plain markdown claims table (rides ADR 0024); a structured jurisdiction vocabulary is **later** (ADR needed) |
| **Substantive gate** | lq-ai: attorney attestation + dual review. lq-skills: quality gate, **no attestation**. Bars diverge silently | The companion trust-tiers ADR (trust tiers, maintainer of record) — not yet written; lq-skills adoption is that repo's own PR (ADR needed for tier semantics — see §New ADRs) |
| **Security gate** | Vetting playbook covers gateway/deps/CI/deploy for unknown authors; **no row for skill content**; lq-skills gate has no adversarial content read | Playbook amendment PR (Decision 3); S1 proposals from external authors get the full playbook read (already the playbook's own §1 rule — needs only a pointer from the routing response) |
| **Scope amendment** | PRD §1.6 changes only by PRD amendment; no documented path | S4 route: mini-PRD in `docs/proposals/` (this paper's own format) → committee → amendment. #287 is the live test case |
| **Maintainer response practice** | Ad hoc; response quality varies by maintainer | Playbook doc `docs/contribute/expansion-playbook.md`, written **after** the first few real routings (drafting it from experience beats drafting it from theory) |

## Reconciliation (verified 2026-07-20, both repos + dry run)

All docket items, gate texts, and repo structures were verified directly against `legalquants/lq-ai` and `legalquants/lq-skills` (issues, PRs, CONTRIBUTING files, CI scripts). The four-shape taxonomy and a draft response process were then **dry-run against four live docket items**, one per shape-class of difficulty. The findings below are the concrete cases the extracted ADRs must serve; they are recorded here in full because this paper is the committed record.

**lq-ai#271 (EUIPO source → S1): routes cleanly; verdict *proceed*.** Anchors cleanly to ADR 0021 D1/D2/D6 (whose registry was designed for exactly this extensibility); single-concern (the author correctly filed the sibling skill work separately as lq-skills#9/#16/#17); no duplicate. Two real, non-blocking obstacles for the eventual PR, both understated by the issue itself: (a) the gateway has **no OAuth2 client-credentials support** — every current `tool_provider` uses a static key or none, so "similar to how any OAuth2-based provider would fit" has no existing provider to model on; (b) ADR 0021 D3's char-fidelity verification is defined for prose, and **what "quoting" a structured register record means is undefined** (→ the S1-interpretive-adapters ADR). The author's `author_association` on lq-ai is NONE — a new-to-this-repo external contributor, so the eventual gateway PR takes the full vetting read.

**lq-ai#174 (GDPR/Spain corpus → S3): does *not* route cleanly; verdict *escalate*.** GDPR/EU expansion itself is settled as in-scope (DE-264, DE-002, both correctly cited by the filer) — but neither anchor covers the actual ask: DE-264 describes integrating with the *existing* PrivacyQuant repo, not standing up a **new** corpus for a jurisdiction PrivacyQuant excludes. The issue's own three-way placement fork (new sibling repo / an `eu/` tree inside PrivacyQuant / lq-skills-only) is a genuinely unanchored structural decision — the reason the S3 route in ADR 0024 names placement a per-proposal maintainer call until the S3 charter ADR exists. Also flagged: the proposed MCP tool "find an AEPD precedent" is ambiguous between serving pinned data and **live external lookup** — the latter is S1-shaped egress, which is why ADR 0024's S3 route gates operator-reaching pieces in lq-ai. The merged EUR-Lex source (lq-ai PR #257) is directly relevant infrastructure the issue does not mention.

**lq-skills#18 (second GDPR Art. 28 skill → S2): routes cleanly; merge-bar *blocked* today.** Substantive, honestly-documented work — not slop and not a mechanical duplicate — but its "complementary, not competing" analysis is **silent on the closest neighbor**, merged `dpa-art28` (#6), which shares the same Art. 28(3)(a)–(h) review core. Genuine differentiators: a machine-scorable 14-item rubric with verbatim-quote verification, a shipped 50-DPA synthetic benchmark, and Spain/AEPD depth (EN/ES) vs. #6's German depth (DE/EN). Mechanically blocked on lq-skills' own gate (skills-qa band "pending", required README table row missing, no CI run on the head). Whether the library carries three confusably-named DPA skills, cross-references, or consolidates is a **maintainer library-shape decision** the contributor cannot resolve — playbook material. Its `jurisdiction: EU-ES` fits no current vocabulary (→ the vocabulary ADR); its Spain-qualified author self-attests his own work (→ the licensure-verification ADR) and is a natural maintainer-of-record candidate under the companion ADR (the recruitment lens in action).

**lq-skills#22 (EAR crypto-scan skill → S2, first-time author): routes cleanly; gate outcome required improvisation.** A full adversarial read over the 1,930-line diff was **clean** — no injection, phone-home, exfiltration, invisible-Unicode, or scope creep; the skill's own instructions mandate local-only writes and secret redaction. But the gate exposed three holes no current document owns: (a) the attestation is present but **nonconforming** — it attests bar status and personal use, not the substantive-accuracy certification skills/CONTRIBUTING §3 prescribes; (b) a named substantive question for the attorney reviewer (the decision tree routes authentication-only crypto toward STRONG-5D002 without surfacing the EAR Cat.5 Pt.2 authentication decontrol or §740.17 — potentially over-inclusive for consuming counsel); (c) the contribution carries **employer-copyrighted material** on an unverifiable "approved by IP counsel" note — the IP-provenance gap in §Open questions. Key merge-bar claims (self-run skills-qa "READY", a test suite not in the PR) are self-attested — Decision 7's record-then-verify posture applied.

**Cross-cutting:** the two items that routed with friction did so exactly where this paper defers to a future ADR (placement, tiers, vocabulary, licensure) — evidence the deferral list is cut correctly rather than left vague. The dry run also surfaced blind spots in the maintainer-assist tooling itself (single-repo canon assumption; no security lane for skill content as agent-executed instructions; attestation checked for presence, never conformance or independence) — fed back to that project; out of this program's scope.

## Roadmap (phased, trigger-driven)

**Phase 1 — now:**
1. **ADR 0024 (routing + claim recording)** — the four routing sentences + the claims table. **Accepted 2026-08-09**; unblocks the docket.
2. **Vetting-playbook amendment** — skill-content threat class + a note that expansion PRs from unknown authors in sensitive classes get the full read. Security-routed docs PR.
3. **The companion trust-tiers / maintainer-of-record ADR** — **not yet written; in progress.** Written and filed once 0024 lands, taking the next free number then.

**Phase 2 — after the first real routings:**
4. `docs/contribute/expansion-playbook.md` — response templates distilled from actual D-step responses (classify → check claims → route → state gate → recruit → record; dispositions: routed / duplicate / preserved-as-DE crediting the proposer / declined-with-cited-reason; disputes get a second reviewer and pause, never waive).
5. **Jurisdiction vocabulary ADR** — one controlled list adopted by both repos' frontmatter, with the multi-code question (`EU-ES` → `[eu, es]`) and grandfathering; carries the CI lint per ADR 0016's pattern.
6. **lq-skills adoption PR** — gate language + lint proposed to that repo under its own process.

**Phase 3 — when triggered (see §New ADRs):** S3 repo charter; records/receipts home (post-ADR 0022); the remaining deferrals.

## New ADRs this program needs

Extraction order is by trigger, not by numbering. Each is one simple decision.

| ADR | Decides | Trigger |
|---|---|---|
| **0024 Routing** (accepted 2026-08-09) | The four routing sentences + claim recording | Now — the docket is waiting |
| **Trust tiers** (in progress — not yet written) | trusted/experimental tiers, maintainer of record, demotion-not-deletion | After 0024 |
| **lq-skills tier semantics** | Whether lq-skills merges can be `trusted` (requiring verified attestation there) or stay `experimental` until adopted into lq-ai | First S2 PR with a claimed qualified attester (#18/#22 live) |
| **Licensure verification** | How a claimed bar admission is verified; self-attestation independence; pseudonymous contributors | First trusted-tier request from an attester not personally known |
| **Jurisdiction vocabulary** | The controlled code list, multi-code declarations, coverage-cell resolution, grandfathering | First D5-style lint work, or the claims table's free-text cells becoming ambiguous |
| **S3 repo charter** | Placement guidance, namespaces replacing `pq-*` (#174's question), creation checklist, org security baseline (CODEOWNERS, provenance) | Acceptance of lq-ai#174, or any new corpus repo |
| **S1 interpretive adapters** | Whether an adapter that *interprets* structured records (register statuses — the #271 case) carries legal judgment needing attestation; what char-fidelity verification means for records vs. prose | The #271 adapter PR, or any records-not-prose S1 source |
| **Records/receipts home** | Whether per-item routing receipts and explainer decks extend `lq-ai-community` (ADR 0022), filed under issue/PR number | PR #311 landing + first disputed routing or a month of routings |
| **Intake automation** | Whether tooling formally assists routing, with a one-way ratchet (automation may demote toward caution, never promote toward a lighter gate) | Strain: repeated ack-window misses, or unclaimed experimental cells exceeding claimed ones |

## Open questions (resolve in the relevant ADR)

- The chassis/plugin architectural direction (a live committee question awaiting founder input — see §Committee views). If adopted, the D1 homes become plugin-distribution channels for the same coverage units; the shapes, gates, and claim recording survive, and the packaging mechanics get their own ADRs under that program.
- `skills/community/` and DE-264 Phase A: retire the empty in-repo path and land `pq-*` in lq-skills, or keep it — a committee scope decision with a PRD amendment (surfaces when DE-264 Phase A is claimed).
- IP provenance / authority to contribute employer-copyrighted material (live in lq-skills#22) — a gate cell no document owns yet; likely a vetting-playbook or CONTRIBUTING addition rather than an ADR.
- S2 naming and library shape (`lq-dpa-art28-review` vs `dpa-art28`; coexist / rename / consolidate) — resolves with the #18 disposition and becomes playbook material.

## Out of scope (file as DE-XXX if they surface)

- Any first-party corpus ownership or per-jurisdiction content curation by the maintainer team (contradicts driver economics; coverage scales with the attorney network per the companion trust-tiers ADR's thesis).
- Per-jurisdiction repos for skills (`lq-skills-eu`, …) — fragments discovery; the claims table gives the by-jurisdiction view without the split.
- An intake form/bot before the manual process has run (see the automation ADR's strain trigger).
- Changes to lq-skills' gate imposed from this repo — everything lq-skills-facing is proposed to that repo under its own process.

## Cross-references

- First extraction: [ADR 0024](../adr/0024-jurisdiction-and-practice-area-expansion.md). Companion: the trust-tiers & maintainer-of-record ADR — **not yet written**; written and filed after 0024 lands, taking the next free ADR number then.
- Canon this program restates: ADR [0021](../adr/0021-content-source-registry-and-free-source-expansion.md), [0016](../adr/0016-transparency-and-governance-invariants.md), [0019](../adr/0019-transparent-validity-treatment-layer.md) D8, [0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md)/[0015](../adr/0015-governed-tool-calling-model.md); [skills/CONTRIBUTING.md](../../skills/CONTRIBUTING.md); [docs/security/external-contribution-vetting.md](../security/external-contribution-vetting.md); PRD §1.6, §9 (DE-001/DE-002/DE-264).
- Governance dependency: GOVERNANCE.md + ADR 0022 — **adopted** (PR #311, merged 2026-07-27); the S4 committee path and response-window norms are defined against that text.
- Style precedent: [fiduciary-grade-agentic-legal-work.md](fiduciary-grade-agentic-legal-work.md) (direction paper → extracted ADRs 0018–0021).
- Community discussion (LegalQuants WhatsApp corpus, member-access required; cited by channel + line so it is checkable): `LQ AI#L551`, `#L609` (jurisdiction-version question and the French/UAE fork intent, 2026-06-12/14); `#L614`, `#L617` (the founder's build-it-into-the-backend rule, 2026-06-14); `#L627`, `#L652` (the practice-area Deep Agents hard fork, 2026-06-14); `#L1271`–`#L1290` (chassis/plugin thread, incl. the disputes-vs-NDA modularity argument, 2026-06-24); `#L1301` (practice-fork contemplation).
- Committee discussion (workspace-access required): the maintenance/tiering thread ([#lqai, 2026-07-17/18](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1784329089914559?thread_ts=1784250520.174489&cid=C0BDS8RR7JM)), the litigation questions-for-the-founder thread ([#lqai, 2026-07-17](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1784240944094989?thread_ts=1784240944.094989&cid=C0BDS8RR7JM)), and the post-call chassis/plugin note ([#lqai, 2026-07-12](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1783869266972389)). Quoted in §Committee views because Slack is not a durable public record; the durable record moves to the meeting-minutes repo when ADR 0022 (PR #311) lands.
- Live evidence (all verifiable on GitHub): lq-ai issues [#174](https://github.com/legalquants/lq-ai/issues/174), [#271](https://github.com/legalquants/lq-ai/issues/271), [#287](https://github.com/legalquants/lq-ai/issues/287), [#309](https://github.com/legalquants/lq-ai/issues/309); lq-ai PRs [#190](https://github.com/legalquants/lq-ai/pull/190) (withdrawn → redirect), [#257](https://github.com/legalquants/lq-ai/pull/257) (EUR-Lex, merged); lq-skills PRs [#5](https://github.com/legalquants/lq-skills/pull/5)–[#10](https://github.com/legalquants/lq-skills/pull/10) (merged), [#9](https://github.com/legalquants/lq-skills/pull/9), [#13](https://github.com/legalquants/lq-skills/pull/13), [#16](https://github.com/legalquants/lq-skills/pull/16)–[#20](https://github.com/legalquants/lq-skills/pull/20), [#22](https://github.com/legalquants/lq-skills/pull/22) (open).
