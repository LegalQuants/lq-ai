<script lang="ts">
	/**
	 * Model picker for the LQ.AI shell composer (D0 + ADR 0011 wave-3).
	 *
	 * Surfaces aliases (`smart`, `fast`, ...) plus live-discovered Ollama,
	 * Anthropic, and OpenAI catalog rows in a single dropdown, grouped
	 * by source. The selected model id flows through `MessageCreate.model`
	 * to `POST /chats/{id}/messages`; the gateway's router accepts both
	 * alias names and raw `provider/model` forms.
	 *
	 * ADR 0011 — transparency-first: each alias row publishes its
	 * resolved primary target inline (`smart → anthropic-prod/claude-opus-4-7`),
	 * along with the number of fallback entries. Users see what aliases
	 * actually do without spelunking through admin config.
	 *
	 * ADR 0038 D1: one entry here is not a provider model. "New harness" sits in
	 * its own Experimental group at the head of the list and shows the
	 * provider/model its runs are pinned to, as an alias shows its target. Choosing
	 * it makes Send start a governed run. Where it cannot be used the row is
	 * disabled and says why.
	 */
	import type { ModelEntry, ModelListResponse } from '../api/models';
	import { groupModels } from '../api/models';
	import { sendWording } from '../run/composer';

	export let models: ModelListResponse = { object: 'list', data: [] };
	export let selectedId: string | null = null;
	export let onSelect: (id: string) => void = () => undefined;
	/**
	 * The New harness entry, or null when the server offers none for this chat. `answersDirectly` is
	 * what the server says of the profile behind it: that its orchestrator may answer a request by
	 * itself. It decides what the picker says Send does. Absent, or where there is no profile to
	 * ask (the read has not come back), the picker says what it said before an answer could be direct.
	 */
	export let harness: {
		id: string;
		label: string;
		resolves: string | null;
		disabledReason: string | null;
		answersDirectly?: boolean;
	} | null = null;

	/** Whether the list is showing. The button toggles it. */
	export let open = false;
	// The picker sits in the composer, usually at the foot of the page, where a list
	// opened downward runs off the screen. It opens toward whichever side has more
	// room, and is no taller than that room.
	let toggleEl: HTMLButtonElement | null = null;
	let openUp = false;
	let maxHeight = 320;

	function toggle(): void {
		if (!open && toggleEl && typeof window !== 'undefined') {
			const rect = toggleEl.getBoundingClientRect();
			const band = visibleBand(toggleEl);
			const above = rect.top - band.top;
			const below = band.bottom - rect.bottom;
			openUp = above > below;
			maxHeight = Math.max(120, Math.min(320, Math.floor((openUp ? above : below) - 12)));
		}
		open = !open;
	}

	/**
	 * The vertical band the list can be seen in: the window, cut short by every
	 * ancestor that clips its overflow. The composer sits inside such containers.
	 */
	function visibleBand(el: HTMLElement): { top: number; bottom: number } {
		let top = 0;
		let bottom = window.innerHeight;
		for (let node = el.parentElement; node; node = node.parentElement) {
			if (getComputedStyle(node).overflowY === 'visible') continue;
			const rect = node.getBoundingClientRect();
			top = Math.max(top, rect.top);
			bottom = Math.min(bottom, rect.bottom);
		}
		return { top, bottom };
	}

	$: grouped = groupModels(models);
	$: selectedEntry = findSelected(models.data, selectedId);
	$: harnessChosen = harness !== null && selectedId === harness.id;
	// What the picker says Send does depends on what the server says of the profile, nothing else.
	$: wording = sendWording(harness?.answersDirectly === true);

	function findSelected(data: ModelEntry[], id: string | null): ModelEntry | null {
		if (!id) return null;
		return data.find((entry) => entry.id === id) ?? null;
	}

	function pick(entry: ModelEntry): void {
		open = false;
		if (entry.id === selectedId) return;
		onSelect(entry.id);
	}

	function pickHarness(): void {
		if (!harness || harness.disabledReason) return;
		open = false;
		if (harnessChosen) return;
		onSelect(harness.id);
	}

	function tierLabel(tier?: number): string {
		if (!tier) return '';
		return `T${tier}`;
	}

	function aliasResolution(entry: ModelEntry): string {
		// "smart → anthropic-prod/claude-opus-4-7 (+2 fallbacks)"
		if (!entry.lq_ai_resolves_to) return '';
		const fb = entry.lq_ai_fallback_count ?? 0;
		const fbHint = fb > 0 ? ` (+${fb} fallback${fb === 1 ? '' : 's'})` : '';
		return `→ ${entry.lq_ai_resolves_to}${fbHint}`;
	}
