<script lang="ts">
	/**
	 * Sidebar listing chats grouped by Project, with a "no project" bucket.
	 *
	 * - Toggle to include archived projects/chats (default off).
	 * - "+ New Chat" button (per Quickstart Step 4): respects the active
	 *   Project context — the new chat inherits the project_id when one is
	 *   selected.
	 * - Project picker spans across groups; clicking a Project header
	 *   filters the sidebar to that project's chats.
	 */
	import type { Chat, Project } from '../types';

	export let groups: Array<{ project: Project | null; chats: Chat[] }> = [];
	export let activeChatId: string | null = null;
	export let activeProjectId: string | null = null;
	export let archivedToggle: boolean = false;

	export let onSelectChat: (chat: Chat) => void = () => undefined;
	export let onNewChat: () => void = () => undefined;
	export let onSelectProject: (project: Project | null) => void = () => undefined;
	export let onToggleArchived: (next: boolean) => void = () => undefined;

	/**
	 * When true, hides the project-filter UI (the "Projects" label, "All chats"
	 * button, and per-project rows in the sidebar header). Used when ChatPanel
	 * is mounted inside a matter workspace that already represents a single
	 * project context — the user shouldn't see redundant project filtering.
	 */
	export let hideProjectFilter: boolean = false;
</script>

<aside
	class="lq-sidebar w-72 flex flex-col"
	data-testid="lq-ai-chat-sidebar"
>
	<div class="lq-sidebar-header">
		<button
			type="button"
			class="lq-btn-primary w-full inline-flex items-center justify-center"
			on:click={onNewChat}
			data-testid="lq-ai-new-chat-btn"
		>
			+ New Chat
		</button>
	</div>

	{#if !hideProjectFilter}
		<div class="lq-sidebar-section-label">
			<span>Projects</span>
			<label class="inline-flex items-center gap-1 cursor-pointer">
				<input
					type="checkbox"
					bind:checked={archivedToggle}
					on:change={() => onToggleArchived(archivedToggle)}
					data-testid="lq-ai-archived-toggle"
				/>
				<span>Show archived</span>
			</label>
		</div>
	{/if}

	<div class="flex-1 overflow-y-auto">
		{#if !hideProjectFilter}
			<button
				type="button"
				class="lq-project-row {activeProjectId === null ? 'lq-project-row--active' : ''}"
				on:click={() => onSelectProject(null)}
			>
				All chats
			</button>

			{#each groups as group (group.project?.id ?? '__no_project__')}
				<div class="mt-2">
					<button
						type="button"
						class="lq-project-row {activeProjectId === group.project?.id ? 'lq-project-row--active' : ''}"
						on:click={() => onSelectProject(group.project)}
						data-testid={`lq-ai-project-${group.project?.id ?? 'no-project'}`}
					>
						{group.project?.name ?? 'Without a project'}
						{#if group.project?.privileged}
							<span
								class="ml-1 inline-block px-1 py-0.5 rounded text-[10px] font-semibold lq-t-error-soft lq-t-error align-middle"
								title="Privileged matter — minimum_inference_tier enforced"
							>
								PRIVILEGED
							</span>
						{/if}
					</button>
					<ul class="mt-0.5">
						{#each group.chats as chat (chat.id)}
							<li>
								<button
									type="button"
									class="lq-chat-row {activeChatId === chat.id ? 'lq-chat-row--active' : ''}"
									on:click={() => onSelectChat(chat)}
									data-testid={`lq-ai-chat-${chat.id}`}
								>
									{chat.title || 'Untitled chat'}
								</button>
							</li>
						{/each}
					</ul>
				</div>
			{/each}

			{#if groups.length === 0}
				<div class="px-3 py-6 text-sm text-center lq-empty-hint">
					No chats yet. Click <strong>+ New Chat</strong> to start.
				</div>
			{/if}
		{:else}
			{#each groups as group (group.project?.id ?? '__no_project__')}
				<ul class="mt-0.5">
					{#each group.chats as chat (chat.id)}
						<li>
							<button
								type="button"
								class="lq-chat-row {activeChatId === chat.id ? 'lq-chat-row--active' : ''}"
								on:click={() => onSelectChat(chat)}
								data-testid={`lq-ai-chat-${chat.id}`}
							>
								{chat.title || 'Untitled chat'}
							</button>
						</li>
					{/each}
				</ul>
			{/each}

			{#if groups.every((g) => g.chats.length === 0)}
				<div class="px-3 py-6 text-sm text-center lq-empty-hint">
					No chats yet. Click <strong>+ New Chat</strong> to start.
				</div>
			{/if}
		{/if}
	</div>
</aside>

<style>
	@import '../styles/practice.css';

	.lq-sidebar {
		background: var(--lq-inset);
		border-right: 1px solid var(--lq-border);
	}

	.lq-sidebar-header {
		padding: 12px;
		border-bottom: 1px solid var(--lq-border);
	}

	.lq-sidebar-section-label {
		padding: 8px 12px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		font-size: 12px;
		color: var(--lq-text-secondary);
		border-bottom: 1px solid var(--lq-border);
	}

	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:hover {
		filter: brightness(0.95);
	}
	.lq-btn-primary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	.lq-project-row {
		display: block;
		width: 100%;
		text-align: left;
		padding: 4px 12px;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--lq-text-secondary);
		background: transparent;
		border: 0;
		cursor: pointer;
	}
	.lq-project-row:hover {
		background: var(--lq-accent-soft);
	}
	.lq-project-row--active {
		font-weight: 600;
		color: var(--lq-accent);
	}

	.lq-chat-row {
		display: block;
		width: 100%;
		text-align: left;
		padding: 6px 20px;
		font-size: 14px;
		border-radius: 2px;
		color: var(--lq-text);
		background: transparent;
		border: 0;
		cursor: pointer;
	}
	.lq-chat-row:hover {
		background: var(--lq-accent-soft);
	}
	.lq-chat-row--active {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border-left: 2px solid var(--lq-accent);
		padding-left: 18px;
	}

	.lq-empty-hint {
		color: var(--lq-text-tertiary);
	}

	/* Colour tokens replacing Tailwind palette utilities (S1-1b). */
	.lq-t-error {
		color: var(--lq-error);
	}
	.lq-t-error-soft {
		background-color: var(--lq-error-soft);
	}
</style>
