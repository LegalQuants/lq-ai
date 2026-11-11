<script lang="ts">
	/**
	 * Left sidebar for the redesigned LQ.AI shell (interface-redesign work plan,
	 * Annex B P1.3a): the skeleton only.
	 *
	 * Rendered by `routes/lq-ai/+layout.svelte` in place of the top bar and tab
	 * row, and only while the developer switch in `../shell.ts` is on. Rows,
	 * order, routes and who may see them all come from `../nav.ts`
	 * (`visibleNav`, `activeNavItemFor`); this component decides nothing about
	 * visibility. The layout keeps every gate (sign-in, forced password change,
	 * idle timeout, preferences).
	 *
	 * Not here yet: recent matters and chats above "All matters" / "All chats",
	 * the notification bell, the narrow-screen collapse (P1.3b), the right
	 * sidebar (P1.4). The foot carries today's full attribution wording
	 * (`DualBrandingFooter`, ADR 0001) until the committee rules on F2.
	 */
	import {
		IconAdjustments,
		IconBook,
		IconBookmark,
		IconBooks,
		IconFlask,
		IconHome,
		IconMessages,
		IconFolders,
		IconPlus,
		IconShieldCheck,
		IconShieldLock,
		IconTable,
		IconTool,
		IconUserCircle,
		IconChevronDown,
		IconFileDescription
	} from '@tabler/icons-svelte';
	import { preferences } from '$lib/lq-ai/stores/preferences';
	import { activeNavItemFor, visibleNav, type NavItem, type NavItemId } from '../nav';
	import type { User } from '../tabs';
	import DualBrandingFooter from './DualBrandingFooter.svelte';

	export let user: User | null;
	export let pathname: string;

	// Same source as the tab row's Autonomous tab: the Labs row follows that rule.
	$: sections = visibleNav(user, { autonomousEnabled: $preferences.autonomous_enabled });
	$: active = activeNavItemFor(pathname);
	$: mainSections = sections.filter((s) => s.id !== 'foot');
	$: foot = sections.find((s) => s.id === 'foot')?.items ?? [];

	const SECTION_LABELS: Partial<Record<string, string>> = {
		matters: 'Matters',
		chats: 'Chats'
	};

	const ICONS: Record<NavItemId, typeof IconHome> = {
		new: IconPlus,
		home: IconHome,
		tabular: IconTable,
		labs: IconFlask,
		customise: IconAdjustments,
		skills: IconTool,
		knowledge: IconBooks,
		playbooks: IconFileDescription,
		'saved-prompts': IconBookmark,
		'all-matters': IconFolders,
		'all-chats': IconMessages,
		learn: IconBook,
		trust: IconShieldLock,
		admin: IconShieldCheck,
		account: IconUserCircle
	};

	// Groups (Customise) open when one of their rows is current; the person can
	// toggle them, and navigating into a child opens the group again.
	let expanded: Partial<Record<NavItemId, boolean>> = {};
	const hasActiveChild = (item: NavItem, current: NavItemId | null) =>
		!!item.children?.some((child) => child.id === current);
	$: for (const section of sections)
		for (const item of section.items)
			if (item.children && hasActiveChild(item, active)) expanded[item.id] = true;

	function toggle(id: NavItemId) {
		expanded = { ...expanded, [id]: !expanded[id] };
	}
</script>

