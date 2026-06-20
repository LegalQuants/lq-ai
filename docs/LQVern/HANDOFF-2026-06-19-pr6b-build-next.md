# Handoff — 2026-06-19 · WS5 6b (chat tool-loop UI) spec+plan DONE, ready to BUILD · 6a merged

**Repo:** `~/Code/lq-ai` (canonical; NEVER `~/Desktop`; Bash cwd resets — prefix every command `cd ~/Code/lq-ai && …`).
**main HEAD = `205efd9`** (PR6a merged; origin == tucuxi). Migration head 0054, `EXPECTED_PATHS` 133 (unchanged by 6b — frontend-only).
**6b branch = `feat/pr6b-chat-tool-loop-ui`** (off `205efd9`, pushed origin + tucuxi). Currently holds two doc commits: the **spec** (`7962491`) and the **plan** (`ac1aa82`). **Next session: BUILD the plan.**
**`origin/main` is PROTECTED** — PR + GitHub merge only; sync tucuxi after. NEVER `git push origin main`.

> Read these memories FIRST: `[[project-legal-research-mcp-milestone]]`, `[[project-pr6-transparency-posture-narrative]]` (has the WS5 6a→6b→6c→6d decomposition + the **D6 forward-consistency** rule), `[[project-pr6-release-completion-gate]]` (the end-of-PR6 release gate), `[[feedback-commit-trailer-model]]`. This file is the session-specific pointer.

---

## NEXT SESSION STARTS HERE — build PR6b

**The plan is complete and committed:** `docs/superpowers/plans/2026-06-19-pr6b-chat-tool-loop-ui.md` (7 tasks; deterministic TS is verbatim; the Svelte component/route chrome is concrete skeletons that mirror `RefusalMessageBubble.svelte`). Spec: `docs/superpowers/specs/2026-06-19-pr6b-chat-tool-loop-ui-design.md`.

**Recommended execution = INLINE** (`superpowers:executing-plans`) — like 6a, the load-bearing verification is visual (do the gate cards render, do the flows work) + the Vitest units; a subagent can't see the rendered UI. (Kevin chose inline-vs-subagent at the plan handoff; default to inline unless he says otherwise.) Tasks 1–3 are clean Vitest TDD; Tasks 4–5 are the stateful ChatPanel/route wiring (verify via build + visual).

**What 6b builds (frontend-only, NOT security-gated → self-merge after CI green):** consume PR5b's two terminal SSE events in the chat UI —
- `tool_confirmation_required` → an in-message approve/deny card (`ToolGatePrompt.svelte`, variant `confirm`) → `POST /api/v1/chats/{id}/tool-calls/{pending_call_id}` `{decision}` → resume the **same** assistant bubble (shared `consumeIntoMessage` helper handles chained gates).
- `mcp_authorization_required` → a connect card → same-tab redirect to `authorize_url?return_url=<chat URL>` → PR4d returns with `?mcp_connected` → a "Continue" button re-sends the last user message.
- **D6 (Task 6, MANDATORY):** flip the 6a narrative's availability claims "coming next" → "shipped" (explorer `AVAILABILITY` block + station 5/7 markers in `governed-tool-flow.html`, Learn section-17 sentence, README sentence). Do NOT let 6b merge without this — it's the honesty rule Kevin set.

## Session-specific gotchas (don't relearn)
1. **Web tests:** `cd web && npx vitest run <file>` and `npm run check:lq-ai` (the scoped svelte-check; CI gate = svelte-check + Vitest). Web is a **pre-built static bundle** — `docker compose up -d --build web` to view a UI change (never `docker compose down -v`).
2. **Visual verification without a full dev flow:** a headless Chromium is cached at
   `/Users/kevinkeller/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell` — used in 6a to `--screenshot`/`--dump-dom` a static HTML file (`--headless --disable-gpu --window-size=1280,860 --screenshot=out.png --virtual-time-budget=2500 file://…`). Reuse it to render `ToolGatePrompt` (both variants) in a tiny static harness for the PR screenshots (Playwright the npm package is NOT installed; only the browser binary).
3. **Anchors already read (in the plan verbatim):** `parser.ts` (terminal `return` pattern), `types.ts` frame interfaces (after line 391), `ChatPanel.svelte` send/consume (~534-621; `messagesApi.sendMessageStream` + `consumeMessageStream`; `messagesStore`, `streamingMessageId`, `sendError`, `draftAssistantId`), `api/messages.ts` (`apiStreamRequest` pattern; `resumeToolCall` goes here), `api/client.ts` `apiStreamRequest` (throws `errorFor(status)` on non-2xx → resume 409/410 = expired), `MessageBubble.svelte` assistant branch (~130-160; render `ToolGatePrompt` after content), chats route `web/src/routes/lq-ai/chats/+page.svelte` (owns the URL for the `?mcp_connected` return handler; reuse the project toast convention — likely `svelte-sonner`).
4. **Commit trailer:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly, never `git add -A`. Push origin + tucuxi.

## After 6b merges (sync tucuxi, then continue WS5)
- **6c** — external-source citations / source-kind (C4) in `api/app/citation/` + `MessageCitation` (migration) + provenance pills + **the case-law results panel** (moved here from 6b — it needs 6c's structured citation data). Backend + frontend. Per D6, 6c updates the narrative for now-real provenance.
- **6d** — the `skills/case-law-research/` SKILL + the C5 frontmatter parser (or docs-only — pin in 6d planning) + **retire the OpenWebUI MCP stub (DE-341)** (migrate `web/backend/open_webui/routers/configs.py` + `utils/middleware.py` off `utils/mcp/client.py` → gateway path, delete the stub). Per D6, 6d does the **final milestone-completion honesty pass** over the whole narrative.
- **THEN the release gate** (`[[project-pr6-release-completion-gate]]`): fresh-clone Docker works per README → build+push GHCR images → rebuild the signed/notarized macOS launcher (`docs/lq-ai-macos-launcher-playbook.md`) → verify for an external user → **tag v0.5.0** (current tags reach v0.4.2).

## The loop (used all milestone — keep it)
brainstorm (forks via AskUserQuestion w/ recommendation) → spec → writing-plans → build (inline for UI/visual work; subagent-driven for backend TDD; independent review before ship) → run gates yourself (evidence before claims) → ship (commit -s + trailer; push origin + tucuxi; PR vs main; CI; self-merge if frontend/api-only, **Kevin merges security-gated**; sync tucuxi). DEs → PRD §9.
