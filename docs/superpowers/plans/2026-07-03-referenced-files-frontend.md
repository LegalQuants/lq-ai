# Referenced Files in Chat — Frontend (referenced-files Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user reference matter documents from the chat composer — inline `@`-mention popover + multi-select document picker — sending `referenced_file_ids` on the message so answers come back with verified, deep-linkable citations (backend channel already shipped, ADR 0022).

**Architecture:** One authoritative `referencedFiles` array in `ChatPanel.svelte` (deduped, cap 16), fed by both affordances, rendered as a removable chips row, sent as `referenced_file_ids`, cleared on successful send. The referenceable list is loaded client-side from `GET /projects/{id}` → `attached_knowledge_base_ids` → `GET /knowledge-bases/{kb_id}/files` (exactly the set the backend validates; no new backend surface). The `@`-mention clones the shipped slash-command machinery (`detectSlashAt` + `SlashPopover`); the picker follows the `AttachKBModal` checkbox-set + `SkillPicker` search patterns.

**Tech Stack:** SvelteKit (Svelte 4, this is an OpenWebUI fork — no React, no runes), TypeScript, Vitest, Cypress.

## Global Constraints

- Repo: `/Users/abc/projs/lqAI/lq-ai`, branch `feat/referenced-files-referenced-file-ids` (frontend rides the same branch as the shipped backend; single referenced-files PR).
- All new code under `web/src/lib/lq-ai/`. New files require TypeScript.
- **No `@testing-library/svelte`** (not installed). Convention: export pure helpers from `<script context="module">` blocks and unit-test those; component wiring is covered by Cypress. See `web/src/lib/lq-ai/__tests__/ChatPanel-slash-detect.test.ts` header.
- Callback props (`onSelect`, `onDismiss`, …), NOT `createEventDispatcher` — matches `SlashPopover`/`AttachKBModal`.
- Design tokens: `--lq-*` custom properties with fallbacks, exactly as `SlashPopover.svelte` does. `data-testid` values prefixed `lq-ai-`.
- No new npm dependencies.
- Cap constant `MESSAGE_REFERENCED_FILES_MAX = 16` — must mirror backend `MESSAGE_REFERENCED_FILES_MAX_LEN` (`api/app/schemas/chats.py`).
- Unit tests: `cd web && npx vitest run src/lib/lq-ai/__tests__/<file>.test.ts`.
- Type gate: `cd web && npm run check:lq-ai` (svelte-check with the lq-ai tsconfig).
- Format/lint touched files: `cd web && npx prettier --plugin-search-dir --write <files> && npx eslint <files>`.
- Commits: imperative mood, `git commit -s`.
- Dev-stack note (manual verification only): the `web` container serves a static bundle — rebuild `web` before checking the UI in the running stack. Never `docker compose down -v`.

## File Structure

- `web/src/lib/lq-ai/files/referenceable.ts` — NEW: referenceable-set domain module (types, cap, merge/dedupe, filter, add/remove, loader).
- `web/src/lib/lq-ai/components/MentionPopover.svelte` — NEW: `@`-mention typeahead listbox (clone of `SlashPopover.svelte`, list passed in, client-side filtering).
- `web/src/lib/lq-ai/components/ReferencedFilesChips.svelte` — NEW: chips row above composer.
- `web/src/lib/lq-ai/components/FilePickerDropdown.svelte` — NEW: multi-select checkbox dropdown with search.
- `web/src/lib/lq-ai/components/ChatPanel.svelte` — MODIFY: mention detection helpers (module block), state + wiring, send payload, template mounts.
- `web/src/lib/lq-ai/components/MessageBubble.svelte` — MODIFY: compact "Referenced:" row on user bubbles.
- `web/src/lib/lq-ai/types.ts` — MODIFY: `MessageCreate.referenced_file_ids`, `MessagePostResponse.applied_referenced_file_ids`, `MessageCompleteFrame.applied_referenced_file_ids`, `Message.referenced_files`.
- Tests: `web/src/lib/lq-ai/__tests__/referenceable.test.ts`, `__tests__/ChatPanel-mention-detect.test.ts`, `__tests__/MentionPopover.test.ts`, `__tests__/FilePickerDropdown.test.ts`; `web/cypress/e2e/referenced-files-referenced-files.cy.ts`.
- Docs: `docs/PRD.md` §3.1 + §9 (referenced-files entry).

---

### Task 1: Referenceable-files domain module

**Files:**
- Create: `web/src/lib/lq-ai/files/referenceable.ts`
- Test: `web/src/lib/lq-ai/__tests__/referenceable.test.ts`

**Interfaces:**
- Consumes: `getProject` (`../api/projects`), `listKnowledgeBaseFiles` (`../api/knowledgeBases`), `KnowledgeBaseFile` type (`../types`).
- Produces (later tasks import all of these from `$lib/lq-ai/files/referenceable`):
  - `MESSAGE_REFERENCED_FILES_MAX: number` (= 16)
  - `interface ReferencedFile { id: string; filename: string; ready: boolean }`
  - `interface ReferenceableLoad { files: ReferencedFile[]; failedKbCount: number }`
  - `toReferencedFile(row: KnowledgeBaseFile): ReferencedFile`
  - `mergeKbFileLists(lists: KnowledgeBaseFile[][]): ReferencedFile[]`
  - `filterReferenceable(files: ReferencedFile[], query: string): ReferencedFile[]`
  - `type AddResult = { added: true; list: ReferencedFile[] } | { added: false; reason: 'duplicate' | 'cap' | 'not-ready' }`
  - `addReferencedFile(list: ReferencedFile[], file: ReferencedFile, cap?: number): AddResult`
  - `removeReferencedFile(list: ReferencedFile[], id: string): ReferencedFile[]`
  - `loadReferenceableFiles(projectId: string): Promise<ReferenceableLoad>`

- [ ] **Step 1: Write the failing test**

`web/src/lib/lq-ai/__tests__/referenceable.test.ts`:

