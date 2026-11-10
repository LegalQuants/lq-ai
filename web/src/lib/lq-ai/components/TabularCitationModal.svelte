<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import type { TabularCellResult } from '$lib/lq-ai/types';
	import { citationPassage } from './tabular-citation';

	export let documentName: string;
	export let columnName: string;
	export let cell: TabularCellResult;

	let dialog: HTMLDialogElement;
	const dispatch = createEventDispatcher<{ close: void }>();

	onMount(() => {
		dialog.showModal();
		return () => dialog.close();
	});

	function close(): void {
		dialog.close();
		dispatch('close');
	}

	function backdropClick(event: MouseEvent): void {
		if (event.target !== dialog) return;
		const bounds = dialog.getBoundingClientRect();
		if (
			event.clientX < bounds.left ||
			event.clientX > bounds.right ||
			event.clientY < bounds.top ||
			event.clientY > bounds.bottom
		)
			close();
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key !== 'Tab') return;
		const controls = dialog.querySelectorAll<HTMLElement>('button, summary');
		const first = controls[0];
		const last = controls[controls.length - 1];
		if (event.shiftKey && event.target === first) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && event.target === last) {
			event.preventDefault();
			first.focus();
		}
	}
</script>

<dialog
	bind:this={dialog}
	class="lq-tabcm"
	aria-labelledby="lq-tabcm-title"
	data-testid="lq-tabcm"
	on:cancel|preventDefault={close}
	on:click={backdropClick}
	on:keydown={handleKeydown}
