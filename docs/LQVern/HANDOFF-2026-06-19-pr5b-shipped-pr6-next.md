# Handoff — 2026-06-19 · Legal-research + MCP: PR5b (governed chat tool-loop) SHIPPED to review · next = PR6/WS5 (transparency surfaces)

**Repo:** `~/Code/lq-ai` (canonical; NEVER `~/Desktop`; Bash cwd resets — prefix every command `cd ~/Code/lq-ai && …`).
**PR5b = PR #187** (`feat/pr5b-chat-tool-loop`, off main `36223de`), **awaiting Kevin's security review + merge** (security-gated: chat send path + a gateway capability). Branch pushed to origin + tucuxi. **Migration head 0054.** **`EXPECTED_PATHS` = 133.**
**`origin/main` is a PROTECTED branch — direct pushes are REJECTED.** Everything lands via PR + GitHub merge; then sync tucuxi: `git push tucuxi <origin-main-sha>:main`. NEVER `git push origin main`.
**ruff pinned `==0.15.17`** in both venvs.

> Read these memories FIRST (durable state): `[[project-legal-research-mcp-milestone]]`, `[[project-pr6-transparency-posture-narrative]]`, `[[feedback-test-runner-venv-not-docker]]`, `[[feedback-commit-trailer-model]]`. This file is the session-specific pointer.

---

## What PR5b shipped (PR #187 — built subagent-driven, 8 tasks)

The **governed chat tool-loop** + persist-and-resume confirmation gate. Backend-only (UI → PR6). Spec `docs/superpowers/specs/2026-06-18-pr5-governed-chat-tool-loop-design.md` §PR5b; plan `docs/superpowers/plans/2026-06-19-pr5b-chat-tool-loop.md`.

**Forks Kevin approved (2026-06-19):** F1 = non-stream tool rounds, stream the final answer (so the gateway only got Anthropic **non-streaming** tool_use bridging — no streaming-delta work); F2 = `max_allowed_tier=None` for chat (mirror autonomous; gateway egress-tier policy is the authority).

| Piece | Where |
|---|---|
| Gateway `tools`/`tool_choice` request fields + Anthropic non-streaming `tool_use`→`tool_calls` bridging (+ assistant tool_use round-trip) | `gateway/app/providers/openai_schema.py`, `anthropic.py` (OpenAI/Ollama already forwarded) |
| api `call_tool(user_token=)` (X-LQ-AI-User-Token header) + api `ChatCompletionRequest` tools/tool_choice | `api/app/clients/gateway.py`, `api/app/schemas/gateway.py` |
| Allowlist assembly (5 fixed research schemas + enabled MCP tools, `mcp__{server}__{tool}`) | `api/app/chat/tool_schemas.py` |
| `chat_pending_tool_call` model + **migration 0054** (resume payloads live here, NOT on counts-only `tool_call_log`) | `api/app/models/chat_pending_tool_call.py`, `api/alembic/versions/0054_*.py` |
| The loop (non-stream rounds, `governed_tool_invocation` reused unmodified, cluster cache, cap 8) | `api/app/chat/tool_loop.py`; `chat_tool_call_cap` in `config.py` |
| `send_message` integration + `tool_confirmation_required` / `mcp_authorization_required` terminal SSE events | `api/app/api/chats.py` |
| Resume route `POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}` `{decision}` | `api/app/api/chats.py` (`EXPECTED_PATHS` 132→133) |

**Gates (local):** gateway **701 pass / 3 skip**; api **2201 pass / 1 skip**; ruff + mypy (`--strict` gateway) clean both. CI on #187 running at handoff time.

**Security invariants held (verified end-to-end in the whole-branch review):** no raw payloads in `tool_call_log`/logs (args → `_args_digest` only; results only in `role="tool"` conversation messages; OAuth token header-only); the confirmation gate can't be bypassed and is **single-use under concurrency** (atomic conditional `UPDATE ... WHERE status='pending' AND expires_at>=now` committed BEFORE execution); `governed_tool_invocation` reused **unmodified** (`origin="chat"`, `max_allowed_tier=None`); empty allowlist ⇒ byte-identical to the existing chat path.

