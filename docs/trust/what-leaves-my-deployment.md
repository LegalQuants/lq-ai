# What leaves my deployment, and who sees it?

This is the single most important question you can ask before you let anyone put client material
into LQ.AI, and it deserves a page that answers it in one screen rather than a chain of links. No
single canonical document in this repository states the answer end to end; this page assembles it
from the Inference Gateway design, the Anonymization Layer, and the honest-state catalog, and names
where the picture is still incomplete rather than inventing a tracking issue for it.

## The interim answer

The Inference Gateway is the only component in the deployment that holds provider API keys and the
only component that makes outbound inference calls — the backend holds exactly one outbound HTTP
client, pointed at the gateway (`api/app/clients/gateway.py`, per
[`docs/HONEST-STATE.md`](../HONEST-STATE.md)). Where a request's content actually goes depends on the
Inference Tier the request routes at:

- **Tier 1 (local-only).** Inference runs on a local endpoint the operator runs — Ollama via
  `docker compose --profile local up` is the reference default, and [README.md](../../README.md)
  names vLLM, llama.cpp, or any OpenAI-compatible local endpoint as equally Tier 1. Nothing leaves
  the deployment.
- **Tiers 2–5 (customer-hosted, enterprise ZDR, standard cloud, consumer/free).** Chat and skill
  content is sent to the configured provider. Whether it is pseudonymized first depends on the
  anonymization posture below.

Before it leaves at Tiers 3–5, chat and skill content is pseudonymized by the gateway's Anonymization
Layer — if the operator has turned the feature on (`anonymization.enabled` defaults to **false** in
`gateway.yaml.example`) and the project is not marked privileged. Retrieved knowledge-base documents
are **not** pseudonymized at any tier, by design — the model needs intact source text to ground
citations — so a KB-attached chat sends the source document itself to whichever tier the request is
routed at, pseudonymization or not.

> [!CAUTION]
> **Silent failure** — a pseudonymization miss is silent. The recognizer set enabled by default has
> not been empirically measured for recall or precision against legal-document prose — Presidio's
> published accuracy figures target general English (news, social media). If a name slips through,
> the unredacted text reaches the provider, the response comes back rehydrated as if nothing
> happened, and there is no in-app signal that anything left unmasked. Operational telemetry cannot
> recover the leak after the fact. See [Anonymization](../security/anonymization.md) for the full
> validated-vs-unvalidated breakdown. A community PR (#439 / DE-240) has since produced a first
> measured pass on a synthetic corpus and found that organization names leak through the default
> recognizer configuration; as of the commit this page was checked against that PR is open, not
> merged, and its findings are not yet reflected in the shipped default.

Privileged projects skip the Anonymization Layer entirely — rewriting privileged work product risks
corrupting it — and are expected to pair with a tier floor of 1 (local-only), which the gateway
enforces server-side: a request that tries to route a privileged project below its floor is refused
with `tier_below_minimum`, not silently downgraded.

## The decision

Given the unmeasured false-negative rate named above, **route privileged matters to Tier 1.** That is
the only path today where the "what leaves my deployment" question has a structural answer rather
than a configured one — local inference means the destination question does not arise. For
non-privileged work at Tiers 3–5, treat the Anonymization Layer as a mitigation with an unmeasured
false-negative rate, not a guarantee, and weigh that against the sensitivity of what you are sending.

> [!NOTE]
> **Professional duty** — this is a confidentiality and competence judgment, made per matter rather
> than once per deployment. Deciding that an unmeasured false-negative rate is acceptable for a given
> client's material is a decision only you can make, and the mitigation is named plainly: where
> validated recognition is required, route that matter to Tier 1 so the question of what a provider
> sees does not arise. Where the matter is privileged, the layer is skipped entirely by design — see
> above — so Tier 1 is the control, not pseudonymization.

## Next

- [Anonymization](../security/anonymization.md) — the full recognizer set, what is validated, what is not.
- [Threat model](../security/threat-model.md) — the STRIDE coverage for every production service.
- [Verify these claims yourself](verify-these-claims.md) — how to check the tier-floor enforcement in source.
