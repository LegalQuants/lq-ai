<script lang="ts">
	/**
	 * Per-chat attached-files panel.
	 *
	 * M1 surface: file picker, upload progress, list of attached files,
	 * detach. Project-attached files (inherited from the chat's Project) are
	 * shown read-only with a tag — those flow through `attached_file_ids`
	 * on the project.
	 *
	 * The file's `ingestion_status` is surfaced (pending / processing /
	 * ready / failed) so the user can see when a file is parseable.
	 *
	 * The citation engine is a future-release item; this panel deliberately
	 * does not surface citation links yet (and the message bubble renders
	 * nothing for empty citation arrays — see MessageBubble's docstring).
	 */
	import type { FileMeta } from '../types';
	import { MAX_CHAT_ATTACHED_FILES } from '../chat/attachedFiles';

	export let chatFiles: FileMeta[] = [];
	/** True while New harness is the chat's model, which uses no skill. */
	export let newHarness = false;
	export let projectFiles: FileMeta[] = [];
	export let uploading: boolean = false;
	// True when the chat already holds MAX_CHAT_ATTACHED_FILES files — the
	// backend rejects sends above the cap, so the attach affordance is
	// disabled with an inline notice instead of failing at send time.
	export let attachLimitReached: boolean = false;
	export let onUpload: (file: File) => void = () => undefined;
	export let onDetach: (file: FileMeta) => void = () => undefined;

	let fileInput: HTMLInputElement;

	function handlePicked(event: Event) {
		const input = event.target as HTMLInputElement;
		if (input.files && input.files.length > 0) {
			onUpload(input.files[0]);
			input.value = '';
		}
	}

	function statusBadge(status: string | undefined): string {
		switch (status) {
			case 'ready':
				return 'lq-t-success-bg lq-t-success';
			case 'processing':
				return 'lq-t-warning-soft lq-t-warning-text';
			case 'failed':
				return 'lq-t-error-soft lq-t-error-strong';
			case 'pending':
			default:
				return 'lq-t-inset lq-t-text2';
		}
	}
</script>

<section
	class="lq-files-panel border-l p-3 w-72 flex flex-col gap-3 overflow-y-auto"
	data-testid="lq-ai-attached-files-panel"
>
	<div>
		<h3 class="text-sm font-semibold lq-heading">Attached files</h3>
		<p class="text-xs lq-subtext mt-0.5">
			{newHarness
				? 'Upload documents for this chat. Pick the ones a request may read above the message box.'
				: 'Upload documents the skill should review.'}
		</p>
	</div>

	<button
		type="button"
		class="lq-btn-secondary text-sm font-medium disabled:opacity-50"
		on:click={() => fileInput?.click()}
		disabled={uploading || attachLimitReached}
		data-testid="lq-ai-upload-btn"
	>
		{uploading ? 'Uploading…' : '+ Files'}
	</button>
	{#if attachLimitReached}
		<p class="text-xs lq-subtext" data-testid="lq-ai-attach-limit-notice">
			Limit of {MAX_CHAT_ATTACHED_FILES} files per chat reached — detach one to add another.
		</p>
	{/if}
	<input
		bind:this={fileInput}
		type="file"
		class="hidden"
		on:change={handlePicked}
		data-testid="lq-ai-file-input"
	/>

	{#if chatFiles.length > 0}
		<div>
			<h4 class="text-xs font-medium uppercase tracking-wide lq-t-text2 mb-1">This chat</h4>
			<ul class="space-y-1">
				{#each chatFiles as f (f.id)}
					<li class="flex items-start justify-between gap-2 group">
						<div class="text-sm lq-t-text truncate">
							<div class="truncate" title={f.filename}>{f.filename}</div>
							<div class="text-xs lq-t-text2 flex items-center gap-1">
								<span class="inline-block px-1 py-0.5 rounded {statusBadge(f.ingestion_status)}">
									{f.ingestion_status ?? 'pending'}
								</span>
								<span>{Math.ceil(f.size_bytes / 1024)} KB</span>
							</div>
							{#if f.ingestion_error}
								<div class="text-xs lq-t-error">{f.ingestion_error}</div>
							{/if}
						</div>
						<button
							type="button"
							class="text-xs lq-t-text3 lq-t-error-hover-text opacity-0 group-hover:opacity-100"
							on:click={() => onDetach(f)}
							title="Detach from this chat"
							data-testid={`lq-ai-detach-${f.id}`}
						>
							Detach
						</button>
					</li>
				{/each}
			</ul>
		</div>
	{/if}

	{#if projectFiles.length > 0}
		<div>
			<h4 class="text-xs font-medium uppercase tracking-wide lq-t-text2 mb-1">
				From project (read-only here)
			</h4>
			<ul class="space-y-1">
				{#each projectFiles as f (f.id)}
					<li class="text-sm lq-t-text2 truncate" title={f.filename}>
						{f.filename}
						<span class="ml-1 inline-block px-1 py-0.5 rounded text-xs {statusBadge(f.ingestion_status)}">
							{f.ingestion_status ?? 'pending'}
						</span>
					</li>
				{/each}
			</ul>
		</div>
	{/if}

	{#if chatFiles.length === 0 && projectFiles.length === 0}
		<p class="text-xs italic lq-subtext">No files attached yet.</p>
	{/if}
</section>

<style>
	@import '../styles/practice.css';

	.lq-files-panel {
		border-color: var(--lq-border);
		background: var(--lq-canvas);
	}

	.lq-heading {
		color: var(--lq-text);
	}

	.lq-subtext {
		color: var(--lq-text-tertiary);
	}

	.lq-btn-secondary {
		background: white;
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius);
		padding: 4px 10px;
		font-size: 13px;
		cursor: pointer;
	}
	.lq-btn-secondary:hover {
		background: var(--lq-accent-soft);
	}
	.lq-btn-secondary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	/* Colour tokens replacing Tailwind palette utilities (S1-1b). */
	.lq-t-error {
		color: var(--lq-error);
	}
	.lq-t-error-hover-text:hover {
		color: var(--lq-error);
	}
	.lq-t-error-soft {
		background-color: var(--lq-error-soft);
	}
	.lq-t-error-strong {
		color: var(--lq-error-text);
	}
	.lq-t-inset {
		background-color: var(--lq-inset);
	}
	.lq-t-success {
		color: var(--lq-success);
	}
	.lq-t-success-bg {
		background-color: var(--lq-success-bg);
	}
	.lq-t-text {
		color: var(--lq-text);
	}
	.lq-t-text2 {
		color: var(--lq-text-secondary);
	}
	.lq-t-text3 {
		color: var(--lq-text-tertiary);
	}
	.lq-t-warning-soft {
		background-color: var(--lq-warning-soft);
	}
	.lq-t-warning-text {
		color: var(--lq-warning-text);
	}
</style>
