# PR6e — Retire the OpenWebUI MCP stub (DE-341) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the legacy OpenWebUI MCP client stub and every importer, reject MCP tool-server verification with a clear "use the gateway" error, and hide the web UI's MCP-add affordance — closing DE-341 and removing a non-gateway egress path from the web backend.

**Architecture:** Pure removal. Delete `web/backend/open_webui/utils/mcp/client.py`; excise the MCP branches from the two backend importers (`configs.py` verify endpoint, `middleware.py` chat tool-loop — dead in LQ.AI) plus the cross-file teardown consumer (`main.py`); hide the openapi↔mcp toggle in `AddToolServerModal.svelte` so only OpenAPI is selectable. No new code, no DB change.

**Tech Stack:** Python (OpenWebUI's FastAPI, in `web/backend/`), TypeScript/SvelteKit (`web/src/`).

## Global Constraints

- **Branch:** `feat/pr6e-mcp-stub-retirement` off `main` (`658fdbc`), already created; the spec is committed on it. Push `origin` + `tucuxi`. `origin/main` PROTECTED — PR + GitHub merge; sync tucuxi after. **Branch-first; never commit on local `main`.**
- **MCP-only removal.** Keep the OpenAPI tool-server paths intact in both the verify endpoint and the middleware loop. Do NOT touch LQ.AI's real MCP flow (`api/app/mcp/**`, `gateway/app/providers/tool/mcp.py`, PR4c per-user OAuth, `mcp.yaml`, `api/app/chat/tool_loop.py`).
- **Frontend = minimal.** Only hide the reachable MCP-*selection* toggle in `AddToolServerModal.svelte`. Leave the now-unreachable MCP form markup (`type === 'mcp'` branches) in place — `type` is permanently `'openapi'`, so it never renders. Do NOT touch `Connection.svelte`'s display-only tooltip label.
- **NO web/backend CI gate exists.** CI's Web job is `working-directory: web` (svelte-check + Vitest, frontend only); repo `ruff.toml` excludes `web/`. So Python edits in `web/backend/` are NOT linted/tested by CI — verify them manually with `python3 -m py_compile <file>` (syntax) + the grep gate. The LQ.AI `api/` + `gateway/` suites are unaffected (don't import `web/backend`).
- **Security-positive, not CODEOWNERS-gated:** `web/backend/open_webui/**` + `web/src/**` + docs; no `gateway/**`/`docs/security/**` substantive change → self-merge after CI green. Removing the stub *removes* a non-gateway external-egress path (strengthens ADR 0014).
- **Commit (every commit):** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly — never `git add -A`.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `web/backend/open_webui/utils/mcp/client.py` | Delete | The stub (whole file; only file in `utils/mcp/`). |
| `web/backend/open_webui/routers/configs.py` | Modify | Remove `MCPClient` import + the `type=='mcp'` verify branch → reject with a clear error; drop now-orphaned MCP-only imports. |
| `web/backend/open_webui/utils/middleware.py` | Modify | Remove `MCPClient` import + the `mcp_clients`/`mcp_tools_dict` MCP tool-loop branch + its merge/metadata-store. |
| `web/backend/open_webui/main.py` | Modify | Remove the `metadata['mcp_clients']` teardown-disconnect block. |
| `web/src/lib/components/AddToolServerModal.svelte` | Modify | Replace the openapi↔mcp toggle with a static "OpenAPI" label. |
| `docs/PRD.md` | Modify | Mark DE-341 resolved (6e). |

---

## Task 1: Backend — delete the stub + excise all importers

**Files:**
- Delete: `web/backend/open_webui/utils/mcp/client.py`
- Modify: `web/backend/open_webui/routers/configs.py`, `web/backend/open_webui/utils/middleware.py`, `web/backend/open_webui/main.py`

**Gate:** `grep -rn "MCPClient\|utils.mcp.client\|mcp_clients" web/backend/` returns nothing; `python3 -m py_compile` clean on all three edited files.

- [ ] **Step 1: Delete the stub + its directory.**
```bash
cd ~/Code/lq-ai && git rm web/backend/open_webui/utils/mcp/client.py && rmdir web/backend/open_webui/utils/mcp 2>/dev/null; ls web/backend/open_webui/utils/mcp 2>&1 | tail -1
```