```ts
/**
 * referenced-files Phase 2 — pure logic of the referenceable-files set.
 * loadReferenceableFiles is NOT tested here (it is a thin fetch
 * composition; Cypress covers it end-to-end with stubbed routes).
 */
import { describe, expect, it } from 'vitest';

import {
	MESSAGE_REFERENCED_FILES_MAX,
	addReferencedFile,
	filterReferenceable,
	mergeKbFileLists,
	removeReferencedFile,
	toReferencedFile,
	type ReferencedFile
} from '../files/referenceable';
import type { KnowledgeBaseFile } from '../types';

function kbFile(overrides: Partial<KnowledgeBaseFile> & { id: string }): KnowledgeBaseFile {
	return {
		owner_id: 'u1',
		filename: `${overrides.id}.pdf`,
		mime_type: 'application/pdf',
		size_bytes: 100,
		hash_sha256: 'x',
		ingestion_status: 'ready',
		created_at: '2026-07-01T00:00:00Z',
		attached_at: '2026-07-01T00:00:00Z',
		...overrides
	} as KnowledgeBaseFile;
}

function ref(id: string, filename = `${id}.pdf`, ready = true): ReferencedFile {
	return { id, filename, ready };
}

describe('toReferencedFile', () => {
	it('marks ready exactly when ingestion_status === "ready"', () => {
		expect(toReferencedFile(kbFile({ id: 'a' })).ready).toBe(true);
		expect(toReferencedFile(kbFile({ id: 'b', ingestion_status: 'processing' })).ready).toBe(false);
		expect(toReferencedFile(kbFile({ id: 'c', ingestion_status: 'failed' })).ready).toBe(false);
	});
});

describe('mergeKbFileLists', () => {
	it('dedupes a file present in several KBs (first occurrence wins)', () => {
		const merged = mergeKbFileLists([
			[kbFile({ id: 'a', filename: 'alpha.pdf' })],
			[kbFile({ id: 'a', filename: 'alpha.pdf' }), kbFile({ id: 'b', filename: 'beta.pdf' })]
		]);
		expect(merged.map((f) => f.id)).toEqual(['a', 'b']);
	});

	it('sorts by filename', () => {
		const merged = mergeKbFileLists([
			[kbFile({ id: '1', filename: 'zeta.pdf' }), kbFile({ id: '2', filename: 'alpha.pdf' })]
		]);
		expect(merged.map((f) => f.filename)).toEqual(['alpha.pdf', 'zeta.pdf']);
	});

	it('returns [] for no KBs', () => {
		expect(mergeKbFileLists([])).toEqual([]);
	});
});

describe('filterReferenceable', () => {
	const files = [ref('1', 'Master Agreement.pdf'), ref('2', 'exhibit-a.pdf')];

	it('returns everything for an empty/whitespace query', () => {
		expect(filterReferenceable(files, '')).toEqual(files);
		expect(filterReferenceable(files, '  ')).toEqual(files);
	});

	it('matches case-insensitive substrings', () => {
		expect(filterReferenceable(files, 'master')).toEqual([files[0]]);
		expect(filterReferenceable(files, 'EXHIBIT')).toEqual([files[1]]);
	});

	it('returns [] when nothing matches', () => {
		expect(filterReferenceable(files, 'zzz')).toEqual([]);
	});
});

describe('addReferencedFile', () => {
	it('adds a ready file', () => {
		const r = addReferencedFile([], ref('1'));
		expect(r).toEqual({ added: true, list: [ref('1')] });
	});

	it('rejects a duplicate id', () => {
		const r = addReferencedFile([ref('1')], ref('1'));
		expect(r).toEqual({ added: false, reason: 'duplicate' });
	});

	it('rejects a non-ready file', () => {
		const r = addReferencedFile([], ref('1', '1.pdf', false));
		expect(r).toEqual({ added: false, reason: 'not-ready' });
	});

	it('rejects past the cap', () => {
		const full = Array.from({ length: MESSAGE_REFERENCED_FILES_MAX }, (_, i) => ref(`f${i}`));
		const r = addReferencedFile(full, ref('overflow'));
		expect(r).toEqual({ added: false, reason: 'cap' });
	});

	it('does not mutate the input list', () => {
		const list = [ref('1')];
		addReferencedFile(list, ref('2'));
		expect(list).toEqual([ref('1')]);
	});
});

describe('removeReferencedFile', () => {
	it('removes by id and leaves others', () => {
		expect(removeReferencedFile([ref('1'), ref('2')], '1')).toEqual([ref('2')]);
	});

	it('is a no-op for an unknown id', () => {
		expect(removeReferencedFile([ref('1')], 'nope')).toEqual([ref('1')]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/referenceable.test.ts`
Expected: FAIL — cannot resolve `../files/referenceable`.

- [ ] **Step 3: Write the module**

`web/src/lib/lq-ai/files/referenceable.ts`:

```ts
/**
 * referenced-files Phase 2 — the referenceable-files set for the chat composer.
 *
 * "Referenceable" = exactly what the backend accepts in
 * `referenced_file_ids` (ADR 0022, KB-only MVP + matter scope): files in
 * Knowledge Bases attached to the chat's project. Loading walks
 * GET /projects/{id} → attached_knowledge_base_ids →
 * GET /knowledge-bases/{kb_id}/files and merges/dedupes (a file may sit
 * in several matter KBs). There is deliberately NO GET /files list call
 * here — that route does not exist (DE-296 unbuilt).
 *
 * `ready` mirrors the backend's ingestion_status === 'ready' send gate:
 * non-ready files render disabled ("Preparing…") and are never
 * selectable — fail-restrictive made visible (P4), so the UI can never
 * assemble a set the backend would 404.
 */
import { listKnowledgeBaseFiles } from '../api/knowledgeBases';
import { getProject } from '../api/projects';
import type { KnowledgeBaseFile } from '../types';

/** Mirrors MESSAGE_REFERENCED_FILES_MAX_LEN (api/app/schemas/chats.py). */
export const MESSAGE_REFERENCED_FILES_MAX = 16;

export interface ReferencedFile {
	id: string;
	filename: string;
	ready: boolean;
}

export interface ReferenceableLoad {
	files: ReferencedFile[];
	/** KBs whose file listing failed; the union of the rest still loads. */
	failedKbCount: number;
}

export function toReferencedFile(row: KnowledgeBaseFile): ReferencedFile {
	return {
		id: row.id,
		filename: row.filename,
		ready: row.ingestion_status === 'ready'
	};
}

export function mergeKbFileLists(lists: KnowledgeBaseFile[][]): ReferencedFile[] {
	const byId = new Map<string, ReferencedFile>();
	for (const list of lists) {
		for (const row of list) {
			// Same File row can be attached to several KBs; its
			// ingestion_status is file-level, so first occurrence wins.
			if (!byId.has(row.id)) byId.set(row.id, toReferencedFile(row));
		}
	}
	return [...byId.values()].sort((a, b) => a.filename.localeCompare(b.filename));
}

export function filterReferenceable(files: ReferencedFile[], query: string): ReferencedFile[] {
	const q = query.trim().toLowerCase();
	if (!q) return files;
	return files.filter((f) => f.filename.toLowerCase().includes(q));
}

export type AddResult =
	| { added: true; list: ReferencedFile[] }
	| { added: false; reason: 'duplicate' | 'cap' | 'not-ready' };

export function addReferencedFile(
	list: ReferencedFile[],
	file: ReferencedFile,
	cap: number = MESSAGE_REFERENCED_FILES_MAX
): AddResult {
	if (!file.ready) return { added: false, reason: 'not-ready' };
	if (list.some((f) => f.id === file.id)) return { added: false, reason: 'duplicate' };
	if (list.length >= cap) return { added: false, reason: 'cap' };
	return { added: true, list: [...list, file] };
}

export function removeReferencedFile(list: ReferencedFile[], id: string): ReferencedFile[] {
	return list.filter((f) => f.id !== id);
}

/**
 * Load the referenceable set for a project. A single KB listing failure
 * degrades to the union of the KBs that did load (surfaced via
 * `failedKbCount` as a non-blocking note); a getProject failure
 * propagates — with no project there is no referenceable set at all.
 */
export async function loadReferenceableFiles(projectId: string): Promise<ReferenceableLoad> {
	const project = await getProject(projectId);
	const kbIds = project.attached_knowledge_base_ids ?? [];
	const settled = await Promise.allSettled(kbIds.map((id) => listKnowledgeBaseFiles(id)));
	const lists = settled
		.filter((s): s is PromiseFulfilledResult<KnowledgeBaseFile[]> => s.status === 'fulfilled')
		.map((s) => s.value);
	return { files: mergeKbFileLists(lists), failedKbCount: settled.length - lists.length };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/referenceable.test.ts`
Expected: PASS (all tests).

- [ ] **Step 5: Format, lint, commit**

```bash
cd web && npx prettier --plugin-search-dir --write src/lib/lq-ai/files/referenceable.ts src/lib/lq-ai/__tests__/referenceable.test.ts && npx eslint src/lib/lq-ai/files/referenceable.ts src/lib/lq-ai/__tests__/referenceable.test.ts
cd /Users/abc/projs/lqAI/lq-ai && git add web/src/lib/lq-ai/files/referenceable.ts web/src/lib/lq-ai/__tests__/referenceable.test.ts
git commit -s -m "feat(web): add referenceable-files domain module for composer references" -m "Refs referenced-files"
```

---

### Task 2: Mention detection + splice helpers (ChatPanel module block)

**Files:**
- Modify: `web/src/lib/lq-ai/components/ChatPanel.svelte` — the `<script context="module">` block at the top (currently lines 1–43, holding `detectSlashAt`). Append the new helpers INSIDE that block; do not touch `detectSlashAt`/`isAtLineStart`.
- Test: `web/src/lib/lq-ai/__tests__/ChatPanel-mention-detect.test.ts`

**Interfaces:**
- Produces (importable from `'../components/ChatPanel.svelte'`):
  - `type MentionDetection = { open: false } | { open: true; query: string; atIndex: number }`
  - `detectMentionAt(text: string, caret: number): MentionDetection`
  - `completeMentionAt(text: string, atIndex: number, queryLength: number, filename: string): string`

