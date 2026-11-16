<script lang="ts">
	/**
	 * The notification list shown in the right sidebar of the redesigned LQ.AI
	 * shell (interface-redesign work plan, Annex B P1.3b; DE-324), opened from
	 * the left sidebar's bell icon or its Notifications row, only when
	 * Automations is on.
	 *
	 * It renders the state of the same controller the old top bar's bell used
	 * (`createNotificationBell`): the newest unread items, per-item "Mark read",
	 * "Mark shown read", distinct loading, error and empty states, and a link
	 * to the full list in Automations. The controller is created by
	 * `ShellSidebar`, which shares one instance between its two placements and
	 * this list. The old `NotificationBell` dropdown is no longer mounted (P1.3c).
	 */
	import { snippet } from '$lib/lq-ai/autonomous/notification-bell';
	import type { createNotificationBell } from '$lib/lq-ai/autonomous/notification-bell-controller';

	export let bell: ReturnType<typeof createNotificationBell>;

	const VIEW_ALL_HREF = '/lq-ai/autonomous/notifications';
	let rootEl: HTMLDivElement;

	// A row's button disappears once it is read: keep focus inside the list.
	function keepFocus(): void {
		rootEl?.focus();
	}

	function markRead(id: string): void {
		keepFocus();
		void bell.markRead(id);
	}

	function markShownRead(): void {
		keepFocus();
		void bell.markShownRead();
	}

	function retry(): void {
		keepFocus();
		void bell.refresh();
	}

	function formatDate(iso: string): string {
		try {
			return new Intl.DateTimeFormat(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			}).format(new Date(iso));
		} catch {
			return iso;
		}
	}
</script>

<div class="lq-notes" tabindex="-1" bind:this={rootEl} data-testid="lq-shell-notifications-panel">
	<div class="lq-notes-bar">
		<p class="lq-notes-summary">
			{#if $bell.unreadCount > 0}
				{$bell.unreadCount} unread, from your Automations runs
			{:else}
				From your Automations runs
			{/if}
		</p>
		{#if $bell.items.length > 0}
			<button
				type="button"
				class="lq-notes-link-button"
				on:click={markShownRead}
				disabled={$bell.markingAll || $bell.pendingIds.size > 0}
				data-testid="lq-shell-notifications-mark-all"
			>
				{$bell.markingAll ? 'Marking…' : 'Mark shown read'}
			</button>
		{/if}
	</div>

	{#if $bell.status === 'error'}
		<p class="lq-notes-state" role="status">
			Notifications unavailable.
			<button type="button" class="lq-notes-link-button" on:click={retry}>Retry</button>
		</p>
	{/if}
	{#if $bell.actionError}
		<p class="lq-notes-state" role="alert">{$bell.actionError}</p>
	{/if}
	{#if $bell.status === 'loading' && $bell.items.length === 0}
		<p class="lq-notes-state" role="status">Loading notifications…</p>
	{:else if $bell.status === 'ready' && $bell.items.length === 0}
		<p class="lq-notes-state">No unread notifications.</p>
	{/if}

	{#if $bell.items.length > 0}
		<ul class="lq-notes-list" aria-label="Unread notifications">
			{#each $bell.items as notification (notification.id)}
				<li class="lq-notes-item" data-testid="lq-shell-notifications-item">
					<p class="lq-notes-title">{notification.title}</p>
					<p class="lq-notes-text">{snippet(notification.body)}</p>
					<div class="lq-notes-meta">
						<time datetime={notification.created_at} title={notification.created_at}>
							{formatDate(notification.created_at)}
						</time>
						<button
							type="button"
							class="lq-notes-mark"
							on:click={() => markRead(notification.id)}
							disabled={$bell.pendingIds.has(notification.id) || $bell.markingAll}
							aria-label={`${$bell.pendingIds.has(notification.id) ? 'Marking…' : 'Mark read'}: ${notification.title}`}
						>
							{$bell.pendingIds.has(notification.id) ? 'Marking…' : 'Mark read'}
						</button>
					</div>
				</li>
			{/each}
		</ul>
	{/if}

	<a class="lq-notes-all" href={VIEW_ALL_HREF} data-testid="lq-shell-notifications-view-all">
		All notifications, in Automations →
	</a>
</div>

<style>
	.lq-notes {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		padding: var(--lq-space-3) var(--lq-space-4);
		gap: var(--lq-space-2);
		outline: none;
		font-size: 13px;
		color: var(--lq-text);
	}
	.lq-notes-bar {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--lq-space-2);
	}
	.lq-notes-summary,
	.lq-notes-state {
		margin: 0;
		color: var(--lq-text-secondary);
	}
	.lq-notes-link-button {
		border: 0;
		padding: 0;
		background: transparent;
		color: var(--lq-text);
		font: inherit;
		font-weight: 600;
		text-decoration: underline;
		cursor: pointer;
		border-radius: var(--lq-radius-pill);
	}
	.lq-notes-link-button:disabled {
		color: var(--lq-text-secondary);
		cursor: not-allowed;
	}
	.lq-notes-list {
		list-style: none;
		margin: 0;
		padding: 0;
		overflow-y: auto;
		min-height: 0;
	}
	.lq-notes-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--lq-space-3) 0;
		border-bottom: 1px solid var(--lq-border);
	}
	.lq-notes-title {
		margin: 0;
		font-weight: 600;
		word-break: break-word;
	}
	.lq-notes-text {
		margin: 0;
		line-height: 1.4;
		color: var(--lq-text-secondary);
		word-break: break-word;
	}
	.lq-notes-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-2);
		font-size: 12px;
		color: var(--lq-text-secondary);
	}
	.lq-notes-mark {
		padding: 2px 10px;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		background: var(--lq-canvas);
		color: var(--lq-text);
		font: inherit;
		cursor: pointer;
	}
	.lq-notes-mark:hover:not(:disabled) {
		background: var(--lq-surface-hover);
	}
	.lq-notes-mark:disabled {
		color: var(--lq-text-secondary);
		cursor: not-allowed;
	}
	.lq-notes-link-button:focus-visible,
	.lq-notes-mark:focus-visible,
	.lq-notes-all:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.lq-notes-all {
		margin-top: auto;
		padding-top: var(--lq-space-3);
		border-top: 1px solid var(--lq-border);
		color: var(--lq-text);
		font-weight: 600;
		text-decoration: none;
	}
	.lq-notes-all:hover {
		text-decoration: underline;
	}
</style>