<div class="lq-sidebar" data-testid="lq-shell-sidebar">
	<a class="lq-sidebar-brand" href="/lq-ai">
		<span class="lq-sidebar-brand-lq">LQ</span>.AI
	</a>

	<nav class="lq-sidebar-nav" aria-label="Primary">
		{#each mainSections as section (section.id)}
			<div class="lq-sidebar-section" data-section={section.id}>
				{#if SECTION_LABELS[section.id]}
					<p class="lq-sidebar-label" id="lq-sidebar-label-{section.id}">
						{SECTION_LABELS[section.id]}
					</p>
				{/if}
				<ul
					class="lq-sidebar-list"
					aria-labelledby={SECTION_LABELS[section.id]
						? `lq-sidebar-label-${section.id}`
						: undefined}
				>
					{#each section.items as item (item.id)}
						<li>
							{#if item.children}
								<button
									type="button"
									class="lq-sidebar-row"
									class:lq-sidebar-row-holds-current={hasActiveChild(item, active)}
									aria-expanded={expanded[item.id] === true}
									aria-controls="lq-sidebar-group-{item.id}"
									data-nav-id={item.id}
									on:click={() => toggle(item.id)}
								>
									<svelte:component
										this={ICONS[item.id]}
										size={16}
										stroke={1.75}
										aria-hidden="true"
									/>
									<span class="lq-sidebar-row-label">{item.label}</span>
									<span
										class="lq-sidebar-chevron"
										class:lq-sidebar-chevron-open={expanded[item.id]}
									>
										<IconChevronDown size={14} stroke={1.75} aria-hidden="true" />
									</span>
								</button>
								<ul
									class="lq-sidebar-list lq-sidebar-children"
									id="lq-sidebar-group-{item.id}"
									hidden={expanded[item.id] !== true}
								>
									{#each item.children as child (child.id)}
										<li>
											<a
												class="lq-sidebar-row"
												class:lq-sidebar-row-current={active === child.id}
												href={child.route}
												aria-current={active === child.id ? 'page' : undefined}
												data-nav-id={child.id}
											>
												<svelte:component
													this={ICONS[child.id]}
													size={16}
													stroke={1.75}
													aria-hidden="true"
												/>
												<span class="lq-sidebar-row-label">{child.label}</span>
											</a>
										</li>
									{/each}
								</ul>
							{:else}
								<a
									class="lq-sidebar-row"
									class:lq-sidebar-new={item.id === 'new'}
									class:lq-sidebar-row-current={active === item.id}
									href={item.route}
									aria-current={active === item.id ? 'page' : undefined}
									data-nav-id={item.id}
								>
									<svelte:component
										this={ICONS[item.id]}
										size={16}
										stroke={1.75}
										aria-hidden="true"
									/>
									<span class="lq-sidebar-row-label">{item.label}</span>
								</a>
							{/if}
						</li>
					{/each}
				</ul>
			</div>
		{/each}

		{#if foot.length > 0}
			<ul class="lq-sidebar-list lq-sidebar-foot" data-section="foot">
				{#each foot as item (item.id)}
					<li>
						<a
							class="lq-sidebar-row"
							class:lq-sidebar-row-current={active === item.id}
							href={item.route}
							aria-current={active === item.id ? 'page' : undefined}
							data-nav-id={item.id}
						>
							<svelte:component this={ICONS[item.id]} size={16} stroke={1.75} aria-hidden="true" />
							<span class="lq-sidebar-row-label">{item.label}</span>
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	</nav>

	<div class="lq-sidebar-attribution">
		<DualBrandingFooter />
	</div>
</div>

<style>
	.lq-sidebar {
		width: 264px;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		min-height: 0;
		background: var(--lq-inset);
		border-right: 1px solid var(--lq-border);
		color: var(--lq-text);
	}
	.lq-sidebar-brand {
		display: block;
		padding: var(--lq-space-4) var(--lq-space-4) var(--lq-space-3);
		font-size: 16px;
		font-weight: 600;
		color: var(--lq-text);
		text-decoration: none;
	}
	.lq-sidebar-brand-lq {
		color: var(--lq-accent);
	}
	.lq-sidebar-nav {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
		padding: var(--lq-space-1) 10px var(--lq-space-3);
	}
	.lq-sidebar-label {
		margin: 0 0 var(--lq-space-1);
		padding: 0 10px;
		font-size: 12px;
		font-weight: 600;
		/* Today's tertiary grey fails 4.5:1 at 12 px on --lq-inset (axe, switch-on run). */
		color: var(--lq-text-secondary);
	}
	.lq-sidebar-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.lq-sidebar-children {
		margin-top: 2px;
		padding-left: var(--lq-space-4);
	}
	.lq-sidebar-children[hidden] {
		display: none;
	}
	.lq-sidebar-foot {
		margin-top: auto;
	}
	.lq-sidebar-row {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		min-height: 32px;
		padding: 0 10px;
		border: 0;
		border-radius: var(--lq-radius);
		background: transparent;
		color: var(--lq-text-secondary);
		font: inherit;
		font-size: 13.5px;
		text-align: left;
		text-decoration: none;
		cursor: pointer;
	}
	.lq-sidebar-row:hover {
		background: var(--lq-surface-hover);
		color: var(--lq-text);
	}
	.lq-sidebar-row:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.lq-sidebar-row-current,
	.lq-sidebar-row-holds-current {
		color: var(--lq-text);
		font-weight: 600;
	}
	.lq-sidebar-row-current {
		background: var(--lq-accent-soft);
	}
	.lq-sidebar-row-label {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lq-sidebar-chevron {
		display: inline-flex;
		transition: transform 0.12s ease;
	}
	.lq-sidebar-chevron-open {
		transform: rotate(180deg);
	}
	.lq-sidebar-new {
		min-height: 36px;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		background: var(--lq-canvas);
		color: var(--lq-text);
		font-weight: 600;
	}
	.lq-sidebar-attribution {
		flex-shrink: 0;
	}
</style>