</script>

<div class="relative inline-block" data-testid="lq-ai-model-picker">
	<button
		type="button"
		class="lq-model-pill"
		bind:this={toggleEl}
		on:click={toggle}
		data-testid="lq-ai-model-picker-toggle"
		title={harnessChosen && harness
			? `${harness.label} (experimental)${harness.resolves ? ` → ${harness.resolves}` : ''}${
					harness.disabledReason ? `. ${harness.disabledReason}` : ''
				}`
			: selectedEntry?.lq_ai_resolves_to
				? `${selectedEntry.id} ${aliasResolution(selectedEntry)}`
				: (selectedEntry?.id ?? 'Select model')}
	>
		<span class="font-medium">Model:</span>
		{#if harnessChosen && harness}
			<span class="ml-1" data-testid="lq-ai-model-picker-harness-selected">{harness.label}</span>
			<span class="ml-1 lq-experimental-chip">experimental</span>
			{#if harness.resolves}
				<span
					class="ml-1 lq-resolution lq-resolution--run"
					data-testid="lq-ai-model-picker-resolution"
				>
					→ {harness.resolves}
				</span>
			{/if}
		{:else}
			<span class="ml-1">{selectedEntry?.id ?? 'smart'}</span>
		{/if}
		{#if !harnessChosen && selectedEntry?.lq_ai_resolves_to}
			<span class="ml-1 lq-resolution" data-testid="lq-ai-model-picker-resolution">
				{aliasResolution(selectedEntry)}
			</span>
		{/if}
		{#if !harnessChosen && selectedEntry?.routed_inference_tier}
			<span class="ml-1 lq-tier-chip" data-testid="lq-ai-model-picker-tier">
				{tierLabel(selectedEntry.routed_inference_tier)}
			</span>
		{/if}
	</button>

	{#if open}
		<div
			class="lq-dropdown absolute z-10 w-72 overflow-auto rounded-md shadow-lg {openUp
				? 'bottom-full mb-1'
				: 'mt-1'}"
			style="max-height: {maxHeight}px"
			data-testid="lq-ai-model-picker-dropdown"
		>
			{#if harness}
				<!-- First in the list, and set apart: it is not a provider model. -->
				<div
					class="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide lq-group-label"
					title={wording.pickerTitle}
				>
					Experimental
				</div>
				<button
					type="button"
					class="lq-option w-full text-left px-3 py-1.5 text-sm flex flex-col items-start {harnessChosen
						? 'lq-option--selected font-semibold'
						: ''}"
					on:click={pickHarness}
					aria-disabled={harness.disabledReason !== null}
					data-testid="lq-ai-model-picker-harness"
				>
					<div class="flex items-center justify-between w-full">
						<span>{harness.label}</span>
						<span class="ml-2 lq-experimental-chip">experimental</span>
					</div>
					{#if harness.resolves}
						<div
							class="text-[10px] lq-mono lq-resolution lq-resolution--run mt-0.5"
							data-testid="lq-ai-model-picker-harness-resolution"
						>
							→ {harness.resolves}
						</div>
					{/if}
					<div class="text-[11px] lq-harness-note mt-0.5">
						{#if harness.disabledReason}
							<span data-testid="lq-ai-model-picker-harness-reason">{harness.disabledReason}</span>
						{:else}
							{wording.pickerNote}
						{/if}
					</div>
				</button>
				<div class="lq-group-rule"></div>
			{/if}

			{#if models.data.length === 0}
				<div class="p-3 text-xs lq-empty" data-testid="lq-ai-model-picker-empty">
					No models available. Check that the Inference Gateway is reachable.
				</div>
			{:else}
				{#if grouped.aliases.length > 0}
					<div
						class="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide lq-group-label"
						title="Convenience defaults — each alias publishes its resolved provider/model below."
					>
						Aliases (defaults)
					</div>
					{#each grouped.aliases as entry (entry.id)}
						<button
							type="button"
							class="lq-option w-full text-left px-3 py-1.5 text-sm flex flex-col items-start {entry.id ===
							selectedId
								? 'lq-option--selected font-semibold'
								: ''}"
							on:click={() => pick(entry)}
							data-testid="lq-ai-model-picker-option"
						>
							<div class="flex items-center justify-between w-full">
								<span>{entry.id}</span>
								{#if entry.routed_inference_tier}
									<span class="ml-2 lq-tier-chip">
										{tierLabel(entry.routed_inference_tier)}
									</span>
								{/if}
							</div>
							{#if entry.lq_ai_resolves_to}
								<div
									class="text-[10px] lq-mono lq-resolution mt-0.5"
									data-testid="lq-ai-model-picker-alias-resolution"
								>
									{aliasResolution(entry)}
								</div>
							{/if}
						</button>
					{/each}
				{/if}

				{#each [...grouped.nativeByProvider.entries()] as [provider, entries] (provider)}
					<div class="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide lq-group-label">
						{provider}
					</div>
					{#each entries as entry (entry.id)}
						<button
							type="button"
							class="lq-option w-full text-left px-3 py-1.5 text-sm flex items-center justify-between {entry.id ===
							selectedId
								? 'lq-option--selected font-semibold'
								: ''}"
							on:click={() => pick(entry)}
							data-testid="lq-ai-model-picker-option"
						>
							<span class="truncate">
								{entry.id.includes('/') ? entry.id.split('/').slice(1).join('/') : entry.id}
							</span>
							{#if entry.routed_inference_tier}
								<span class="ml-2 lq-tier-chip">
									{tierLabel(entry.routed_inference_tier)}
								</span>
							{/if}
						</button>
					{/each}
				{/each}
			{/if}
		</div>
	{/if}
</div>

<style>
	@import '../styles/practice.css';

	/* Trigger pill — slate variant per spec */
	.lq-model-pill {
		background: var(--lq-tier-soft);
		color: var(--lq-tier);
		border: 1px solid var(--lq-tier-border);
		padding: 4px 10px;
		border-radius: var(--lq-radius);
		font-size: 12px;
		font-family: ui-monospace, monospace;
		cursor: pointer;
	}
	.lq-model-pill:hover {
		filter: brightness(0.97);
	}
	.lq-model-pill:focus-visible {
		outline: 2px solid var(--lq-tier);
		outline-offset: 2px;
	}

	.lq-resolution {
		font-size: 10px;
		color: var(--lq-text-tertiary);
	}
	/* Where a run's calls go: a fact to be read, so not in the faint colour. */
	.lq-resolution--run {
		color: var(--lq-text-secondary);
	}

	.lq-tier-chip {
		padding: 1px 4px;
		border-radius: var(--lq-radius-sm);
		background: var(--lq-tier-soft);
		color: var(--lq-tier);
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	/* Dropdown */
	.lq-dropdown {
		border: 1px solid var(--lq-border);
		background: var(--lq-canvas);
	}

	.lq-empty {
		color: var(--lq-text-tertiary);
	}

	.lq-group-label {
		color: var(--lq-text-tertiary);
	}

	.lq-option {
		background: transparent;
		border: 0;
		color: var(--lq-text);
		cursor: pointer;
	}
	.lq-option:hover:not([aria-disabled='true']) {
		background: var(--lq-accent-soft);
	}
	/* Not the `disabled` attribute: the row stays reachable by keyboard and by a
	   screen reader, so the reason it cannot be chosen can be read. */
	.lq-option[aria-disabled='true'] {
		cursor: not-allowed;
		color: var(--lq-text-tertiary);
	}
	.lq-group-rule {
		margin-top: 4px;
		border-top: 1px solid var(--lq-border);
	}
	.lq-experimental-chip {
		padding: 1px 4px;
		border-radius: var(--lq-radius-sm);
		background: var(--lq-warn-soft);
		color: var(--lq-warn);
		border: 1px solid var(--lq-warn-border);
		font-size: 10px;
		font-weight: 400;
		font-family: ui-monospace, monospace;
	}
	.lq-harness-note {
		font-weight: 400;
		color: var(--lq-text-secondary);
		white-space: normal;
	}
	.lq-option--selected {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
	}

	.lq-mono {
		font-family: ui-monospace, monospace;
	}
</style>
