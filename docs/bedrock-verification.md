# Required AWS Bedrock verification

**Status: pending.** No successful live AWS check or application acceptance
is claimed for this replacement. Mocked tests and skipped provider tests do
not pass these gates. Record the exact implementation commit for every run.

## Gate A — account/model access, early

Before committing to the full implementation effort, arrange a dedicated
test account/key, an approved region and entitled models. Use synthetic
prompts, never matter data. Keep the key in the local test environment's
`AWS_BEARER_TOKEN_BEDROCK`; do not put it in a command argument, committed
file, PR, screenshot or test report. The gateway runtime encrypted-key path
is also available for application acceptance.

Use the AWS model-card/native examples to establish account access before
diagnosing adapter behavior. An entitlement denial is a blocked access
check, not a successful protocol test. If access is unavailable, record an
owner/action and revise the delivery estimate immediately.

Suggested starting matrix, checked against AWS documentation on 17 October
2026; actual account access remains unverified:

| Protocol | Endpoint / region | Candidate model | Access | Adapter | Application |
| --- | --- | --- | --- | --- | --- |
| Messages | runtime / us-east-1 | us.anthropic.claude-haiku-4-5-20251001-v1:0 | pending | pending | pending |
| Chat Completions | runtime / us-east-1 | openai.gpt-oss-20b-1:0 | pending | pending | pending |
| Responses | mantle / us-east-1 | google.gemma-4-31b | pending | pending | pending |

The Haiku profile can process in other US regions. Use an approved model
and routing profile if that does not meet the test environment's policy.
Gemma's model card specifies Mantle's `/openai/v1` path. No model-name
heuristic chooses that path in the adapter.

## Gate B — real adapter requests during implementation

As each protocol is implemented, verify the actual adapter against AWS.
The opt-in provider test exercises unary and streaming completion, a
function proposal and a continuation with a synthetic local tool result.
It sends at most **18 requests**, each with a maximum output budget of
1,024 tokens. Review the account budget/access before enabling it.

From `gateway/`, with the dedicated key already supplied securely:

```sh
LQ_AI_BEDROCK_VERIFY=1 LQ_AI_BEDROCK_TEST_REGION=us-east-1 \
  uv run --frozen --extra dev pytest tests/test_bedrock_provider.py \
  -m provider -v --junitxml=/tmp/bedrock-verification.xml
```

Do not use the explicit opt-in in ordinary CI. Without it, the six cases
skip; with it, absent credentials **fail** the gate. Access errors fail
rather than being relabeled as skips. Restrict the command to one protocol
while that increment is being implemented, then run the complete matrix.

Per-protocol overrides use this prefix:

| Protocol | Prefix |
| --- | --- |
| Messages | LQ_AI_BEDROCK_MESSAGES |
| Chat Completions | LQ_AI_BEDROCK_CHAT_COMPLETIONS |
| Responses | LQ_AI_BEDROCK_RESPONSES |

Append `_MODEL`, `_ENDPOINT` (`runtime` or `mantle`) or `_BASE_URL` as
needed. Exact protocol base paths are validated. Region uses
`LQ_AI_BEDROCK_TEST_REGION`. Test every endpoint/protocol combination that
will be advertised, including additional Mantle/runtime combinations if
claimed. A pass on the candidate matrix alone does not certify untested
models, regions, paths or endpoint combinations.

The XML records protocol, model, region, endpoint, streaming mode, token
usage and AWS request IDs when supplied. Keep a companion record with
implementation SHA, timestamp, runner and secret-free configuration. Retain
only redacted/synthetic evidence. A pass on the direct adapter test does
not pass Gate C or prove that the backend governed the synthetic local tool.

Also verify safe invalid/revoked credential and unavailable-model behavior.
Record controlled timeout/throttle fault injection separately from actual
AWS evidence; do not generate costly load to provoke a rate limit. Inspect
sanitized request evidence for `store=false` and `background=false` on
Responses; verify relevant account logging/retention configuration
separately. Never log authorization headers.

## Gate C — normal application acceptance before merge

Run the replacement at the exact reviewed SHA through application → API →
gateway → AWS. For **each protocol**:

1. Select the named provider/model and see the actual provider/model/tier.
2. Complete a normal unary turn and a streamed turn with visible output.
3. Complete a governed tool-call/result round trip with intact call IDs and
   arguments, followed by a multi-turn continuation.
4. Check usage/cost or explicit unknown-cost disclosure, actionable errors,
   masked key administration, rotation and revocation.
5. Check the affected flow at desktop/phone widths in light/dark schemes.

Confirm expectations before running. Record each as matches, differs or
not-reached with evidence and SHA. A blocked/skipped/error-only row remains
unverified. Re-run affected checks after implementation/config changes.
The feature is not merge-ready until the required live/application rows
are complete and normal CI/security review is green.

## Source checks

- [Claude Haiku 4.5 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html)
- [AWS Chat Completions guide](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html)
- [Gemma 4 31B model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-google-gemma-4-31b.html)
- [Design and scope](proposals/bedrock-compatible-provider.md)
