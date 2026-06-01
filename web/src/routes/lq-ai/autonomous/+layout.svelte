<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { preferences, initPreferences } from '$lib/lq-ai/stores/preferences';
	import { autonomousApi } from '$lib/lq-ai/api';

	$: pathname = $page.url.pathname;

	const NOTIFICATIONS_HREF = '/lq-ai/autonomous/notifications';

	const navLinks = [
		{ href: '/lq-ai/autonomous/configure',      label: 'Configure',     exact: false },
		{ href: '/lq-ai/autonomous',               label: 'Sessions',      exact: true  },
		{ href: '/lq-ai/autonomous/memory',         label: 'Memory',        exact: false },
		{ href: '/lq-ai/autonomous/precedents',     label: 'Precedents',    exact: false },
		{ href: '/lq-ai/autonomous/proposals',      label: 'Proposals',     exact: false },
		{ href: '/lq-ai/autonomous/schedules',      label: 'Schedules',     exact: false },
		{ href: '/lq-ai/autonomous/watches',        label: 'Watches',       exact: false },
		{ href: NOTIFICATIONS_HREF,                 label: 'Notifications', exact: false }
	];

	function isActive(href: string, exact: boolean): boolean {
		if (exact) return pathname === href;
		return pathname === href || pathname.startsWith(href + '/');
	}

	/** Unread notification count — best-effort; errors are silently swallowed. */
	let unreadCount = 0;

	async function fetchUnreadCount(): Promise<void> {
		try {
			const resp = await autonomousApi.listNotifications(true);
			unreadCount = resp.notifications.length;
		} catch {
			// Best-effort badge — do not surface errors here.
		}
	}

	onMount(async () => {
		await initPreferences();
		if (!$preferences.autonomous_enabled) {
			goto('/lq-ai/settings/autonomous');
			return;
		}
		// Initial unread count fetch (opt-in already confirmed above).
		await fetchUnreadCount();
	});

	/**
	 * Re-fetch unread count whenever the user navigates away FROM the notifications
	 * page (they may have marked items read while there). Using $page reactivity is
	 * lighter than a cross-component store and sufficient for this best-effort badge.
	 */
	let prevPathname = '';
	$: {
		const current = $page.url.pathname;
		if (
			prevPathname !== current &&
			prevPathname.startsWith(NOTIFICATIONS_HREF) &&
			!current.startsWith(NOTIFICATIONS_HREF) &&
			$preferences.autonomous_enabled
		) {
			fetchUnreadCount();
		}
		prevPathname = current;
	}
</script>

{#if $preferences.autonomous_enabled}
	<div class="admin-shell">
		<nav class="admin-nav" aria-label="Autonomous navigation">
			<ul class="admin-nav-list">
				{#each navLinks as link}
					<li>
						<a
							href={link.href}
							class="admin-nav-link"
							class:admin-nav-link--active={isActive(link.href, link.exact)}
							aria-current={isActive(link.href, link.exact) ? 'page' : undefined}
						>
							{link.label}
							{#if link.href === NOTIFICATIONS_HREF && unreadCount > 0}
								<span class="nav-unread-badge" aria-label="{unreadCount} unread">
									{unreadCount > 99 ? '99+' : unreadCount}
								</span>
							{/if}
						</a>
					</li>
				{/each}
			</ul>
		</nav>
		<div class="admin-content">
			<slot />
		</div>
	</div>
{/if}

<style>
	.admin-shell {
		display: flex;
		flex-direction: column;
		gap: 0;
		width: 100%;
		min-height: 0;
	}

	.admin-nav {
		border-bottom: 1px solid var(--lq-border);
		background: var(--lq-surface);
	}

	.admin-nav-list {
		list-style: none;
		margin: 0;
		padding: 0 var(--lq-space-5);
		display: flex;
		gap: 0;
	}

	.admin-nav-link {
		display: block;
		padding: var(--lq-space-3) var(--lq-space-4);
		color: var(--lq-text-secondary);
		text-decoration: none;
		font-size: 14px;
		font-weight: 500;
		border-bottom: 2px solid transparent;
		margin-bottom: -1px;
		transition:
			color 0.12s,
			border-color 0.12s;
	}

	.admin-nav-link:hover {
		color: var(--lq-text);
	}

	.admin-nav-link--active {
		color: var(--lq-accent);
		border-bottom-color: var(--lq-accent);
	}

	.nav-unread-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		margin-left: 6px;
		border-radius: 9px;
		font-size: 11px;
		font-weight: 600;
		line-height: 1;
		background: var(--lq-accent);
		color: white;
		vertical-align: middle;
		/* Prevent badge from inheriting the link's text decoration / underline */
		text-decoration: none;
	}

	.admin-content {
		flex: 1;
		min-width: 0;
	}
</style>