**Review-loop catches worth knowing (all fixed before ship):**
- Cap now counts **governed** calls only (executed + tier-refused), with a zero-governed-round termination guard (a hallucination-only round can't loop forever).
- Gate-persistence failure now emits a terminal **error frame**, not a silent `[DONE]`.
- The whole-branch review caught a **Critical**: resume fed an **orphaned `role="tool"` message** with no preceding assistant `tool_calls` turn → real providers (Anthropic/OpenAI) **400**. Tests had passed only because the mock gateway didn't enforce tool_use/tool_result pairing. Fixed by reconstructing the assistant `tool_calls` turn (shared `tool_call_id`) on all resume sub-paths; locked by approve+deny pairing tests.

---

## After Kevin merges PR5b
1. Sync tucuxi main: `git push tucuxi <origin-main-sha>:main`.
2. Update `[[project-legal-research-mcp-milestone]]` with the squash SHA + "WS4 COMPLETE".
3. Delete the feature branch on both remotes.

## NEXT = PR6 / WS5 — transparency surfaces (the milestone's closing workstream)
The backend confirmation-gate + connect-on-demand **protocol** exists (SSE events + the resume endpoint); PR6 RENDERS it and tells the posture story. Per `[[project-pr6-transparency-posture-narrative]]` (Kevin's explicit ask) the surfaces must **narrate the security posture**, not just the mechanics:
- The **`playground`-skill "how it works" visualization** in Learn/how-it-works for the CourtListener/MCP flow (use the `playground` skill).
- README + LQ.AI docs updates alongside it.
- The **UI**: case-law panel, MCP provenance pills, the **destructive-confirm prompt** rendering (consumes `tool_confirmation_required` → `POST .../tool-calls/{id}`), the inline-connect prompt (consumes `mcp_authorization_required` → `/api/v1/mcp/oauth/{server}/authorize` with PR4d `return_url`).
- **External-source citation provenance** — net-new citation "source-kind" modeling (proposal C4); PR5 feeds raw tool results into the conversation, rich provenance is PR6.
- The **skill-frontmatter tool-usage + `minimum_inference_tier` parser** (proposal C5) — build or scope to docs.
- **Retire the OpenWebUI MCP stub (DE-341)** — now unblocked (chat path is gateway-brokered); migrate `web/backend/open_webui/routers/configs.py` + `utils/middleware.py` off `utils/mcp/client.py`, then delete the stub.

## DEs filed this PR (PRD §9)
DE-345 (shared `_stream_loop_outcome` renderer — the send/resume rendering duplication), DE-346 (`find_in_case` result-shape unify chat vs autonomous), DE-347 (chat tool-path OTel `chat.tool_call` span — loop passes `span=None`), DE-348 (resolve expired confirmation-gate `tool_call_log` row to `expired` + a `chat_pending_tool_call` TTL pruner), DE-349 (merge consecutive `tool_result` messages into one Anthropic user message — bites multi-read-only-tool rounds against Anthropic; the single-call resume path is fine). Still open from earlier: DE-336/337/338/340/342/343/344 + DE-341 (now unblocked).

## The loop (used all milestone — keep it)
verify ask vs code → surface forks via AskUserQuestion w/ recommendation → subagent-driven (fresh implementer per task; spec + quality review; opus for the load-bearing helper/guard + the whole-branch review on security-critical work) → run gates yourself (full api suite via :15433; ruff format --check + check; mypy; evidence before claims) → ship (`git commit -s` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; stage explicitly, never `git add -A`; push origin + tucuxi; PR vs main; watch CI; **Kevin merges security-gated**, then sync tucuxi). Ledger lives at `.git/sdd/progress.md`.

## Hard-won facts (don't relearn)
- **Tests via host venv, NOT docker** (`[[feedback-test-runner-venv-not-docker]]`): gateway `cd gateway && .venv/bin/pytest …`; api `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest …` (throwaway pgvector on :15433, conftest auto-migrates to head 0054). NEVER host `alembic upgrade` against the dev DB (:15432). Never `docker compose down -v`.
- **Subagents may spin up their own git worktree + cherry-pick back** — verify the commit landed on the feature branch and clean up the stray worktree (`git worktree remove --force …` + `git branch -D worktree-agent-…`) afterward. PR5b Task 5 did this.
- **Collision guards** crash the whole api suite at collection: a new route → `IMPLEMENTED_ROUTES` (`test_endpoints.py`) AND `EXPECTED_PATHS` + the pinned count (`test_openapi.py`, now **133**); `backend-openapi.yaml` is hand-maintained (DE-337).
