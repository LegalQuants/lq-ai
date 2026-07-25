# ADR 0025 — Slack identity resolution calls `users.info` from the api (audited egress exception)

- **Status:** Proposed
- **Date:** 2026-07-25
- **Related:** DE-288 (`/lq` slash command), ADR 0014 (single-egress gateway), ADR 0016 P1 (backend makes no direct third-party egress), `docs/intake-bridges.md`

## Context

DE-288's quick-ask flow must map a Slack slash-command invoker to an LQ.AI
account, fail-closed, before running anything on their behalf. The binding is
profile-email matching, which requires one Slack Web API call
(`users.info`) authenticated with the workspace's bot token.

The bot token's custody model (docs/intake-bridges.md) is: tokens land in the
api's encrypted storage at OAuth time and are "decrypted in-memory only when
needed". The bridges are deliberately dumb normalizers — signature
verification and payload shaping, no authority decisions, no token storage.

That leaves exactly two places the `users.info` call can live:

1. **The api** — the token custodian makes the call. Violates the letter of
   ADR 0016 P1 (the backend's only outbound HTTP client is the gateway
   client), enforced by `test_backend_makes_no_direct_third_party_egress`.
2. **The slack-bridge** — the Slack egress boundary makes the call, but it
   holds no tokens, so the api would need a bridge-bearer endpoint that hands
   back decrypted bot tokens per request.

## Decision

Option 1: the api makes the `users.info` call directly from
`app/api/integrations_quick_ask.py`, and that module is added to the
transparency test's `_EGRESS_ALLOWLIST` as a second audited egress boundary.

Rationale:

- **Token custody beats egress purity.** Option 2 turns a one-time,
  forward-only token flow (bridge → api at OAuth install) into a standing
  retrieval channel (api → bridge, on demand). A compromised bridge bearer
  token would then yield raw `xoxb-` tokens for every connected workspace —
  a strictly larger blast radius than the api holding one additional,
  narrowly-scoped outbound call.
- **The egress is narrow and non-influenceable.** One fixed URL constant
  (`https://slack.com/api/users.info`), GET, no user-controlled host or path,
  bearer = the workspace's own token, response parsed for a single field
  (profile email). Nothing about the LLM path, provider keys, or the gateway
  boundary changes.
- **Air-gap posture is unaffected in practice.** The code path only executes
  on a quick-ask from a connected Slack workspace; operators without Slack
  connected have no reachable path to this egress. Slack integration is
  inherently not an air-gap feature.

## Consequences

- `_EGRESS_ALLOWLIST` grows to `{clients/gateway.py, api/integrations_quick_ask.py}`;
  the test failure message continues to force this decision-recording step on
  any future addition.
- The PRD/architecture claim "the backend's only egress is the gateway" must
  be qualified: "…plus one audited Slack identity-resolution call (ADR 0025)".
- If a future intake-bridges phase gives the bridges their own token store
  (e.g. bridge-local encrypted storage), the call should move there and this
  exception be retired.

> **Status note:** AI-drafted as part of the DE-288 sweep PR, pending
> maintainer review alongside the code.
