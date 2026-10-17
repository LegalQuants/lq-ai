<script context="module" lang="ts">
	import type { ReceiptEvent, ReceiptEventKind } from '../api/receipts';

	export const ALL_KINDS: ReceiptEventKind[] = [
		'message',
		'inference',
		'audit',
		'skill',
		'retrieval',
		'error'
	];

	export const KIND_ICONS: Record<ReceiptEventKind, string> = {
		message: '👤',
		inference: '🧠',
		audit: '📜',
		skill: '🛠',
		retrieval: '📎',
		error: '🛡'
	};

	export const KIND_LABELS: Record<ReceiptEventKind, string> = {
		message: 'events',
		inference: 'providers',
		audit: 'audit',
		skill: 'events',
		retrieval: 'retrievals',
		error: 'errors'
	};

	/**
	 * Plain-English description of each event kind for non-technical users.
	 * Surfaced via the row's `title` attribute so a hover explains what
	 * the icon + short description mean without forcing the user to
	 * expand the detail JSON.
	 */
	export const KIND_DESCRIPTION: Record<ReceiptEventKind, string> = {
		message:
			"A chat message — either your question or the AI's reply. Includes token counts when available.",
		inference:
			'A call to an AI provider. Shows which provider and model handled the request, and which inference tier it ran at.',
		audit:
			'An audited action recorded for compliance review (logins, skill installs, tier overrides, account deletions, etc.).',
		skill:
			"A skill applied to a chat — the structured prompt that shaped the AI's answer. Shows where the skill was attached from.",
		retrieval:
			'A knowledge-base retrieval — the AI searched attached documents and pulled in matching chunks as context.',
		error:
			"A refusal or error — typically the Inference Gateway blocking a request that would have routed below the matter's tier floor."
	};

	/** Wave D.2 — human-readable labels for the per-attachment ``source``
	 *  tag the chats handler records (slash / picker / wizard-tryout /
	 *  tryit-tab / capture). Unknown / missing values render unlabelled. */
	export const SOURCE_LABEL: Record<string, string> = {
		slash: 'slash command',
		picker: 'picker',
		'wizard-tryout': 'wizard try-it',
		'tryit-tab': 'try-it tab',
		capture: 'capture'
	};

	/** Format a timestamp string (ISO 8601) as HH:MM:SS. */
	export function formatTimestamp(ts: string): string {
		const d = new Date(ts);
		return d.toTimeString().slice(0, 8);
	}

	/** Build a 1-line description for an event based on its kind + detail. */
	export function eventDescription(event: ReceiptEvent): string {
		const { kind, detail } = event;
		switch (kind) {
			case 'message':
				return `${detail.message_kind === 'user' ? 'User' : 'AI'} message${
					detail.prompt_tokens ? ` — ${detail.prompt_tokens} tokens` : ''
				}`;
			case 'inference':
				return `${detail.provider} — ${detail.model} (tier ${detail.tier})`;
			case 'audit':
				if (detail.action === 'skill.reference_read') {
					return `Reference read — ${detail.provider} (${detail.outcome})`;
				}
				return String(detail.action ?? 'audit event');
			case 'skill': {
				const src = SOURCE_LABEL[String(detail.source ?? '')] ?? null;
				return src
					? `Skill applied: ${detail.skill_name} (via ${src})`
					: `Skill applied: ${detail.skill_name}`;
			}
			case 'retrieval':
				return `KB retrieval — ${detail.chunk_count} chunks`;
			case 'error':
				return detail.refusal_reason ? `Refused: ${detail.refusal_reason}` : 'Refused';
			default:
				return kind;
		}
	}

	/** Apply the filter to the events array. */
	export function filterEvents(
		events: ReceiptEvent[],
		selectedKinds: ReceiptEventKind[]
	): ReceiptEvent[] {
		const allowed = new Set(selectedKinds);
		return events.filter((e) => allowed.has(e.kind));
	}
</script>

<script lang="ts">
	// NOTE: helpers + types imported from module scope above are automatically
	// available in the instance script — do NOT re-import (Svelte 5 will throw
	// duplicate-id) per T13/T14 finding.

	export let events: ReceiptEvent[];
	export let selectedKinds: ReceiptEventKind[] = ALL_KINDS;
	export let onFilterChange: (kinds: ReceiptEventKind[]) => void = () => {};

	let expanded: Set<string> = new Set(); // event indexes that are expanded

	$: filtered = filterEvents(events, selectedKinds);

	function toggleExpand(idx: number) {
		const key = String(idx);
		if (expanded.has(key)) expanded.delete(key);
		else expanded.add(key);
		expanded = new Set(expanded); // trigger reactivity
	}

	function toggleKind(kind: ReceiptEventKind) {
		const next = selectedKinds.includes(kind)
			? selectedKinds.filter((k) => k !== kind)
			: [...selectedKinds, kind];
		onFilterChange(next);
	}
</script>

<div class="receipts-list">
	<!-- Filter chips -->
	<div class="chips" role="group" aria-label="Filter receipts by kind">
		<button
			class:active={selectedKinds.length === ALL_KINDS.length}
			on:click={() => onFilterChange([...ALL_KINDS])}>all</button
		>
		{#each ['message', 'retrieval', 'inference', 'audit', 'error'] as ReceiptEventKind[] as kind}
			<button
				class:active={selectedKinds.includes(kind)}
				on:click={() => toggleKind(kind)}
				data-testid="filter-chip-{kind}">{KIND_LABELS[kind]}</button
			>
		{/each}
	</div>

	<!-- Event list -->
	{#if filtered.length === 0}
		<div class="empty" data-testid="empty-state">
			No receipts yet — events will appear here as the chat progresses.
		</div>
	{:else}
		{#each filtered as event, idx (idx)}
			<button
				class="row"
				on:click={() => toggleExpand(idx)}
				data-testid="receipt-row"
				title={KIND_DESCRIPTION[event.kind]}
			>
				<span class="ts">{formatTimestamp(event.ts)}</span>
				<span class="icon">{KIND_ICONS[event.kind]}</span>
				<span class="desc">{eventDescription(event)}</span>
				{#if expanded.has(String(idx))}
					<pre class="detail">{JSON.stringify(event.detail, null, 2)}</pre>
				{/if}
			</button>
		{/each}
	{/if}
</div>

<style>
	.receipts-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		height: 100%;
	}
	.chips {
		display: flex;
		gap: 3px;
		flex-wrap: wrap;
		padding-bottom: 6px;
		border-bottom: 1px solid #e5e7eb;
	}
	.chips button {
		background: #f3f4f6;
		color: #374151;
		padding: 2px 6px;
		border-radius: 9999px;
		font-size: 9px;
		border: 0;
		cursor: pointer;
	}
	.chips button.active {
		background: #4338ca;
		color: #fff;
	}
	.row {
		display: grid;
		grid-template-columns: auto auto 1fr;
		gap: 6px;
		padding: 4px 0;
		border-bottom: 1px solid #f3f4f6;
		text-align: left;
		background: transparent;
		border: 0;
		cursor: pointer;
		font-size: 10px;
		color: #374151;
	}
	.ts {
		color: #6b7280;
		font-family: monospace;
	}
	.icon {
		font-size: 12px;
	}
	.detail {
		grid-column: 1 / -1;
		background: #f9fafb;
		padding: 6px;
		border-radius: 4px;
		font-size: 9px;
		white-space: pre-wrap;
	}
	.empty {
		color: #9ca3af;
		padding: 20px;
		text-align: center;
		font-size: 11px;
	}
</style>
