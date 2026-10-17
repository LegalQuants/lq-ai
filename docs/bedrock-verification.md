# Bedrock release acceptance and deferred AWS verification

**Maintainer decision, 17 October 2026:** no live AWS check is required for
PR #744 or the 0.9.1 release. Account/model access, live adapter checks and
full application acceptance against AWS are deferred to follow-up work. No
successful live AWS check or application acceptance against AWS is claimed.
The deferred plan below defines the proposed follow-up issue's scope.

## Required for PR #744 / 0.9.1

- Real gateway HTTP routing with mocked AWS: unary and streaming
  function-call/result continuation for Messages, Chat Completions and
  Responses, with explicit runtime/Mantle base paths, preserved call IDs
  and arguments, routed provider/tier and usage. These tests supply a
  synthetic tool result; they do not execute a backend tool.
- Key masking, rotation, revocation and restart after revocation; strict
  protocol/origin configuration, sanitized failures, timeout classes and
  stateless Responses behavior.
- Full gateway regressions, lint, formatting and strict types; normal CI,
  stack smoke and maintainer security review at the final PR SHA. The
  existing API suite continues to test provider-independent tool governance.

These checks establish the implementation contracts without AWS calls.
They do not verify account entitlement, actual provider behavior, retention,
logging, residency or a live application round trip. The following deferred
checks are retained for a follow-up issue and are not release blockers.

## Deferred A — account/model access

When the follow-up is scheduled, arrange a dedicated test account/key, an
approved region and entitled models. Use synthetic prompts, never matter
data. Keep the key in the local test environment's
`AWS_BEARER_TOKEN_BEDROCK`; do not put it in a command argument, committed
file, PR, screenshot or test report. The gateway runtime encrypted-key path
is also available for application acceptance.

Use the AWS model-card/native examples to establish account access before
diagnosing adapter behavior. An entitlement denial is a blocked access
check, not a successful protocol test. If access is unavailable, record an
owner/action on the follow-up issue.

Suggested starting matrix, checked against AWS documentation on 17 October
2026; actual account access remains unverified:

| Protocol | Endpoint / region | Candidate model | Access | Adapter | Application |
| --- | --- | --- | --- | --- | --- |
| Messages | runtime / us-east-1 | us.anthropic.claude-haiku-4-5-20251001-v1:0 | deferred | deferred | deferred |
| Chat Completions | runtime / us-east-1 | openai.gpt-oss-20b-1:0 | deferred | deferred | deferred |
| Responses | mantle / us-east-1 | google.gemma-4-31b | deferred | deferred | deferred |

The Haiku profile can process in other US regions. Use an approved model
and routing profile if that does not meet the test environment's policy.
Gemma's model card specifies Mantle's `/openai/v1` path. No model-name
heuristic chooses that path in the adapter.

## Deferred B — real adapter requests

In the follow-up, verify the actual adapter against AWS at a recorded SHA.
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
not establish deferred C or prove that the backend governed the synthetic
local tool.

Also verify safe invalid/revoked credential and unavailable-model behavior.
Record controlled timeout/throttle fault injection separately from actual
AWS evidence; do not generate costly load to provoke a rate limit. Inspect
sanitized request evidence for `store=false` and `background=false` on
Responses; verify relevant account logging/retention configuration
separately. Never log authorization headers.

## Deferred C — application acceptance against AWS

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
Completion of this follow-up requires the live/application rows above.
For #744 / 0.9.1, the release checks at the top of this document apply; the
maintainer has explicitly deferred these live checks.

## Source checks

- [Claude Haiku 4.5 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html)
- [AWS Chat Completions guide](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html)
- [Gemma 4 31B model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-google-gemma-4-31b.html)
- [Design and scope](proposals/bedrock-compatible-provider.md)
