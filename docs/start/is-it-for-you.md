# Is LQ.AI right for your team?

LQ.AI suits teams that want to run their own application and are prepared to maintain it. Try the tasks you care about before deciding.

## Who it is designed for

The main focus is in-house legal work: contracts, policies, regulatory questions, and advice. That includes a legal team of one. Lawyers at firms, solo practitioners, legal-aid teams, and clinics can use it too — the useful question is whether its tasks match your work, not whether you're the intended practitioner type. LQ.AI ships 15 built-in skills: 10 starter skills calibrated to that in-house work, plus 5 more — case-law research, three Tabular Review column skills (contract-snapshot, msa-snapshot, nda-snapshot), and playbook-easy-extract, an internal skill that feeds the Easy Playbook generation pipeline. Read their scope in the [skills](../../skills/) directory and try examples before judging the fit.

### Details

- **Primary user, in the PRD's own words:** "in-house counsel at organizations of any size, from solo General Counsel to enterprise legal departments" ([PRD §1.4](../PRD.md#14-target-users)). Nothing in [PRD §1.6](../PRD.md#16-out-of-scope-v1) disqualifies a reader by where they practise — every v1 exclusion on this page is a *use case*, not a practitioner type — and the repository's own forward-looking notes describe the positioning as "open-source AI for legal teams — covering in-house, firm, and solo practitioners" ([PRD §9, DE-023](../PRD.md#de-023--external-counsel-collaboration-boundary)).
- **The skill count, checked against the code, not just the README.** The API's skill registry (`api/app/skills/loader.py`, `api/app/skills/registry.py`) walks every top-level folder under `skills/` that contains a `SKILL.md` and serves all of them through `GET /api/v1/skills` — 15 folders as of the checked commit, matching what README documents as the full built-in set: "Ten starter skills ship with the M1 release" (README.md:109) plus "Five additional built-in skills also ship in `skills/` beyond the ten above" (README.md:126). One instructional aside elsewhere in the README ("browse the 10 built-in skills," README.md:246) hasn't caught up to that second figure, and nothing in the frontend hardcodes either number — if the exact count matters to your evaluation, open the [skills](../../skills/) directory and count yourself rather than trust either line.

## You need someone to run it

You need a computer or server that can run Docker, and someone responsible for updates, backups, user access, provider keys, and investigating problems. That person can be in IT, legal operations, or an outside support team. The people using the results still need to review the answers and their sources.

### Details

- **Host requirement:** Docker Desktop 4.x+ (or Docker Engine 24+ on Linux) and `git` — no other host tooling, no Python, no Node, no language-specific runtimes. Plan for roughly 8 GB of free disk space and 6 GB of RAM available to Docker (README.md:167).
- **Who the "operator" is, per the PRD:** "the person or team deploying LQ.AI within an organization. Could be the legal team itself (technical GC, legal-ops manager) or IT/SRE deploying on legal's behalf. The operator cares about deployment ergonomics, key management, audit trails, and integration with existing identity providers." ([PRD §1.4](../PRD.md#14-target-users))

## If you want a fully managed service

The installation covered on this site runs on infrastructure you manage. The project mentions paid support and managed services, but does not specify an available service package or its commitments beyond that mention. If you want someone else to host and operate it, confirm the arrangement directly.

### Details

- v1 is self-hosted only — "No legalquants.com-hosted instance" ([PRD §1.6](../PRD.md#16-out-of-scope-v1)).
- The PRD's own procurement appendix names a managed-service option in one place: "For organizations that require commercial support, LegalQuants offers managed services (hosted deployments, custom skill authoring, training, support) — the software remains open source and self-hostable; the services are paid" (PRD, Appendix E, "Is this under support?"). As of the checked commit, that sentence — plus a matching parenthetical in [PRD §7.1](../PRD.md#71-project-philosophy) — is the full specification; there is no published service catalog, pricing, or SLA in this repository. Ask LegalQuants directly if that's what you need.

## If company sign-in is required

The LQ.AI login code supports local email-and-password accounts and authenticator-app (TOTP) codes. It does not implement SAML, LDAP/Active Directory, SCIM, or trusted-header sign-in in that login path, as of the checked commit. The underlying OpenWebUI code has its own identity features, but that does not establish that they work for the LQ.AI workspace. If company sign-in is mandatory, require a demonstration of that exact flow before proceeding.

### Details

- **What the PRD claims vs. what ships.** [PRD §5.1](../PRD.md#51-authentication-and-authorization) describes OAuth (Google, Microsoft, GitHub), SAML 2.0, LDAP/Active Directory, SCIM 2.0, and trusted-header SSO as "first-class IdP integrations" the backend implements. `api/app/api/auth.py` — the module that implements login, MFA, and password change — has no SAML, LDAP, or trusted-header code path as of the checked commit, and `docs/HONEST-STATE.md` does not carry a row for authentication providers. What is shipped and verifiable there: local email/password login and TOTP-based MFA enrollment/verification (`api/app/api/auth.py`; TOTP handling in `api/app/security/totp.py`). Treat the broader IdP claim as **not documented in the repository as of the checked commit** until you can point at the code yourself.
- **One qualification:** the `web/` fork inherits upstream OpenWebUI's own LDAP sign-in configuration (`ENABLE_LDAP` and the `LDAP_*` settings, `web/backend/open_webui/config.py:2754-2772`). It is upstream code, is not wired to LQ.AI's own auth surface (which is backend-owned per [ADR 0002](../adr/0002-backend-owned-auth.md)), and is not documented as supported anywhere in this repository as of the checked commit — do not plan on it without reading that path yourself.

## If you need litigation operations

Do not choose it as a replacement for e-discovery, docket management, or court filing. Those workflows are outside the stated v1 scope. Case-law research through CourtListener is a separate capability: retrieving an opinion and showing which sources were consulted does not establish that a legal conclusion is correct. A disputes practice may still find individual research, drafting, or contract tasks useful.

[PRD §1.6](../PRD.md#16-out-of-scope-v1) states this non-goal directly:

> "E-discovery or litigation-specific workflows. Focus is in-house counsel work: contracts, policies, regulatory matters, advice. Litigation tools are a separate product category."

> [!NOTE]
> **Professional duty** — If your practice needs litigation-specific tooling, LQ.AI's v1 scope does not cover it (PRD §1.6) — that tooling is a separate product category, and routing litigation work through a research feature that was not built for it is a competence question (Model Rule 1.1 territory in ABA-model jurisdictions), not a product limitation you can work around.

### Details

- **What research does ship:** case-law lookup via CourtListener, plus three further free authority sources (GovInfo, SEC EDGAR, EUR-Lex by CELEX number) added since, all routed through the Inference Gateway and tier-gated like every other external call (`docs/HONEST-STATE.md` §5.5–§5.6). The PRD marks the core capability explicitly partial — "PR6 status: PARTIAL — case-law retrieval shipped; full research surface still deferred" ([PRD §3.6](../PRD.md#36-research)) — and `docs/HONEST-STATE.md` §5.5 is specific about the boundary: case-law retrieval and "Sources consulted" provenance ship; result-content accuracy judging does not, and that provenance is a deliberately different data structure from the Citation Engine's character-verified quotes. Research retrieval is not e-discovery, docket management, or filing support.
- **A live disagreement, for transparency:** a practising litigator's scope proposal ([issue #287](https://github.com/LegalQuants/lq-ai/issues/287)) reached the community's [decision log](https://github.com/LegalQuants/lq-ai-community/blob/main/decisions/README.md), which narrows the conversation to "research and drafting" without amending the PRD text quoted above. This page follows the PRD (§1.6, §3.6) and `docs/HONEST-STATE.md` §5.5, checked against the commit stamped in this page's footer; if the decision log reads differently to you, the PRD is this project's top-priority canonical source (see `CLAUDE.md`'s decision routing), and the gap between the two is worth raising as an issue rather than resolving by guesswork.

## If you need a complete legal operations system

The app has matters and some intake connections, but those do not establish a complete request portal with service deadlines, approvals, escalations, and management dashboards. Direct contract-lifecycle-management integrations and billing or time tracking are also listed outside the v1 scope. Demonstrate any required connection or approval process before depending on it.

### Details

- [PRD §1.6](../PRD.md#16-out-of-scope-v1) puts the full intake/triage/matter-management workflow out of scope for v1: "LQ.AI is the analytical AI layer; Streamline AI and Checkbox occupy the operational-workflow layer. They are complementary; v1 stays on the analytical side. Light intake bridges (§3.x Slack/Teams Bridge in M3) are in scope; full operational workflow is not."
- The same section lists "Direct integrations with CLM systems (Ironclad, Concord, etc.)" and "Billing / time tracking" as separate v1 non-goals.

## If you work with outside counsel or on a phone

Do not assume team accounts provide the access controls you need for collaboration between firms or with outside counsel. Test who can see each matter, file, and result. The documented mobile option is the responsive website; a native iOS or Android app is outside the stated scope.

### Details

- The repository does not document, as of the checked commit, any multi-firm or external-counsel collaboration feature, or any per-seat model for granting an outside lawyer scoped access beyond your own deployment. [PRD §9, DE-023](../PRD.md#de-023--external-counsel-collaboration-boundary) tracks this as an open question at priority P3, "no v1 implementation expected" — the acceptance criteria call for a future PRD revision and observed community demand before any commitment, not a specific ship date.
- Mobile: "Mobile applications. Web UI is responsive, but no native iOS/Android apps" ([PRD §1.6](../PRD.md#16-out-of-scope-v1)). There is nothing to install from an app store; a phone browser pointed at your deployment is the whole mobile story as of the checked commit.

## Compare it with a hosted legal product

A hosted service may suit you better if reducing installation and maintenance work is your priority. LQ.AI gives you source files you can inspect and change, including skills and the code that checks quotations. Compare the actual support, data handling, and features offered by each product; being self-hosted does not by itself make a deployment more private or better supported.

### Details

- The category is more crowded than a three-name shorthand suggests, but GC.AI, Spellbook, and Legora are the names [PRD §1.2](../PRD.md#12-positioning) uses most. Those products can be faster to get running because someone else operates the infrastructure — if "someone hosts this for me, with nothing to run" matters more to you than seeing how it works, that's a genuine point in their favor.
- Where LQ.AI departs structurally: the skills, the citation-verification logic, and every artifact shaping an answer ship as source you can read, fork, and audit ([PRD §1.3](../PRD.md#13-transparency-as-a-founding-principle)) — a closed competitor's equivalent claim is not independently checkable by you.

## Compare it with a general chat tool

For an occasional question, a chat tool you already use may be simpler. LQ.AI is worth evaluating when you want repeatable skills, work organized by matter, and checks against uploaded source text. Compare the actual account terms and settings of any alternative; consumer and business offerings can have different privacy arrangements.

### Details

- Against ChatGPT, Claude, or Microsoft Copilot: LQ.AI is purpose-built for legal workflows — a curated skill library, citations verified against the source document, and a confidentiality posture generalist consumer tools don't carry, addressing the kind of privilege exposure courts have already flagged (PRD §1.2 cites *U.S. v. Heppner*). If your need is a single low-stakes question with no confidentiality concern and no citation requirement, a generalist tool is the simpler choice for that one case.

## Compare it with OpenWebUI

LQ.AI builds on OpenWebUI. If you mainly want to host a chat interface, consider whether OpenWebUI alone meets the need. LQ.AI adds legal-task skills and playbooks, organization background, source-quotation checks, routing rules, and audit records. Each addition has limits described in this guide; none guarantees that an answer is right.

### Details

- LQ.AI is a fork of [OpenWebUI](https://github.com/open-webui/open-webui), pinned and tracked per [ADR 0001](../adr/0001-openwebui-fork-pin.md). What LQ.AI adds lives outside `web/` entirely — the Citation Engine, the Anonymization Layer, tier derivation and floor enforcement, the skill/playbook/Organization-Profile model, and the privilege-aware audit log are in `api/` and `gateway/` (README.md, "Architecture"). The fork's own changes are auditable: ADR 0001 notes anyone can diff `web/` against the pinned upstream tag and see exactly what changed.
- `docs/comparison.md` is the project's own evidence-linked comparison, but as of the checked commit it argues a narrower case than the three comparisons above — it measures LQ.AI against a proprietary "fiduciary-grade" category on verifiability, and does not name a case where a commercial product is the better choice, or compare against OpenWebUI directly. Read [`docs/comparison.md`](../comparison.md) itself for the verifiability argument in full.

## Before deciding

Try a made-up document that resembles your work. Confirm the file type is supported, the right people can access it, the chosen model receives only what you intend, and the result is useful to a reviewer. Current uploads accept PDF, plain text, and Markdown (`api/app/pipeline/parsers.py:135-156`); naming Word documents in a skill's description does not add DOCX upload support — a Word document must be pasted as text or converted to PDF first (`docs/skill-authoring-guide.md:177`).

If none of the checks on this page describe your situation, nothing in the project's stated scope rules you out, and the remaining question is fit rather than eligibility. None of these are permanent, either — several are named as open work on the published-gaps page in the trust centre. They're disqualifiers for *today's* checked commit, not forever.

The checks above are the reader-facing v1 non-goals from [PRD §1.6](../PRD.md#16-out-of-scope-v1) as of the checked commit — read it yourself and check. The section lists one further entry, the Tucuxi cognitive-architecture integration, which this page leaves out because it is a proprietary component of another product rather than something a reader evaluating LQ.AI would come here wanting.

Start with [What it touches](what-it-touches.md) for prerequisites and where data lives, then the [quickstart](../quickstart.md) if you've decided to try it.
