<script context="module" lang="ts">
	/**
	 * Pure copy helper exported for unit tests — accessible without
	 * @testing-library/svelte (mirrors the ToolGatePrompt / RefusalMessageBubble
	 * pattern; per CLAUDE.md "Don't add libraries without justification").
	 */

	/** Pill copy helper — singular/plural count of external sources consulted. */
	export function sourcesPillLabel(n: number): string {
		return `${n} source${n === 1 ? '' : 's'} consulted`;
	}
</script>

<script lang="ts">
	import { IconScale, IconChevronUp, IconChevronDown } from '@tabler/icons-svelte';
	import type { ToolSource } from '../types';

	/** External-source provenance rows for this message. Empty → renders nothing. */
	export let sources: ToolSource[] = [];

	/** Starts collapsed; user expands to see the full list. */
	let expanded = false;
</script>

{#if sources.length > 0}
	<div class="lq-sources" data-testid="lq-ai-tool-sources">
		<button
			type="button"
			class="lq-sources-header"
			data-testid="lq-ai-tool-sources-toggle"
			on:click={() => (expanded = !expanded)}
			aria-expanded={expanded}
		>
			<span class="lq-sources-icon" aria-hidden="true"><IconScale size={14} stroke={1.75} aria-hidden="true" /></span>
			<span class="lq-sources-label">Sources consulted ({sources.length})</span>
			<span class="lq-sources-chevron" aria-hidden="true"
				>{#if expanded}<IconChevronUp size={14} stroke={1.75} aria-hidden="true" />{:else}<IconChevronDown size={14} stroke={1.75} aria-hidden="true" />{/if}</span
			>
		</button>
		{#if expanded}
			<ul class="lq-sources-list" data-testid="lq-ai-tool-sources-list">
				{#each sources as s (s.id)}
					<li class="lq-source-row" data-testid="lq-ai-tool-source-row">
						<span class="lq-source-label">{s.label}</span>
						{#if s.subtitle}
							<span class="lq-source-sub">{s.subtitle}</span>
						{/if}
						{#if s.url}
							<a
								class="lq-source-link"
								href={s.url}
								target="_blank"
								rel="noopener"
							>View on CourtListener ↗</a>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
{/if}

<style>
	/* Mirror M2Citations' sidecar styling — muted card, small text.
	   Container/header/list chrome adapted from .lq-m2-citations. */
	.lq-sources {
		font-size: 12px;
		line-height: 1.4;
		margin-top: 8px;
		border: 1px solid rgba(107, 114, 128, 0.24);
		border-radius: 6px;
		overflow: hidden;
	}

	.lq-sources-header {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 6px 10px;
		background: rgba(107, 114, 128, 0.06);
		border: none;
		cursor: pointer;
		font: inherit;
		font-size: 12px;
		font-weight: 500;
		color: var(--lq-text-secondary); /* gray-600 */
		text-align: left;
		transition: background-color 0.15s ease;
	}
	.lq-sources-header:hover {
		background: rgba(107, 114, 128, 0.12);
	}
	.lq-sources-header:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: -2px;
	}

	.lq-sources-icon {
		flex-shrink: 0;
	}
	.lq-sources-label {
		flex: 1;
	}
	.lq-sources-chevron {
		font-size: 10px;
		opacity: 0.6;
		flex-shrink: 0;
	}

	.lq-sources-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.lq-source-row {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 6px 10px;
		border-top: 1px solid rgba(107, 114, 128, 0.16);
		font-size: 12px;
	}
	.lq-source-row:first-child {
		border-top: none;
	}

	.lq-source-label {
		font-weight: 600;
		color: var(--lq-text);
	}

	.lq-source-sub {
		color: var(--lq-text-tertiary);
		font-size: 11px;
	}

	.lq-source-link {
		color: var(--lq-accent);
		text-decoration: underline;
		font-size: 11px;
	}
	.lq-source-link:hover {
		text-decoration: underline;
	}
</style>