- [ ] **Step 2: `configs.py` — remove the MCP verify branch.** Remove the import at L20 (`from open_webui.utils.mcp.client import MCPClient`). In `verify_tool_servers_config` (L363-485), replace the entire `if form_data.type == 'mcp':` block (L369-446 — both the OAuth-2.1-discovery sub-branch AND the `else:` MCPClient sub-branch) with a single rejection, leaving the `else:  # openapi` body (L447-477) as the post-`else` code. The result:
```python
    try:
        if form_data.type == 'mcp':
            raise HTTPException(
                status_code=400,
                detail='MCP tool servers are configured by the operator via the gateway, not added here.',
            )

        # openapi
        token = None
        headers = None
        if form_data.auth_type == 'bearer':
            token = form_data.key
        elif form_data.auth_type == 'session':
            token = request.state.token.credentials
        elif form_data.auth_type == 'system_oauth':
            try:
                if request.cookies.get('oauth_session_id', None):
                    oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                        user.id,
                        request.cookies.get('oauth_session_id', None),
                    )
                    if oauth_token:
                        token = oauth_token.get('access_token', '')
            except Exception as e:
                pass

        if token:
            headers = {'Authorization': f'Bearer {token}'}

        if form_data.headers and isinstance(form_data.headers, dict):
            if headers is None:
                headers = {}
            headers.update(form_data.headers)

        url = get_tool_server_url(form_data.url, form_data.path)
        return await get_tool_server_data(url, headers=headers)
    except HTTPException as e:
        raise e
    except Exception as e:
        log.debug(f'Failed to connect to the tool server: {e}')
        raise HTTPException(
            status_code=400,
            detail=f'Failed to connect to the tool server',
        )
```
(I.e. the openapi branch is unindented from `else:` to run after the early `raise`, preserving its exact logic.)

- [ ] **Step 3: `configs.py` — drop now-orphaned MCP-only imports.** The MCP branch was the only user of `get_discovery_urls` (imported ~L25) and `OAuthMetadata` (`from mcp.shared.auth import OAuthMetadata` ~L33). Confirm + remove:
```bash
cd ~/Code/lq-ai && grep -n "get_discovery_urls\|OAuthMetadata" web/backend/open_webui/routers/configs.py
```
Expected after Step 2: each appears ONLY on its import line. Remove those two import lines (the `get_discovery_urls` entry from its multi-name import group; the whole `from mcp.shared.auth import OAuthMetadata` line). If either shows a use elsewhere, leave that import.

