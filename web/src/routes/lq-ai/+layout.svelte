<script lang="ts">
	import { IconSettings } from '@tabler/icons-svelte';
	/**
	 * LQ.AI shell layout. Acts as the auth gate + force-change-password gate
	 * for every route under `/lq-ai/*` except `/lq-ai/login` and
	 * `/lq-ai/change-password`.
	 *
	 * - No access token → redirect to /lq-ai/login.
	 * - Access token but `must_change_password` → redirect to /lq-ai/change-password.
	 * - Otherwise: render the child route.
	 */
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { auth } from '$lib/lq-ai/auth/store';
	import { authApi } from '$lib/lq-ai/api';
	import { LQAIApiError, PasswordChangeRequiredError } from '$lib/lq-ai/api/client';
	import ShellAttribution from '$lib/lq-ai/components/ShellAttribution.svelte';
	import TopTabBar from '$lib/lq-ai/components/TopTabBar.svelte';
	import AmbientTrustChrome from '$lib/lq-ai/components/AmbientTrustChrome.svelte';
	import SessionTimeoutWarning from '$lib/lq-ai/components/SessionTimeoutWarning.svelte';
	import NotificationBell from '$lib/lq-ai/components/NotificationBell.svelte';
	import ShellSidebar from '$lib/lq-ai/components/ShellSidebar.svelte';
	import PageHeader from '$lib/lq-ai/components/PageHeader.svelte';
	import RightSidebar from '$lib/lq-ai/components/RightSidebar.svelte';
	import { readShellSwitch, sidebarChromeOn, type ShellVariant } from '$lib/lq-ai/shell';
	import { autonomousChromeEnabled, initPreferences } from '$lib/lq-ai/stores/preferences';
	import { startTracker, stopTracker, noteActivity } from '$lib/lq-ai/stores/sessionActivity';
	import '$lib/lq-ai/styles/practice.css';
	import '$lib/lq-ai/styles/typography.css';

	let booted = false;

	function isAuthExempt(pathname: string): boolean {
		return pathname === '/lq-ai/login' || pathname === '/lq-ai/change-password';
	}

	$: pathname = $page.url.pathname;

	async function gate() {
		if (!$auth.access_token) {
			if (!isAuthExempt(pathname)) {
				goto('/lq-ai/login');
			}
			booted = true;
			return;
		}

		// Refresh `/users/me` to pick up server-side flag changes.
		try {
			const user = await authApi.getCurrentUser();
			if (user.must_change_password && pathname !== '/lq-ai/change-password') {
				goto('/lq-ai/change-password');
				return;
			}
		} catch (e: unknown) {
			if (e instanceof PasswordChangeRequiredError) {
				goto('/lq-ai/change-password');
				return;
			}
			if (e instanceof LQAIApiError && e.status === 401) {
				goto('/lq-ai/login');
				return;
			}
			console.error('lq-ai: failed to refresh user', e);
		}
		booted = true;
	}

	let activityHandler: (() => void) | null = null;

	// Developer-only switch for the redesigned chrome (see $lib/lq-ai/shell).
	// Off by default; sign-in and forced password change keep today's chrome.
	let shell: ShellVariant = 'tabs';
	onMount(() => {
		shell = readShellSwitch();
	});
	$: sidebarChrome = sidebarChromeOn(shell, isAuthExempt(pathname));

	onMount(() => {
		// Layouts survive client-side sign-in/navigation. Sync each new signed-in user,
		// and let the store discard responses from an earlier session.
		let preferenceUserId: string | null = null;
		const unsubscribePreferences = auth.subscribe((session) => {
			const userId = session.access_token ? (session.user?.id ?? null) : null;
			if (userId === preferenceUserId) return;
			preferenceUserId = userId;
			if (userId) void initPreferences();
		});
		gate();
		if (!isAuthExempt($page.url.pathname)) {
			startTracker(() => goto('/lq-ai/login?reason=idle-timeout'));
			activityHandler = () => noteActivity();
			(['mousedown', 'keydown', 'scroll', 'touchstart'] as const).forEach((e) =>
				window.addEventListener(e, activityHandler!, { passive: true })
			);
		}
		return unsubscribePreferences;
	});

	onDestroy(() => {
		stopTracker();
		if (activityHandler) {
			(['mousedown', 'keydown', 'scroll', 'touchstart'] as const).forEach((e) =>
				window.removeEventListener(e, activityHandler!)
			);
			activityHandler = null;
		}
	});
