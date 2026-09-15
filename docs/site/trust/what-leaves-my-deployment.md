---
title: What leaves my deployment, and who sees it?
description: The honest interim answer to LQ.AI's highest-severity question, and the decision it ends in while the definitive version waits on an open issue.
audience: [evaluator, operator]
status: draft
sources:
  - README.md
  - docs/security/anonymization.md
  - docs/HONEST-STATE.md
sidebar:
  order: 2
---

This is the single most important question you can ask before you let anyone put client material
into LQ.AI, and it deserves a page that answers it in one screen rather than a chain of links. This
page is a stub: the definitive, measured version — an exact map of what a chat or skill turn sends
to which destination, per inference tier, verified rather than described — waits on
[issue #439](https://github.com/LegalQuants/lq-ai/issues/439). What follows is the honest answer
available today from the repository, and the decision it points to until #439 closes.

## The interim answer

The Inference Gateway is the only component in the deployment that holds provider API keys and
the only component that makes outbound inference calls — the backend holds exactly one outbound
HTTP client, pointed at the gateway (`api/app/clients/gateway.py`, per `docs/HONEST-STATE.md`).
Where a request's content actually goes depends on the Inference Tier the request routes at:

- **Tier 1 (local-only).** Inference runs on a local endpoint the operator runs — Ollama via
  `docker compose --profile local up` is the reference default, and README.md names vLLM,
  llama.cpp, or any OpenAI-compatible local endpoint as equally Tier 1. Nothing leaves the
  deployment.
- **Tiers 2–5 (customer-hosted, enterprise ZDR, standard cloud, consumer/free).** Chat and skill
  content is sent to the configured provider. Whether it is pseudonymized first depends on the
  anonymization posture below.

Before it leaves at Tiers 3–5, chat and skill content is pseudonymized by the gateway's
Anonymization Layer — if the operator has turned the feature on (`anonymization.enabled` defaults
to **false** in `gateway.yaml`) and the project is not marked privileged. Retrieved
knowledge-base documents are **not** pseudonymized at any tier, by design — the model needs intact
source text to ground citations — so a KB-attached chat sends the source document itself to
whichever tier the request is routed at, pseudonymization or not.

:::caution[Silent failure]
A pseudonymization miss is silent. The recognizer set enabled by default has not been empirically
measured for recall or precision against legal-document prose — Presidio's published accuracy
figures target general English (news, social media). If a name slips through, the unredacted text
reaches the provider, the response comes back rehydrated as if nothing happened, and there is no
in-app signal that anything left unmasked. Operational telemetry cannot recover the leak
after the fact. See [Anonymization](anonymization.md) for the full validated-vs-unvalidated
breakdown.
:::

Privileged projects skip the Anonymization Layer entirely — rewriting privileged work product
risks corrupting it — and are expected to pair with a tier floor of 1 (local-only), which the
gateway enforces server-side: a request that tries to route a privileged project below its floor
is refused with `tier_below_minimum`, not silently downgraded.

## The decision

Until #439 publishes the measured picture, **route privileged matters to Tier 1.** That is the
only path today where the "what leaves my deployment" question has a structural answer rather than
a configured one — local inference means the destination question does not arise. For
non-privileged work at Tiers 3–5, treat the Anonymization Layer as a mitigation with an unmeasured
false-negative rate, not a guarantee, and weigh that against the sensitivity of what you are
sending.

:::note[Professional duty]
This is a confidentiality and competence judgment, made per matter rather than once per
deployment. Deciding that an unmeasured false-negative rate is acceptable for a given client's
material is a decision only you can make, and the source states the mitigation plainly: where
validated recognition is required, route that matter to Tier 1 so the question of what a provider
sees does not arise. Where the matter is privileged, the layer is skipped entirely by design — see
above — so Tier 1 is the control, not pseudonymization.
:::

## Next

- [Anonymization](anonymization.md) — the full recognizer set, what is validated, what is not.
- [Threat model](threat-model.md) — the STRIDE coverage for every production service.
- [Verify these claims yourself](verify-these-claims.md) — how to check the tier-floor enforcement in source.
