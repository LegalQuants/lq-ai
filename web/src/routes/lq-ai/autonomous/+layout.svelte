<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { preferences, initPreferences } from '$lib/lq-ai/stores/preferences';

	$: pathname = $page.url.pathname;

	const navLinks = [
		{ href: '/lq-ai/autonomous',               label: 'Sessions',      exact: true  },
		{ href: '/lq-ai/autonomous/memory',         label: 'Memory',        exact: false },
		{ href: '/lq-ai/autonomous/precedents',     label: 'Precedents',    exact: false },
		{ href: '/lq-ai/autonomous/proposals',      label: 'Proposals',     exact: false },
		{ href: '/lq-ai/autonomous/schedules',      label: 'Schedules',     exact: false },
		{ href: '/lq-ai/autonomous/watches',        label: 'Watches',       exact: false },
		{ href: '/lq-ai/autonomous/notifications',  label: 'Notifications', exact: false }
	];

	function isActive(href: string, exact: boolean): boolean {
		if (exact) return pathname === href;
		return pathname === href || pathname.startsWith(href + '/');
	}

	onMount(async () => {
		await initPreferences();
		if (!$preferences.autonomous_enabled) {
			goto('/lq-ai/settings/autonomous');
		}
	});
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

	.admin-content {
		flex: 1;
		min-width: 0;
	}
</style>
