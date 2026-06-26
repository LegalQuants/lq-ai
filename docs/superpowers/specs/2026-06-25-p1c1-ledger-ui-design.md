# P1-C1 — Matter/chat-scoped Citation Ledger UI (design)

**Date:** 2026-06-25
**Milestone:** Fiduciary-grade agentic legal work — Phase 1 (WS-C)
**Branch:** `feat/fiduciary-p1c1-ledger-ui`
**Pins:** [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D3 (fiduciary-grade gate), D4 (one-click trace). Consumes the merged **P1-A3** (`GET /api/v1/chats/{chat_id}/ledger`, #223) + **P1-B1** (`gates[]` in that response, #225).
**Security review:** not required (frontend `web/` only; no gateway, no auth/authz/crypto change).

## Problem

The Citation Ledger is populated and readable (`GET /chats/{chat_id}/ledger` → `{chat_id, entries[], gates[]}`), but nothing renders it. The milestone's whole point — *transparency you can demonstrate, not assert* (ADR 0018 D4: one click from a cited assertion to the exact source and passage read, with verification status visible) — is invisible until there's UI. P1-C1 builds that surface. It does **not** add backend behavior; it consumes what A3/B1 already return.

## Decisions (maintainer-approved 2026-06-25)

- **Per-message inline pill + panel** (not a chat-level drawer). A fiduciary badge on each assistant turn opens a panel showing that turn's ledger entries + verdict. This reuses the established `MessageBubble` lazy-fetch pattern (`loadCitations`/`loadSources`) and the existing 5-state citation rendering, and is turn-scoped to match the `?message_id` filter. A chat-level rollup drawer is deferred (a later DE if wanted).
- **Additive, not a replacement.** The existing `M2Citations` (inline citation chips) and `ToolSourcesPanel` ("sources consulted") stay. The ledger is the *unified one-click-trace* view alongside them; v1 does not rip out working components.
- **Reuse the 5-state map.** Ledger entry `verification_status` maps onto the existing `CitationRenderState` (`web/src/lib/lq-ai/citations/state.ts`): `exact_match`/`tolerant_match` → `verified-exact`/`verified-tolerant` (green, "verbatim"); `paraphrase_judge`/`ensemble_strict`/`ensemble_majority` → `verified-paraphrase` (amber, "supported"); `unverified`/`failed`/`provenance` → `unverified`-style (gray). No new states.
- **Fiduciary badge = `TrustPill`.** The three gate verdicts map to `TrustPill` tones: `fiduciary_grade` → sage; `supported_only` → amber; `flagged` → red. Each carries an `InfoTip`.

## Design

### Component 1 — API client (`web/src/lib/lq-ai/api/ledger.ts`)

Mirrors `citations.ts` (the `apiRequest` wrapper handles auth + 401-refresh + typed errors):

```ts
import { apiRequest } from './client';
import type { ChatLedger } from '../types';

export async function getChatLedger(chatId: string, messageId?: string): Promise<ChatLedger> {
  const q = messageId ? `?message_id=${encodeURIComponent(messageId)}` : '';
  return apiRequest<ChatLedger>(`/chats/${encodeURIComponent(chatId)}/ledger${q}`);
}
```

Re-exported as `ledgerApi` from `web/src/lib/lq-ai/api/index.ts`. Types in `web/src/lib/lq-ai/types` (or a `types.ts` sibling):

```ts
export interface LedgerPassage { text: string; offset_start: number; offset_end: number; page?: number | null; }
export interface LedgerSource {
  kind: string; // kb_document | caselaw | mcp ...
  source_file_id?: string; opinion_id?: number; cluster_id?: number;
  label?: string | null; subtitle?: string | null; url?: string | null;
  external_ref?: string | null; tool?: string | null;
  passages?: LedgerPassage[];
}
export interface LedgerEntry {
  id: string; message_id: string; source_kind: string;
  verification_status: string; confidence: number | null;
  provider: string | null; retrieved_at: string | null;
  treatment_id: string | null; created_at: string; source: LedgerSource;
}
export interface LedgerGate {
  message_id: string; gate_status: 'fiduciary_grade' | 'supported_only' | 'flagged';
  pass_count: number; supported_count: number; fail_count: number;
  total_assertions: number; confidence: number | null; created_at: string;
}
export interface ChatLedger { chat_id: string; entries: LedgerEntry[]; gates: LedgerGate[]; }
```

### Component 2 — Gate→badge + status→state mapping (`web/src/lib/lq-ai/citations/ledger-state.ts`)

Two pure functions (unit-testable, no DOM):

```ts
import type { CitationRenderState } from './state';

export function ledgerEntryState(status: string): CitationRenderState {
  switch (status) {
    case 'exact_match': return 'verified-exact';
    case 'tolerant_match': return 'verified-tolerant';
    case 'paraphrase_judge':
    case 'ensemble_strict':
    case 'ensemble_majority': return 'verified-paraphrase';
    default: return 'unverified'; // unverified | failed | provenance | unknown
  }
}

export interface GateBadge { tone: 'sage' | 'amber' | 'red'; label: string; tip: string; }
export function gateBadge(gate: LedgerGate | undefined): GateBadge | null {
  if (!gate) return null;
  switch (gate.gate_status) {
    case 'fiduciary_grade':
      return { tone: 'sage', label: 'Fiduciary-grade',
        tip: `Every cited assertion (${gate.pass_count}) is verified verbatim against its source.` };
    case 'supported_only':
      return { tone: 'amber', label: 'Supported — not all verbatim',
        tip: `${gate.supported_count} assertion(s) are supported (paraphrase), not verbatim; none failed.` };
    case 'flagged':
      return { tone: 'red', label: 'Unverified claims flagged',
        tip: `${gate.fail_count} cited assertion(s) could not be verified.` };
  }
}
```

Reusing `CitationRenderState` means the entry chips pick up the existing colors/labels/tooltips for free.

### Component 3 — `LedgerEntryRow.svelte`

One row per `LedgerEntry`: a state chip (color from `ledgerEntryState` → the existing palette), the source identity (file name for `kb_document`, "Cluster N / opinion N" for `caselaw`, label/url for `mcp`), and — when present — the passage(s) read shown as quoted text with a char-offset caption (`chars 1240–1310`). The passage text *is* the one-click trace (the chat owner is entitled to it). Provenance-only entries (no `passages`) render identity + a "consulted" tag, no quote.

### Component 4 — `CitationLedgerPanel.svelte`

Follows the `TierDetailsPanel` modal pattern (`fixed inset-0 z-50` backdrop, focus-trap, Esc-to-close). Header: the gate verdict badge + a one-line count summary (`2 verbatim · 1 supported · 0 unverified`). Body: the list of `LedgerEntryRow`. Footer/empty: "No sources were brought into context for this turn" when `entries` is empty.

### Component 5 — `MessageBubble.svelte` wiring

A new lazy-fetch block alongside `loadCitations`/`loadSources`, fired once per assistant message after streaming completes (`!isStreaming && message.id && message.chat_id && fetchedLedger === null && !ledgerFetchInflight`):

```ts
fetchedLedger = await ledgerApi.getChatLedger(chatId, messageId); // {entries, gates}
```

404/empty → `fetchedLedger = { chat_id, entries: [], gates: [] }` (degrade silently, no pill). When `entries.length > 0` **or** a gate exists, render the **fiduciary badge** (`TrustPill` with `gateBadge(gates[0])`) in the message's pill row; `onClick` opens `CitationLedgerPanel`. The badge is the entry point; the panel is the trace.

## Error handling

- 404 / network error → no ledger pill (matches how citations/sources degrade today); never blocks the bubble.
- A turn with a gate but zero entries (e.g. a chit-chat `fiduciary_grade`/`total_assertions=0`) → render the badge, panel shows the empty-state line (the verdict is still meaningful: "no cited assertions").
- Unknown `source_kind` / `verification_status` → entry renders with the `unverified` fallback state and its raw identity; never throws.

## Testing

- **Vitest (unit):** `getChatLedger` builds the right path (with/without `messageId`); `ledgerEntryState` maps every status (incl. unknown → `unverified`); `gateBadge` returns the right tone/label for all three verdicts + `null` for undefined.
- **Component (Vitest + Testing Library or Svelte harness):** `CitationLedgerPanel` renders the correct badge + counts per verdict; `LedgerEntryRow` shows passage + offsets for quote kinds and the "consulted" tag for provenance; empty-entries shows the empty line.
- **Playwright (optional, e2e):** a seeded chat whose assistant turn has a ledger → the fiduciary badge appears; clicking opens the panel with the entries; the verbatim vs supported chips are visually distinct.
- Gates: `npm run lint` (ESLint/Prettier) + `svelte-check` + Vitest. **Rebuild the `web` container** before manual verification (it serves a prebuilt static bundle — no HMR).

## Acceptance criteria

1. Each assistant turn with a ledger shows a fiduciary badge reflecting its gate verdict (sage/amber/red); clicking opens a panel listing the turn's entries, each resolved to source identity + passage(s) read + a verification-state chip.
2. The verbatim (green) vs supported (amber) vs unverified (gray/red) distinction is visible and reuses the existing 5-state rendering — no new state machine.
3. A turn with no ledger renders no badge; a turn with a gate but no entries renders the badge + an empty-state panel; nothing ever throws on unknown kinds/statuses.
4. The existing `M2Citations` / `ToolSourcesPanel` are unchanged (additive).
5. `svelte-check` + lint clean; Vitest unit + component tests green.

## Out of scope / sequencing

- **Chat-level / matter-level ledger rollup drawer** — deferred (file a DE if wanted); v1 is per-turn.
- **Derived treatment** (`treatment_id`) rendering — WS-G; null today, ignored by the row.
- **The richer caselaw SUPPORTED/FAIL data** the amber/red chips will show for caselaw arrives with **P1-B1b**; C1 renders whatever statuses the ledger contains, so it works today (KB verbatim + provenance) and gets richer automatically once B1b lands.
