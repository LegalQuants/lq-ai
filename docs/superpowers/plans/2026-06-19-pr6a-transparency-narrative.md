# PR6a — Transparency narrative (governed-tool-flow explorer + Learn + README + authority docs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the interactive "how it works" explorer + Learn page + README + authority-doc updates that make the legal-research + MCP **security posture** legible to an in-house lawyer.

**Architecture:** One new self-contained single-file HTML explorer (`web/static/learn/playgrounds/governed-tool-flow.html`) matching the existing 18 playgrounds' house style — a step-through of the 7-station governed tool flow with 4 guardrail toggles that reveal the refusal/confirm paths. Surfaced via a new entry in the Learn `how` page, narrated in the README, and grounded by flipping ADR 0014/0015 to Accepted + refreshing the boundary-register. No `api/`/`gateway/` code.

**Tech Stack:** Static HTML + inline CSS/vanilla JS (no build step, no deps); SvelteKit (`web/src/routes/lq-ai/learn/how/+page.svelte`); Markdown/YAML docs.

## Global Constraints

- **Branch:** `feat/pr6a-transparency-narrative` off `main` (`97ccbc0`), already created. Push `origin` + `tucuxi`. `origin/main` is PROTECTED — PR + GitHub merge only; sync tucuxi after. **Security-gated** (touches `docs/security/boundary-registers.md`, CODEOWNERS) → **the maintainer reviews/merges**; do NOT self-merge.
- **Accuracy is a hard gate (D5).** Every station, toggle, audit note, and posture claim must reflect real merged PR1–PR5b behavior; example data is clearly labeled "illustrative" (the artifact is static — no live calls); each posture callout links to its verifiable source file. An inaccurate claim is a defect, not polish.
- **Forward consistency (D6).** All "available today vs. coming next" claims live in ONE `AVAILABILITY` block in the explorer + one parallel sentence each in the Learn copy and README — nowhere else. (Later sub-PRs 6b/6c/6d update that one block.)
- **House-style match (E).** The explorer must visually match the existing playgrounds: copy the `:root` theme variables + font stack from `web/static/learn/playgrounds/request-lifecycle.html`; reuse the toggle markup/JS pattern from `web/static/learn/playgrounds/autonomous-flow.html`. Single self-contained file, no external dependencies.
- **No backend / no routes.** No `api`/`gateway` code, no new endpoint → no `EXPECTED_PATHS`/`IMPLEMENTED_ROUTES`/migration change.
- **Web is a pre-built static bundle** — rebuild `web` before viewing a change; `svelte-check` + Vitest are the CI web gates.
- **Commit (every commit):** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly — never `git add -A`.
- **The `playground` skill** may be used to scaffold the explorer's interaction, but the deliverable conforms to the house style above and the exact 7-station/4-toggle design in Task 1 (house-style + accuracy are the binding constraints).

## TDD note

This sub-PR produces a static viz + Svelte copy + Markdown — there is no pytest harness, so classic red/green TDD does not apply. Each task's gate is the appropriate real check: opening the artifact in a browser and exercising the toggles, `svelte-check`, valid links, and the **mandatory accuracy cross-check against the cited source files**. Tasks state their gate explicitly.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `web/static/learn/playgrounds/governed-tool-flow.html` | Create | The explorer (7 stations, 4 toggles, AVAILABILITY block, source footer). |
| `web/src/routes/lq-ai/learn/how/+page.svelte` | Modify (append entry 19 after line ~818) | Embed the explorer with framing paragraph + full-screen link + source refs. |
| `README.md` | Modify (after the M4 paragraph, before the `---` ~line 88 in "What it does") | One posture paragraph + the single availability sentence. |
| `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md` | Modify (line 3) | `**Status:** Proposed` → `Accepted`. |
| `docs/adr/0015-governed-tool-calling-model.md` | Modify (line 3) | `**Status:** Proposed` → `Accepted`. |
| `docs/security/boundary-registers.md` | Modify (the existing "Gateway boundary — tool / data-source egress (ADR 0014)" entry, ~lines 224–256) | Refresh PARTIAL → SHIPPED across WS2/WS3/WS4; fix the stale ADR filename link; add MCP + governed-loop + confirmation-gate coverage. |
| `gateway.yaml.example`, `mcp.yaml.example` | Verify only (no edit expected) | Confirm the operator-allowlist surfaces are already clearly shown (they are — Task 4 records this). |

