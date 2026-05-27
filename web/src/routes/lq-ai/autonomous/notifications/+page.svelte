<script lang="ts">
	/**
	 * /lq-ai/autonomous/notifications — M4-C2 Task 17.
	 *
	 * In-app notification surface for LQVern autonomous layer events.
	 * Email delivery is handled server-side (M4-C1); this page is the durable
	 * in-app record. "Mark read" (read_at) is the dismiss action.
	 *
	 * Behavior:
	 *   - List all notifications (newest first, default).
	 *   - Unread rows (read_at == null) visually distinct: accent dot + bold title.
	 *   - Click unread row OR "Mark read" button → readNotification(id) → reload.
	 *   - "Mark all read" button: Promise.allSettled over unread ids → reload.
	 *   - "Unread only" toggle using listNotifications(true).
	 *
	 * Structure mirrors watches/+page.svelte (Task 16):
	 *   onMount → load(), loading/error/success banners, LQAIApiError, per-row pending.
	 *
	 * The global-chrome bell is explicitly deferred (DE-324). This page + the rail
	 * badge (in +layout.svelte) are the only notification surfaces in this iteration.
	 */
	import { onMount } from 'svelte';

	import { autonomousApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { AutonomousNotificationRead } from '$lib/lq-ai/api/autonomous';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let notifications: AutonomousNotificationRead[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	/** Whether the "Unread only" filter is active. */
	let unreadOnly = false;

	/** Map of notification id → pending action label. */
	let pendingIds: Map<string, string> = new Map();

	/** Whether mark-all-read is in progress. */
	let markingAllRead = false;

	// ---------------------------------------------------------------------------
	// Load
	// ---------------------------------------------------------------------------

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			const resp = await autonomousApi.listNotifications(unreadOnly || undefined);
			notifications = resp.notifications;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need to enable autonomous mode to view notifications.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Derived helpers
	// ---------------------------------------------------------------------------

	$: unreadNotifications = notifications.filter((n) => n.read_at === null);
	$: hasUnread = unreadNotifications.length > 0;

	// ---------------------------------------------------------------------------
	// Row action: mark single notification read
	// ---------------------------------------------------------------------------

	async function handleMarkRead(notification: AutonomousNotificationRead): Promise<void> {
		if (notification.read_at !== null) return; // already read — no-op
		pendingIds = new Map(pendingIds).set(notification.id, 'marking');
		actionError = null;
		actionSuccess = null;
		try {
			await autonomousApi.readNotification(notification.id);
			actionSuccess = `"${notification.title}" marked as read.`;
			await load();
		} catch (err) {
			if (err instanceof LQAIApiError) {
				actionError = `Mark read failed (${err.status}): ${err.message}`;
			} else {
				actionError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			const next = new Map(pendingIds);
			next.delete(notification.id);
			pendingIds = next;
		}
	}

	// ---------------------------------------------------------------------------
	// Bulk action: mark all unread notifications read
	// ---------------------------------------------------------------------------

	async function handleMarkAllRead(): Promise<void> {
		const ids = unreadNotifications.map((n) => n.id);
		if (ids.length === 0) return;
		markingAllRead = true;
		actionError = null;
		actionSuccess = null;
		try {
			const results = await Promise.allSettled(ids.map((id) => autonomousApi.readNotification(id)));
			const failedCount = results.filter((r) => r.status === 'rejected').length;
			const succeededCount = results.filter((r) => r.status === 'fulfilled').length;
			if (failedCount === 0) {
				actionSuccess = `All ${succeededCount} notification${succeededCount !== 1 ? 's' : ''} marked as read.`;
			} else {
				actionSuccess = `${succeededCount} marked as read; ${failedCount} failed — try again.`;
			}
			await load();
		} catch (err) {
			// Outer try/catch only fires if load() throws; allSettled doesn't throw.
			actionError = err instanceof Error ? err.message : String(err);
		} finally {
			markingAllRead = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Toggle unread-only filter
	// ---------------------------------------------------------------------------

	async function toggleUnreadOnly(): Promise<void> {
		unreadOnly = !unreadOnly;
		await load();
	}

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	function formatDate(iso: string): string {
		try {
			return new Intl.DateTimeFormat(undefined, {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			}).format(new Date(iso));
		} catch {
			return iso;
		}
	}

	function pendingLabel(id: string): string | undefined {
		return pendingIds.get(id);
	}
</script>

<div class="notifications-page">
	<header class="page-header">
		<div class="page-header-row">
			<div>
				<h1 class="lq-text-page-h">Notifications</h1>
				<p class="page-intro">
					In-app notifications from LQVern autonomous sessions. Click an unread item or use "Mark
					read" to dismiss it. Email delivery is handled separately per your notification settings.
				</p>
			</div>
			<div class="header-actions">
				<button
					type="button"
					class="filter-toggle"
					class:filter-toggle--active={unreadOnly}
					on:click={toggleUnreadOnly}
					disabled={loading}
					aria-pressed={unreadOnly}
				>
					Unread only
				</button>
				<button
					type="button"
					class="mark-all-button"
					on:click={handleMarkAllRead}
					disabled={!hasUnread || markingAllRead || loading}
					aria-label="Mark all notifications as read"
				>
					{markingAllRead ? 'Marking all…' : 'Mark all read'}
				</button>
			</div>
		</div>
	</header>

	<!-- ================================================================ -->
	<!-- Banners                                                           -->
	<!-- ================================================================ -->

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	<!-- ================================================================ -->
	<!-- Loading + empty states                                           -->
	<!-- ================================================================ -->

	{#if loading && notifications.length === 0}
		<p class="loading">Loading notifications…</p>
	{/if}

	{#if !loading && notifications.length === 0 && !listError}
		<p class="empty-state">
			{#if unreadOnly}
				No unread notifications.
			{:else}
				No notifications.
			{/if}
		</p>
	{/if}

	<!-- ================================================================ -->
	<!-- Notification list                                                 -->
	<!-- ================================================================ -->

	{#if notifications.length > 0}
		<ul class="notification-list" aria-label="Notifications">
			{#each notifications as notification (notification.id)}
				{@const isUnread = notification.read_at === null}
				{@const pending = pendingLabel(notification.id)}
				<li
					class="notification-row"
					class:notification-row--unread={isUnread}
					class:notification-row--read={!isUnread}
				>
					{#if isUnread}
						<!--
							Unread row: a full-row button for click-to-read, with the explicit
							"Mark read" action button inside (stopPropagation keeps both working).
						-->
						<button
							type="button"
							class="row-click-target"
							on:click={() => handleMarkRead(notification)}
							disabled={!!pending || markingAllRead}
							aria-label={`Mark "${notification.title}" as read`}
						>
							<div class="notification-indicator" aria-hidden="true">
								<span class="unread-dot"></span>
							</div>
							<div class="notification-body">
								<div class="notification-header-row">
									<span class="notification-title notification-title--unread">
										{notification.title}
									</span>
									<span class="notification-meta">
										<span class="notification-channel">{notification.channel}</span>
										<time
											class="notification-date"
											datetime={notification.created_at}
											title={notification.created_at}
										>
											{formatDate(notification.created_at)}
										</time>
									</span>
								</div>
								<p class="notification-text">{notification.body}</p>
								{#if notification.session_id}
									<p class="notification-session">
										Session: <code class="session-id">{notification.session_id}</code>
									</p>
								{/if}
							</div>
						</button>
						<div class="notification-actions">
							<button
								type="button"
								class="action-button"
								on:click={() => handleMarkRead(notification)}
								disabled={!!pending || markingAllRead}
								aria-label={`Mark "${notification.title}" as read`}
							>
								{pending === 'marking' ? 'Marking…' : 'Mark read'}
							</button>
						</div>
					{:else}
						<!--
							Read row: plain layout, no interactive wrapper needed.
						-->
						<div class="notification-indicator" aria-hidden="true">
							<span class="read-dot"></span>
						</div>
						<div class="notification-body">
							<div class="notification-header-row">
								<span class="notification-title">
									{notification.title}
								</span>
								<span class="notification-meta">
									<span class="notification-channel">{notification.channel}</span>
									<time
										class="notification-date"
										datetime={notification.created_at}
										title={notification.created_at}
									>
										{formatDate(notification.created_at)}
									</time>
								</span>
							</div>
							<p class="notification-text">{notification.body}</p>
							{#if notification.session_id}
								<p class="notification-session">
									Session: <code class="session-id">{notification.session_id}</code>
								</p>
							{/if}
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	/* ------------------------------------------------------------------ */
	/* Page layout                                                         */
	/* ------------------------------------------------------------------ */

	.notifications-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-header-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--lq-space-4);
		flex-wrap: wrap;
	}

	.page-intro {
		color: var(--lq-text-secondary);
		max-width: 60rem;
		font-size: 14px;
		line-height: 1.5;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--lq-space-3);
		flex-shrink: 0;
		flex-wrap: wrap;
	}

	/* ------------------------------------------------------------------ */
	/* Header buttons                                                      */
	/* ------------------------------------------------------------------ */

	.filter-toggle {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		transition:
			background 0.1s,
			color 0.1s,
			border-color 0.1s;
	}

	.filter-toggle:hover:not(:disabled) {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
		color: var(--lq-text);
	}

	.filter-toggle--active {
		background: var(--lq-accent-soft, rgba(var(--lq-accent-rgb, 59, 130, 246), 0.1));
		color: var(--lq-accent);
		border-color: var(--lq-accent);
	}

	.filter-toggle:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.mark-all-button {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		white-space: nowrap;
	}

	.mark-all-button:hover:not(:disabled) {
		filter: brightness(0.95);
	}

	.mark-all-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* ------------------------------------------------------------------ */
	/* Banners                                                             */
	/* ------------------------------------------------------------------ */

	.error-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border-radius: 6px;
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.success-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border-radius: 6px;
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.loading {
		color: var(--lq-text-secondary);
		padding: var(--lq-space-3);
	}

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	/* ------------------------------------------------------------------ */
	/* Notification list                                                   */
	/* ------------------------------------------------------------------ */

	.notification-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		overflow: hidden;
	}

	.notification-row {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-3);
		padding: var(--lq-space-4);
		border-bottom: 1px solid var(--lq-border);
		transition: background 0.1s;
	}

	.notification-row:last-child {
		border-bottom: none;
	}

	.notification-row--unread {
		background: var(--lq-accent-soft, rgba(59, 130, 246, 0.04));
	}

	.notification-row--unread:has(.row-click-target:hover) {
		background: var(--lq-accent-soft, rgba(59, 130, 246, 0.08));
	}

	/* Full-row transparent button for unread click-to-read */
	.row-click-target {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-3);
		background: transparent;
		border: none;
		padding: 0;
		cursor: pointer;
		text-align: left;
		color: inherit;
		font: inherit;
	}

	.row-click-target:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
		border-radius: 2px;
	}

	.row-click-target:disabled {
		cursor: not-allowed;
		opacity: 0.7;
	}

	.notification-row--read {
		background: var(--lq-surface);
		opacity: 0.75;
	}

	/* ------------------------------------------------------------------ */
	/* Row indicator (unread dot / read dot)                               */
	/* ------------------------------------------------------------------ */

	.notification-indicator {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		padding-top: 3px; /* vertically align with first line of title */
	}

	.unread-dot {
		display: block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--lq-accent);
	}

	.read-dot {
		display: block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--lq-border);
	}

	/* ------------------------------------------------------------------ */
	/* Notification content                                                */
	/* ------------------------------------------------------------------ */

	.notification-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.notification-header-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--lq-space-3);
		flex-wrap: wrap;
	}

	.notification-title {
		font-size: 14px;
		font-weight: 400;
		color: var(--lq-text-secondary);
		word-break: break-word;
	}

	.notification-title--unread {
		font-weight: 600;
		color: var(--lq-text);
	}

	.notification-meta {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
		flex-shrink: 0;
	}

	.notification-channel {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		background: var(--lq-inset, rgba(0, 0, 0, 0.04));
		color: var(--lq-text-tertiary);
		border: 1px solid var(--lq-border);
	}

	.notification-date {
		font-size: 12px;
		color: var(--lq-text-tertiary);
		white-space: nowrap;
	}

	.notification-text {
		font-size: 13px;
		color: var(--lq-text-secondary);
		margin: 0;
		line-height: 1.5;
		word-break: break-word;
	}

	.notification-session {
		font-size: 11px;
		color: var(--lq-text-tertiary);
		margin: 0;
	}

	.session-id {
		font-family: var(--font-mono, monospace);
		font-size: 11px;
	}

	/* ------------------------------------------------------------------ */
	/* Per-row action button                                               */
	/* ------------------------------------------------------------------ */

	.notification-actions {
		flex-shrink: 0;
		display: flex;
		align-items: flex-start;
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
		transition: background 0.1s;
		white-space: nowrap;
	}

	.action-button:hover:not(:disabled) {
		background: var(--lq-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
