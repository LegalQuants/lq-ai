# Bedrock compatible-API replacement for PR #265

Status: maintainer-directed implementation, 17 October 2026; live AWS
verification and application acceptance against AWS deferred beyond 0.9.1.

Origin and credit: Jason Lee / @dropthejase,
[PR #265](https://github.com/LegalQuants/lq-ai/pull/265). The original
contribution established the three-protocol approach and translation/test
examples. This replacement retains that credit while implementing against
current main. It does not close the original PR or claim its missing
sign-offs have been repaired.

## Maintainer direction

Keep Claude Messages, Chat Completions and Responses in the replacement.
The maintainer initially required live AWS verification, then explicitly
deferred it beyond PR #744 / 0.9.1 on 17 October 2026. Release acceptance
uses mocked gateway contracts, existing regression suites, CI and security
review; no live AWS compatibility is claimed.
The following implementation choices carry that direction into the gateway:

1. Each `type: bedrock` entry explicitly sets `bedrock_protocol` to
   `messages`, `chat_completions` or `responses`. Multiple entries may share
   an operator key. Model IDs do not select protocols or trigger URL retries.
2. `bedrock_endpoint` defaults to `runtime`; `mantle` requires explicit
   selection. The configured base path must match the selected protocol.
   Allowed origins are regional AWS Bedrock HTTPS origins, without embedded
   credentials, query strings, fragments or custom ports. Redirects are
   refused and the owned HTTP client ignores ambient proxy settings.
3. The compatible APIs use operator-supplied Bedrock API keys through the
   existing `ProviderKeyResolver`. Messages reuses the Anthropic adapter;
   Chat Completions reuses the OpenAI adapter. No AWS/LLM SDK is added.
4. Responses sends `store: false` and `background: false`. Remote conversation
   IDs and stateful options are refused. Full text/function-call/result
   history is reconstructed locally. Only governed function tools are
   forwarded; unexpected server-side output is refused.
5. ADR 0027's timeout classification remains unchanged. The generic-network
   timeout exception implicit in #265 is rejected: every protocol preserves
   `ProviderTimeoutError` and the existing audit classification. Upstream
   bodies and credentials are not included in public error envelopes.
6. Bedrock opts into strict validation on the reused streaming translators:
   malformed/error events and missing native terminal markers fail the
   request. A stream with no text or function calls cannot mark the adapter
   healthy. Existing provider configurations retain their parsing behavior.

These choices amend DE-035's initial transport plan. Its original
InvokeModel/SigV4/Event Stream implementation remains deferred. An existing
`bedrock` entry without `bedrock_protocol` continues to represent that
unimplemented slot; it is not silently converted to API-key transport.

## Operator configuration

Use separate entries when a catalogue spans protocols. These entries are
examples, not entitlement or contractual privacy claims:

```yaml
providers:
  - name: aws-claude
    type: bedrock
    bedrock_protocol: messages
    bedrock_endpoint: runtime
    base_url: https://bedrock-runtime.us-east-1.amazonaws.com/anthropic
    api_key_env: AWS_BEARER_TOKEN_BEDROCK
    tier: 3
    models: [us.anthropic.claude-haiku-4-5-20251001-v1:0]
  - name: aws-chat
    type: bedrock
    bedrock_protocol: chat_completions
    bedrock_endpoint: runtime
    base_url: https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1
    api_key_env: AWS_BEARER_TOKEN_BEDROCK
    tier: 3
    models: ['openai.gpt-oss-20b-1:0']
  - name: aws-responses
    type: bedrock
    bedrock_protocol: responses
    bedrock_endpoint: mantle
    base_url: https://bedrock-mantle.us-east-1.api.aws/openai/v1
    api_key_env: AWS_BEARER_TOKEN_BEDROCK
    tier: 3
    models: [google.gemma-4-31b]
```

`api_key_encrypted` may replace `api_key_env`; do not specify both. The
existing admin key APIs rotate/revoke keys and rebuild/remove the adapter.
An explicit key source is required; there is no implicit environment-key
fallback that could restore a revoked runtime key after restart.
The operator must verify the tier against the actual terms, retention,
invocation logging and residency requirements. The Haiku example uses a
geographic inference profile; selecting a region does not establish
in-region-only processing. No default profile is silently chosen by code.

Configured Bedrock models appear as direct provider/model entries when a
key resolves. This is the operator's catalogue, not live discovery or proof
of entitlement. Health reports the outcome observed by this adapter; until
successful inference, it reports access unverified. Polling health makes
no billable inference calls. Rebuilding after key rotation resets that
observed state. A successful request is not a privacy-tier certification.

## Verification and release status

[Bedrock verification](../bedrock-verification.md) separates 0.9.1 release
acceptance from deferred account access, live adapter evidence and full
application acceptance against AWS. The latter are follow-up work, not
merge gates for #744 under the maintainer decision. Mocked CI does not
establish actual AWS compatibility. Protocol support must not be described
as live verified until its matrix row passes at the exact implementation
SHA. The opt-in live test suite remains available for that follow-up.

Embeddings, SigV4/STS/cross-account credential refresh, remote sessions,
background jobs, built-in/server-side tools and live AWS model discovery
remain outside this implementation. The first version handles the gateway's
text/function-calling contract; it does not add multimodal input or a public
Responses endpoint. The gateway still exposes Chat Completions to callers.

## Sources and adopted constraints

- PRD §4 / DE-035: provider abstraction and Bedrock scope.
- ADR 0011: operator keys, routing disclosure and direct model selection.
- ADR 0014 / ADR 0015: one egress boundary and governed tools.
- ADR 0027: timeout and empty-response behavior.
- [AWS endpoint guidance](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html):
  runtime is recommended for new applications; Mantle remains supported for
  model/capability needs.
- [AWS Messages API](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html):
  compatible Messages surfaces and API-key request examples.
- [AWS Responses API](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html):
  explicit non-storage is required to avoid the default stored-state mode.

## Undo

Disable the Bedrock entries or revert the implementation. A code revert
cannot recall requests already transmitted, leaked keys or AWS charges.
No schema migration or dependency addition is introduced.
