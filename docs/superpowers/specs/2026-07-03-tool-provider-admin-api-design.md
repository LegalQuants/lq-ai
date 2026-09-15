# Design — Runtime tool/authority-provider admin API + "Research sources" card

**Date:** 2026-07-03
**Owner:** Claude Code (driven), maintainer + **security** review
**Origin:** Donna upstream request `Donna/docs/upstream-requests/lq-ai-runtime-tool-provider-admin-api.md` (also closes a real gap in LQ.AI's own web UI)
**Branch:** `feat/tool-provider-admin-api`
**Status:** Approved design — ready for implementation plan
**⚠️ Security-gated:** gateway config write + secrets + admin authz → auto-routed to security reviewers per `.github/CODEOWNERS` (`gateway/**` + auth/secret paths).
**Target release:** post-v0.6.0 → cut **v0.6.1** after merge.

---

## 1. Problem

The fiduciary-grade authority sources (CourtListener, GovInfo, SEC EDGAR, EUR-Lex) can only be enabled today by hand-editing `gateway.yaml` (uncomment the `tool_providers:` block) + setting a token in `.env` + restarting the gateway. There is **no in-app / runtime path**. This blocks:
- **LQ.AI's own web UI** — a lawyer cannot turn on case-law research from the app (the headline v0.6.0 milestone is only reachable via YAML editing). The inference BYOK **Provider keys** card exists (Anthropic/OpenAI), but there is no equivalent for tool/authority providers.
- **Donna's BFF** — cannot build a "Research sources" admin card without an API.

**Gap verified (current `main`):** `gateway/app/config_writer.py` `upsert_provider_key` / `_find_provider_entry` read `raw.get("providers")` (inference `providers:` only, never `tool_providers`); the api's `/admin/provider-keys` endpoints are thin proxies to `GatewayClient.{list,set,rotate,delete}_provider_key`; there is **no** tool-provider route anywhere in `api/app/api/admin.py`; the gateway has the `tool_providers` config model (`gateway/app/config.py:180 ToolProviderConfig`, `:582` the list) + `list_tool_providers` (consumed by `api/app/research/registry.py resolve_available_sources`) but **no writer**; `gateway.yaml.example` ships the entire `tool_providers:` block commented out (so a default install reports all four sources `enabled=false`, including the keyless EDGAR/EUR-Lex).

## 2. Thesis / approach

**Mirror the inference BYOK provider-keys path, one layer down into `tool_providers`.** Reuse the exact substrate — gateway master key, ADR 0011 Fernet encryption, hot-apply/reload, the thin-api-proxy-to-gateway pattern — but operate on the gateway's `tool_providers:` block instead of `providers:`. New dedicated `/admin/tool-providers` route (decided: not a `kind` discriminator on the inference endpoint — tool_providers semantics genuinely differ). Plus the in-app **"Research sources"** card in `web/` (decided: fix our own UI gap, not API-only).

## 3. Goals / non-goals

**Goals**
- Gateway `config_writer` functions to enable/disable a `tool_providers` entry and set/rotate/clear its key, encrypted at rest, hot-applied (no restart).
- Gateway admin HTTP endpoints for tool-providers (parallel to the provider-key gateway endpoints), that the api proxies.
- API `AdminUser`-gated `/api/v1/admin/tool-providers[/{type}]` endpoints (GET/POST/PATCH/DELETE), secrets **write-only, never returned**.
- A `web/` Settings **"Research sources"** card mirroring the Provider keys card.
- **Allow enabling a registered type not yet present** in `tool_providers` — the key difference from the inference path (safe: `SOURCE_REGISTRY` owns the adapter + base-url/allowlist defaults).

**Non-goals (YAGNI)**
- No MCP-connector admin (that has its own `/admin/mcp` surface + per-user OAuth). Scope is the four `SOURCE_REGISTRY` authority/research sources.
- No changes to how the loop *uses* the sources (registry/adapters unchanged) — only the config write path.
- No new secret-storage mechanism — reuse ADR 0011 encryption exactly as provider-keys does.
- Keyless sources (EDGAR/EUR-Lex) do not gain a key input beyond enable/disable.

## 4. Current-state anchors (read these first when building)

- **Inference path to mirror (api, thin proxy):** `api/app/api/admin.py` — `list_provider_keys`→`gateway.list_provider_keys()`, `set_provider_key`→`gateway.set_provider_key(body)`, `rotate_provider_key`→`gateway.rotate_provider_key(provider, body)`, `revoke_provider_key`→`gateway.delete_provider_key(provider)` (DELETE-204 uses the `response_class=Response` recipe). `GatewayClient` (`api/app/clients/gateway.py`, `get_gateway_client` dep) adds the gateway-key header.
- **Gateway writer to parallel:** `gateway/app/config_writer.py` — `upsert_provider_key` (`:450`), `_find_provider_entry` (`:418`, reads `raw.get("providers")`). Mirror onto `tool_providers`.
- **Gateway provider-key admin HTTP endpoints:** find them in the gateway app (the api's `GatewayClient.set_provider_key` etc. call gateway routes) — add tool-provider siblings alongside.
- **Config model:** `gateway/app/config.py:180` `ToolProviderConfig` (fields to write: name, type, base_url/allowlist, `api_key_env` vs `api_key_encrypted`, egress tier — read the model), `:582` `tool_providers: list[ToolProviderConfig]`, `:604` the duplicate-name validator.
- **Registry (defaults + which types/keys):** `api/app/research/registry.py` `SOURCE_REGISTRY` — the four `SourceSpec`s (type, ops, adapter); the api's GET builds status by joining this against `gateway.list_tool_providers()` (`resolve_available_sources`). Note the api owns `SOURCE_REGISTRY`; the gateway owns the config — decide where the "registered type + key_required + defaults" truth lives (see §7 open items).
- **Web card to mirror:** the existing Provider keys card in `web/` (added in PR #202; grep `ProviderKeysCard` / provider-keys). Mirror its structure (masked write-only input, hot-apply, list + badges).
- **Hot-apply mechanism:** whatever `upsert_provider_key` triggers to reload the live gateway config without restart — reuse it.
- **`gateway.yaml.example`:** the commented `tool_providers:` block + `courtlistener-prod` template (`api_key_env: COURTLISTENER_API_TOKEN`) — the shape the writer must produce.

## 5. API contract (the deliverable for Donna)

All `AdminUser`-gated; secrets write-only, never returned (P3 / ADR 0016); admin state-changes write an `audit_log` row (match the provider-keys convention).

- **`GET /api/v1/admin/tool-providers`** → `200` `[{type, enabled, name?, has_key, key_required, egress_tier?}]` for each `SOURCE_REGISTRY` type (status only, no secret).
- **`POST /api/v1/admin/tool-providers`** body `{type, api_key?}` → enable a registered type: create/enable the `tool_providers` entry with the registry's defaults; store `api_key_encrypted` if `api_key` given (ADR 0011); keyless types enable with no key. `201`/`200`. **Adding a not-yet-present registered type is allowed.**
- **`PATCH /api/v1/admin/tool-providers/{type}`** body `{api_key?, enabled?}` → set/rotate key and/or toggle enabled. `200`.
- **`DELETE /api/v1/admin/tool-providers/{type}`** → disable/remove the entry (revoke key). `204` (DELETE-204 `response_class=Response` recipe).
- **Status codes (match the inference path):** `400` no gateway master key configured; `404` type not in `SOURCE_REGISTRY` (the loop only calls sources it has an adapter for); `409` an **env-provided** key (`api_key_env`) is not runtime-revocable/rotatable (surface honestly, like the inference path's env-key conflict).
- **Hot-apply:** on any write, the gateway reloads live config; no restart. Proof: after `POST` with a CourtListener token, `GET /api/v1/research/sources` shows that source `enabled=true` with no restart.

## 6. Web "Research sources" card

`web/` Settings card mirroring the Provider keys card: lists each authority source with an **Available/Unavailable** badge (from `GET /admin/tool-providers`), a **masked write-only** key input for the key-bearing sources (CourtListener, GovInfo), and an **enable/disable** toggle; POST/PATCH/DELETE to the new endpoints; hot-applied (re-fetch status after a write). No secret ever displayed. Follows `lq-*` design-system + the existing card's conventions; svelte-check clean.

## 7. Open items to resolve during planning (flagged, not hand-waved)

- **Where "key_required" + defaults live.** `SOURCE_REGISTRY` (api) knows the types/adapters; the gateway owns config + the `base_url`/allowlist defaults + which env var a key maps to. Decide: does the api pass the full entry shape to the gateway, or does the gateway hold a registry of tool-provider *defaults* keyed by type (cleaner — the gateway validates the type + fills base_url/allowlist itself, so the api can't inject an arbitrary egress target)? **Recommendation: the gateway owns the tool-provider default registry** (SSRF/egress safety per ADR 0014 — the api must not be able to set an arbitrary `base_url`). The api's `SOURCE_REGISTRY` stays the read-side/status source of truth.
- **Name vs type.** `tool_providers` entries have a `name` (e.g. `courtlistener-prod`) and a `type`. The admin API is keyed by **type** (one enabled provider per registry type is the model); the writer derives/uses a canonical name per type.
- **Env-key vs runtime-key precedence** (the `409` case): if `COURTLISTENER_API_TOKEN` is set in the env, is the runtime key path a conflict (409) or an override? Mirror whatever the inference path does for env-provided keys.

## 8. Testing

- **Gateway** (`gateway/`, mypy --strict): `config_writer` unit tests — `upsert_tool_provider` creates/updates the `tool_providers` block (keyed by type, canonical name), encrypts the key (ADR 0011), keyless enable, `remove_tool_provider`; the gateway admin endpoints return the right 400/404/409; hot-apply reloads config.
- **API** (`api/`): endpoint tests for each verb — admin-gated (non-admin 403), the 400/404/409 codes, **secret never returned** in any response, `GET` status shape, unregistered-type 404; a hot-apply integration proof (enable → `research/sources` reflects it).
- **Web:** svelte-check clean; a render/structure check on the card; masked input never surfaces the key.
- **Security review focus:** the api cannot set an arbitrary egress `base_url` (gateway-owned defaults); keys encrypted at rest + never logged/returned; admin-only; audit row on writes.
- Coverage no-decrease. Run `ruff format`+`ruff check`, `mypy` (gateway strict / api standard), and the OpenAPI drift-guard (**new routes → regenerate `backend-openapi.generated.yaml` via `make openapi`** AND bump `IMPLEMENTED_ROUTES`/`EXPECTED_PATHS` path count in `api/tests/test_endpoints.py`+`test_openapi.py` — 4 new paths).

## 9. Process

Branch (done) → spec → `writing-plans` → `subagent-driven-development` → **security-gated PR** (do not self-merge past the security review) → merge → mirror `origin`→`tucuxi` → reply to Donna's request doc with the §5 contract + squash SHA → **then v0.6.1** (version bump + `git tag v0.6.1`→GHCR + `desktop-v0.6.1`→.dmg + real-Mac verify, per the release ritual).

## 10. Risks

- **SSRF / arbitrary-egress** if the api could set `base_url` — mitigated by gateway-owned defaults (§7); the security reviewer must confirm.
- **Secret leakage** — write-only, encrypted, never returned/logged; tests assert it.
- **Collision-guard breakage** — 4 new routes → the path-count guards + OpenAPI export must be updated together (§8), or the whole api suite fails at collection.
- **Hot-apply correctness** — a write that doesn't reload leaves the UI showing stale `enabled`; the hot-apply proof test guards it.
