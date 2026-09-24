# What information is sent outside LQ.AI?

The answer depends on which services you enable and where they run. Keeping uploaded files on
your own computer does not keep every use of their contents there.

## When you ask a cloud AI service

The request can include your question, document passages, skill instructions, supporting files
and search results. The uploaded file itself may stay in local storage while text extracted from
it is sent to the provider.

Where a request's content actually goes depends on the Inference Tier it routes at. The Inference
Gateway is the only component in the deployment that holds provider API keys and the only
component that makes outbound inference calls — the backend holds exactly one outbound HTTP
client, pointed at the gateway (`api/app/clients/gateway.py`, per
[`docs/HONEST-STATE.md`](../HONEST-STATE.md)).

- **Tier 1 (local-only).** Inference runs on a local endpoint the operator runs — Ollama via
  `docker compose --profile local up` is the reference default, and [README.md](../../README.md)
  names vLLM, llama.cpp, or any OpenAI-compatible local endpoint as equally Tier 1. Nothing leaves
  the deployment for chat (document search is a separate question — see "Other connections to
  check" below).
- **Tiers 2–5 (customer-hosted, enterprise ZDR, standard cloud, consumer/free).** Chat and skill
  content is sent to the configured provider. Whether it is pseudonymized first depends on the
  anonymization posture below.

Before it leaves at Tiers 3–5, chat and skill content is pseudonymized by the gateway's
Anonymization Layer — if the operator has turned the feature on (`anonymization.enabled` defaults
to **false** in `gateway.yaml.example`) and the project is not marked privileged. Retrieved
knowledge-base documents are **not** pseudonymized at any tier, by design — the model needs intact
source text to ground citations — so a KB-attached chat sends the source document itself to
whichever tier the request is routed at, pseudonymization or not.

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

## Other connections to check

A single request already bundles several data categories — chat history, the attached skill, its
reference files, organization background and retrieved document passages — before any of the
connections below even fire. Document-search models, research tools, email and monitoring can also
send information out, on their own schedule and independently of which chat model you pick.
Installation and document processing may download software or model files. Review each enabled
service and its address — picking a local chat model does not by itself settle any of these.

- **Document search (embeddings).** Turning a document chunk into a vector for search sends that
  chunk's text to whichever provider backs the gateway's `embedding` alias —
  `openai-prod/text-embedding-3-small` by default in
  [`gateway.yaml.example`](../../gateway.yaml.example) — independently of the chat model's tier.
  A Tier 1 chat model does not, by itself, keep document search local; repointing the alias needs
  a local, embedding-capable adapter that doesn't exist yet — Ollama's adapter explicitly raises
  `ProviderUnsupportedError` for embeddings today (`gateway/app/providers/ollama.py:260-284`; ADR 0008).
- **Research tools.** Skill and chat tool calls to CourtListener, GovInfo, EDGAR, EUR-Lex, or an
  MCP server go through the gateway's tool-provider proxy (`gateway/app/api/tools.py`), never
  directly from the backend (ADR 0014). CourtListener/GovInfo/EDGAR/EUR-Lex are off until the
  operator uncomments and configures the matching block in `gateway.yaml` — or enables it at
  runtime via Admin → Research sources / `POST /api/v1/admin/tool-providers`
  (`gateway/app/tool_provider_defaults.py`), no YAML edit or restart needed — with its own
  `egress_tier` and an exact outbound-host allowlist either way. MCP servers are configured
  separately, in a `mcp_servers:` block in `mcp.yaml` (`MCP_CONFIG_PATH`, default `./mcp.yaml`;
  `gateway/app/config.py:227-229`, template `mcp.yaml.example`), not in `gateway.yaml`.
- **Email.** The autonomous layer sends a best-effort SMTP copy of an in-app notification only
  when `smtp_host` is configured (`api/app/config.py`); it is unset by default, so a fresh install
  sends no email.
- **Monitoring.** OpenTelemetry traces go to the operator's own configured endpoint only if
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set — unset by default, so no traces leave
  (`api/app/observability.py`, `gateway/app/observability.py`). Prometheus's `/metrics` is scraped
  by the operator's own monitoring, not pushed out by LQ.AI. The audit log itself has no
  first-class streaming or export path as of this commit — the PRD names SIEM streaming via
  syslog or webhook as a future capability, but the shipped path is an operator-run
  `pg_dump --table=audit_log` against their own Postgres (`docs/security/audit-logging.md`).
- **Downloads.** The first document you upload triggers Docling to download roughly 700 MB of
  layout and OCR models from Hugging Face, unless they're already cached in the `ingest-hf-cache`
  / `ingest-easyocr-cache` volumes — see [Use AI without an internet connection](../operate/air-gapped.md)
  for how to avoid or pre-seed that download, and for the Ollama model pull, which is a separate,
  operator-run step.

## Where API keys are handled

When you save a provider key through the app (**Admin → Provider keys**), it passes through the
API to the gateway (`api/app/api/admin.py`), which Fernet-encrypts it, persists it into
`gateway.yaml`, and hot-applies the rebuilt adapter with no gateway restart
(`gateway/app/provider_keys.py`, `apply_provider_key`). The gateway still has to send
the key to the provider itself when it makes a request on your behalf. A key saved this way is
encrypted at rest, but other copies — a `.env` file next to your compose file, a secrets manager, a
container's environment, or a backup of the `gateway-config` volume — aren't touched by saving
through the app and need their own handling. See
[Replace a leaked API key](../operate/rotate-a-leaked-key.md#finding-other-copies) and
[Encrypted keys](../security/encrypted-keys.md) for what those copies are and how to rotate all of them.

## What the five tier labels mean

The project labels routes from Tier 1 through Tier 5: local-only inference; customer-hosted cloud
inference; enterprise managed inference with ZDR / no-training commitments; a standard cloud API
under default commercial terms; and consumer or free-tier access. Lower numbers mean a stronger
intended privacy posture. These are routing classifications the operator declares per provider in
`gateway.yaml` — the gateway enforces the classification, it does not verify a provider's actual
contract, account plan, or hosting region. Confirm the endpoint, hosting arrangement and terms
behind the label yourself with your provider — the codebase only shows you what tier was declared,
not what the account terms actually are.

## Privileged matters and fallbacks

The app can restrict routing for a matter or skill and reject routes that do not meet that
requirement: privileged projects skip the Anonymization Layer entirely — rewriting privileged work
product risks corrupting it — and are expected to pair with a tier floor of 1 (local-only). The
gateway enforces that floor server-side: a request that tries to route a privileged project below
its floor is refused with `tier_below_minimum`, not silently downgraded. That refusal check runs
against the *primary* candidate model only — if the primary fails and the request falls through to
a configured fallback, the fallback's own tier is not independently re-checked against the floor
(`gateway/app/api/inference.py`), so check your fallback model choices as well as the preferred one.
Privileged requests skip the identifying-detail replacement path, so do not assume the privilege
label alone means text has been scrubbed before sending.

Given the unmeasured false-negative rate named above, **route privileged matters to Tier 1.** That
is the only path today where the "what leaves my deployment" question has a structural answer
rather than a configured one — local inference means the destination question does not arise. For
non-privileged work at Tiers 3–5, treat the Anonymization Layer as a mitigation with an unmeasured
false-negative rate, not a guarantee, and weigh that against the sensitivity of what you are
sending.

> [!NOTE]
> **Professional duty** — this is a confidentiality and competence judgment, made per matter rather
> than once per deployment. Deciding that an unmeasured false-negative rate is acceptable for a
> given client's material is a decision only you can make, and the mitigation is named plainly:
> where validated recognition is required, route that matter to Tier 1 so the question of what a
> provider sees does not arise. Where the matter is privileged, the layer is skipped entirely by
> design — see above — so Tier 1 is the control, not pseudonymization.

## Next

- [Anonymization](../security/anonymization.md) — the full recognizer set, what is validated, what is not.
- [Threat model](../security/threat-model.md) — the STRIDE coverage for every production service.
- [Verify these claims yourself](verify-these-claims.md) — how to check the tier-floor enforcement in source.
