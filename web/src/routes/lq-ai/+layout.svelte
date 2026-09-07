<script lang="ts">
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
	import DualBrandingFooter from '$lib/lq-ai/components/DualBrandingFooter.svelte';
	import TopTabBar from '$lib/lq-ai/components/TopTabBar.svelte';
	import AmbientTrustChrome from '$lib/lq-ai/components/AmbientTrustChrome.svelte';
	import NotificationBell from '$lib/lq-ai/components/NotificationBell.svelte';
	import SessionTimeoutWarning from '$lib/lq-ai/components/SessionTimeoutWarning.svelte';
	import { preferences, initPreferences } from '$lib/lq-ai/stores/preferences';
	import { shouldShowBell } from '$lib/lq-ai/autonomous/notification-bell';
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
		// Sync preferences so autonomous-gated chrome (notification bell)
		// renders for opted-in users. Non-opted-in users keep the default
		// (autonomous_enabled: false) and see NO chrome change. Not awaited:
		// the localStorage cache applies synchronously and the fresh server
		// value lands reactively — don't delay shell boot on it.
		void initPreferences();
		booted = true;
	}

	let activityHandler: (() => void) | null = null;

	onMount(() => {
		gate();
		if (!isAuthExempt($page.url.pathname)) {
			startTracker(() => goto('/lq-ai/login?reason=idle-timeout'));
			activityHandler = () => noteActivity();
			(['mousedown', 'keydown', 'scroll', 'touchstart'] as const).forEach((e) =>
				window.addEventListener(e, activityHandler!, { passive: true })
			);
		}
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
	<div class="lq-shell">
		{#if !isAuthExempt(pathname)}
			<header class="lq-topbar">
				<a class="lq-brand" href="/lq-ai">
					<span class="lq-brand-lq">LQ</span>.AI
				</a>
				<div style="display: inline-flex; align-items: center; gap: var(--lq-space-3);">
					<AmbientTrustChrome />
					{#if shouldShowBell($preferences.autonomous_enabled)}
						<NotificationBell />
					{/if}
					<a href="/lq-ai/settings/appearance" aria-label="Settings" title="Settings" style="color: var(--lq-text-secondary); text-decoration: none; padding: var(--lq-space-1) var(--lq-space-2); border-radius: var(--lq-radius-sm);">⚙</a>
				</div>
			</header>
			<TopTabBar user={$auth.user ?? null} pathname={pathname} />
		{/if}
		<main id="lq-main">
			<slot />
		</main>
		<DualBrandingFooter />
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
</style>