- [ ] **Step 4: `middleware.py` — remove the MCP tool-loop branch.** Remove:
  - the import L117 `from open_webui.utils.mcp.client import MCPClient`;
  - `mcp_clients = {}` (L2603) and `mcp_tools_dict = {}` (L2604);
  - the entire `for tool_id in tool_ids:` MCP loop (L2607-2722 — the `if tool_id.startswith('server:mcp:')` block is the loop's only body, so remove the `for` line too), leaving `if tool_ids:` to contain just the `tools_dict = await get_tools(request, tool_ids, ...)` call (currently L2724);
  - the merge `if mcp_tools_dict: tools_dict = {**tools_dict, **mcp_tools_dict}` (L2736-2737);
  - the store `if mcp_clients: metadata['mcp_clients'] = mcp_clients` (L2785-2786).
  After: the `if tool_ids:` block resolves OpenAPI/built-in tools via `get_tools(...)` only. Read the surrounding indentation carefully — `if tool_ids:` at 8 spaces, its body at 12.

- [ ] **Step 5: `main.py` — remove the teardown MCP-disconnect.** In the request `finally:` block (L1921), remove the MCP-cleanup comment + inner try (L1922-1940 — the `# MCP cleanup …` comment through the `except asyncio.CancelledError: pass` that closes the `if mcp_clients := metadata.get('mcp_clients')` try). Leave the `finally:` and the subsequent `try: if metadata.get('chat_id')` block (L1942+) intact.

- [ ] **Step 6: Grep gate + syntax check.**
```bash
cd ~/Code/lq-ai && grep -rn "MCPClient\|utils\.mcp\.client\|mcp_clients\|mcp_tools_dict" web/backend/ || echo "(clean — no stub references)"
python3 -m py_compile web/backend/open_webui/routers/configs.py web/backend/open_webui/utils/middleware.py web/backend/open_webui/main.py && echo "py_compile OK"
```
Both must pass: grep clean, py_compile OK. (py_compile is parse-only — it validates syntax/indentation without importing heavy deps.)

- [ ] **Step 7: Commit.**
```bash
git add web/backend/open_webui/utils/mcp/client.py web/backend/open_webui/routers/configs.py web/backend/open_webui/utils/middleware.py web/backend/open_webui/main.py
git commit -s -m "refactor(web): retire OpenWebUI MCP client stub + importers (DE-341, PR6e)

Removes web/backend's direct-MCP egress path (configs verify + the dead chat
tool-loop branch + teardown); MCP is gateway-brokered per ADR 0014. OpenAPI
tool-server paths untouched.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Frontend — hide the MCP-add toggle

**Files:**
- Modify: `web/src/lib/components/AddToolServerModal.svelte` (the type toggle, L468-495)

**Gate:** `npm run check:lq-ai` 0 errors; web Vitest green; no selectable MCP type in the modal.

- [ ] **Step 1: Replace the toggle with a static OpenAPI label.** In `AddToolServerModal.svelte`, the "Type" row (L468-495) currently renders a clickable `<button>` (L474-487) that flips `type` between `'openapi'` and `'mcp'` when `!direct`. Replace the inner `{#if !direct} <button…>…</button> {:else} <div…>OpenAPI</div> {/if}` (L473-492) so BOTH cases render the static OpenAPI label (no toggle):
```svelte
								<div class="">
									<div class="text-xs text-gray-700 dark:text-gray-300">
										{$i18n.t('OpenAPI')}
									</div>
								</div>
```
`type` keeps its default `'openapi'` (L40 / reset at L350), so every `type === 'mcp'` branch in the rest of the modal is now unreachable (left in place per the minimal scope). Do not remove `registerOAuthClient`/MCP markup elsewhere in the file.

- [ ] **Step 2: svelte-check + Vitest.**
```bash
cd ~/Code/lq-ai/web && npm run check:lq-ai 2>&1 | tail -3
npx vitest run 2>&1 | tail -5
```
Expected: svelte-check 0 errors (pre-existing warnings in other files OK); Vitest green. (The toggle removal leaves valid Svelte; the unreachable MCP markup still type-checks.)

- [ ] **Step 3: Commit** (`git add web/src/lib/components/AddToolServerModal.svelte`).
```bash
git commit -s -m "feat(web): drop the MCP option from the add-tool-server modal (DE-341, PR6e)

LQ.AI connectors are operator-configured via the gateway, not user-added MCP
tool servers. Only OpenAPI is selectable; the unreachable MCP form markup is
left for a later cleanup.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Docs — DE-341 resolved + verify sweep

**Files:**
- Modify: `docs/PRD.md` (the DE-341 entry, ~L4594)

**Gate:** DE-341 marked resolved; no boundary-register/narrative doc still describes the stub as a live gap.

- [ ] **Step 1: Mark DE-341 resolved.** In `docs/PRD.md` §9, find the `#### DE-341 —` entry (`grep -n "DE-341" docs/PRD.md`). Append a resolution line to its body (preserve the deferral history, don't delete the entry):
```markdown

**Resolved in PR6e (2026-06-20):** deleted `web/backend/open_webui/utils/mcp/client.py` and excised its importers (`configs.py` verify branch → now rejects MCP with a "configured via the gateway" error; the dead `middleware.py` chat-loop branch; the `main.py` teardown); the web UI no longer offers MCP as an add-tool-server type. LQ.AI's gateway-brokered MCP path (ADR 0014 / PR4-5) is the sole MCP egress.
```

- [ ] **Step 2: Verify sweep (fix only genuine drift).**
```bash
cd ~/Code/lq-ai && grep -rni "open_webui.*mcp.*stub\|mcp.*client.py\|utils/mcp/client" docs/ || echo "(no stub references in docs)"
grep -rn "coming next\|Coming next\|next release" web/static/learn/playgrounds/governed-tool-flow.html web/src/routes/lq-ai/learn/how/+page.svelte README.md || echo "(no forward promises)"
```
If `docs/security/boundary-registers.md` (or any doc) describes the OpenWebUI MCP stub as a live non-gateway-egress gap, update it to note it's removed in 6e. The narrative grep should be clean already (6d dropped the stub-retirement "coming next").

- [ ] **Step 3: Commit** (`git add docs/PRD.md` + any boundary-register doc genuinely changed).

---

## Task 4: Verify + ship

**Files:** none (verification + ship).

- [ ] **Step 1: Full grep + syntax gate.**
```bash
cd ~/Code/lq-ai && grep -rn "MCPClient\|utils\.mcp\.client\|mcp_clients\|mcp_tools_dict" web/backend/ web/src/ || echo "(clean — no stub references anywhere)"
python3 -m py_compile web/backend/open_webui/routers/configs.py web/backend/open_webui/utils/middleware.py web/backend/open_webui/main.py && echo "py_compile OK"
```
Expected: grep clean across web/backend AND web/src; py_compile OK.

- [ ] **Step 2: Web checks + LQ.AI suites unaffected.**
```bash
cd ~/Code/lq-ai/web && npm run check:lq-ai 2>&1 | tail -3 && npx vitest run 2>&1 | tail -4
```
Expected: svelte-check 0 errors; Vitest green. (The api/gateway suites don't import web/backend, so they're unaffected — CI will confirm.)

- [ ] **Step 3: Build + manual verify the OpenAPI flow.** Rebuild `web` (pre-built bundle):
```bash
cd ~/Code/lq-ai && docker compose up -d --build web 2>&1 | tail -5
```
Open the add-tool-server modal: confirm the "Type" row shows a static **OpenAPI** label with no MCP toggle, and the OpenAPI add/verify flow still works. (If a live add-tool-server UI isn't reachable in the dev build, a `grep` confirming the toggle is gone + svelte-check is an acceptable substitute — note it.)

- [ ] **Step 4: Push both remotes + open the PR.**
```bash
cd ~/Code/lq-ai && git push -u origin feat/pr6e-mcp-stub-retirement && git push -u tucuxi feat/pr6e-mcp-stub-retirement
gh pr create --repo LegalQuants/lq-ai --base main --head feat/pr6e-mcp-stub-retirement \
  --title "PR6e/WS5: retire the OpenWebUI MCP stub (DE-341)" \
  --body-file <(printf '%s\n' "<PR body: deletes web/backend's legacy MCPClient stub + all importers (configs verify branch → gateway-rejection; the dead middleware chat-loop branch; the main.py teardown); hides the web UI MCP add-tool-server option (OpenAPI only); MCP-only removal (OpenAPI tool servers untouched); security-positive — removes a non-gateway egress path, strengthening ADR 0014; not security-gated; LQ.AI's real gateway-brokered MCP path untouched; DE-341 marked resolved; closes the milestone's last code change before the release gate>")
```
Not security-gated → **self-merge after CI green** (CI = Web svelte-check+Vitest + the api/gateway jobs, all unaffected by web/backend). After merge, sync tucuxi main. **After 6e: the release gate** (fresh-clone Docker → GHCR images → rebuilt macOS launcher → external-user verification → tag v0.5.0).

---

## Self-Review (run before executing)

**Spec coverage:** Delete stub (§Component 1) → Task 1 Step 1 ✓. configs.py MCP branch → reject (§Component 1) → Task 1 Steps 2-3 ✓. middleware.py dead branch removal (§Component 1) → Task 1 Step 4 ✓ (+ the main.py teardown consumer found in planning → Step 5). Frontend hide MCP toggle, minimal (§Component 2, brainstorm decision) → Task 2 ✓. Docs DE-341 resolved + verify sweep (§Component 3) → Task 3 ✓. Grep gate / py_compile / OpenAPI-intact (§Acceptance) → Tasks 1, 4 ✓. Non-goals respected: OpenAPI paths kept, LQ.AI real MCP path untouched, Connection.svelte tooltip left, unreachable MCP markup left (minimal frontend).

**Placeholder scan:** the configs.py replacement is verbatim (the openapi branch preserved exactly, unindented). The middleware.py + main.py removals are precise line-range excisions (no new code — read-and-delete with the exact anchors). The frontend replacement block is verbatim. PR body is a ship-time fill-in.

**Consistency:** the grep gate string (`MCPClient|utils.mcp.client|mcp_clients|mcp_tools_dict`) is identical across Task 1 Step 6 and Task 4 Step 1. The rejection `detail` string is identical in Task 1 Step 2 and the DE-341 resolution note. The `type` default `'openapi'` (Task 2) is what makes the left-in-place MCP markup unreachable (stated in both the constraint and Task 2 Step 1).

**Execution note:** inline. The load-bearing verification is the grep gate (no importers remain) + py_compile (web/backend has no CI gate) + svelte-check + the OpenAPI-flow manual check. The api/gateway suites are unaffected (they don't import web/backend) but CI runs them anyway. Anchors verified against the tree at write time (`main`=`658fdbc`): configs.py verify L363-485 (MCP branch 369-446), middleware.py MCP sites L117/2603-2604/2607-2722/2736-2737/2785-2786, main.py teardown L1921-1940, AddToolServerModal toggle L468-495, Connection.svelte:53 (display-only, left). Re-confirm line numbers before each edit (read the surrounding block).
```