>
	<header class="lq-tabcm__header">
		<div>
			<h2 id="lq-tabcm-title">{columnName}</h2>
			<p class="lq-tabcm__document">{documentName}</p>
		</div>
		<button
			type="button"
			class="lq-tabcm__close"
			data-testid="lq-tabcm-close"
			on:click={close}
			aria-label="Close citations">×</button
		>
	</header>

	<section class="lq-tabcm__body">
		{#if cell.confidence === 'failed'}
			<p class="lq-tabcm__failed"><strong>Not found.</strong> Extraction failed for this cell.</p>
			{#if cell.error}
				<pre class="lq-tabcm__error" data-testid="lq-tabcm-error">{cell.error}</pre>
			{/if}
		{:else}
			<dl class="lq-tabcm__meta">
				<div class="lq-tabcm__value">
					<dt>Extracted value</dt>
					<dd data-testid="lq-tabcm-value">{cell.value ?? '—'}</dd>
				</div>
				<div>
					<dt>Extraction confidence</dt>
					<dd>{cell.confidence}</dd>
				</div>
				{#if cell.tier_used !== null && cell.tier_used !== undefined}
					<div>
						<dt>Inference tier</dt>
						<dd>Tier {cell.tier_used}</dd>
					</div>
				{/if}
			</dl>
		{/if}

		<h3>Supporting source</h3>
		{#if cell.citations.length === 0}
			<p class="lq-tabcm__empty">
				No citations were attached to this cell. This value has no verified source location.
			</p>
		{:else}
			<ul class="lq-tabcm__cites" data-testid="lq-tabcm-citations">
				{#each cell.citations as cite (cite.citation_id)}
					{@const passage = citationPassage(cite)}
					<li class="lq-tabcm__cite">
						<div class="lq-tabcm__source-label">
							<strong>{documentName}</strong>{#if cite.source_page != null}<span
									>Page {cite.source_page}</span
								>{/if}
						</div>
						{#if cite.source_text}
							<blockquote class="lq-tabcm__passage" data-testid="lq-tabcm-source">
								{#if passage}{passage.before}<mark>{passage.match}</mark
									>{passage.after}{:else}{cite.source_text}{/if}
							</blockquote>
						{:else}
							<p class="lq-tabcm__empty">Source text is unavailable for this citation.</p>
						{/if}
						{#if passage}<p class="lq-tabcm__location">
								Highlighted text is the located source span.
							</p>{/if}
						<details class="lq-tabcm__details">
							<summary>Citation details</summary>
							<dl>
								<div>
									<dt>Citation</dt>
									<dd><code>{cite.citation_id}</code></dd>
								</div>
								<div>
									<dt>Document</dt>
									<dd><code>{cite.document_id}</code></dd>
								</div>
								{#if cite.chunk_id}<div>
										<dt>Chunk</dt>
										<dd><code>{cite.chunk_id}</code></dd>
									</div>{/if}
								{#if cite.verification_method}<div>
										<dt>Verification</dt>
										<dd>{cite.verification_method.replaceAll('_', ' ')}</dd>
									</div>{/if}
							</dl>
						</details>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</dialog>

<style>
	.lq-tabcm {
		width: min(44rem, calc(100% - 2rem));
		max-width: none;
		max-height: calc(100dvh - 2rem);
		margin: auto;
		padding: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		background: var(--lq-canvas, #fff);
		color: var(--lq-text, #1a1a1a);
		font-family: var(--lq-font-sans);
		font-size: 0.875rem;
		line-height: 1.5;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg, 8px);
		box-shadow: 0 24px 64px rgb(0 0 0 / 0.2);
	}
	.lq-tabcm::backdrop {
		background: rgb(15 23 42 / 0.55);
	}
	.lq-tabcm__header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		padding: 1.25rem;
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-tabcm h2 {
		margin: 0;
		font-size: 1rem;
		font-weight: 600;
	}
	.lq-tabcm__document {
		margin: 0.25rem 0 0;
		color: var(--lq-text-secondary);
		overflow-wrap: anywhere;
	}
	.lq-tabcm__close {
		display: grid;
		place-items: center;
		flex-shrink: 0;
		width: 2rem;
		height: 2rem;
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		font: inherit;
		font-size: 1.5rem;
		cursor: pointer;
	}
	.lq-tabcm__close:focus-visible,
	.lq-tabcm summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.lq-tabcm__body {
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.lq-tabcm__failed {
		padding: 0.75rem;
		background: var(--lq-warn-soft);
		border: 1px solid var(--lq-warn-border);
		border-radius: var(--lq-radius);
		margin: 0;
	}
	.lq-tabcm__error {
		margin: 0;
		padding: 0.75rem;
		background: var(--lq-inset);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.lq-tabcm__meta {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
		margin: 0;
	}
	.lq-tabcm__value {
		grid-column: 1 / -1;
	}
	.lq-tabcm dt {
		color: var(--lq-text-secondary);
		font-size: 0.8125rem;
	}
	.lq-tabcm dd {
		margin: 0.25rem 0 0;
		overflow-wrap: anywhere;
	}
	.lq-tabcm__value dd {
		font-weight: 600;
	}
	.lq-tabcm h3 {
		margin: 0;
		font-size: 0.875rem;
		font-weight: 600;
	}
	.lq-tabcm__empty {
		margin: 0;
		color: var(--lq-text-secondary);
	}
	.lq-tabcm__cites {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.lq-tabcm__cite {
		padding: 1rem;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		background: var(--lq-inset);
	}
	.lq-tabcm__source-label {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 0.5rem;
		overflow-wrap: anywhere;
	}
	.lq-tabcm__source-label span,
	.lq-tabcm__location {
		color: var(--lq-text-secondary);
		font-size: 0.8125rem;
	}
	.lq-tabcm__passage {
		margin: 0.75rem 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		line-height: 1.65;
	}
	.lq-tabcm mark {
		background: var(--lq-accent-soft);
		color: var(--lq-text);
		font-weight: 600;
		padding: 0.125rem 0;
		text-decoration: underline;
		text-decoration-color: var(--lq-accent);
		text-underline-offset: 0.2em;
	}
	.lq-tabcm__location {
		margin: 0 0 0.75rem;
	}
	.lq-tabcm__details {
		border-top: 1px solid var(--lq-border);
		padding-top: 0.75rem;
		font-size: 0.8125rem;
	}
	.lq-tabcm summary {
		cursor: pointer;
		color: var(--lq-text-secondary);
	}
	.lq-tabcm__details dl {
		display: grid;
		gap: 0.5rem;
		margin: 0.75rem 0 0;
	}
	.lq-tabcm code {
		font-size: 0.75rem;
	}
	@media (max-width: 480px) {
		.lq-tabcm__header,
		.lq-tabcm__body {
			padding: 1rem;
		}
		.lq-tabcm__cite {
			padding: 0.75rem;
		}
	}
</style>
