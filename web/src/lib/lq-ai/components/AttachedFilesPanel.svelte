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
	 * Citation evidence is rendered on the resulting assistant message via the
	 * relational citation endpoint. This panel remains focused on attachment
	 * selection/readiness and does not duplicate those evidence links.
	 */
	import type { FileMeta } from '../types';
	import { canAttachChatFile, MAX_DIRECT_CHAT_ATTACHMENTS } from '../chat/messageCreate';

	export let chatFiles: FileMeta[] = [];
	export let projectFiles: FileMeta[] = [];
	export let uploading: boolean = false;
	export let onUpload: (file: File) => void = () => undefined;
	export let onDetach: (file: FileMeta) => void = () => undefined;

	let fileInput: HTMLInputElement;
	$: attachmentLimitReached = !canAttachChatFile(chatFiles.length);

	function handlePicked(event: Event) {
		const input = event.target as HTMLInputElement;
		if (!attachmentLimitReached && input.files && input.files.length > 0) {
			onUpload(input.files[0]);
		}
		input.value = '';
	}

	function statusBadge(status: string | undefined): string {
		switch (status) {
			case 'ready':
				return 'bg-emerald-100 text-emerald-800';
			case 'processing':
				return 'bg-amber-100 text-amber-800';
			case 'failed':
				return 'bg-rose-100 text-rose-800';
			case 'pending':
			default:
				return 'bg-gray-100 text-gray-700';
		}
	}
</script>

<section
	class="lq-files-panel border-l p-3 w-72 flex flex-col gap-3 overflow-y-auto"
	data-testid="lq-ai-attached-files-panel"
>
	<div>
		<h3 class="text-sm font-semibold lq-heading">Attached files</h3>
		<p class="text-xs lq-subtext mt-0.5">Upload documents to ground this chat.</p>
	</div>

	<button
		type="button"
		class="lq-btn-secondary text-sm font-medium disabled:opacity-50"
		on:click={() => fileInput?.click()}
		disabled={uploading || attachmentLimitReached}
		data-testid="lq-ai-upload-btn"
	>
		{uploading ? 'Uploading…' : attachmentLimitReached ? '4-file limit reached' : '+ Files'}
	</button>
	<p class="text-xs lq-subtext">Up to {MAX_DIRECT_CHAT_ATTACHMENTS} files per chat.</p>
	<input
		bind:this={fileInput}
		type="file"
		class="hidden"
		disabled={uploading || attachmentLimitReached}
		on:change={handlePicked}
		data-testid="lq-ai-file-input"
	/>

	{#if chatFiles.length > 0}
		<div>
			<h4 class="text-xs font-medium uppercase tracking-wide text-gray-500 mb-1">This chat</h4>
			<ul class="space-y-1">
				{#each chatFiles as f (f.id)}
					<li class="flex items-start justify-between gap-2 group">
						<div class="text-sm text-gray-800 dark:text-gray-200 truncate">
							<div class="truncate" title={f.filename}>{f.filename}</div>
							<div class="text-xs text-gray-500 flex items-center gap-1">
								<span class="inline-block px-1 py-0.5 rounded {statusBadge(f.ingestion_status)}">
									{f.ingestion_status ?? 'pending'}
								</span>
								<span>{Math.ceil(f.size_bytes / 1024)} KB</span>
							</div>
							{#if f.ingestion_error}
								<div class="text-xs text-rose-600">{f.ingestion_error}</div>
							{/if}
						</div>
						<button
							type="button"
							class="text-xs text-gray-400 hover:text-rose-600 opacity-0 group-hover:opacity-100"
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
			<h4 class="text-xs font-medium uppercase tracking-wide text-gray-500 mb-1">
				From project (read-only here)
			</h4>
			<ul class="space-y-1">
				{#each projectFiles as f (f.id)}
					<li class="text-sm text-gray-700 dark:text-gray-300 truncate" title={f.filename}>
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
</style>
