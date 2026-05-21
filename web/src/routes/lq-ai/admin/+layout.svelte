<script lang="ts">
	import { page } from '$app/stores';

	$: pathname = $page.url.pathname;

	const navLinks = [
		{ href: '/lq-ai/admin/audit-log', label: 'Audit log' },
		{ href: '/lq-ai/admin/models', label: 'Models' },
		{ href: '/lq-ai/admin/word-addin', label: 'Word add-in' },
		{ href: '/lq-ai/admin/developer', label: 'Developer Support' }
	];
</script>

<div class="admin-shell">
	<nav class="admin-nav" aria-label="Admin navigation">
		<ul class="admin-nav-list">
			{#each navLinks as link}
				<li>
					<a
						href={link.href}
						class="admin-nav-link"
						class:admin-nav-link--active={pathname.startsWith(link.href)}
						aria-current={pathname.startsWith(link.href) ? 'page' : undefined}
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
