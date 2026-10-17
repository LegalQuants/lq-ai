<script context="module" lang="ts">
	import { getSkillContents, type ReferenceRange } from '../api/skills';
	import type { SkillReferencePage } from '../types';

	export type ResourceContentsResult =
		| { contents: SkillReferencePage[]; error: null }
		| { contents: null; error: string };

	/** Human inspection remains available when the model's reference-read tool is disabled. */
	export async function loadResourceContents(
		slug: string,
		range?: ReferenceRange
	): Promise<ResourceContentsResult> {
		try {
			const skill = await getSkillContents(slug, range);
			return { contents: skill.on_demand_contents ?? [], error: null };
		} catch (e) {
			return {
				contents: null,
				error: e instanceof Error ? e.message : 'Failed to load references'
			};
		}
	}

	export function modelReadLabel(enabled: boolean | undefined): string {
		return enabled === true
			? 'The model can read these references when needed.'
			: enabled === false
				? 'Model reading is disabled for this deployment. You can still inspect the references here.'
				: 'Model reading availability could not be determined.';
	}
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import type { SkillResourceFile } from '../types';

	export let slug: string;
	export let files: SkillResourceFile[] = [];
	export let referenceReadEnabled: boolean | undefined = undefined;

	let contents: SkillReferencePage[] | null = null;
	let error: string | null = null;
	let loading = false;

	async function load(): Promise<void> {
		loading = true;
		error = null;
		const result = await loadResourceContents(slug);
		contents = result.contents;
		error = result.error;
		loading = false;
	}

	let paging: string | null = null;
	let pageErrors: Record<string, string> = {};

	async function readPortion(source: SkillReferencePage, offset: number): Promise<void> {
		paging = source.path;
		pageErrors = { ...pageErrors, [source.path]: '' };
		const result = await loadResourceContents(slug, {
			path: source.path,
			offset_bytes: offset,
			expected_sha256: source.sha256
		});
		const page = result.contents?.find((entry) => entry.path === source.path);
		if (page) contents = (contents ?? []).map((entry) => (entry.path === page.path ? page : entry));
		else
			pageErrors = {
				...pageErrors,
				[source.path]: result.error ?? 'Reference is no longer available. Reload the skill.'
			};
		paging = null;
	}

	onMount(() => {
		if (files.length > 0) void load();
	});
</script>

<section class="resources" aria-label="On-demand references">
	<h2 class="lq-text-label">On-demand references</h2>
	<p class="lq-text-body note">{modelReadLabel(referenceReadEnabled)}</p>
	<p class="lq-text-caption note">
		These are separate from references included in every use of the skill. Currently available: up
		to 64 text files in the skill's references folder. Files of any size remain listed; each read
		returns at most 64 KiB. Request another portion when needed. Other bundled paths are not
		available for on-demand reading yet.
	</p>
	{#if files.length === 0}
		<p class="lq-text-body note">This skill has no on-demand references.</p>
	{:else}
		{#if loading}
			<p class="lq-text-body note" role="status">Loading reference contents…</p>
		{:else if error}
			<p class="lq-text-body error" role="alert">Couldn't load reference contents: {error}</p>
			<button type="button" on:click={load}>Retry</button>
		{/if}
		{#each files as file (file.path)}
			<details>
				<summary
					>{file.path} <span class="note">({file.size_bytes.toLocaleString()} bytes)</span></summary
				>
				{#if contents}
					{@const source = contents.find((entry) => entry.path === file.path)}
					{#if source}
						{#if source.size_bytes !== undefined}
							<p class="lq-text-caption note" role="status">
								Bytes {source.offset_bytes.toLocaleString()}–{source.end_offset_bytes.toLocaleString()}
								(end exclusive) of {source.size_bytes.toLocaleString()}.
								{source.has_more ? 'More remains.' : 'End of file.'}
							</p>
						{/if}
						<pre>{source.content}</pre>
						{#if pageErrors[source.path]}
							<p class="error" role="alert">{pageErrors[source.path]}</p>
						{/if}
						{#if source.has_more && source.next_offset_bytes !== null}
							<button
								type="button"
								disabled={paging !== null}
								on:click={() => readPortion(source, source.next_offset_bytes ?? 0)}
							>
								{paging === source.path ? 'Loading…' : 'Read next portion'}
							</button>
						{/if}
						{#if source.offset_bytes > 0}
							<button
								type="button"
								disabled={paging !== null}
								on:click={() => readPortion(source, 0)}>Read first portion</button
							>
						{/if}
					{:else}
						<p class="lq-text-body note">
							This reference is no longer available. Reload the skill to refresh its file list.
						</p>
					{/if}
				{:else}
					<p class="lq-text-body note">{loading ? 'Loading…' : 'Contents are unavailable.'}</p>
				{/if}
			</details>
		{/each}
	{/if}
</section>

<style>
	.resources {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}
	.note {
		color: var(--lq-text-secondary);
	}
	.error {
		color: var(--lq-error);
	}
	summary {
		cursor: pointer;
		overflow-wrap: anywhere;
		padding: var(--lq-space-2) 0;
	}
	pre {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-3);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		color: var(--lq-text);
		font-size: 13px;
	}
	button {
		align-self: flex-start;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: 4px 10px;
		color: var(--lq-text);
		background: var(--lq-surface);
	}
</style>
