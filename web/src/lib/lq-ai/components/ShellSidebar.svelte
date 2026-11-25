<script context="module" lang="ts">
	import { chatsApi, projectsApi } from '$lib/lq-ai/api';
	import { createSidebarLists } from '../sidebarLists';

	// One instance for the session: the lists survive page changes, so moving
	// between pages does not empty the sidebar while it refreshes.
	const sharedLists = createSidebarLists({
		listProjects: () => projectsApi.listProjects(),
		listChats: (opts) => chatsApi.listChats(opts)
	});
</script>

<script lang="ts">
	/**
	 * Left sidebar for the redesigned LQ.AI shell (interface-redesign work plan,
	 * Annex B P1.3a and P1.3b).
	 *
	 * Rendered by `routes/lq-ai/+layout.svelte` in place of the top bar and tab
	 * row, and only while the developer switch in `../shell.ts` is on. Rows,
	 * order, routes and who may see them all come from `../nav.ts`
	 * (`visibleNav`, `activeNavItemFor`); this component decides nothing about
	 * visibility. The layout keeps every gate (sign-in, forced password change,
	 * idle timeout, preferences, the Autonomous opt-in) and passes the bell's
	 * gate in as `automations`.
	 *
	 * P1.3b adds: recent matters with their chats and other chats above "All
	 * matters" / "All chats" (`../sidebarLists`); the notification bell in two
	 * places, an icon beside the sidebar toggle and a Notifications row under
	 * Customise, both only when Automations is on and both opening the list in
	 * the right sidebar; and the collapse (`../leftSidebar`): a strip with the
	 * toggle when collapsed, and on narrow screens the sidebar opens over the
	 * page, closing on Escape, on navigation, on the backdrop and when focus
	 * leaves it. On a matter page it starts collapsed, so the chat composer
	 * keeps its width, and remembers a choice made there separately. The foot carries today's full attribution wording
	 * (`DualBrandingFooter`, ADR 0001) until the committee rules on F2.
	 */
	import { onDestroy, onMount, tick } from 'svelte';
	import { browser } from '$app/environment';
	import { afterNavigate } from '$app/navigation';
	import {
		IconAdjustments,
		IconBell,
		IconBook,
		IconBookmark,
		IconBooks,
		IconFlask,
		IconFolder,
		IconHome,
		IconLayoutSidebarLeftCollapse,
		IconLayoutSidebarLeftExpand,
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
	import { autonomousApi } from '$lib/lq-ai/api';
	import { badgeText } from '$lib/lq-ai/autonomous/notification-bell';
	import { createNotificationBell } from '$lib/lq-ai/autonomous/notification-bell-controller';
	import { preferences } from '$lib/lq-ai/stores/preferences';
	import { activeChatStore, chatsStore } from '$lib/lq-ai/stores';
	import { chatHref } from '$lib/lq-ai/run/links';
	import { activeNavItemFor, visibleNav, type NavItem, type NavItemId } from '../nav';
	import type { User } from '../tabs';
	import {
		LEFT_SIDEBAR_ID,
		NARROW_QUERY,
		focusLeftSidebar,
		focusLeftSidebarOpener,
		leftSidebarMode,
		leftSidebarNarrow,
		leftSidebarOpen,
		leftSidebarPageFor,
		setLeftSidebarOpen,
		shouldCloseOnFocusOut,
		syncLeftSidebar
	} from '../leftSidebar';
	import {
		clearRightSidebarOverlay,
		focusRightSidebar,
		handleRightSidebarKeydown,
		rightSidebarOverlayLabel,
		showRightSidebarOverlay
	} from '../rightSidebar';
	import {
		currentSidebarRows,
		listClaimsCurrent,
		mergeChats,
		shapeSidebarLists,
		type SidebarListsController
	} from '../sidebarLists';
	import DualBrandingFooter from './DualBrandingFooter.svelte';
	import NotificationsPanel from './NotificationsPanel.svelte';

	export let user: User | null;
	export let pathname: string;
	/** The chat id in the address (`/lq-ai/chats?id=`), for the current row. */
	export let urlChatId: string | null = null;
	/** Automations is on for this person (the layout's `autonomousChromeEnabled`). */
	export let automations = false;
	/** The lists' data; tests pass a seeded one. */
	export let lists: SidebarListsController = sharedLists;
	/** The notification controller; created here when absent (tests pass one). */
	export let notifications: ReturnType<typeof createNotificationBell> | null = null;

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

	// ---- Recent matters and chats ----
	// Chats the open chat page already knows are laid over the fetched page;
	// only the signed-in person's own, like the list the sidebar fetches.
	$: liveChats = $chatsStore.filter((c) => !!user && c.owner_id === user.id);
	// Lists loaded for someone else are never shown (seeded test data has no owner).
	$: own = $lists.user === undefined || $lists.user === (user?.id ?? null);
	$: shaped = own
		? shapeSidebarLists($lists.projects, mergeChats($lists.chats, liveChats))
		: shapeSidebarLists([], liveChats);
	$: current = currentSidebarRows(pathname, urlChatId, $activeChatStore?.id ?? null);
	$: claimed = listClaimsCurrent(shaped, current);
	$: listsPending =
		$lists.status === 'idle' || ($lists.status === 'loading' && $lists.loadedAt === null);
	$: listsFailed = $lists.status === 'error';

	// A listed matter or chat that is current wins over its "All" row.
	$: currentNav = (id: NavItemId): boolean =>
		active === id &&
		!(id === 'all-matters' && claimed.matters) &&
		!(id === 'all-chats' && claimed.chats);

	// On a matter page the matter is the page; its open chat is current within it.
	$: chatCurrent = (chatId: string): 'page' | 'true' | undefined =>
		current.chatId !== chatId ? undefined : current.matterId ? 'true' : 'page';

	// Sign-in changes empty the lists first, so nobody sees the previous person's matters.
	$: if (browser) lists.forUser(user?.id ?? null);

	function retryLists(): void {
		void lists.refresh({ force: true });
	}

	// ---- Notification bell (only when Automations is on) ----
	const NOTIFICATIONS_LABEL = 'Notifications';
	type Bell = ReturnType<typeof createNotificationBell>;
	let bell = null as Bell | null;
	let ownsBell = false;
	$: syncBell(automations);
	function syncBell(on: boolean): void {
		if (on && !bell) {
			ownsBell = !notifications;
			bell = notifications ?? createNotificationBell(autonomousApi);
			if (browser) void bell.refresh();
		} else if (!on && bell) {
			if (ownsBell) bell.destroy();
			bell = null;
			if (notificationsShown) clearRightSidebarOverlay();
		}
	}
	$: notificationsShown = $rightSidebarOverlayLabel === NOTIFICATIONS_LABEL;
	$: unread = $bell?.unreadCount ?? 0;
	$: badge = badgeText(unread);
	$: bellLabel =
		badge === '99+'
			? `Notifications, 99+ (${unread} unread)`
			: unread > 0
				? `Notifications, ${unread} unread`
				: 'Notifications';

	async function toggleNotifications(event: MouseEvent): Promise<void> {
		if (!bell) return;
		let opener = event.currentTarget as HTMLElement | null;
		if (notificationsShown) {
			clearRightSidebarOverlay();
			return;
		}
		if (mode === 'overlay') {
			// The panel goes away; focus comes back to the strip's toggle.
			setLeftSidebarOpen(false, true);
			opener = document.querySelector<HTMLElement>('[data-left-sidebar-opener]');
		}
		showRightSidebarOverlay(
			{ label: NOTIFICATIONS_LABEL, component: NotificationsPanel, props: { bell } },
			opener
		);
		void bell.refresh();
		await tick();
		focusRightSidebar();
	}

	// ---- Collapse and narrow screens ----
	$: mode = leftSidebarMode({ open: $leftSidebarOpen, narrow: $leftSidebarNarrow });
	let panelEl: HTMLDivElement | undefined;

	// Matter pages start collapsed and remember their own choice (`../leftSidebar`).
	$: sidebarPage = leftSidebarPageFor(pathname);
	// Not on the server or before mount: the state is loaded in the browser only.
	let mounted = false;
	$: if (mounted) resyncForPage(sidebarPage);
	function resyncForPage(page: typeof sidebarPage): void {
		syncLeftSidebar($leftSidebarNarrow, undefined, page);
	}

	async function toggleSidebar(): Promise<void> {
		const next = !$leftSidebarOpen;
		setLeftSidebarOpen(next, $leftSidebarNarrow, undefined, sidebarPage);
		await tick();
		if (next) focusLeftSidebar();
		else focusLeftSidebarOpener();
	}

	async function closeOverlay(): Promise<void> {
		setLeftSidebarOpen(false, true);
		await tick();
		focusLeftSidebarOpener();
	}

	function onPanelKeydown(event: KeyboardEvent): void {
		if (mode === 'overlay') handleRightSidebarKeydown(event, () => void closeOverlay());
	}

	function onPanelFocusout(event: FocusEvent): void {
		if (shouldCloseOnFocusOut(mode, panelEl ?? null, event.relatedTarget as Node | null))
			setLeftSidebarOpen(false, true);
	}

	// Following a link from the overlay closes it.
	let lastLocation = `${pathname}?${urlChatId ?? ''}`;
	$: if (`${pathname}?${urlChatId ?? ''}` !== lastLocation) {
		lastLocation = `${pathname}?${urlChatId ?? ''}`;
		if ($leftSidebarNarrow && $leftSidebarOpen) setLeftSidebarOpen(false, true);
	}

	onMount(() => {
		const query = window.matchMedia?.(NARROW_QUERY);
		const apply = () => syncLeftSidebar(!!query?.matches, undefined, sidebarPage);
		apply();
		mounted = true;
		query?.addEventListener?.('change', apply);
		return () => query?.removeEventListener?.('change', apply);
	});

	afterNavigate(() => {
		void lists.refresh();
		void bell?.refresh();
	});

	onDestroy(() => {
		if (bell && ownsBell) bell.destroy();
		if (notificationsShown) clearRightSidebarOverlay();
	});
</script>

<div
	class="lq-sidebar"
	class:lq-sidebar-collapsed={mode !== 'open'}
	data-testid="lq-shell-sidebar"
	data-mode={mode}
>
	{#if mode !== 'open'}
		<div class="lq-sidebar-strip" data-testid="lq-shell-sidebar-strip">
			<button
				type="button"
				class="lq-sidebar-icon-button"
				aria-controls={LEFT_SIDEBAR_ID}
				aria-expanded={mode === 'overlay'}
				aria-label="Open sidebar"
				title="Open sidebar"
				data-left-sidebar-opener
				data-testid="lq-shell-sidebar-open"
				on:click={toggleSidebar}
			>
				<IconLayoutSidebarLeftExpand size={18} stroke={1.75} aria-hidden="true" />
			</button>
			{#if bell}
				<button
					type="button"
					class="lq-sidebar-icon-button lq-sidebar-bell"
					aria-expanded={notificationsShown}
					aria-label={bellLabel}
					title="Notifications"
					data-testid="lq-shell-bell-strip"
					on:click={toggleNotifications}
				>
					<IconBell size={18} stroke={1.75} aria-hidden="true" />
					{#if badge !== null}
						<span class="lq-sidebar-count lq-sidebar-count-dot" aria-hidden="true">{badge}</span>
					{/if}
				</button>
			{/if}
		</div>
	{/if}

	{#if mode === 'overlay'}
		<!-- The backdrop is a pointer convenience; Escape and the toggle close it from the keyboard. -->
		<div
			class="lq-sidebar-backdrop"
			role="presentation"
			data-testid="lq-shell-sidebar-backdrop"
			on:click={() => void closeOverlay()}
		></div>
	{/if}

	{#if mode !== 'collapsed'}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			id={LEFT_SIDEBAR_ID}
			class="lq-sidebar-panel"
			class:lq-sidebar-overlay={mode === 'overlay'}
			bind:this={panelEl}
			on:keydown={onPanelKeydown}
			on:focusout={onPanelFocusout}
		>
			<div class="lq-sidebar-head">
				<a class="lq-sidebar-brand" href="/lq-ai">
					<span class="lq-sidebar-brand-lq">LQ</span>.AI
				</a>
				<div class="lq-sidebar-head-actions">
					{#if bell}
						<button
							type="button"
							class="lq-sidebar-icon-button lq-sidebar-bell"
							aria-expanded={notificationsShown}
							aria-label={bellLabel}
							title="Notifications"
							data-testid="lq-shell-bell"
							on:click={toggleNotifications}
						>
							<IconBell size={18} stroke={1.75} aria-hidden="true" />
							{#if badge !== null}
								<span class="lq-sidebar-count lq-sidebar-count-dot" aria-hidden="true">{badge}</span
								>
							{/if}
						</button>
					{/if}
					<button
						type="button"
						class="lq-sidebar-icon-button"
						aria-controls={LEFT_SIDEBAR_ID}
						aria-expanded="true"
						aria-label={mode === 'overlay' ? 'Close sidebar' : 'Collapse sidebar'}
						title={mode === 'overlay' ? 'Close sidebar' : 'Collapse sidebar'}
						data-left-sidebar-close
						data-testid="lq-shell-sidebar-toggle"
						on:click={toggleSidebar}
					>
						<IconLayoutSidebarLeftCollapse size={18} stroke={1.75} aria-hidden="true" />
					</button>
				</div>
			</div>

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
							{#if section.id === 'matters'}
								{#if listsPending && shaped.matters.length === 0}
									<li class="lq-sidebar-status"><span role="status">Loading matters…</span></li>
								{/if}
								{#each shaped.matters as matter (matter.project.id)}
									<li>
										<a
											class="lq-sidebar-row"
											class:lq-sidebar-row-current={current.matterId === matter.project.id}
											href="/lq-ai/matters/{encodeURIComponent(matter.project.id)}"
											aria-current={current.matterId === matter.project.id ? 'page' : undefined}
											data-sidebar-matter={matter.project.id}
										>
											<IconFolder size={16} stroke={1.75} aria-hidden="true" />
											<span class="lq-sidebar-row-label">{matter.project.name}</span>
										</a>
										{#if matter.chats.length > 0}
											<ul class="lq-sidebar-list lq-sidebar-children">
												{#each matter.chats as chat (chat.id)}
													<li>
														<a
															class="lq-sidebar-row lq-sidebar-chat"
															class:lq-sidebar-row-current={chatCurrent(chat.id) !== undefined}
															href={chatHref(chat.id)}
															aria-current={chatCurrent(chat.id)}
															data-sidebar-chat={chat.id}
														>
															<span class="lq-sidebar-row-label"
																>{chat.title || 'Untitled chat'}</span
															>
														</a>
													</li>
												{/each}
											</ul>
										{/if}
									</li>
								{/each}
							{:else if section.id === 'chats'}
								{#if listsPending && shaped.otherChats.length === 0}
									<li class="lq-sidebar-status"><span role="status">Loading chats…</span></li>
								{/if}
								{#each shaped.otherChats as chat (chat.id)}
									<li>
										<a
											class="lq-sidebar-row lq-sidebar-chat"
											class:lq-sidebar-row-current={chatCurrent(chat.id) !== undefined}
											href={chatHref(chat.id)}
											aria-current={chatCurrent(chat.id)}
											data-sidebar-chat={chat.id}
										>
											<span class="lq-sidebar-row-label">{chat.title || 'Untitled chat'}</span>
										</a>
									</li>
								{/each}
								{#if listsFailed}
									<li class="lq-sidebar-status" data-testid="lq-shell-lists-error">
										<span role="status">Couldn’t load recent matters and chats.</span>
										<button type="button" class="lq-sidebar-retry" on:click={retryLists}
											>Retry</button
										>
									</li>
								{/if}
							{/if}
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
														class:lq-sidebar-row-current={currentNav(child.id)}
														href={child.route}
														aria-current={currentNav(child.id) ? 'page' : undefined}
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
											class:lq-sidebar-row-current={currentNav(item.id)}
											href={item.route}
											aria-current={currentNav(item.id) ? 'page' : undefined}
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
							{#if section.id === 'primary' && bell}
								<li>
									<button
										type="button"
										class="lq-sidebar-row"
										class:lq-sidebar-row-current={notificationsShown}
										aria-expanded={notificationsShown}
										aria-label={bellLabel}
										data-testid="lq-shell-notifications-row"
										on:click={toggleNotifications}
									>
										<IconBell size={16} stroke={1.75} aria-hidden="true" />
										<span class="lq-sidebar-row-label">Notifications</span>
										{#if badge !== null}
											<span class="lq-sidebar-count" aria-hidden="true">{badge}</span>
										{/if}
									</button>
								</li>
							{/if}
						</ul>
					</div>
				{/each}

				{#if foot.length > 0}
					<ul class="lq-sidebar-list lq-sidebar-foot" data-section="foot">
						{#each foot as item (item.id)}
							<li>
								<a
									class="lq-sidebar-row"
									class:lq-sidebar-row-current={currentNav(item.id)}
									href={item.route}
									aria-current={currentNav(item.id) ? 'page' : undefined}
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
							</li>
						{/each}
					</ul>
				{/if}
			</nav>

			<div class="lq-sidebar-attribution">
				<DualBrandingFooter />
			</div>
		</div>
	{/if}
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
	/* Collapsed (any width) and narrow screens: only the strip takes room. */
	.lq-sidebar-collapsed {
		width: 48px;
	}
	.lq-sidebar-panel {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		background: var(--lq-inset);
		color: var(--lq-text);
	}
	/* Narrow screens, open: the panel lies over the page from the left edge. */
	.lq-sidebar-overlay {
		position: fixed;
		top: 0;
		bottom: 0;
		left: 0;
		z-index: 41;
		width: min(264px, calc(100vw - 48px));
		border-right: 1px solid var(--lq-border);
	}
	.lq-sidebar-backdrop {
		position: fixed;
		inset: 0;
		z-index: 40;
		background: var(--lq-text);
		opacity: 0.2;
	}
	.lq-sidebar-strip {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--lq-space-2);
		padding: var(--lq-space-3) 0;
	}
	.lq-sidebar-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-2);
		padding: var(--lq-space-3) var(--lq-space-2) var(--lq-space-2) 0;
	}
	.lq-sidebar-head-actions {
		display: inline-flex;
		align-items: center;
		gap: 2px;
	}
	.lq-sidebar-icon-button {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border: 0;
		border-radius: var(--lq-radius-pill);
		background: transparent;
		color: var(--lq-text-secondary);
		cursor: pointer;
	}
	.lq-sidebar-icon-button:hover,
	.lq-sidebar-icon-button[aria-expanded='true'].lq-sidebar-bell {
		background: var(--lq-surface-hover);
		color: var(--lq-text);
	}
	.lq-sidebar-icon-button:focus-visible,
	.lq-sidebar-retry:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	/* Counts are black on white or white on black, never orange or red (C15, C26). */
	.lq-sidebar-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: var(--lq-radius-pill);
		background: var(--lq-text);
		color: var(--lq-canvas);
		font-size: 11px;
		font-weight: 600;
		line-height: 1;
	}
	.lq-sidebar-count-dot {
		position: absolute;
		top: -2px;
		right: -4px;
	}
	.lq-sidebar-status {
		padding: var(--lq-space-1) 10px;
		font-size: 12.5px;
		color: var(--lq-text-secondary);
	}
	.lq-sidebar-retry {
		border: 0;
		padding: 0;
		background: transparent;
		color: var(--lq-text);
		font: inherit;
		font-weight: 600;
		text-decoration: underline;
		cursor: pointer;
	}
	.lq-sidebar-chat {
		font-size: 13px;
	}
	.lq-sidebar-brand {
		display: block;
		padding: var(--lq-space-1) var(--lq-space-4);
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
		border-radius: var(--lq-radius-pill);
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
		background: var(--lq-selected);
	}
	/* Trust & Privacy is a governance entry point: its icon is orange, its label ink. */
	.lq-sidebar-row[data-nav-id='trust'] :global(svg) {
		color: var(--lq-governance);
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
	/* The primary action of the shell: an ink pill (ADR 0045 §1, §5). */
	.lq-sidebar-new {
		min-height: 36px;
		border: 1px solid var(--lq-accent);
		border-radius: var(--lq-radius-pill);
		background: var(--lq-accent);
		color: var(--lq-on-accent);
		font-weight: 600;
	}
	.lq-sidebar-new:hover {
		background: color-mix(in srgb, var(--lq-accent) 82%, var(--lq-canvas));
		color: var(--lq-on-accent);
	}
	.lq-sidebar-attribution {
		flex-shrink: 0;
	}
</style>