---

## Task 1: The governed-tool-flow explorer

**Files:**
- Create: `web/static/learn/playgrounds/governed-tool-flow.html`
- Reference (read first, do not modify): `web/static/learn/playgrounds/request-lifecycle.html` (theme + layout), `web/static/learn/playgrounds/autonomous-flow.html` (toggle markup + JS state/re-render pattern)

**Interfaces:**
- Produces: a static file served at `/learn/playgrounds/governed-tool-flow.html` (the Learn entry in Task 2 iframes this exact path).

**Gate:** open the file directly in a browser (`file://…/governed-tool-flow.html` or via the running web container) — confirm: all 7 stations render; each of the 4 toggles, when flipped, re-runs the flow and changes the highlighted station + the posture callout to the refusal/confirm path; the AVAILABILITY block is present; the source footer links resolve. **Accuracy:** every station/toggle/audit line matches the cited source (see the accuracy table below).

- [ ] **Step 1: Read the two template playgrounds** (`request-lifecycle.html`, `autonomous-flow.html`) to internalize: the `:root` theme variables + font stack, the `.app`→`header`/`.main`/`output` grid, the `.controls` sidebar, and the `.toggle` markup + its `addEventListener("change", …) → update state → render()` wiring.

- [ ] **Step 2: Scaffold the file** with the verbatim house `<head>`/theme. Copy the `:root` custom-property block and the `html, body { font: … }` rule from `request-lifecycle.html` exactly. Set `<title>LQ.AI — Governed Tool Boundary</title>`. Layout: `.app` grid = header / `.main` (controls sidebar + a stations column) / a footer source-links bar. Header: `<h1>LQ.AI — Governed Tool Boundary</h1>` + a subtitle "How a case-law / connector lookup leaves your environment — and everything that gates it." + the `↩ Learn` and `View source ↗` links exactly as the templates have them.

- [ ] **Step 3: Encode the 7 stations as a JS data array** and render them into the stations column. Each station object: `{ n, title, posture, recorded }`. Use this EXACT copy (accuracy-checked):

```js
const STATIONS = [
  { n: 1, title: "Allowlist assembled",
    posture: "The backend builds a closed, per-turn set of tools from only the research + MCP connectors the operator enabled. The model can't reach beyond it.",
    recorded: "What's recorded: which tools were offered. The set is operator-config, not model choice." },
  { n: 2, title: "Model picks a tool",
    posture: "The model chooses among allowed tools only (e.g. CourtListener search, or an enabled MCP tool) — a closed set, not open-ended function-calling.",
    recorded: "What's recorded: the chosen tool + provider (names/types only)." },
  { n: 3, title: "Gateway egress + SSRF check",
    posture: "The call leaves your environment only through the Inference Gateway, which validates the outbound target. The backend never calls a third party directly — the gateway is the sole egress and the only MCP-protocol speaker.",
    recorded: "Never sent: anything to a host the operator didn't allowlist." },
  { n: 4, title: "Tier gate + rate limit",
    posture: "The connector's egress tier is checked and rate-limited. A call above the allowed tier is refused at the boundary.",
    recorded: "What's recorded: the egress tier + outcome." },
  { n: 5, title: "Per-user OAuth (connectors that need it)",
    posture: "For OAuth connectors, your personal token travels as a request header — never in a URL, body, or log — and is encrypted at rest. The gateway brokers the call without learning who you are.",
    recorded: "Never logged: the token. It is carried in a header and stored encrypted (Fernet)." },
  { n: 6, title: "Audit row written",
    posture: "Every call (and every refusal) is written to an audit log — counts and types only.",
    recorded: "Never written to the audit row or any log line: the raw request arguments or the tool's results. Only a digest + outcome." },
  { n: 7, title: "Result returned — or a confirmation gate",
    posture: "Read-only results flow back into your conversation. A tool marked destructive (or any connector tool that isn't explicitly read-only) pauses for your explicit approval before it runs.",
    recorded: "Safe by default: an un-annotated connector tool requires confirmation rather than running silently." },
];
```