**Contract:** the popover opens when an `@` sits at a word start (position 0 or preceded by whitespace, including newline) and everything between the `@` and the caret matches `[^\s@]` (filenames: letters any case, digits, dots, hyphens, underscores; a space terminates the query). `a@b` (email-like) never opens. Unlike the slash, mid-line triggers ARE allowed.

- [ ] **Step 1: Write the failing test**

`web/src/lib/lq-ai/__tests__/ChatPanel-mention-detect.test.ts`:

```ts
/**
 * referenced-files Phase 2 — @-mention detection + splice helpers. Same convention
 * as ChatPanel-slash-detect.test.ts: pure module-scope helpers exported
 * from ChatPanel.svelte, tested without mounting the component.
 */
import { describe, expect, it } from 'vitest';

import { completeMentionAt, detectMentionAt } from '../components/ChatPanel.svelte';

describe('detectMentionAt', () => {
	it('does not open when caret is at position 0', () => {
		expect(detectMentionAt('', 0)).toEqual({ open: false });
		expect(detectMentionAt('@foo', 0)).toEqual({ open: false });
	});

	it('opens with empty query when text is just "@"', () => {
		expect(detectMentionAt('@', 1)).toEqual({ open: true, query: '', atIndex: 0 });
	});

	it('opens at start of textarea with a query', () => {
		expect(detectMentionAt('@nda', 4)).toEqual({ open: true, query: 'nda', atIndex: 0 });
	});

	it('opens mid-line after a space (unlike slash detection)', () => {
		expect(detectMentionAt('summarize @exh', 14)).toEqual({
			open: true,
			query: 'exh',
			atIndex: 10
		});
	});

	it('opens after a newline', () => {
		expect(detectMentionAt('line one\n@doc', 13)).toEqual({
			open: true,
			query: 'doc',
			atIndex: 9
		});
	});

	it('does NOT open for email-like text (@ not at word start)', () => {
		expect(detectMentionAt('a@b', 3)).toEqual({ open: false });
		expect(detectMentionAt('user@example.com', 16)).toEqual({ open: false });
	});

	it('accepts dots, hyphens, underscores, uppercase in the query', () => {
		expect(detectMentionAt('@Master-Agreement_v2.pdf', 25)).toEqual({
			open: true,
			query: 'Master-Agreement_v2.pdf',
			atIndex: 0
		});
	});

	it('closes when the query is interrupted by a space', () => {
		expect(detectMentionAt('@exh ibit', 9)).toEqual({ open: false });
	});

	it('does not open when the caret sits before the @', () => {
		expect(detectMentionAt('hi @doc', 2)).toEqual({ open: false });
	});

	it('does not treat @@ as a mention', () => {
		expect(detectMentionAt('@@', 2)).toEqual({ open: false });
	});
});

describe('completeMentionAt', () => {
	it('completes "@query" at the start of the text', () => {
		expect(completeMentionAt('@nda tell me', 0, 3, 'NDA-2024.pdf')).toBe('@NDA-2024.pdf tell me');
	});

	it('completes "@query" mid-text without doubling spaces', () => {
		expect(completeMentionAt('summarize @exh please', 10, 3, 'exhibit-a.pdf')).toBe(
			'summarize @exhibit-a.pdf please'
		);
	});

	it('appends a separating space at the end of the text', () => {
		expect(completeMentionAt('summarize @exh', 10, 3, 'exhibit-a.pdf')).toBe(
			'summarize @exhibit-a.pdf '
		);
	});

	it('completes a bare "@" (empty query)', () => {
		expect(completeMentionAt('hello @', 6, 0, 'a.pdf')).toBe('hello @a.pdf ');
	});

	it('keeps filenames containing spaces inline', () => {
		expect(completeMentionAt('@ber', 0, 3, 'BERGE SISAR.HL.2002.pdf')).toBe(
			'@BERGE SISAR.HL.2002.pdf '
		);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/ChatPanel-mention-detect.test.ts`
Expected: FAIL — `detectMentionAt` is not exported.

- [ ] **Step 3: Append the helpers to ChatPanel's module block**

Inside `<script context="module" lang="ts">` in `ChatPanel.svelte`, after `detectSlashAt` (before the closing `</script>` at line 43), add:

```ts
	/**
	 * referenced-files Phase 2 — @-mention detection for referenced files.
	 *
	 * Differs from detectSlashAt on purpose:
	 *   - Triggers ANYWHERE the `@` starts a word (position 0 or preceded
	 *     by whitespace), not only at line start — "summarize @exhibit-a"
	 *     is the core use case.
	 *   - Query char class is [^\s@] (filenames carry uppercase, dots,
	 *     underscores); a space terminates the candidate query.
	 *   - `a@b` / "user@example.com" never trigger (word-start guard).
	 */
	export type MentionDetection =
		| { open: false }
		| { open: true; query: string; atIndex: number };

	export function detectMentionAt(text: string, caret: number): MentionDetection {
		if (caret === 0) return { open: false };
		let scan = caret;
		while (scan > 0 && /[^\s@]/.test(text[scan - 1])) scan--;
		if (scan === 0 || text[scan - 1] !== '@') return { open: false };
		const atIndex = scan - 1;
		if (atIndex > 0 && !/\s/.test(text[atIndex - 1])) return { open: false };
		return { open: true, query: text.slice(atIndex + 1, caret), atIndex };
	}

	/**
	 * Complete a mention selection inline: replace the partial "@query"
	 * with "@<filename>" so the case name stays readable in the message
	 * AND rides into the sent content as part of the query (the
	 * referenced-files set carries the id; the text carries the meaning).
	 * A separating space is ensured after the completed mention so typing
	 * continues naturally and the popover does not immediately reopen.
	 */
	export function completeMentionAt(
		text: string,
		atIndex: number,
		queryLength: number,
		filename: string
	): string {
		const before = text.slice(0, atIndex);
		const after = text.slice(atIndex + 1 + queryLength);
		const sep = /^\s/.test(after) ? '' : ' ';
		return `${before}@${filename}${sep}${after}`;
	}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/ChatPanel-mention-detect.test.ts`
Expected: PASS. Also run `npx vitest run src/lib/lq-ai/__tests__/ChatPanel-slash-detect.test.ts` — must still PASS (no regression to the slash helpers).

- [ ] **Step 5: Format, lint, commit**

```bash
cd web && npx prettier --plugin-search-dir --write src/lib/lq-ai/components/ChatPanel.svelte src/lib/lq-ai/__tests__/ChatPanel-mention-detect.test.ts && npx eslint src/lib/lq-ai/components/ChatPanel.svelte src/lib/lq-ai/__tests__/ChatPanel-mention-detect.test.ts
cd /Users/abc/projs/lqAI/lq-ai && git add web/src/lib/lq-ai/components/ChatPanel.svelte web/src/lib/lq-ai/__tests__/ChatPanel-mention-detect.test.ts
git commit -s -m "feat(web): add @-mention detection + splice helpers to ChatPanel" -m "Refs referenced-files"
```

---

### Task 3: MentionPopover component

**Files:**
- Create: `web/src/lib/lq-ai/components/MentionPopover.svelte`
- Test: `web/src/lib/lq-ai/__tests__/MentionPopover.test.ts`

**Interfaces:**
- Consumes: `ReferencedFile`, `filterReferenceable` from `$lib/lq-ai/files/referenceable` (Task 1); `nextIndex` re-used from `./SlashPopover.svelte` (already exported from its module block).
- Produces:
  - Component props: `query: string`, `files: ReferencedFile[]` (the FULL referenceable list — filtering happens inside), `loading: boolean`, `error: string | null`, `onSelect: (file: ReferencedFile) => void`, `onDismiss: () => void`, `onRetry: () => void`.
  - Module-block helpers (unit-tested): `mentionResults(files, query)`, `mentionStateKind(state)`, `decideMentionKeyAction(key, state)`, and types `MentionPopoverState`, `MentionStateKind`, `MentionKeyAction`.

