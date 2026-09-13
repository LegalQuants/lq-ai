<script lang="ts">
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';
	import { skillsApi } from '$lib/lq-ai/api';
	import type { SkillInputs, SkillInputDef } from '$lib/lq-ai/types';

	export let slug: string;
	export let contentMd: string;
	export let contentYaml: string;

	let inputs: SkillInputs | null = null;
	let inputsError: string | null = null;
	let inputsLoading = true;

	let copyLabel = 'Copy raw';

	async function loadInputs(): Promise<void> {
		inputsLoading = true;
		inputsError = null;
		try {
			inputs = await skillsApi.getInputs(slug);
		} catch (e) {
			inputsError = e instanceof Error ? e.message : 'Failed to load inputs';
		} finally {
			inputsLoading = false;
		}
	}

	async function copyRaw(): Promise<void> {
		try {
			await navigator.clipboard.writeText(contentYaml);
			copyLabel = 'Copied!';
			setTimeout(() => {
				copyLabel = 'Copy raw';
			}, 1500);
		} catch {
			copyLabel = 'Copy failed';
		}
	}

	function typeLabel(def: SkillInputDef): string {
		if (def.type === 'enum' && def.enum && def.enum.length > 0) {
			return `enum: ${def.enum.join(' | ')}`;
		}
		return def.type ?? 'string';
	}

	// Skill bodies are authored content — team-scope skills and, for built-in
	// skills, the `skills/community` git submodule — so the raw HTML that marked
	// passes through MUST be DOMPurify-sanitized before {@html} below, or a
	// crafted body runs script in the viewer's session (stored XSS). Mirrors
	// the DOMPurify pattern used for assistant markdown in MessageBubble.
	// #288 (D-01).
	$: renderedMd = DOMPurify.sanitize(marked(contentMd ?? '', { breaks: true }) as string);

	onMount(() => {
		loadInputs();
	});
</script>

<div class="lq-source-view">
	<section class="lq-source-section">
		<div class="lq-source-section-header">
			<h2 class="lq-text-label">Frontmatter</h2>
			<button type="button" class="lq-copy-btn" on:click={copyRaw}>{copyLabel}</button>
		</div>
		<pre class="lq-yaml-block">{contentYaml}</pre>
	</section>

	<section class="lq-source-section">
		<h2 class="lq-text-label">Body</h2>
		<div class="lq-prose">
			{@html renderedMd}
		</div>
	</section>

	<section class="lq-source-section">
		<h2 class="lq-text-label">Inputs</h2>
		{#if inputsLoading}
			<p class="lq-text-body" style="color: var(--lq-text-secondary);">Loading inputs…</p>
		{:else if inputsError}
			<p class="lq-text-body" style="color: var(--lq-error);">{inputsError}</p>
		{:else if inputs && (inputs.required.length > 0 || inputs.optional.length > 0)}
			{#if inputs.required.length > 0}
				<h3 class="lq-text-label lq-inputs-subhead">Required</h3>
				<ul class="lq-inputs-list">
					{#each inputs.required as def (def.name)}
						<li class="lq-input-row">
							<code class="lq-input-name">{def.name}</code>
							<span class="lq-input-type">{typeLabel(def)}</span>
							<span class="lq-pill lq-pill-required">required</span>
							{#if def.description}
								<span class="lq-input-desc">{def.description}</span>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
			{#if inputs.optional.length > 0}
				<h3 class="lq-text-label lq-inputs-subhead">Optional</h3>
				<ul class="lq-inputs-list">
					{#each inputs.optional as def (def.name)}
						<li class="lq-input-row">
							<code class="lq-input-name">{def.name}</code>
							<span class="lq-input-type">{typeLabel(def)}</span>
							<span class="lq-pill lq-pill-optional">optional</span>
							{#if def.description}
								<span class="lq-input-desc">{def.description}</span>
							{/if}
							{#if def.default !== undefined && def.default !== null && def.default !== ''}
								<span class="lq-input-default">default: <code>{String(def.default)}</code></span>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		{:else}
			<p class="lq-text-body" style="color: var(--lq-text-secondary);">(This skill declares no inputs.)</p>
		{/if}
	</section>
</div>

<style>
	.lq-source-view {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-6);
	}

	.lq-source-section {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.lq-source-section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.lq-yaml-block {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-3) var(--lq-space-4);
		font-family: monospace;
		font-size: 13px;
		white-space: pre-wrap;
		overflow-x: auto;
		color: var(--lq-text);
		margin: 0;
	}

	.lq-copy-btn {
		background: transparent;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: 4px 10px;
		font-size: 12px;
		color: var(--lq-text-secondary);
		cursor: pointer;
	}
	.lq-copy-btn:hover {
		background: var(--lq-inset);
	}

	.lq-prose {
		font-size: 14px;
		line-height: 1.6;
		color: var(--lq-text);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-4);
		background: var(--lq-surface);
	}
	:global(.lq-prose h1, .lq-prose h2, .lq-prose h3) {
		font-weight: 600;
		margin-top: 1em;
		margin-bottom: 0.5em;
		color: var(--lq-text);
	}
	:global(.lq-prose p) {
		margin-bottom: 0.75em;
	}
	:global(.lq-prose ul, .lq-prose ol) {
		padding-left: 1.5em;
		margin-bottom: 0.75em;
	}
	:global(.lq-prose code) {
		font-family: monospace;
		font-size: 0.9em;
		background: var(--lq-inset);
		padding: 1px 4px;
		border-radius: 3px;
	}
	:global(.lq-prose pre) {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-3);
		overflow-x: auto;
		margin-bottom: 0.75em;
	}

	.lq-inputs-subhead {
		margin-top: var(--lq-space-3);
		color: var(--lq-text-secondary);
	}

	.lq-inputs-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.lq-input-row {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
		padding: var(--lq-space-2) var(--lq-space-3);
		background: var(--lq-inset);
		border-radius: var(--lq-radius);
		border: 1px solid var(--lq-border);
	}

	.lq-input-name {
		font-family: monospace;
		font-size: 13px;
		font-weight: 600;
		color: var(--lq-text);
	}

	.lq-input-type {
		font-size: 12px;
		color: var(--lq-text-secondary);
	}

	.lq-input-desc {
		font-size: 13px;
		color: var(--lq-text-secondary);
		flex-basis: 100%;
		margin-top: 2px;
	}

	.lq-input-default {
		font-size: 12px;
		color: var(--lq-text-tertiary);
	}

	.lq-pill {
		display: inline-flex;
		align-items: center;
		padding: 2px 7px;
		border-radius: var(--lq-radius-pill, 9999px);
		font-size: 11px;
		font-weight: 500;
	}

	.lq-pill-required {
		background: var(--lq-accent-soft, rgba(79, 70, 229, 0.1));
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent);
	}

	.lq-pill-optional {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
	}
</style>
