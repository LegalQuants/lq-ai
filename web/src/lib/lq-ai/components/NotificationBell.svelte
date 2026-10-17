<script lang="ts">
	/**
	 * NotificationBell — global-chrome bell for autonomous notifications (DE-324).
	 *
	 * Mounted in the /lq-ai shell topbar, gated by the parent layout on
	 * `autonomousChromeEnabled`: a successful preference response for the current
	 * signed-in user must confirm opt-in before this component is mounted.
	 * Cached enabled flags alone emit no bell DOM or notification requests.
	 *
	 * Behavior:
	 *   - Fetches unread notifications (newest first) via
	 *     `GET /autonomous/notifications?unread=true` on mount and after every
	 *     client-side navigation, on opening, and after reads — no polling loop.
	 *   - Badge shows the server-side unread total (`total_count`), capped at
	 *     99+ to mirror the autonomous rail badge.
	 *   - Click → dropdown listing the newest unread items with per-item
	 *     "Mark read" and a "Mark shown read" bulk action (Promise.allSettled,
	 *     mirroring the notifications page), plus a "View all" link to
	 *     /lq-ai/autonomous/notifications.
	 *
	 * Dropdown idiom mirrors `MessageOverflowMenu.svelte` (disclosure widget,
	 * not a WAI-ARIA menu): aria-expanded trigger, Escape-to-close via
	 * svelte:window, close-on-focusout with a tick + requestAnimationFrame
	 * defer so clicks on items register before the focusout teardown.
	 * Loading and unavailable states remain distinct from an empty inbox; failed
	 * reads remain retryable. Async list responses are ordered against reads.
	 */
	import { onDestroy, onMount, tick } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { autonomousApi } from '$lib/lq-ai/api';
	import { badgeText, snippet } from '$lib/lq-ai/autonomous/notification-bell';
	import { createNotificationBell } from '$lib/lq-ai/autonomous/notification-bell-controller';

	const VIEW_ALL_HREF = '/lq-ai/autonomous/notifications';
	const bell = createNotificationBell(autonomousApi);
	let open = false;
	let rootEl: HTMLDivElement;
	let triggerEl: HTMLButtonElement;

	$: badge = badgeText($bell.unreadCount);
	$: triggerLabel =
		$bell.unreadCount > 0 ? `Notifications, ${$bell.unreadCount} unread` : 'Notifications';

	afterNavigate(() => {
		open = false;
		void bell.refresh();
	});
	// Preference confirmation can mount this component after the initial navigation
	// callbacks have already run, so initial loading cannot rely on afterNavigate.
	onMount(() => void bell.refresh());
	onDestroy(() => bell.destroy());

	function toggle(): void {
		open = !open;
		if (open) void bell.refresh();
	}

	async function handleFocusout(): Promise<void> {
		await tick();
		requestAnimationFrame(() => {
			if (rootEl && !rootEl.contains(document.activeElement)) open = false;
		});
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (open && e.key === 'Escape') {
			open = false;
			triggerEl?.focus();
		}
	}

	function handleMarkRead(id: string): void {
		// Keep focus inside the disclosure when a pending/removed row loses its button.
		triggerEl?.focus();
		void bell.markRead(id);
	}

	function handleMarkAllRead(): void {
		triggerEl?.focus();
		void bell.markShownRead();
	}

	function handleRetry(): void {
		// The retry control disappears after success; retain disclosure focus.
		triggerEl?.focus();
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

<svelte:window on:keydown={handleKeydown} />

<div
	class="bell"
	bind:this={rootEl}
	on:focusout={handleFocusout}
	data-testid="lq-ai-notification-bell"
>
	<button
		type="button"
		class="trigger"
		aria-label={triggerLabel}
		aria-expanded={open}
		data-testid="lq-ai-notification-bell-trigger"
		bind:this={triggerEl}
		on:click={toggle}
	>
		<span class="bell-icon" aria-hidden="true">🔔</span>
		{#if badge !== null}
			<span class="unread-badge" aria-hidden="true" data-testid="lq-ai-notification-bell-badge">
				{badge}
			</span>
		{/if}
	</button>

	{#if open}
		<div class="dropdown" data-testid="lq-ai-notification-bell-dropdown">
			<div class="dropdown-header">
				<span class="dropdown-title">Notifications</span>
				{#if $bell.items.length > 0}
					<button
						type="button"
						class="mark-all"
						on:click={handleMarkAllRead}
						disabled={$bell.markingAll || $bell.pendingIds.size > 0}
						aria-label="Mark shown notifications as read"
					>
						{$bell.markingAll ? 'Marking…' : 'Mark shown read'}
					</button>
				{/if}
			</div>

			{#if $bell.status === 'error'}
				<p class="empty" role="status">
					Notifications unavailable. <button type="button" on:click={handleRetry}>Retry</button>
				</p>
			{/if}
			{#if $bell.actionError}
				<p class="empty" role="alert">{$bell.actionError}</p>
			{/if}
			{#if $bell.status === 'loading' && $bell.items.length === 0}
				<p class="empty" role="status">Loading notifications…</p>
			{:else if $bell.status === 'ready' && $bell.items.length === 0}
				<p class="empty">No unread notifications.</p>
			{/if}
			{#if $bell.items.length > 0}
				<ul class="items" aria-label="Unread notifications">
					{#each $bell.items as notification (notification.id)}
						<li class="item">
							<div class="item-body">
								<div class="item-header-row">
									<span class="item-title">{notification.title}</span>
									<time
										class="item-date"
										datetime={notification.created_at}
										title={notification.created_at}
									>
										{formatDate(notification.created_at)}
									</time>
								</div>
								<p class="item-text">{snippet(notification.body)}</p>
							</div>
							<button
								type="button"
								class="mark-read"
								on:click={() => handleMarkRead(notification.id)}
								disabled={$bell.pendingIds.has(notification.id) || $bell.markingAll}
								aria-label={`Mark "${notification.title}" as read`}
							>
								{$bell.pendingIds.has(notification.id) ? 'Marking…' : 'Mark read'}
							</button>
						</li>
					{/each}
				</ul>
			{/if}

			<div class="dropdown-footer">
				<a class="view-all" href={VIEW_ALL_HREF} on:click={() => (open = false)}>
					View all notifications
				</a>
			</div>
		</div>
	{/if}
</div>

<style>
	.bell {
		position: relative;
		display: inline-block;
	}

	/* Trigger mirrors the topbar's ⚙ settings affordance + MessageOverflowMenu trigger. */
	.trigger {
		position: relative;
		background: transparent;
		border: 0;
		padding: var(--lq-space-1) var(--lq-space-2);
		cursor: pointer;
		color: var(--lq-text-secondary);
		font-size: 16px;
		line-height: 1;
		border-radius: var(--lq-radius-sm, 4px);
	}

	.trigger:hover {
		background: var(--lq-inset, #fafbfa);
		color: var(--lq-text);
	}

	.trigger:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}

	/* Badge mirrors .nav-unread-badge in autonomous/+layout.svelte. */
	.unread-badge {
		position: absolute;
		top: -4px;
		right: -6px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: 9px;
		font-size: 11px;
		font-weight: 600;
		line-height: 1;
		background: var(--lq-accent);
		color: white;
	}

	/* Dropdown surface mirrors MessageOverflowMenu's .menu. */
	.dropdown {
		position: absolute;
		right: 0;
		top: 100%;
		margin-top: var(--lq-space-1);
		width: 340px;
		/* Reserve the shell's trailing Settings control and page padding on phones. */
		max-width: calc(100vw - 5 * var(--lq-space-4));
		background: var(--lq-canvas, #ffffff);
		border: 1px solid var(--lq-border, #e5e7eb);
		border-radius: var(--lq-radius, 6px);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
		z-index: 10;
	}

	.dropdown-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-3);
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
	}

	.dropdown-title {
		font-size: 13px;
		font-weight: 600;
		color: var(--lq-text);
	}

	.mark-all {
		background: transparent;
		border: 0;
		padding: 2px 4px;
		font-size: 12px;
		font-weight: 500;
		color: var(--lq-accent);
		cursor: pointer;
		border-radius: var(--lq-radius-sm, 4px);
		white-space: nowrap;
	}

	.mark-all:hover:not(:disabled) {
		background: var(--lq-inset, #fafbfa);
	}

	.mark-all:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.empty {
		margin: 0;
		padding: var(--lq-space-4) var(--lq-space-3);
		font-size: 13px;
		font-style: italic;
		color: var(--lq-text-secondary);
	}

	.items {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 320px;
		overflow-y: auto;
	}

	.item {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-2);
		padding: var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
	}

	.item:last-child {
		border-bottom: none;
	}

	.item-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.item-header-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--lq-space-2);
	}

	.item-title {
		font-size: 13px;
		font-weight: 600;
		color: var(--lq-text);
		word-break: break-word;
	}

	.item-date {
		font-size: 11px;
		color: var(--lq-text-tertiary);
		white-space: nowrap;
	}

	.item-text {
		margin: 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--lq-text-secondary);
		word-break: break-word;
	}

	.mark-read {
		flex-shrink: 0;
		padding: 2px 8px;
		border-radius: var(--lq-radius-sm, 4px);
		font-size: 12px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
		white-space: nowrap;
		transition: background 0.1s;
	}

	.mark-read:hover:not(:disabled) {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.mark-read:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.dropdown-footer {
		border-top: 1px solid var(--lq-border);
		padding: var(--lq-space-2) var(--lq-space-3);
		text-align: center;
	}

	.view-all {
		font-size: 13px;
		font-weight: 500;
		color: var(--lq-accent);
		text-decoration: none;
	}

	.view-all:hover {
		text-decoration: underline;
	}

	.view-all:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
		border-radius: var(--lq-radius-sm, 4px);
	}
</style>