**Behavior notes:** results are the ready-only subset (`mentionResults` filters `f.ready`) — the mention flow is keyboard-driven and never offers a row that can't be selected; non-ready files remain visible (disabled) in the picker (Task 4) instead. Keyboard/mousedown/race semantics are identical to `SlashPopover`.

- [ ] **Step 1: Write the failing test**

`web/src/lib/lq-ai/__tests__/MentionPopover.test.ts`:

```ts
/**
 * referenced-files Phase 2 — MentionPopover pure helpers (module-block exports,
 * SlashPopover convention: no component mount).
 */
import { describe, expect, it } from 'vitest';

import {
	decideMentionKeyAction,
	mentionResults,
	mentionStateKind,
	type MentionPopoverState
} from '../components/MentionPopover.svelte';
import type { ReferencedFile } from '../files/referenceable';

function ref(id: string, filename = `${id}.pdf`, ready = true): ReferencedFile {
	return { id, filename, ready };
}

function state(overrides: Partial<MentionPopoverState> = {}): MentionPopoverState {
	return { results: [], activeIndex: 0, loading: false, error: null, query: '', ...overrides };
}

describe('mentionResults', () => {
	it('filters by query and drops non-ready files', () => {
		const files = [ref('1', 'alpha.pdf'), ref('2', 'beta.pdf', false), ref('3', 'gamma.pdf')];
		expect(mentionResults(files, 'a').map((f) => f.id)).toEqual(['1', '3']);
	});

	it('returns all ready files for an empty query', () => {
		const files = [ref('1'), ref('2', '2.pdf', false)];
		expect(mentionResults(files, '').map((f) => f.id)).toEqual(['1']);
	});
});

describe('mentionStateKind', () => {
	it('orders loading > error > empty > results', () => {
		expect(mentionStateKind(state({ loading: true, error: 'x' }))).toBe('loading');
		expect(mentionStateKind(state({ error: 'x' }))).toBe('error');
		expect(mentionStateKind(state({ query: 'q' }))).toBe('empty-with-query');
		expect(mentionStateKind(state())).toBe('empty-no-query');
		expect(mentionStateKind(state({ results: [ref('1')] }))).toBe('results');
	});
});

describe('decideMentionKeyAction', () => {
	const two = state({ results: [ref('1'), ref('2')], activeIndex: 0 });

	it('Escape dismisses even with no results', () => {
		expect(decideMentionKeyAction('Escape', state())).toEqual({ kind: 'dismiss' });
	});

	it('Enter selects the active row', () => {
		expect(decideMentionKeyAction('Enter', two)).toEqual({ kind: 'select', result: ref('1') });
	});

	it('ArrowDown/ArrowUp wrap around', () => {
		expect(decideMentionKeyAction('ArrowDown', { ...two, activeIndex: 1 })).toEqual({
			kind: 'move',
			nextIndex: 0
		});
		expect(decideMentionKeyAction('ArrowUp', two)).toEqual({ kind: 'move', nextIndex: 1 });
	});

	it('is a noop for other keys and for Enter with no results', () => {
		expect(decideMentionKeyAction('a', two)).toEqual({ kind: 'noop' });
		expect(decideMentionKeyAction('Enter', state())).toEqual({ kind: 'noop' });
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/MentionPopover.test.ts`
Expected: FAIL — cannot resolve `../components/MentionPopover.svelte`.

- [ ] **Step 3: Write the component**

`web/src/lib/lq-ai/components/MentionPopover.svelte`. Structure it as a clone of `SlashPopover.svelte` (read that file first — same two-script layout, same `<svelte:window on:keydown>`, same mousedown-not-click row handler, same a11y attributes with ids `lq-mention-row-{i}`, same five render states). Differences only:

