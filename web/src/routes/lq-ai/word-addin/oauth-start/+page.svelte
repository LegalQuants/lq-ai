<script lang="ts" context="module">
	// Minimal ambient declaration for the Office.js surface this page
	// uses — keeps us from pulling @types/office-js (~140KB of types
	// for a single dialog page) into the web/ devDependencies. Full
	// types live in word-addin/ where the React task pane actually
	// uses the broader Office API surface.
	declare const Office: {
		onReady: (callback: () => void) => void;
		context: {
			ui: {
				messageParent: (message: string) => void;
			};
		};
	};
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { authApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';

	let email = '';
	let password = '';
	let error: string | null = null;
	let busy = false;
	let officeReady = false;
	let officeError: string | null = null;

	onMount(() => {
		// Office.js is loaded via the <svelte:head> script tag below. The
		// library may have already fired its `Office.onReady` callback
		// before this mount handler runs; guard for both timings.
		if (typeof Office === 'undefined') {
			officeError =
				'This page is intended to be opened from the LQ.AI Word add-in. The Office.js library did not load — close this window and try again.';
			return;
		}
		Office.onReady(() => {
			officeReady = true;
		});
	});

	function postToParent(message: unknown) {
		try {
			Office.context.ui.messageParent(JSON.stringify(message));
		} catch (e) {
			// In rare edge cases (Office host disconnect) messageParent
			// throws. Surface the error inline; the user can close the
			// dialog manually.
			officeError =
				'Could not post the sign-in result back to the LQ.AI add-in. ' +
				(e instanceof Error ? e.message : 'Unknown error.');
		}
	}

	async function submit() {
		if (!officeReady) {
			officeError = 'The Office.js bridge is not ready yet. Please wait a moment and try again.';
			return;
		}
		error = null;
		busy = true;
		try {
			const res = await authApi.login({ email, password });
			if (res.user.must_change_password) {
				// Word add-in doesn't have a change-password UI in M3-B2 — the
				// user has to set a new password in the web app first. Tell
				// the add-in to surface that path rather than getting stuck.
				postToParent({
					type: 'oauth-error',
					reason:
						'Your account requires a password change before you can use the add-in. Open the LQ.AI web app, sign in, change your password, and then return to the add-in to sign in.'
				});
				return;
			}
			postToParent({ type: 'oauth-success', login: res });
		} catch (e: unknown) {
			if (e instanceof LQAIApiError) {
				error = e.status === 401 ? 'Invalid email or password.' : e.message;
			} else if (e instanceof Error) {
				error = e.message;
			} else {
				error = 'Sign-in failed.';
			}
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head>
	<title>Sign in to LQ.AI · Word add-in</title>
	<!-- Office.js is required for `Office.context.ui.messageParent` to
	     reach the parent task pane. Loaded from Microsoft's CDN; same
	     URL the task pane itself uses. -->
	<script src="https://appsforoffice.microsoft.com/lib/1/hosted/office.js"></script>
</svelte:head>

<main class="oauth-page">
	<div class="oauth-card">
		<header class="oauth-header">
			<span class="oauth-logo" aria-hidden="true">LQ</span>
			<h1 class="oauth-title">Sign in to LQ.AI</h1>
			<p class="oauth-subtitle">Word add-in is requesting access to this deployment.</p>
		</header>

		{#if officeError}
			<p class="oauth-status oauth-status-error" role="alert">{officeError}</p>
		{:else}
			<form class="oauth-form" on:submit|preventDefault={submit}>
				<div class="form-row">
					<label for="email">Email</label>
					<input
						id="email"
						type="email"
						autocomplete="username"
						required
						bind:value={email}
						disabled={busy}
					/>
				</div>
				<div class="form-row">
					<label for="password">Password</label>
					<input
						id="password"
						type="password"
						autocomplete="current-password"
						required
						bind:value={password}
						disabled={busy}
					/>
				</div>
				{#if error}
					<p class="oauth-status oauth-status-error" role="alert">{error}</p>
				{/if}
				<button type="submit" class="oauth-submit" disabled={busy || !officeReady}>
					{busy ? 'Signing in…' : officeReady ? 'Sign in' : 'Waiting for Office.js…'}
				</button>
			</form>
		{/if}

		<p class="oauth-footnote">
			Closing this window cancels the sign-in. You can retry from the add-in's task pane.
		</p>
	</div>
</main>

<style>
	.oauth-page {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--lq-bg, #f7f9fc);
		padding: var(--lq-space-4, 16px);
		font-family:
			'Segoe UI',
			-apple-system,
			BlinkMacSystemFont,
			'Helvetica Neue',
			Arial,
			sans-serif;
	}

	.oauth-card {
		width: 100%;
		max-width: 360px;
		background: var(--lq-surface, white);
		border: 1px solid var(--lq-border, #e1e5ec);
		border-radius: 8px;
		padding: var(--lq-space-5, 20px);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4, 16px);
		box-shadow: 0 4px 14px rgba(0, 0, 0, 0.04);
	}

	.oauth-header {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		text-align: center;
	}

	.oauth-logo {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border-radius: 8px;
		background: var(--lq-accent, #2563eb);
		color: white;
		font-weight: 700;
		font-size: 13px;
		letter-spacing: 0.04em;
	}

	.oauth-title {
		margin: 0;
		font-size: 18px;
		font-weight: 600;
	}

	.oauth-subtitle {
		margin: 0;
		font-size: 13px;
		color: var(--lq-text-secondary, #5a6472);
	}

	.oauth-form {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3, 12px);
	}

	.form-row {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.form-row label {
		font-size: 13px;
		font-weight: 500;
	}

	.form-row input {
		padding: 8px 10px;
		border: 1px solid var(--lq-border, #e1e5ec);
		border-radius: 4px;
		background: var(--lq-bg, white);
		color: var(--lq-text, #1f2329);
		font-size: 14px;
		font-family: inherit;
	}

	.form-row input:focus {
		outline: 2px solid var(--lq-accent, #2563eb);
		outline-offset: -1px;
		border-color: var(--lq-accent, #2563eb);
	}

	.oauth-submit {
		margin-top: 4px;
		background: var(--lq-accent, #2563eb);
		color: white;
		border: none;
		border-radius: 4px;
		padding: 9px 14px;
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
		transition: opacity 0.15s;
	}

	.oauth-submit:hover:not(:disabled) {
		opacity: 0.9;
	}

	.oauth-submit:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}

	.oauth-status {
		margin: 0;
		padding: 8px 10px;
		border-radius: 4px;
		font-size: 13px;
	}

	.oauth-status-error {
		background: var(--lq-error-bg, #fef2f2);
		color: var(--lq-error-text, #991b1b);
		border: 1px solid var(--lq-error-border, #fecaca);
	}

	.oauth-footnote {
		margin: 0;
		font-size: 12px;
		color: var(--lq-text-secondary, #5a6472);
		text-align: center;
		line-height: 1.5;
	}
</style>
