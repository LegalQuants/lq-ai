# Learn-tab "Autonomous flow" visualization — spec

> **Deliverable (b)** of the M4/LQVern implementation-planning session (companion to [`docs/M4-IMPLEMENTATION-PLAN.md`](../M4-IMPLEMENTATION-PLAN.md), built by Task **M4-D1**). This is the design contract for the public Learn-tab explainer of the Autonomous Layer.
>
> **Scope of this document:** a *spec*, not the built artifact. It pins what to build so M4-D1 is mechanical. Kevin decides build-now-vs-later; the planning session's decision is **spec-only** — the build is sequenced as M4-D1, after the substrate (M4-A3/A4) lands so the depicted span/attribute/receipt names match shipped code.
>
> **Sources of truth this spec must not drift from:** [ADR 0013](../adr/0013-autonomous-layer-design-influences.md) (the design), [PRD §3.10](../PRD.md#310-autonomous-layer-m4) (the capability), [`agentic-flow-alignment-guide.md`](agentic-flow-alignment-guide.md) (the chokepoint shape + span/audit names), and the existing playground conventions in `web/static/learn/playgrounds/`.

---

## 0. The one teaching point

Everything below serves a single headline message:

> **You can audit exactly what the agent did and why.**

An autonomous agent acts without a human watching each step. The Learn explainer's job is to show — concretely, interactively — that this autonomy is *bounded and legible*: it runs through declared phases, every tool call passes one brake-checked chokepoint, the brakes (cost / halt / phase-grant) visibly fire, and the run produces a human-readable receipt. The visualization is the public face of the §1.3 transparency principle applied to *actions*, not just prompts.

---

## 1. Conventions to mirror (non-negotiable)

The new playground is a **self-contained single-file HTML** document under `web/static/learn/playgrounds/`, exactly like its siblings (`otel-eval.html`, `test-landscape.html`, `playbook-cascade.html`). Specifically:

- **Single file, no build step, no external fetches.** All data is inline; the playground works offline.
- **Shared dark theme** via the CSS custom properties used across the existing playgrounds — reuse the same `:root` variable block: `--bg: #0c0f14`, `--bg-elev: #151a23`, `--bg-elev-2: #1d242f`, `--border`, `--text`, `--text-dim`, `--accent: #7dd3fc`, and the status palette `--verified` (green), `--partial` (amber), `--unverified` (red), `--pending` (grey). **Do not introduce new colors** — map the brake outcomes onto the existing palette (below).
- **Layout:** the `.app { display: grid; grid-template-rows: auto 1fr; height: 100vh; }` shell with a `<header>` (h1 + `.subtitle` + `.spacer` + a doc link), exactly as `otel-eval.html`.
- **Controls + preview.** A control strip drives a live preview; a copy-out affordance where relevant (consistent with the playground skill's pattern).
- **Test hooks.** Root element carries a `data-testid`; when embedded in the how-page it is referenced as `data-testid="learn-playground-autonomous-flow"`.
- **Filename:** `web/static/learn/playgrounds/autonomous-flow.html`.

---

## 2. The "Autonomous flow" playground — contents

### 2.1 Header

- **h1:** `LQ.AI — Autonomous flow: a single agent, fully audited`
- **subtitle:** `Step a single-agent session through its phases and watch the brakes fire`
- **doc link** (top-right): → `docs/LQVern/agentic-flow-alignment-guide.md` ("How aligned flows are built").
- **Honesty badge** (required until §3.10 flips to shipped): a pill in the header reading **`PLANNED — M4 capability`** in `--partial` (amber), with hover text: *"This illustrates the M4 Autonomous Layer's design. It is not running in your deployment yet."* M4-D2 removes the badge when §3.10 ships.

### 2.2 The model: one session, five phases, one chokepoint

The preview renders a **single `autonomous_session`** walking the closed phase enum left-to-right:

```
intake  →  analysis  →  drafting  →  ethics_review  →  delivery
```

Under each phase, show the **tool grants** for that phase (R6) as chips — exactly the `PHASE_GRANTS` map from the alignment guide / M4-A2:

| Phase | Granted intents (chips) |
|---|---|
| `intake` | `retrieve_chunks` |
| `analysis` | `retrieve_chunks`, `run_skill`, `run_playbook` |
| `drafting` | `run_skill`, `emit_finding`, `propose_memory` |
| `ethics_review` | `emit_finding` *(retrieval/skills visibly stripped here)* |
| `delivery` | `notify` |

A chip that is **not** granted in the current phase renders dimmed (`--pending`); attempting it (see Scenario C) flashes it red (`--unverified`).

### 2.3 The chokepoint panel

A central panel depicts the single `guarded_tool_call` chokepoint every tool routes through, with the four ordered checks (mirroring the alignment-guide pseudo-code) lighting up in sequence for each call:

1. **R5 — read `halt_state`** (before the call)
2. **R6 — phase grants this intent?**
3. **R4 — projected cost ≤ `max_cost_usd`?**
4. **open OTel span + write audit row → run tool → record cost + outcome**

Each check renders pass (`--verified`), block (`--unverified`), or pending (`--pending`). The teaching emphasis: **there is exactly one chokepoint** — a label states "every tool call goes through here; a new tool gets the brakes for free and cannot route around them."

### 2.4 Controls

A control strip lets the user drive the session:

- **Step / Auto-run** — advance the session one tool call at a time, or play it through.
- **Cost cap slider** — `max_cost_usd` (default **$5**, the `gateway.yaml` default). Lowering it mid-run triggers Scenario A.
- **Halt button** ("the red button") — sets `halt_state = halt_requested`; the next step shows the session stopping (Scenario B).
- **Force ungranted call** — attempt a tool not granted in the current phase (Scenario C).
- **Idle toggle** — simulate inactivity past `idle_halt_minutes` (default **5**) → `running → paused → halted` (Scenario D).

### 2.5 The four brake scenarios (the demonstrable bar — DE-293)

The playground must let the user trigger each brake and see the outcome + the resulting audit/span attribute. These mirror the M4-A3 acceptance tests one-to-one, so the public explainer and the test suite tell the same story:

- **Scenario A — R4 cost cap.** Projected cost exceeds `max_cost_usd` → session sets `cost_cap_reached = true`, `halt_state = halted`, **preserves the partial result**, emits `autonomous.outcome = "cost_cap_reached"`. Panel shows the partial findings retained.
- **Scenario B — R5 external halt.** User hits Halt mid-run → the **next** `guarded_tool_call` reads `halt_requested`, transitions to `halted`, emits `autonomous.outcome = "external_halt"`. Emphasis: the halt is honored at the next tool boundary, not mid-tool.
- **Scenario C — R6 phase-grant.** A `retrieve_chunks` attempt during `ethics_review` (granted only at `intake`/`analysis`) → blocked, `autonomous.outcome = "tool_not_granted"`, audited. The stripped chip flashes red.
- **Scenario D — R5 idle timeout.** Inactivity past `idle_halt_minutes` → `running → paused → halted` (reason `idle_timeout`), shown across two "watchdog ticks."

### 2.6 The OTel + audit side-panel (the "counts only" guarantee)

A collapsible side-panel shows, for the current step, the **`autonomous.tool_call` span attributes** and the **audit row** being written — using the exact attribute names from the alignment guide / M4-A3:

- Span attributes shown: `autonomous.session_id`, `autonomous.phase`, `autonomous.tool` (the intent), `autonomous.halt_state`, `autonomous.cost_usd`, `autonomous.outcome`.
- Audit action shown: one of the closed set `autonomous_session.{started, phase_transition, tool_call, halted, cost_cap_reached, completed}`.
- **The privacy teaching point** (the heart of D6): a side-by-side, mirroring `otel-eval.html`'s anonymization panel — **what DOES appear** (intent label, phase, cost, outcome, counts, IDs) vs **what NEVER appears** (the document text, raw PERSON / MATTER_NUMBER values, prompt bodies, model responses). State explicitly that this extends the M2 anonymization-span guarantee enforced by `gateway/tests/test_anonymization_observability.py`.

### 2.7 The receipt (the payoff)

When the session reaches a terminal state (`completed` / `halted` / `cost_cap_reached`), render the **per-session receipt** — the artifact that delivers the headline teaching point. It lists, per tool call: the phase, the intent, the inputs *seen* (counts/types/IDs only), the cost, the outcome, and the gates passed; then the phase-transition trail and the terminal state + reason. A caption: *"This is what the user sees afterward — exactly what the agent did and why. No raw document content; every action accounted for."* The receipt shape mirrors `api/app/autonomous/receipt.py::build_receipt` (M4-A4).

---

## 3. How-it-Works page wiring

Add a new section to `web/src/routes/lq-ai/learn/how/+page.svelte`, following the established pattern (`<section class="lq-how-section" data-testid="lq-ai-learn-how-section-autonomous-flow">` → `<h2 class="lq-section-h">N. Title</h2>` → a 2–3 sentence intro → the embedded playground iframe with `data-testid="learn-playground-autonomous-flow"` → a doc-link footer).

- **Section title:** `N. Autonomy you can audit: the Autonomous flow` (the handoff anticipated **§13**, with otel-eval at §11 and test-landscape becoming §12 once its wiring lands — **verify the live section numbering at build time**; the page has grown since the handoff, so count the existing sections rather than hard-coding 13).
- **Intro copy (2–3 sentences):** "The Autonomous Layer (M4) runs a single agent on your behalf — on a schedule, or when documents arrive — without you watching each step. Because no human approves each action, the agent runs through declared phases behind one brake-checked chokepoint, and every run produces an auditable receipt. Step through a session below and trip each brake yourself." Mark the section's status as **planned M4 capability** in the intro until §3.10 ships.
- **Doc-link footer:** → the alignment guide + ADR 0013.

---

## 4. Build page wiring

Add an **"anatomy of an aligned agentic flow"** element to `web/src/routes/lq-ai/learn/build/+page.svelte`:

- A compact diagram/callout naming the four obligations a contributor's flow must satisfy (the alignment-guide §7 checklist, condensed): **(1)** every tool through the single `guarded_tool_call`; **(2)** R4/R5/R6 checked *before* the tool runs; **(3)** `autonomous.session` + `autonomous.tool_call` spans + closed-enum audit, counts/types only; **(4)** a user-readable receipt.
- A prominent link to [`docs/LQVern/agentic-flow-alignment-guide.md`](agentic-flow-alignment-guide.md) as the authoritative how-to.
- **Gotcha for the implementer:** `.gitignore` has a `build/` entry that **shadows** `web/src/routes/lq-ai/learn/build/` — edits to that file need `git add -f` (memory / handoff §5).

---

## 5. Updates to existing visualizations

Two shipped playgrounds gain the new autonomous node so the architecture story stays current:

### 5.1 `web/static/learn/playgrounds/system-architecture.html`

- Add the **`api/app/autonomous`** executor as a node on the **arq-worker** (it shares the worker with the playbook/tabular/ingest jobs — show it as another job on the same worker process, not a new service).
- Add its data stores: the five tables (`autonomous_sessions`, `autonomous_schedules`, `autonomous_watches`, `autonomous_memory`, `precedent_entries`) under Postgres.
- Show the **trigger edges**: the ingest pipeline → `autonomous_session_job` (the watch direct-enqueue, Decision M4-7) and the arq cron → the schedule dispatcher.
- Reinforce that **inference still flows through the gateway** (no new provider edge from `api/app/autonomous` — the executor calls the gateway exactly as playbooks do).

### 5.2 `web/static/learn/playgrounds/data-residency.html`

- Add the five autonomous tables to the **"stays in your Postgres"** column (per-user memory, precedents, session receipts never leave the deployment).
- Show that autonomous inference takes the **same gateway anonymization path** as chat — so the data-residency story for an autonomous run is identical to an interactive one (this is *why* the executor routes through the gateway).
- No new external destination is introduced by the autonomous layer (email notification, if SMTP is configured, is the one new egress — depict it honestly as operator-configured + off by default).

---

## 6. Honesty requirements (verification gates for M4-D1)

- The playground carries the **`PLANNED — M4 capability`** badge (§2.1) until the M4-D2 PR flips §3.10 to shipped; M4-D2 removes it in the same PR that flips the status.
- Every span attribute, audit action, phase name, tool intent, and receipt field shown in the playground **matches the names emitted by shipped code** (M4-A3 / M4-A4). No invented attributes. If the implementation renames something, the playground updates in the same PR (the alignment-guide §7 checklist makes this a PR gate).
- The "what NEVER appears" privacy panel (§2.6) is not decorative — it states the actual guarantee and names the test that enforces it.

---

## 7. Acceptance (M4-D1 done-when)

- `web/static/learn/playgrounds/autonomous-flow.html` renders standalone (offline) and is reachable from `/lq-ai/learn`.
- The four brake scenarios (A–D) are each triggerable and show the correct outcome + the matching span attribute + audit action.
- The receipt renders with **no raw entity values**.
- The new how-page section embeds the playground; the build-page anatomy element links the alignment guide.
- `system-architecture.html` + `data-residency.html` show the `api/app/autonomous` arq node + its five stores + the gateway inference path.
- `cd web && npm run check` passes; the honesty badge is present (pre-ship).

---

*Companion to [`docs/M4-IMPLEMENTATION-PLAN.md`](../M4-IMPLEMENTATION-PLAN.md) (Task M4-D1 builds this). Design pinned in [ADR 0013](../adr/0013-autonomous-layer-design-influences.md); contributor contract in [`agentic-flow-alignment-guide.md`](agentic-flow-alignment-guide.md).*
