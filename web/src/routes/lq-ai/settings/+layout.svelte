<script lang="ts">
	import { page } from '$app/stores';

	$: pathname = $page.url.pathname;

	const navLinks = [
		{ href: '/lq-ai/settings/appearance', label: 'Appearance' },
		{ href: '/lq-ai/settings/account', label: 'Account' },
		{ href: '/lq-ai/settings/autonomous', label: 'Autonomous' }
	];
</script>

<div class="settings-shell">
	<nav class="settings-nav" aria-label="Settings navigation">
		<ul class="settings-nav-list">
			{#each navLinks as link}
				<li>
					<a
						href={link.href}
						class="settings-nav-link"
						class:settings-nav-link--active={pathname.startsWith(link.href)}
						aria-current={pathname.startsWith(link.href) ? 'page' : undefined}
					>
						{link.label}
					</a>
				</li>
			{/each}
		</ul>
	</nav>
	<div class="settings-content">
		<slot />
	</div>
</div>

<style>
	.settings-shell {
		display: flex;
		gap: var(--lq-space-6);
		padding: var(--lq-space-6) var(--lq-space-5);
		max-width: 860px;
		margin: 0 auto;
		width: 100%;
	}

	.settings-nav {
		width: 160px;
		flex-shrink: 0;
	}

	.settings-nav-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.settings-nav-link {
		display: block;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-radius: var(--lq-radius-sm);
		color: var(--lq-text-secondary);
		text-decoration: none;
		font-size: 14px;
		font-weight: 500;
		transition: color 0.12s, background 0.12s;
	}

	.settings-nav-link:hover {
		color: var(--lq-text);
		background: var(--lq-inset);
	}

	.settings-nav-link--active {
		color: var(--lq-accent);
		background: var(--lq-accent-soft);
	}

	.settings-content {
		flex: 1;
		min-width: 0;
	}
</style>