- [ ] **Step 4: Encode the 4 guardrail toggles** (default ON = the protection in place). Each toggle flips a state flag; a `render()` recomputes which station the flow halts/pauses at and swaps the posture callout to the refusal/confirm message. Use this EXACT toggle copy + behavior:

```js
// toggle id -> { label, sub, breaksAt, breakKind, breakMsg }
const TOGGLES = {
  allowlisted: { label: "Connector allowlisted", sub: "Operator wired this connector in gateway.yaml / mcp.yaml.",
    breaksAt: 1, breakKind: "refused",
    breakMsg: "Refused: the tool never enters the allowlist, so it never reaches the network. Nothing leaves your environment unless the operator wired it." },
  oauth: { label: "OAuth connected", sub: "You've connected your account for this connector.",
    breaksAt: 5, breakKind: "connect",
    breakMsg: "Paused for connect: the chat surfaces an inline 'connect this connector' prompt (per-user consent) before the call proceeds." },
  tier: { label: "Within egress-tier ceiling", sub: "The connector's tier is within the allowed ceiling.",
    breaksAt: 4, breakKind: "refused",
    breakMsg: "Refused at the gateway: the connector's egress tier exceeds the ceiling. Tier-gated egress is enforced at the boundary." },
  readonly: { label: "Tool is read-only", sub: "The chosen tool is a read-only lookup.",
    breaksAt: 7, breakKind: "confirm",
    breakMsg: "Paused at the confirmation gate: a destructive tool requires your explicit approval before it runs." },
};
```

Render logic: walk stations 1→7; if a toggle is OFF, the flow halts/pauses at that toggle's `breaksAt` station, marking it `refused`/`connect`/`confirm` and showing `breakMsg` in the posture callout; stations after a hard `refused` are dimmed. Multiple toggles off → halt at the earliest `breaksAt`. Wire each `<input type="checkbox">` with `addEventListener("change", … ; render())`, mirroring `autonomous-flow.html`.

- [ ] **Step 5: Add the AVAILABILITY block** (D6 — the single source of temporal truth). Render a small labeled panel with EXACTLY this content:

```
Available today: the governed backend tool-loop, the gateway egress boundary, per-user OAuth, the per-call audit, and the confirmation-gate protocol — all shipped and running.
Coming in the next release: the in-chat confirmation prompt and the inline connect-on-demand UI that render this gate inside the chat. (The backend protocol exists now; the chat UI lands in the next transparency release.)
```

Stations 5 and 7 must reference this block (e.g. a small "ⓘ availability" marker linking/scrolling to it) rather than restating the timing inline.

- [ ] **Step 6: Add the source-links footer** (accuracy contract). A footer bar listing the verifiable sources, each an `<a target="_blank" rel="noopener">` to the GitHub blob on `main`:
  - ADR 0014 — `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md`
  - ADR 0015 — `docs/adr/0015-governed-tool-calling-model.md`
  - Allowlist assembly — `api/app/chat/tool_schemas.py`
  - The loop — `api/app/chat/tool_loop.py`
  - Gateway egress — `gateway/app/providers/tool/`
  - Governance + audit — `api/app/tools/governance.py`, `api/app/models/tool_call_log.py`
  - Per-user OAuth — `gateway/app/providers/tool/oauth_passthrough.py`, `api/app/mcp/oauth.py`
  Plus a one-line note: "Illustrative walkthrough — this page makes no live network calls."

