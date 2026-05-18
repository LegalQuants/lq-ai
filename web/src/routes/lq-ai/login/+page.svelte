<script lang="ts">
	import { goto } from '$app/navigation';

	import { authApi, bootstrapApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import DualBrandingFooter from '$lib/lq-ai/components/DualBrandingFooter.svelte';

	let email = '';
	let password = '';
	let error: string | null = null;
	let busy = false;
	// M3-0.1 / DE-283 — populated after the first 401 if the deployment is
	// still in fresh-install state. Stays null in all other paths so the
	// hint never appears to operators who have already rotated.
	let bootstrapLogsHint: string | null = null;
	let hintCopied = false;

	async function submit() {
		error = null;
		busy = true;
		try {
			const res = await authApi.login({ email, password });
			if (res.user.must_change_password) {
				goto('/lq-ai/change-password');
			} else {
				goto('/lq-ai');
			}
		} catch (e: unknown) {
			if (e instanceof LQAIApiError) {
				error = e.status === 401 ? 'Invalid email or password.' : e.message;
				if (e.status === 401) {
					// Probe the fresh-install state lazily — only after the
					// operator has already tried and failed. A clean 401 from a
					// rotated deployment is the common case; we don't want to
					// load extra signal there.
					void checkBootstrapStatus();
				}
			} else if (e instanceof Error) {
				error = e.message;
			} else {
				error = 'Login failed.';
			}
		} finally {
			busy = false;
		}
	}

	async function checkBootstrapStatus() {
		try {
			const status = await bootstrapApi.getBootstrapStatus();
			bootstrapLogsHint = status.default_password_active ? status.logs_hint : null;
		} catch {
			// Best-effort surface: if the probe itself fails, fall back to the
			// plain 401. Don't mask the real auth error with a hint error.
			bootstrapLogsHint = null;
		}
	}

	async function copyHint() {
		if (!bootstrapLogsHint) return;
		try {
			await navigator.clipboard.writeText(bootstrapLogsHint);
			hintCopied = true;
			setTimeout(() => {
				hintCopied = false;
			}, 1500);
		} catch {
			// Clipboard write can fail under restrictive iframe sandboxes; the
			// command stays visible inline so manual copy still works.
		}
	}
</script>

<div
	class="min-h-screen flex flex-col bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100"
	data-testid="lq-ai-login-page"
>
	<main class="flex-1 flex items-center justify-center">
		<form
			class="lq-form-card max-w-sm w-full space-y-3"
			on:submit|preventDefault={submit}
		>
			<div class="flex items-center gap-2">
				<span
					class="inline-flex items-center justify-center h-9 w-9 rounded bg-indigo-600 text-white font-semibold"
				>
					LQ
				</span>
				<div>
					<h1 class="lq-text-page-h">Sign in to LQ.AI</h1>
					<p class="lq-text-caption" style="color: var(--lq-text-tertiary);">Open-Source Legal AI</p>
				</div>
			</div>

			<label class="block">
				<span class="lq-text-label">Email</span>
				<input
					type="email"
					autocomplete="username"
					required
					class="mt-1 block w-full text-sm border border-gray-300 rounded px-2 py-1 dark:bg-gray-800"
					bind:value={email}
					data-testid="lq-ai-login-email"
				/>
			</label>

			<label class="block">
				<span class="lq-text-label">Password</span>
				<input
					type="password"
					autocomplete="current-password"
					required
					class="mt-1 block w-full text-sm border border-gray-300 rounded px-2 py-1 dark:bg-gray-800"
					bind:value={password}
					data-testid="lq-ai-login-password"
				/>
			</label>

			{#if error}
				<div
					class="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1"
					data-testid="lq-ai-login-error"
				>
					{error}
				</div>
			{/if}

			{#if bootstrapLogsHint}
				<div
					class="lq-bootstrap-hint text-sm rounded border px-3 py-2 space-y-2"
					data-testid="lq-ai-bootstrap-hint"
					role="status"
					aria-live="polite"
				>
					<p class="font-medium">First-run deployment?</p>
					<p>
						The bootstrap admin password is printed once to the API
						container's logs. Run the command below to retrieve it,
						sign in, then rotate immediately.
					</p>
					<div class="flex items-stretch gap-2">
						<code
							class="flex-1 px-2 py-1 rounded bg-white dark:bg-gray-900 border border-amber-200 dark:border-amber-700 text-xs overflow-x-auto whitespace-nowrap"
							data-testid="lq-ai-bootstrap-hint-command"
						>
							{bootstrapLogsHint}
						</code>
						<button
							type="button"
							class="px-2 py-1 text-xs rounded border border-amber-300 dark:border-amber-700 hover:bg-amber-100 dark:hover:bg-amber-900"
							on:click={copyHint}
							data-testid="lq-ai-bootstrap-hint-copy"
							aria-label="Copy command to clipboard"
						>
							{hintCopied ? 'Copied' : 'Copy'}
						</button>
					</div>
				</div>
			{/if}

			<button
				type="submit"
				class="lq-btn-primary w-full"
				disabled={busy}
				data-testid="lq-ai-login-submit"
			>
				{busy ? 'Signing in…' : 'Sign in'}
			</button>
		</form>
	</main>
	<DualBrandingFooter />
</div>

<style>
	.lq-form-card {
		padding: var(--lq-space-6);
		border-radius: var(--lq-radius-lg);
		border: 1px solid var(--lq-border);
		background: var(--lq-canvas);
		box-shadow: 0 1px 4px rgba(0,0,0,0.06);
	}

	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius);
		padding: 8px 16px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
		display: block;
	}

	.lq-btn-primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.lq-bootstrap-hint {
		background: #fffbeb;
		border-color: #fcd34d;
		color: #78350f;
	}

	:global(.dark) .lq-bootstrap-hint {
		background: rgba(120, 53, 15, 0.25);
		border-color: rgba(252, 211, 77, 0.4);
		color: #fde68a;
	}
</style>