</script>

{#if booted}
	<div class="lq-shell" class:lq-shell-sidebar={sidebarChrome}>
		{#if sidebarChrome}
			<ShellSidebar
				user={$auth.user ?? null}
				{pathname}
				urlChatId={$page.url.searchParams.get('id')}
				automations={$autonomousChromeEnabled}
			/>
			<PageHeader {pathname} />
		{:else if !isAuthExempt(pathname)}
			<header class="lq-topbar">
				<a class="lq-brand" href="/lq-ai">
					<span class="lq-brand-lq">LQ</span>.AI
				</a>
				<div style="display: inline-flex; align-items: center; gap: var(--lq-space-3);">
					<AmbientTrustChrome />
					{#if $autonomousChromeEnabled}
						<NotificationBell />
					{/if}
					<a href="/lq-ai/settings/appearance" aria-label="Settings" title="Settings" style="color: var(--lq-text-secondary); text-decoration: none; padding: var(--lq-space-1) var(--lq-space-2); border-radius: var(--lq-radius-sm); display: inline-flex;"><IconSettings size={18} stroke={1.75} aria-hidden="true" /></a>
				</div>
			</header>
			<TopTabBar user={$auth.user ?? null} pathname={pathname} />
		{/if}
		<main id="lq-main">
			<slot />
		</main>
		{#if sidebarChrome}
			<RightSidebar {pathname} />
		{/if}
		<ShellAttribution {sidebarChrome} />
		<SessionTimeoutWarning />
	</div>
{/if}

<style>
	/* OpenWebUI's app.html pins html { overflow-y: hidden !important; } so
	   the chat UI can manage its own scroll containers. The LQ.AI shell's
	   non-chat surfaces (settings, admin sub-routes, trust page) need a
	   scrollable main; the chat shell already wraps itself in flex+
	   overflow-hidden and manages internal scroll, so adding overflow-y
	   here doesn't disturb it. min-height: 0 lets flex children shrink
	   correctly inside the column. */
	.lq-shell { background: var(--lq-canvas); color: var(--lq-text); height: 100vh; display: flex; flex-direction: column; }
	.lq-topbar {
		display: flex; align-items: center; justify-content: space-between;
		padding: var(--lq-space-3) var(--lq-space-4);
		border-bottom: 1px solid var(--lq-border);
		background: var(--lq-canvas);
		flex-shrink: 0;
	}
	.lq-brand {
		font-size: 16px; font-weight: 600; color: var(--lq-text);
		text-decoration: none;
	}
	.lq-brand-lq { color: var(--lq-accent); }
	main { flex: 1; min-height: 0; overflow-y: auto; }
	/* Switch on: left sidebar | page header over main | right sidebar. The
	   header and the right sidebar are absent when the page has nothing for
	   them, and the middle column takes the space. Explicit placement keeps
	   main in its row when the header is absent. */
	.lq-shell-sidebar {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		grid-template-rows: auto minmax(0, 1fr) auto;
	}
	.lq-shell-sidebar > :global(.lq-sidebar) {
		grid-column: 1;
		grid-row: 1 / -1;
	}
	.lq-shell-sidebar > :global(.lq-page-header) {
		grid-column: 2;
		grid-row: 1;
	}
	.lq-shell-sidebar main {
		grid-column: 2;
		grid-row: 2;
		min-width: 0;
	}
	/* The attribution footer below the page, present only while the left
	   sidebar is collapsed to its strip (see ShellAttribution). */
	.lq-shell-sidebar > :global([data-testid='lq-ai-dual-branding-footer']) {
		grid-column: 2;
		grid-row: 3;
		min-width: 0;
	}
	.lq-shell-sidebar > :global(.lq-right-sidebar) {
		grid-column: 3;
		grid-row: 1 / -1;
	}
</style>