- [ ] **Step 7: Accuracy self-check.** Before committing, verify each claim against the source (this is the gate, restated as a checklist the implementer runs):

| Claim in the explorer | Verify against |
|---|---|
| Closed per-turn allowlist, operator-enabled only | `api/app/chat/tool_schemas.py` (`assemble_allowlist`) |
| Sole egress / only MCP speaker / SSRF target validation | ADR 0014; `gateway/app/providers/tool/` (`validate_egress_target`) |
| Egress tier checked + rate-limited + refused over ceiling | `gateway` `route_tool_call`; ADR 0014 |
| Token header-only, never logged, Fernet at rest, gateway user-unaware | `gateway/app/providers/tool/oauth_passthrough.py`, `api/app/mcp/oauth.py` |
| Audit counts/types only, no raw args/results (digest only) | `api/app/models/tool_call_log.py`, `api/app/tools/governance.py` (`args_digest`) |
| Destructive / un-annotated ⇒ requires confirmation; persist-and-resume gate | `api/app/chat/tool_loop.py` (gate), ADR 0015 |
| In-chat confirm/connect UI is NOT yet shipped (6b) | true as of this PR — the AVAILABILITY block says so |

- [ ] **Step 8: Commit.**
```bash
git add web/static/learn/playgrounds/governed-tool-flow.html
git commit -s -m "feat(learn): governed-tool-flow posture explorer (PR6a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Learn `how` page entry (section 19)

**Files:**
- Modify: `web/src/routes/lq-ai/learn/how/+page.svelte` (append a new `<section>` after the last existing entry, ~line 818, before the page footer ~line 821)

**Interfaces:**
- Consumes: the explorer at `/learn/playgrounds/governed-tool-flow.html` (Task 1).

**Gate:** `svelte-check` passes; in the running web app the new section renders, the iframe loads the explorer, and the "Open full-screen" link works.

- [ ] **Step 1: Read the existing entries** (e.g. sections 1–2, lines 34–121) to copy the exact markup conventions: `<section class="lq-how-section" data-testid="…">`, `<h2 class="lq-section-h">N. Title: Subtitle</h2>`, `<p class="lq-text-body">`, the `.lq-playground-wrap` iframe block (`loading="lazy"`, the inline `style="width:100%;height:900px;border:…;border-radius:8px;"`), and the `.lq-playground-foot` (full-screen link + `.lq-source-ref`). Confirm the current highest section number (18) so the new one is **19**.

- [ ] **Step 2: Append the new section** after the last entry. Use this content (the single availability sentence per D6 is included verbatim):

```svelte
<p class="lq-transition lq-text-body">
  The newest capability lets the assistant look up case law and reach operator-approved
  connectors — without ever loosening the security boundary. This last playground walks that
  governed path and lets you switch each guardrail off to see how the boundary reacts.
</p>

