---
title: Is LQ.AI for you?
description: Checkable disqualifiers, and honest answers to the two questions that come up most — litigation, and why not buy something instead.
audience: [operator, evaluator]
status: draft
sources:
  - docs/comparison.md
  - docs/PRD.md
  - docs/HONEST-STATE.md
  - docs/adr/0001-openwebui-fork-pin.md
  - README.md
  - api/app/api/auth.py
  - web/backend/open_webui/config.py
sidebar:
  order: 2
---

This page is a set of checks, not a description. Read the list below against your own situation; if any of it is true for you today, LQ.AI's v1 is probably not the right tool yet, and the reason is named so you can judge it yourself rather than finding out after an install.

## Who it's built for — and who it doesn't rule out

The primary user is "in-house counsel at organizations of any size, from solo General Counsel to enterprise legal departments" ([PRD §1.4](../../PRD.md#14-target-users)). A legal function of one is inside that sentence, not an edge case of it.

In-house is the focus, not a gate on who you are. Nothing in [PRD §1.6](../../PRD.md#16-out-of-scope-v1) disqualifies a reader by where they practise — every v1 exclusion below is a *use case*, not a practitioner type, and the repository's own forward-looking notes describe the positioning as "open-source AI for legal teams — covering in-house, firm, and solo practitioners" ([PRD §9, DE-023](../../PRD.md#de-023--external-counsel-collaboration-boundary)). So if you are at a firm, in disputes, at a legal-aid organization, or in a clinic, the software installs and runs for you the same way.

What is calibrated to in-house work is the substance: PRD §1.6 defines the focus as "contracts, policies, regulatory matters, advice", and the ten starter skills sit inside that. That makes it a fit judgement you make from the [skill catalogue](../skills/catalogue.intro.md) — does this work look like your work? — rather than a boundary the project draws around you. Two things the repository does *not* document as of the checked commit: any multi-firm or external-counsel collaboration feature (DE-023 is an open question at P3, with "no v1 implementation expected"), and any per-seat model for granting an outside lawyer scoped access beyond the same DE.

## You're probably not a fit today if…

- **Nobody on your side can run Docker, and there's no server or VM available.** LQ.AI is self-hosted — Docker Desktop 4.x+ or Docker Engine 24+ is the only host requirement (no Python, no Node), but something has to run it ([README](../../../README.md#quick-start)).
- **You want a vendor to hold your infrastructure and provider keys for you, with nothing to operate.** v1 is self-hosted only — "No legalquants.com-hosted instance" (PRD §1.6). A paid managed-service option from LegalQuants is named once in the PRD (Appendix E, "Is this under support?") but not specified beyond that sentence in this repository as of the checked commit — ask LegalQuants directly if that's what you need.
- **You need litigation-specific tooling: e-discovery, docket management, filing.** See [Can it do litigation?](#can-it-do-litigation) below — the short answer is no.
- **You need enterprise SSO (SAML) or LDAP/AD sign-in today.** PRD §5.1 describes SAML 2.0, LDAP/AD, SCIM 2.0, and trusted-header SSO as "first-class IdP integrations" the backend implements — but `api/app/api/auth.py` (the module that implements login, MFA, and password change) has no SAML, LDAP, or trusted-header code path as of the checked commit, and `docs/HONEST-STATE.md` does not carry a row for authentication providers. What is shipped and verifiable: local email/password accounts and TOTP-based MFA (`api/app/api/auth.py`). Treat the broader IdP claim as **not documented in the repository as of the checked commit** until you can point at the code yourself. One qualification: the `web/` fork inherits upstream OpenWebUI's own LDAP sign-in configuration (`ENABLE_LDAP` and the `LDAP_*` settings in `web/backend/open_webui/config.py`). It is upstream code, is not wired to LQ.AI's own auth surface, and is not documented as supported anywhere in this repository as of the checked commit — do not plan on it without reading that path yourself.
- **Nobody in-house or on your IT side can act as the operator** — the person who deploys it, holds the keys, and reads the audit log. LQ.AI's operator role assumes someone technical is doing this, whether that's legal ops or IT/SRE acting on legal's behalf (PRD §1.4).
- **You need a request portal, SLAs, approvals, escalations, or matter-management dashboards.** PRD §1.6 puts full intake/triage/matter-management workflow out of scope for v1 — the analytical layer is LQ.AI's side of the line, and "Streamline AI and Checkbox occupy the operational-workflow layer… Light intake bridges (§3.x Slack/Teams Bridge in M3) are in scope; full operational workflow is not."
- **You need direct integrations with CLM systems, or billing/time tracking.** PRD §1.6 lists "Direct integrations with CLM systems (Ironclad, Concord, etc.)" and "Billing / time tracking" as separate v1 non-goals.
- **Your lawyers need a native phone app.** PRD §1.6: "Mobile applications. Web UI is responsive, but no native iOS/Android apps." There is nothing to install from an app store; a phone browser pointed at your deployment is the whole mobile story as of the checked commit.

That is the complete set of reader-facing v1 non-goals in [PRD §1.6](../../PRD.md#16-out-of-scope-v1) as of the checked commit — read it yourself and check. The list has one further entry, the Tucuxi cognitive-architecture integration, which is a proprietary component of another product rather than something a reader would come here wanting. **If none of these is true for you, nothing in the project's stated scope rules you out**, and the remaining question is fit rather than eligibility — start with [what it touches](what-it-touches.md).

None of these are permanent — several are named as open work on the [published gaps](../trust/published-gaps.md) page. They're disqualifiers for *today's* checked commit, not forever.

## Can it do litigation?

No — not as a litigation-workflow product. PRD §1.6 lists this as an explicit non-goal, in these words:

> "E-discovery or litigation-specific workflows. Focus is in-house counsel work: contracts, policies, regulatory matters, advice. Litigation tools are a separate product category."

What *does* ship, and can be mistaken for litigation support, is legal **research**: case-law lookup via CourtListener, routed through the Inference Gateway and tier-gated like every other external call. The PRD marks it explicitly partial — "PR6 status: PARTIAL — case-law retrieval shipped; full research surface still deferred" (PRD §3.6) — and `docs/HONEST-STATE.md` §5.5 is specific about the boundary: case-law retrieval and "Sources consulted" provenance ship; result-content accuracy judging does not, and that provenance is a deliberately different data structure from the Citation Engine's character-verified quotes. Research retrieval is not e-discovery, docket management, or filing support.

:::note[Professional duty]
If your practice needs litigation-specific tooling, LQ.AI's v1 scope does not cover it (PRD §1.6) — that tooling is a separate product category, and routing litigation work through a research feature that was not built for it is a competence question (Model Rule 1.1 territory in ABA-model jurisdictions), not a product limitation you can work around.
:::

The community has debated this boundary in public: a practising litigator's scope proposal ([issue #287](https://github.com/LegalQuants/lq-ai/issues/287)) reached the community's [decision log](https://github.com/LegalQuants/lq-ai-community/blob/main/decisions/README.md), which narrows the conversation to "research and drafting" without amending the PRD text quoted above. This page follows the PRD (§1.6, §3.6) and `docs/HONEST-STATE.md` §5.5, checked against the commit stamped in this page's footer; if the decision log reads differently to you, the PRD is this project's top-priority canonical source (see `CLAUDE.md`'s decision routing), and the gap between the two is worth raising as an issue rather than resolving by guesswork.

## Why not buy a commercial product — or use the open-source alternative?

Three different comparisons, each honest about where it loses.

**Against the commercial category** (GC.AI, Spellbook, Legora, and the others named in PRD §1.2): those products can be faster to get running because someone else operates the infrastructure — if "someone hosts this for me, with nothing to run" matters more than seeing how it works, that is a genuine point in their favor, and PRD Appendix E's "Is this under support?" answer is that LegalQuants offers a paid managed-service layer on the same open-source software rather than a differently-visible product. Where LQ.AI departs structurally: the skills, the citation-verification logic, and every artifact shaping an answer ship as source you can read, fork, and audit (PRD §1.3) — a closed competitor's equivalent claim is not independently checkable by you.

**Against generalist tools** (ChatGPT, Claude, Copilot): LQ.AI is purpose-built for legal workflows — a curated skill library, citations verified against the source document, and a confidentiality posture generalist consumer tools don't carry, addressing the kind of privilege exposure courts have already flagged (PRD §1.2 cites *U.S. v. Heppner*). If your need is a single low-stakes question with no confidentiality concern and no citation requirement, a generalist tool is the simpler choice for that one case; LQ.AI's case is the recurring, citation-grounded, matter-scoped work.

**Against the visible open-source alternative:** LQ.AI is a fork of [OpenWebUI](https://github.com/open-webui/open-webui), pinned and tracked per [ADR 0001](../../adr/0001-openwebui-fork-pin.md). If you only need a self-hosted chat UI with no legal-specific layer, plain OpenWebUI is the leaner choice. What LQ.AI adds around that fork lives outside `web/` entirely — the Citation Engine, the Anonymization Layer, tier derivation and floor enforcement, the skill/playbook/Organization-Profile model, and the privilege-aware audit log are in `api/` and `gateway/` (README.md, "Architecture"). The fork's own changes are auditable: ADR 0001 notes anyone can diff `web/` against the pinned upstream tag and see exactly what changed.

`docs/comparison.md` is the project's own evidence-linked comparison, but as of the checked commit it argues a narrower case than the one above — it measures LQ.AI against a proprietary "fiduciary-grade" category on verifiability, and does not name a case where a commercial product is the better choice, or compare against OpenWebUI directly. The three comparisons above are built from the PRD and ADR 0001 instead; read `docs/comparison.md` itself for the verifiability argument in full.

## Next

- [What it touches](what-it-touches.md) — prerequisites and where data lives, before you install
- [Quickstart](quickstart.md) — if you've decided to try it
- [The trust centre](../trust/index.md) — for a security or procurement review