1. Module block (replaces SlashPopover's fetch-oriented helpers):

```ts
	/**
	 * MentionPopover — typeahead listbox for @-referencing matter
	 * documents (referenced-files Phase 2). Clone of SlashPopover with the fetch
	 * replaced by client-side filtering over the caller-loaded
	 * referenceable list: the whole matter file set is already in memory
	 * (files/referenceable.ts), so there is no per-keystroke request and
	 * no request-token race guard.
	 *
	 * Only READY files are offered — the mention flow is keyboard-driven
	 * and never renders a disabled row; non-ready files surface as
	 * "Preparing…" rows in FilePickerDropdown instead.
	 */
	import { filterReferenceable, type ReferencedFile } from '../files/referenceable';
	import { nextIndex } from './SlashPopover.svelte';

	export type MentionPopoverState = {
		results: ReferencedFile[];
		activeIndex: number;
		loading: boolean;
		error: string | null;
		query: string;
	};

	export type MentionStateKind =
		| 'loading'
		| 'error'
		| 'empty-with-query'
		| 'empty-no-query'
		| 'results';

	export type MentionKeyAction =
		| { kind: 'select'; result: ReferencedFile }
		| { kind: 'dismiss' }
		| { kind: 'move'; nextIndex: number }
		| { kind: 'noop' };

	export function mentionResults(files: ReferencedFile[], query: string): ReferencedFile[] {
		return filterReferenceable(files, query).filter((f) => f.ready);
	}

	export function mentionStateKind(state: MentionPopoverState): MentionStateKind {
		if (state.loading) return 'loading';
		if (state.error) return 'error';
		if (state.results.length === 0) {
			return state.query ? 'empty-with-query' : 'empty-no-query';
		}
		return 'results';
	}

	export function decideMentionKeyAction(
		key: string,
		state: MentionPopoverState
	): MentionKeyAction {
		if (key === 'Escape') return { kind: 'dismiss' };
		const len = state.results.length;
		if (len === 0) return { kind: 'noop' };
		if (key === 'Enter') {
			const result = state.results[state.activeIndex];
			if (!result) return { kind: 'noop' };
			return { kind: 'select', result };
		}
		if (key === 'ArrowDown') {
			return { kind: 'move', nextIndex: nextIndex(state.activeIndex, len, 1) };
		}
		if (key === 'ArrowUp') {
			return { kind: 'move', nextIndex: nextIndex(state.activeIndex, len, -1) };
		}
		return { kind: 'noop' };
	}
```

2. Instance script:

```ts
	export let query: string;
	export let files: ReferencedFile[];
	export let loading: boolean = false;
	export let error: string | null = null;
	export let onSelect: (file: ReferencedFile) => void;
	export let onDismiss: () => void;
	export let onRetry: () => void;

	let activeIndex = 0;
	let lastQuery: string | undefined;

	$: results = mentionResults(files, query);
	// Reset the active row on ANY query change (matching SlashPopover's
	// semantics): after an edit, position N of the new result set is an
	// unrelated file, so a stale highlight must never survive the edit.
	$: if (query !== lastQuery) {
		lastQuery = query;
		activeIndex = 0;
	}
	// Clamp if the file list itself shrinks (e.g. a reload) with no query change.
	$: if (activeIndex >= results.length) activeIndex = 0;
	$: kind = mentionStateKind({ results, activeIndex, loading, error, query });

	function onWindowKey(e: KeyboardEvent) {
		const action = decideMentionKeyAction(e.key, { results, activeIndex, loading, error, query });
		switch (action.kind) {
			case 'select':
				e.preventDefault();
				e.stopPropagation();
				onSelect(action.result);
				return;
			case 'dismiss':
				e.preventDefault();
				e.stopPropagation();
				onDismiss();
				return;
			case 'move':
				e.preventDefault();
				e.stopPropagation();
				activeIndex = action.nextIndex;
				return;
			case 'noop':
				return;
		}
	}

	function onRowMouseDown(e: MouseEvent, file: ReferencedFile) {
		e.preventDefault();
		onSelect(file);
	}
```

3. Template: same shape as SlashPopover with `aria-label="Document suggestions"`, root class `lq-mention-popover`, `data-testid="lq-ai-mention-popover"` on the root div, and these state texts:
   - loading → `Loading documents…`
   - error → `Couldn't load documents ·` + retry button calling `onRetry`
   - empty-with-query → `No matching documents · Esc to dismiss`
   - empty-no-query → `No documents ready to reference in this matter`
   - results rows: icon `📄`, title `{r.filename}`, no description line; row ids `lq-mention-row-{i}`, row `data-testid="lq-ai-mention-row"`.

4. Styles: copy SlashPopover's `<style>` block verbatim, renaming every `lq-slash-popover` class to `lq-mention-popover` (drop the unused `__desc`/`__link` rules).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/MentionPopover.test.ts`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
cd web && npx prettier --plugin-search-dir --write src/lib/lq-ai/components/MentionPopover.svelte src/lib/lq-ai/__tests__/MentionPopover.test.ts && npx eslint src/lib/lq-ai/components/MentionPopover.svelte src/lib/lq-ai/__tests__/MentionPopover.test.ts
cd /Users/abc/projs/lqAI/lq-ai && git add web/src/lib/lq-ai/components/MentionPopover.svelte web/src/lib/lq-ai/__tests__/MentionPopover.test.ts
git commit -s -m "feat(web): add MentionPopover for @-referencing matter documents" -m "Refs referenced-files"
```

---

### Task 4: ReferencedFilesChips + FilePickerDropdown components

**Files:**
- Create: `web/src/lib/lq-ai/components/ReferencedFilesChips.svelte`
- Create: `web/src/lib/lq-ai/components/FilePickerDropdown.svelte`
- Test: `web/src/lib/lq-ai/__tests__/FilePickerDropdown.test.ts`

**Interfaces:**
- Consumes: `ReferencedFile`, `filterReferenceable` (Task 1).
- Produces:
  - `ReferencedFilesChips` props: `files: ReferencedFile[]`, `notice: string | null`, `onRemove: (id: string) => void`.
  - `FilePickerDropdown` props: `files: ReferencedFile[]`, `loading: boolean`, `error: string | null`, `failedKbCount: number`, `selectedIds: string[]`, `capReached: boolean`, `onToggle: (file: ReferencedFile) => void`, `onClose: () => void`, `onRetry: () => void`.
  - `FilePickerDropdown` module helper (unit-tested): `rowDisabled(file: ReferencedFile, selected: boolean, capReached: boolean): boolean`.

- [ ] **Step 1: Write the failing test**

`web/src/lib/lq-ai/__tests__/FilePickerDropdown.test.ts`:

```ts
/** referenced-files Phase 2 — FilePickerDropdown row-disable logic. */
import { describe, expect, it } from 'vitest';

import { rowDisabled } from '../components/FilePickerDropdown.svelte';
import type { ReferencedFile } from '../files/referenceable';

function ref(ready: boolean): ReferencedFile {
	return { id: '1', filename: 'a.pdf', ready };
}

describe('rowDisabled', () => {
	it('disables non-ready rows regardless of selection state', () => {
		expect(rowDisabled(ref(false), false, false)).toBe(true);
		expect(rowDisabled(ref(false), true, true)).toBe(true);
	});

	it('disables unselected rows at the cap', () => {
		expect(rowDisabled(ref(true), false, true)).toBe(true);
	});

	it('keeps SELECTED rows enabled at the cap so they can be unchecked', () => {
		expect(rowDisabled(ref(true), true, true)).toBe(false);
	});

	it('enables ready rows below the cap', () => {
		expect(rowDisabled(ref(true), false, false)).toBe(false);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/FilePickerDropdown.test.ts`
Expected: FAIL — cannot resolve the component.

- [ ] **Step 3: Write both components**

`web/src/lib/lq-ai/components/ReferencedFilesChips.svelte`:

```svelte
<script lang="ts">
	/**
	 * referenced-files Phase 2 — the authoritative referenced-files set, rendered
	 * as removable chips above the composer. Both entry affordances
	 * (FilePickerDropdown, MentionPopover) converge on this one row.
	 */
	import type { ReferencedFile } from '../files/referenceable';

	export let files: ReferencedFile[];
	export let notice: string | null = null;
	export let onRemove: (id: string) => void;
</script>

{#if files.length > 0 || notice}
	<div class="lq-ref-chips" data-testid="lq-ai-referenced-chips">
		{#each files as f (f.id)}
			<span class="lq-ref-chip" data-testid="lq-ai-referenced-chip">
				<span class="lq-ref-chip__icon" aria-hidden="true">📄</span>
				<span class="lq-ref-chip__name" title={f.filename}>{f.filename}</span>
				<button
					type="button"
					class="lq-ref-chip__remove"
					aria-label={`Remove ${f.filename}`}
					on:click={() => onRemove(f.id)}
				>
					×
				</button>
			</span>
		{/each}
		{#if notice}
			<span class="lq-ref-chips__notice" data-testid="lq-ai-referenced-notice">{notice}</span>
		{/if}
	</div>
{/if}

<style>
	.lq-ref-chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--lq-space-1, 4px);
		padding: var(--lq-space-1, 4px) 0;
		font-family: var(--lq-font-sans);
		font-size: 12px;
	}

	.lq-ref-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 220px;
		padding: 2px var(--lq-space-2, 8px);
		border: 1px solid var(--lq-accent-border, #cfe4d8);
		border-radius: 999px;
		background: var(--lq-accent-soft, #e8f4ec);
		color: var(--lq-text, #1a1a1a);
	}

	.lq-ref-chip__name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.lq-ref-chip__remove {
		background: none;
		border: 0;
		padding: 0 2px;
		font: inherit;
		color: var(--lq-text-tertiary, #9ca3af);
		cursor: pointer;
	}

	.lq-ref-chip__remove:hover {
		color: var(--lq-text, #1a1a1a);
	}

	.lq-ref-chips__notice {
		color: var(--lq-text-tertiary, #9ca3af);
	}
</style>
```

`web/src/lib/lq-ai/components/FilePickerDropdown.svelte`:

```svelte
<script context="module" lang="ts">
	/**
	 * FilePickerDropdown — multi-select referenced-documents picker
	 * (referenced-files Phase 2). Checkbox-set pattern from AttachKBModal, search
	 * pattern from SkillPicker. Unlike MentionPopover this DOES render
	 * non-ready files — disabled, with a "Preparing…" badge — so the user
	 * can see why a document isn't offered yet (P4 made visible).
	 */
	import {
		MESSAGE_REFERENCED_FILES_MAX,
		filterReferenceable,
		type ReferencedFile
	} from '../files/referenceable';

	export function rowDisabled(
		file: ReferencedFile,
		selected: boolean,
		capReached: boolean
	): boolean {
		if (!file.ready) return true;
		return capReached && !selected;
	}
</script>

<script lang="ts">
	export let files: ReferencedFile[];
	export let loading: boolean = false;
	export let error: string | null = null;
	export let failedKbCount: number = 0;
	export let selectedIds: string[];
	export let capReached: boolean = false;
	export let onToggle: (file: ReferencedFile) => void;
	export let onClose: () => void;
	export let onRetry: () => void;

	let searchTerm = '';

	$: filtered = filterReferenceable(files, searchTerm);
	$: selectedSet = new Set(selectedIds);

	function onWindowKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			onClose();
		}
	}
</script>

<svelte:window on:keydown={onWindowKey} />

<div class="lq-file-picker" data-testid="lq-ai-file-picker" role="dialog" aria-label="Reference documents">
	<div class="lq-file-picker__head">
		<input
			type="search"
			class="lq-file-picker__search"
			placeholder="Search matter documents…"
			bind:value={searchTerm}
			data-testid="lq-ai-file-picker-search"
		/>
		<button type="button" class="lq-file-picker__done" on:click={onClose} data-testid="lq-ai-file-picker-done">
			Done
		</button>
	</div>

	{#if loading}
		<div class="lq-file-picker__status">Loading documents…</div>
	{:else if error}
		<div class="lq-file-picker__status lq-file-picker__status--error">
			Couldn't load documents ·
			<button type="button" class="lq-file-picker__retry" on:click={onRetry}>retry</button>
		</div>
	{:else if files.length === 0}
		<div class="lq-file-picker__status" data-testid="lq-ai-file-picker-empty">
			No documents in this matter's knowledge bases yet.
		</div>
	{:else}
		{#if failedKbCount > 0}
			<div class="lq-file-picker__status lq-file-picker__status--error">
				{failedKbCount} knowledge base{failedKbCount === 1 ? '' : 's'} failed to load ·
				<button type="button" class="lq-file-picker__retry" on:click={onRetry}>retry</button>
			</div>
		{/if}
		{#if capReached}
			<div class="lq-file-picker__status" data-testid="lq-ai-file-picker-cap">
				Reference limit reached ({MESSAGE_REFERENCED_FILES_MAX} documents per message).
			</div>
		{/if}
		{#each filtered as f (f.id)}
			{@const disabled = rowDisabled(f, selectedSet.has(f.id), capReached)}
			<label class="lq-file-picker__row" class:disabled data-testid="lq-ai-file-picker-row">
				<input
					type="checkbox"
					checked={selectedSet.has(f.id)}
					{disabled}
					on:change={() => onToggle(f)}
				/>
				<span class="lq-file-picker__name" title={f.filename}>{f.filename}</span>
				{#if !f.ready}
					<span class="lq-file-picker__badge">Preparing…</span>
				{/if}
			</label>
		{:else}
			<div class="lq-file-picker__status">No documents match “{searchTerm}”.</div>
		{/each}
	{/if}
</div>

<style>
	.lq-file-picker {
		display: flex;
		flex-direction: column;
		min-width: 300px;
		max-width: clamp(300px, 90vw, 440px);
		max-height: 340px;
		overflow-y: auto;
		background: var(--lq-surface, var(--lq-canvas, #ffffff));
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius, 6px);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
		padding: var(--lq-space-1, 4px);
		font-family: var(--lq-font-sans);
		font-size: 13px;
		color: var(--lq-text, #1a1a1a);
	}

	.lq-file-picker__head {
		display: flex;
		gap: var(--lq-space-1, 4px);
		padding: var(--lq-space-1, 4px);
	}

	.lq-file-picker__search {
		flex: 1;
		font: inherit;
		padding: 4px var(--lq-space-2, 8px);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius-sm, 4px);
	}

	.lq-file-picker__done {
		background: none;
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius-sm, 4px);
		padding: 4px var(--lq-space-2, 8px);
		font: inherit;
		cursor: pointer;
	}

	.lq-file-picker__status {
		padding: var(--lq-space-2, 8px) var(--lq-space-3, 12px);
		color: var(--lq-text-tertiary, #9ca3af);
		font-size: 12px;
	}

	.lq-file-picker__status--error {
		color: var(--lq-error, #b54848);
	}

	.lq-file-picker__retry {
		background: none;
		border: 0;
		padding: 0;
		color: inherit;
		font: inherit;
		text-decoration: underline;
		cursor: pointer;
	}

	.lq-file-picker__row {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2, 8px);
		padding: var(--lq-space-2, 8px) var(--lq-space-3, 12px);
		border-radius: var(--lq-radius-sm, 4px);
		cursor: pointer;
	}

	.lq-file-picker__row:hover:not(.disabled) {
		background: var(--lq-accent-soft, #e8f4ec);
	}

	.lq-file-picker__row.disabled {
		color: var(--lq-text-tertiary, #9ca3af);
		cursor: not-allowed;
	}

	.lq-file-picker__name {
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.lq-file-picker__badge {
		font-size: 11px;
		color: var(--lq-text-tertiary, #9ca3af);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: 999px;
		padding: 0 6px;
	}
</style>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/FilePickerDropdown.test.ts`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
cd web && npx prettier --plugin-search-dir --write src/lib/lq-ai/components/ReferencedFilesChips.svelte src/lib/lq-ai/components/FilePickerDropdown.svelte src/lib/lq-ai/__tests__/FilePickerDropdown.test.ts && npx eslint src/lib/lq-ai/components/ReferencedFilesChips.svelte src/lib/lq-ai/components/FilePickerDropdown.svelte src/lib/lq-ai/__tests__/FilePickerDropdown.test.ts
cd /Users/abc/projs/lqAI/lq-ai && git add web/src/lib/lq-ai/components/ReferencedFilesChips.svelte web/src/lib/lq-ai/components/FilePickerDropdown.svelte web/src/lib/lq-ai/__tests__/FilePickerDropdown.test.ts
git commit -s -m "feat(web): add referenced-files chips row + multi-select file picker" -m "Refs referenced-files"
```

---

### Task 5: Wire it all into ChatPanel + message types

**Files:**
- Modify: `web/src/lib/lq-ai/types.ts` (`MessageCreate` ~line 347, `MessagePostResponse` ~line 375, `MessageCompleteFrame` ~line 400, `Message` ~line 295)
- Modify: `web/src/lib/lq-ai/components/ChatPanel.svelte`

**Interfaces:**
- Consumes: everything produced by Tasks 1–4.
- Produces: the send payload field `referenced_file_ids: string[]` (wire), the optimistic user `Message.referenced_files: Array<{ id: string; filename: string }>` that Task 6 renders.

Line numbers below are as of commit `124502d` — verify each anchor by its quoted code before editing (earlier tasks shift them slightly).

- [ ] **Step 1: Extend the types** (`web/src/lib/lq-ai/types.ts`)

In `MessageCreate` (after the `set_sticky` field, ~line 372):

```ts
	/**
	 * referenced-files Phase 2 — caller-selected matter documents grounding THIS
	 * turn via file-scoped retrieval + verified citations (ADR 0022).
	 * Distinct from the (unwired) verbatim file_ids channel. Cap 16
	 * (MESSAGE_REFERENCED_FILES_MAX, enforced UI-side so the backend 422
	 * is unreachable through this client).
	 */
	referenced_file_ids?: string[];
```

In `MessagePostResponse` (after `applied_skills`, ~line 381):

```ts
	/** referenced-files — echo of the validated referenced_file_ids. */
	applied_referenced_file_ids?: string[];
```

In `MessageCompleteFrame` (after `routed_provider`, ~line 407):

```ts
	/** referenced-files — echo of the validated referenced_file_ids (parity with applied_skills). */
	applied_referenced_file_ids?: string[];
```

In `Message` (after `citations?: Citation[];`, ~line 321):

```ts
	/**
	 * referenced-files Phase 2 — client-side stamp of the documents referenced when
	 * THIS user message was sent ({id, filename} pairs). NOT persisted:
	 * the backend stores no messages.referenced_file_ids column (ADR
	 * 0022), so the row disappears on reload. Set only on the optimistic
	 * user message at send time.
	 */
	referenced_files?: Array<{ id: string; filename: string }>;
```

- [ ] **Step 2: ChatPanel — imports + state**

In the instance `<script>` of `ChatPanel.svelte`: add to the component imports (after the `SlashPopover` import, ~line 103):

```ts
	import MentionPopover from '$lib/lq-ai/components/MentionPopover.svelte';
	import FilePickerDropdown from '$lib/lq-ai/components/FilePickerDropdown.svelte';
	import ReferencedFilesChips from '$lib/lq-ai/components/ReferencedFilesChips.svelte';
	import {
		MESSAGE_REFERENCED_FILES_MAX,
		addReferencedFile,
		loadReferenceableFiles,
		removeReferencedFile,
		type ReferencedFile
	} from '$lib/lq-ai/files/referenceable';
```

After the slash state block (`let slashStartIndex = -1;`, ~line 799), add:

```ts
	// referenced-files Phase 2 — referenced files. One authoritative, deduped,
	// cap-16 list feeding `referenced_file_ids`; both the @-mention
	// popover and the picker mutate it. Plain array reassignment (not
	// Map mutation) so Svelte 4 reactivity tracks changes.
	let referencedFiles: ReferencedFile[] = [];
	let referencedNotice: string | null = null;

	// The referenceable set (all files across the matter's attached KBs),
	// lazily loaded per project and cached until a chat/project switch or
	// an explicit refresh (picker re-open / retry).
	let referenceable: ReferencedFile[] = [];
	let referenceableLoading = false;
	let referenceableError: string | null = null;
	let referenceableFailedKbCount = 0;
	let referenceableLoadedForProject: string | null = null;

	let filePickerOpen = false;
	let mentionOpen = false;
	let mentionQuery = '';
	let mentionAtIndex = -1;

	async function ensureReferenceable(force = false): Promise<void> {
		if (!composerProjectId) return;
		if (!force && referenceableLoadedForProject === composerProjectId) return;
		referenceableLoading = true;
		referenceableError = null;
		try {
			const load = await loadReferenceableFiles(composerProjectId);
			referenceable = load.files;
			referenceableFailedKbCount = load.failedKbCount;
			referenceableLoadedForProject = composerProjectId;
		} catch (e: unknown) {
			referenceableError = e instanceof Error ? e.message : 'Failed to load documents';
			referenceable = [];
			referenceableFailedKbCount = 0;
			referenceableLoadedForProject = null;
		} finally {
			referenceableLoading = false;
		}
	}

	function addReference(file: ReferencedFile): void {
		const result = addReferencedFile(referencedFiles, file);
		if (result.added) {
			referencedFiles = result.list;
			referencedNotice = null;
		} else if (result.reason === 'cap') {
			referencedNotice = `You can reference up to ${MESSAGE_REFERENCED_FILES_MAX} documents per message.`;
		}
		// 'duplicate' and 'not-ready' are silent no-ops: the picker
		// disables those rows and the mention popover never offers them.
	}

	function removeReference(id: string): void {
		referencedFiles = removeReferencedFile(referencedFiles, id);
		referencedNotice = null;
	}

	function toggleReference(file: ReferencedFile): void {
		if (referencedFiles.some((f) => f.id === file.id)) removeReference(file.id);
		else addReference(file);
	}

	function toggleFilePicker(): void {
		filePickerOpen = !filePickerOpen;
		if (filePickerOpen) {
			mentionOpen = false;
			void ensureReferenceable(true);
		}
	}

	function onMentionSelect(file: ReferencedFile): void {
		if (mentionAtIndex >= 0) {
			composerText = completeMentionAt(
				composerText,
				mentionAtIndex,
				mentionQuery.length,
				file.filename
			);
		}
		addReference(file);
		mentionOpen = false;
		mentionQuery = '';
		mentionAtIndex = -1;
	}

	function onMentionDismiss(): void {
		mentionOpen = false;
		mentionQuery = '';
		mentionAtIndex = -1;
	}
```

- [ ] **Step 3: ChatPanel — extend `onComposerInput`** (~line 801)

Replace the body so it runs BOTH detections (they are mutually exclusive by trigger char — slash requires `/` at line start, mention requires `@` at word start):

```ts
	function onComposerInput(e: Event): void {
		const ta = e.target as HTMLTextAreaElement;
		// `bind:value` has already updated `composerText` before this
		// handler fires; we read from the textarea directly anyway so the
		// caret position and value are guaranteed consistent.
		const detection = detectSlashAt(ta.value, ta.selectionStart);
		if (detection.open) {
			slashOpen = true;
			slashQuery = detection.query;
			slashStartIndex = detection.slashIndex;
		} else {
			slashOpen = false;
			slashQuery = '';
			slashStartIndex = -1;
		}

		// referenced-files Phase 2 — @-mention detection. Only offered in project
		// chats (a projectless chat has no referenceable set; the backend
		// 404s any referenced id there — never render the affordance).
		const mention = composerProjectId ? detectMentionAt(ta.value, ta.selectionStart) : { open: false as const };
		if (mention.open) {
			mentionOpen = true;
			mentionQuery = mention.query;
			mentionAtIndex = mention.atIndex;
			filePickerOpen = false;
			void ensureReferenceable();
		} else {
			mentionOpen = false;
			mentionQuery = '';
			mentionAtIndex = -1;
		}
	}
```

- [ ] **Step 4: ChatPanel — reset on chat switch** (`selectChat`, after `skillInputs = {};` ~line 332)

```ts
		// referenced-files — referenced files are per-draft; the referenceable cache
		// is per-project and re-validated lazily by ensureReferenceable().
		referencedFiles = [];
		referencedNotice = null;
		filePickerOpen = false;
		mentionOpen = false;
		mentionQuery = '';
		mentionAtIndex = -1;
```

- [ ] **Step 5: ChatPanel — send payload + stamp + clear** (`sendMessage`)

In the optimistic user message build (~line 591, `const userMsg: Message = {...}`), add after `is_enhanced: isEnhancedSend,`:

```ts
			referenced_files:
				referencedFiles.length > 0
					? referencedFiles.map(({ id, filename }) => ({ id, filename }))
					: undefined,
```

In the `sendMessageStream` body (~lines 633–645), add after `skill_inputs: ...`:

```ts
						// referenced-files Phase 2 — ground this turn in the user-selected
						// matter documents (file-scoped retrieval + citations).
						referenced_file_ids:
							referencedFiles.length > 0 ? referencedFiles.map((f) => f.id) : undefined,
```

Right after `composerText = '';` (~line 648, the send-in-flight point where the draft clears), add:

```ts
				// Referenced files are turn-scoped (like the backend channel):
				// clear on a successfully-initiated send, preserve on failure so
				// the user can adjust and retry.
				referencedFiles = [];
				referencedNotice = null;
				filePickerOpen = false;
```

- [ ] **Step 6: ChatPanel — template mounts**

(a) Chips row — insert immediately BEFORE `<div class="flex items-end gap-2">` (~line 1071):

```svelte
				<ReferencedFilesChips
					files={referencedFiles}
					notice={referencedNotice}
					onRemove={removeReference}
				/>
```

(b) Mention popover — inside `<div class="lq-composer-wrap flex-1">`, right after the existing `{#if slashOpen}...{/if}` block (~line 1090):

```svelte
							{#if mentionOpen}
								<div class="lq-composer-popover" data-testid="lq-ai-mention-popover-anchor">
									<MentionPopover
										query={mentionQuery}
										files={referenceable}
										loading={referenceableLoading}
										error={referenceableError}
										onSelect={onMentionSelect}
										onDismiss={onMentionDismiss}
										onRetry={() => void ensureReferenceable(true)}
									/>
								</div>
							{/if}
```

(c) Picker button + dropdown — inside the existing `{#if composerProjectId}` toolbar block (~line 1102), after the Attach-KB button (`data-testid="lq-ai-attach-kb-btn"`), add:

```svelte
								<div class="lq-file-picker-anchor">
									<button
										type="button"
										class="lq-btn-secondary text-sm"
										aria-label="Reference matter documents"
										title="Reference matter documents in this message"
										on:click={toggleFilePicker}
										data-testid="lq-ai-file-picker-btn"
									>
										📄
									</button>
									{#if filePickerOpen}
										<div class="lq-composer-popover">
											<FilePickerDropdown
												files={referenceable}
												loading={referenceableLoading}
												error={referenceableError}
												failedKbCount={referenceableFailedKbCount}
												selectedIds={referencedFiles.map((f) => f.id)}
												capReached={referencedFiles.length >= MESSAGE_REFERENCED_FILES_MAX}
												onToggle={toggleReference}
												onClose={() => (filePickerOpen = false)}
												onRetry={() => void ensureReferenceable(true)}
											/>
										</div>
									{/if}
								</div>
```

(d) Anchor style — `lq-composer-popover` is an existing class (used by the slash popover anchor). For the picker anchor add to ChatPanel's `<style>` block:

```css
	.lq-file-picker-anchor {
		position: relative;
	}
```

Check how `.lq-composer-popover` is positioned (grep ChatPanel's style block / `web/src/lib/lq-ai/styles`); if it is absolutely positioned relative to `.lq-composer-wrap`, the picker's copy inside `.lq-file-picker-anchor` will anchor to the button — verify visually in Cypress `cy.get('[data-testid="lq-ai-file-picker"]').should('be.visible')`.

- [ ] **Step 7: Run the full frontend unit suite + type gate**

```bash
cd web && npx vitest run src/lib/lq-ai/__tests__/ && npm run check:lq-ai
```
Expected: all vitest files PASS (including the pre-existing ones); svelte-check reports no NEW errors in the touched files (note any pre-existing baseline errors and leave them).

- [ ] **Step 8: Format, lint, commit**

```bash
cd web && npx prettier --plugin-search-dir --write src/lib/lq-ai/types.ts src/lib/lq-ai/components/ChatPanel.svelte && npx eslint src/lib/lq-ai/types.ts src/lib/lq-ai/components/ChatPanel.svelte
cd /Users/abc/projs/lqAI/lq-ai && git add web/src/lib/lq-ai/types.ts web/src/lib/lq-ai/components/ChatPanel.svelte
git commit -s -m "feat(web): wire referenced files into composer send path" -m "Refs referenced-files"
```

---

### Task 6: "Referenced:" row on the user message bubble

**Files:**
- Modify: `web/src/lib/lq-ai/components/MessageBubble.svelte`

**Interfaces:**
- Consumes: `Message.referenced_files` (Task 5's type addition; stamped on the optimistic user message at send time).

- [ ] **Step 1: Read `MessageBubble.svelte`** and locate the user-role content rendering (the component renders both roles; find where the message content/pills render for `message.role === 'user'`).

- [ ] **Step 2: Add the row** — immediately after the user message's content rendering, add:

```svelte
	{#if message.role === 'user' && message.referenced_files?.length}
		<!-- referenced-files Phase 2 — session-only stamp (not persisted server-side;
		     disappears on reload). Shows which matter documents grounded
		     this turn. -->
		<div class="lq-msg-referenced" data-testid="lq-ai-referenced-row">
			📄 Referenced: {message.referenced_files.map((f) => f.filename).join(', ')}
		</div>
	{/if}
```

And to the component's `<style>` block:

```css
	.lq-msg-referenced {
		margin-top: 4px;
		font-size: 12px;
		color: var(--lq-text-tertiary, #9ca3af);
	}
```

Match the component's existing markup/indentation idiom; if user-message pills (e.g. the ✨ enhanced pill) render in a specific footer area, put the row there instead — same visual tier.

- [ ] **Step 3: Gate + commit**

```bash
cd web && npx vitest run src/lib/lq-ai/__tests__/ && npm run check:lq-ai && npx prettier --plugin-search-dir --write src/lib/lq-ai/components/MessageBubble.svelte && npx eslint src/lib/lq-ai/components/MessageBubble.svelte
cd /Users/abc/projs/lqAI/lq-ai && git add web/src/lib/lq-ai/components/MessageBubble.svelte
git commit -s -m "feat(web): show referenced documents on sent user messages" -m "Refs referenced-files"
```

---

### Task 7: Cypress e2e + PRD docs + full gate

**Files:**
- Create: `web/cypress/e2e/referenced-files-referenced-files.cy.ts`
- Modify: `docs/PRD.md` (§3.1 ~line 338; §9 referenced-files entry ~lines 4942–4948)

- [ ] **Step 1: Read an existing chat spec for the harness pattern** — `web/cypress/e2e/chat.cy.ts` (auth/bootstrap, how chats/projects/messages routes are stubbed, how the composer is driven). Reuse its login/bootstrap helpers exactly; the new spec must run in the same way (`npx cypress run --spec cypress/e2e/referenced-files-referenced-files.cy.ts` or the repo's documented Cypress invocation).

- [ ] **Step 2: Write the spec.** Adapt the setup to the harness pattern found in Step 1; the scenario bodies must cover exactly these five cases (testids are fixed by Tasks 4–5):

```ts
/**
 * referenced-files Phase 2 — referenced files in the chat composer.
 * All API routes stubbed; asserts the wire contract (referenced_file_ids
 * on POST /messages) and the two entry affordances.
 */
describe('referenced-files referenced files', () => {
	// Stub set (adapt names to the chat.cy.ts harness):
	//  - GET  **/api/v1/projects/proj-1            → { id: 'proj-1', attached_knowledge_base_ids: ['kb-1'], ... }
	//  - GET  **/api/v1/knowledge-bases/kb-1/files → [
	//      { id: 'file-1', filename: 'master-agreement.pdf', ingestion_status: 'ready', ... },
	//      { id: 'file-2', filename: 'exhibit-a.pdf',        ingestion_status: 'ready', ... },
	//      { id: 'file-3', filename: 'pending-upload.pdf',   ingestion_status: 'processing', ... }
	//    ]
	//  - POST **/api/v1/chats/*/messages           → cy.intercept(...).as('send') with an SSE-ish stub
	//    per the chat.cy.ts pattern.

	it('picker flow: select two files, chips render, send carries both ids, set clears', () => {
		// open picker → search 'agreement' → check row → clear search →
		// check 'exhibit-a' → Done → two chips visible →
		// type a message → Send → cy.wait('@send').its('request.body')
		//   .should((b) => expect(b.referenced_file_ids).to.deep.equal(['file-1', 'file-2'])) →
		// chips row empties after send.
	});

	it('mention flow: typing @exh opens popover, Enter splices text and adds chip', () => {
		// type 'summarize @exh' → popover visible with exhibit-a.pdf →
		// {enter} → composer value === 'summarize ' →
		// chip 'exhibit-a.pdf' visible → popover closed.
	});

	it('non-ready file shows disabled "Preparing…" row in the picker and is absent from the mention popover', () => {
		// picker: row for pending-upload.pdf has a disabled checkbox + badge.
		// mention: '@pending' → 'No matching documents' empty state.
	});

	it('chip remove (×) drops the file from the set', () => {
		// add via picker → click chip × → chips row empty →
		// send → request body has NO referenced_file_ids key.
	});

	it('projectless chat: no picker button, @ never opens the popover', () => {
		// bootstrap a chat with project_id: null →
		// composer visible, lq-ai-file-picker-btn does not exist →
		// type '@doc' → lq-ai-mention-popover-anchor does not exist.
	});
});
```

Every `it` body must be fully implemented (the comments above are the scenario contract, not placeholders to leave in).

- [ ] **Step 3: Run the spec** against the dev stack if it is up (`docker compose ps` — if the stack is down, note it and rely on CI; do NOT start/rebuild the stack destructively). If runnable: `cd web && npx cypress run --spec cypress/e2e/referenced-files-referenced-files.cy.ts`. Expected: all 5 passing.

- [ ] **Step 4: PRD edits**

(a) §3.1 (~line 338), append to the `referenced_file_ids` sentence added by the backend PR:

```markdown
The web composer surfaces this channel through two affordances (referenced-files Phase 2): an inline `@`-mention popover and a multi-select document picker, converging on one deduped, cap-16 chip set; non-`ready` documents render disabled ("Preparing…"), so the UI can never assemble a set the backend would reject.
```

(b) §9 referenced-files entry (~line 4948): replace the `**Deferred:**` paragraph with:

```markdown
**Phase 2 (SHIPPED 2026-07-03):** composer `@`-mention popover + multi-select document picker (web), one authoritative cap-16 referenced-set fed by both, KB-file listing composed client-side from `GET /projects/{id}` + `GET /knowledge-bases/{kb_id}/files` (no DE-296 dependency). **Deferred:** Phase 3 — embed-on-reference, where selecting a file eagerly (re-)triggers its embedding pipeline rather than requiring pre-existing `ready` status.
```

- [ ] **Step 5: Full gate**

```bash
cd web && npx vitest run src/lib/lq-ai/__tests__/ && npm run check:lq-ai && npx prettier --plugin-search-dir --check "src/lib/lq-ai/**/*.{ts,svelte}" "cypress/e2e/referenced-files-referenced-files.cy.ts"
```
(If prettier flags files this feature did not touch, leave them — check only the touched set.)

- [ ] **Step 6: Commit**

```bash
cd /Users/abc/projs/lqAI/lq-ai && git add web/cypress/e2e/referenced-files-referenced-files.cy.ts docs/PRD.md
git commit -s -m "test(web): e2e for composer referenced files + PRD Phase 2 docs" -m "Refs referenced-files"
```