<!-- 19: Governed tool boundary -->
<section class="lq-how-section" data-testid="lq-ai-learn-how-section-governed-tool-flow">
  <h2 class="lq-section-h">19. Case-law &amp; connectors: the governed tool boundary</h2>
  <p class="lq-text-body">
    When the assistant looks up case law (CourtListener) or calls an operator-approved connector
    (an MCP server), the request leaves your environment only through the Inference Gateway — the
    single audited egress. The operator chooses which connectors exist; every call is tier-gated
    and audited (counts and types only, never the raw arguments or results); per-user connector
    tokens travel in a header and are never logged; and a destructive tool pauses for your explicit
    approval. Step through the flow, then flip any guardrail off to see the boundary refuse, prompt,
    or pause. <strong>Available today:</strong> the governed backend tool-loop, egress boundary,
    per-user OAuth, audit, and the confirmation-gate protocol. <strong>Coming next:</strong> the
    in-chat confirmation and connect prompts that render this gate inside the chat.
  </p>
  <div class="lq-playground-wrap">
    <iframe
      src="/learn/playgrounds/governed-tool-flow.html"
      title="Governed Tool Boundary"
      loading="lazy"
      data-testid="learn-playground-governed-tool-flow"
      style="width: 100%; height: 900px; border: 1px solid var(--lq-border, #e5e7eb); border-radius: 8px;"
    ></iframe>
  </div>
  <div class="lq-playground-foot">
    <a
      href="/learn/playgrounds/governed-tool-flow.html"
      class="lq-link lq-fullscreen-link"
      target="_blank"
      rel="noopener noreferrer">Open full-screen ↗</a
    >
    <span class="lq-source-ref">
      Source:
      <a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0014-gateway-egress-boundary-for-tool-providers.md" class="lq-link" target="_blank" rel="noopener noreferrer">ADR 0014</a>;
      <a href="https://github.com/LegalQuants/lq-ai/blob/main/docs/adr/0015-governed-tool-calling-model.md" class="lq-link" target="_blank" rel="noopener noreferrer">ADR 0015</a>;
      <a href="https://github.com/LegalQuants/lq-ai/blob/main/api/app/chat/tool_loop.py" class="lq-link" target="_blank" rel="noopener noreferrer">api/app/chat/tool_loop.py</a>
    </span>
  </div>
</section>
```

- [ ] **Step 3: Run `svelte-check`.**
```bash
cd /Users/kevinkeller/Code/lq-ai/web && npm run check 2>&1 | tail -20
```
Expected: no new errors/warnings introduced by the change. (If the repo's check command differs, use the one in `web/package.json` `scripts` — confirm before running.)

- [ ] **Step 4: Commit.**
```bash
git add web/src/routes/lq-ai/learn/how/+page.svelte
git commit -s -m "feat(learn): add governed-tool-boundary section to how-it-works (PR6a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: README posture paragraph + ADR status flips

**Files:**
- Modify: `README.md` (in "## What it does", after the M4 Autonomous Layer paragraph, before the `---` separator ~line 88)
- Modify: `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md` (line 3)
- Modify: `docs/adr/0015-governed-tool-calling-model.md` (line 3)

**Gate:** Markdown renders; the README links resolve; both ADRs read `**Status:** Accepted`.

- [ ] **Step 1: Add the README capability paragraph**, matching the existing `**Name.**`-led prose style, with the single availability sentence (D6):

```markdown
**Legal research + connectors (MCP), gateway-brokered.** The assistant can look up case law (CourtListener) and call operator-approved connectors (MCP servers) — always through the Inference Gateway, the single audited egress and the only component that speaks the MCP protocol. The operator chooses which connectors exist; every call is tier-gated and recorded (counts and types only, never raw arguments or results); per-user connector tokens travel in a request header and are never logged; and destructive tools pause for explicit human approval. See the [governed-tool-boundary explorer](web/src/routes/lq-ai/learn/how/+page.svelte) in Learn → How it works, and [ADR 0014](docs/adr/0014-gateway-egress-boundary-for-tool-providers.md) / [ADR 0015](docs/adr/0015-governed-tool-calling-model.md) for the boundary and the governed tool-calling model. *Available today: the governed backend tool-loop, egress boundary, per-user OAuth, audit, and confirmation-gate protocol; the in-chat confirmation/connect UI lands in the next release.*
```

- [ ] **Step 2: Flip ADR 0014 status.** In `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md` change line 3 `**Status:** Proposed` → `**Status:** Accepted`. If the ADR has a status/history note convention used by other Accepted ADRs (check a sibling ADR that is already "Accepted"), match it (e.g. append "(accepted 2026-06-19, implemented PR1–PR5b)").

- [ ] **Step 3: Flip ADR 0015 status.** Same change in `docs/adr/0015-governed-tool-calling-model.md` line 3.

- [ ] **Step 4: Commit.**
```bash
git add README.md docs/adr/0014-gateway-egress-boundary-for-tool-providers.md docs/adr/0015-governed-tool-calling-model.md
git commit -s -m "docs(pr6a): README legal-research+MCP posture paragraph; ADR 0014/0015 -> Accepted

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Refresh the boundary-register (+ verify yaml examples)

**Files:**
- Modify: `docs/security/boundary-registers.md` (the existing "Gateway boundary — tool / data-source egress (ADR 0014)" entry, ~lines 224–256)
- Verify only (no edit expected): `gateway.yaml.example` (`tool_providers` block), `mcp.yaml.example`

**Gate:** the refreshed entry accurately reflects shipped WS2/WS3/WS4; the ADR reference link is correct (the file is `0014-gateway-egress-boundary-for-tool-providers.md`, NOT the `0014-tool-provider-egress-boundary.md` the current entry cites); all verification-path commands in the entry resolve to real files/tests.

- [ ] **Step 1: Read the existing entry** (~lines 224–256) and the file header/conventions. Note the current `**Current implementation state.** PARTIAL` and the stale `**Reference.** ADR 0014 (docs/adr/0014-tool-provider-egress-boundary.md)` link.

- [ ] **Step 2: Refresh the entry** to reflect the now-shipped milestone, preserving the existing structure (definition → controls → audit surface → current state → reference → verification path):
  - **Current implementation state:** PARTIAL → **SHIPPED** — name WS3 (CourtListener research provider), WS2 (MCP servers + per-user OAuth passthrough, Fernet-at-rest, header-only token), WS4 (governed chat tool-loop + persist-and-resume confirmation gate). Keep it honest: note the in-chat confirmation/connect UI is the next transparency release (matches the explorer's AVAILABILITY block).
  - **Controls:** add the MCP-specific controls (per-user OAuth out-of-band, token header-only/never-logged, gateway user-unaware) and the governed-loop controls (closed allowlist, tier ceiling, destructive-tool confirmation gate, autonomous layer never auto-granted destructive tools).
  - **Audit surface:** add `tool_call_log` (the api-side governance audit) alongside `tool_egress_log` — both counts/types only, `args_digest` not raw payloads.
  - **Reference:** fix to `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md` and add `docs/adr/0015-governed-tool-calling-model.md`.
  - **Verification path:** update the `bash` block so every command resolves today — point at `gateway/app/providers/tool/`, `api/app/tools/governance.py`, `api/app/chat/tool_loop.py`, `api/app/mcp/oauth.py`, and the actual current example-config test name (verify the test path before citing it; if `gateway/tests/test_example_config_tool_providers.py` no longer exists, cite the real current test).

- [ ] **Step 2a: Verify the example-config test name** before writing it into the verification path:
```bash
ls gateway/tests/ | grep -i example_config; ls gateway/tests/ | grep -i tool_provider
```
Cite whatever actually exists.

- [ ] **Step 3: Verify the yaml examples are adequate (no edit expected).** Read `gateway.yaml.example` `tool_providers` block + `mcp.yaml.example`. Both already show the operator-allowlist surfaces with inline comments (name/type/base_url/egress_tier/allowlist.hosts/rate_limit; MCP auth none|bearer|oauth + oauth_client_id + AS-host allowlist note). Confirm this; only edit if a surface is genuinely missing or wrong. Record the verification result in the commit message ("yaml examples verified adequate; no edit needed").

- [ ] **Step 4: Commit.**
```bash
git add docs/security/boundary-registers.md
git commit -s -m "docs(security): refresh tool-provider egress register to SHIPPED (WS2/3/4) + fix ADR link (PR6a)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Accuracy review, build/visual check, ship

**Files:** none (verification + ship).

**Gate:** the explorer is accurate + renders; `svelte-check` clean; web builds; PR opened.

- [ ] **Step 1: Whole-narrative accuracy review.** Re-read the explorer copy, the Learn paragraph, the README paragraph, and the boundary-register against the Task 1 accuracy table + the cited source files. Confirm no overclaim and no stale timing (the AVAILABILITY block + the three parallel sentences all agree: in-chat confirm/connect UI = next release). This is the load-bearing gate — treat any mismatch as a blocking defect.

- [ ] **Step 2: Build the web bundle + visual check.** Rebuild the `web` container (the bundle is pre-built — a source change isn't visible until rebuild). Open Learn → How it works, scroll to section 19, confirm: the iframe loads the explorer; each of the 4 toggles flips the flow to its refusal/connect/confirm path; the AVAILABILITY block and source links render; "Open full-screen" works. Capture a screenshot for the PR.
```bash
# rebuild only the web service (do NOT docker compose down -v)
docker compose up -d --build web 2>&1 | tail -5
```

- [ ] **Step 3: Run the web checks one more time.**
```bash
cd /Users/kevinkeller/Code/lq-ai/web && npm run check 2>&1 | tail -20
```
Expected: no new errors.

- [ ] **Step 4: Push both remotes + open the PR.**
```bash
cd /Users/kevinkeller/Code/lq-ai
git push -u origin feat/pr6a-transparency-narrative
git push -u tucuxi feat/pr6a-transparency-narrative
gh pr create --repo LegalQuants/lq-ai --base main --head feat/pr6a-transparency-narrative \
  --title "PR6a/WS5: transparency narrative — governed-tool-flow explorer + Learn + README + authority docs" \
  --body-file <(printf '%s\n' "<PR body: what it is, the posture story, the security-gated note (boundary-registers), the D6 forward-consistency obligation for 6b/6c/6d, a screenshot, and 'no api/gateway code'>")
```
Security-gated (boundary-registers) → **the maintainer reviews/merges**; do NOT self-merge. After merge, sync tucuxi main.

---

## Self-Review (run before dispatching execution)

**Spec coverage:** Explorer step-through + 4 toggles (D2) → Task 1 ✓. One explorer, both providers (D4) → Task 1 stations/toggles cover research + MCP ✓. Accuracy contract + source footer (D5) → Task 1 Steps 6–7 + Task 5 Step 1 ✓. AVAILABILITY block + forward consistency (D6) → Task 1 Step 5, mirrored in Task 2/3 copy ✓. Learn entry (Architecture B) → Task 2 ✓. README (C) → Task 3 ✓. ADR flips + boundary-register + yaml verify (D) → Tasks 3–4 ✓. Security-gated, branch/push/PR (Gating) → Task 5 ✓. Non-goals respected (no api/gateway code, no 6b/6c/6d surfaces, no learn/use entry, deferred reference docs) ✓.

**Placeholder scan:** Station/toggle/AVAILABILITY/README/Learn copy is provided verbatim. The one deliberately-deferred-to-implementation item — the exact test name in the boundary-register verification path — is gated by Task 4 Step 2a (verify-before-citing), not a placeholder. The PR body is a fill-in at ship time (Task 5 Step 4), acceptable.

**Consistency:** The iframe `src`, the file path, and the full-screen link all use `/learn/playgrounds/governed-tool-flow.html` across Tasks 1–2. The AVAILABILITY wording in the explorer (Task 1 Step 5), the Learn paragraph (Task 2 Step 2), and the README sentence (Task 3 Step 1) say the same thing (in-chat confirm/connect UI = next release). Section number 19 is consistent.

**Note for execution:** this sub-PR is visual/accuracy-driven, not pytest-TDD. Inline execution (with the controller able to use the `playground` skill + run the browser/visual check) may fit better than the heavy subagent-driven loop — but Task 1's accuracy review still warrants an independent reviewer pass before ship.
