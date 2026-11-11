<script lang="ts">
	import { onMount } from 'svelte';
	import { auth } from '../auth/store';
	import { setUser } from '../auth/store';
	import { mfaDisable, mfaEnable, mfaSetup } from '../api/auth';
	import type { MfaSetupResponse } from '../types';
	import { get } from 'svelte/store';
	import LqText from './shared/LqText.svelte';

	type MfaState =
		| { kind: 'idle'; alreadyEnrolled: boolean }
		| { kind: 'setting-up' }
		| { kind: 'verifying'; secret: string; provisioning_uri: string; recovery_codes: string[]; code: string; error: string | null }
		| { kind: 'enabled' }
		| { kind: 'disabling'; password: string; code: string; error: string | null }
		| { kind: 'error'; message: string };

	let state: MfaState = { kind: 'idle', alreadyEnrolled: false };

	onMount(() => {
		const user = get(auth).user;
		state = { kind: 'idle', alreadyEnrolled: user?.mfa_enabled ?? false };
	});

	async function startSetup() {
		state = { kind: 'setting-up' };
		try {
			const res: MfaSetupResponse = await mfaSetup();
			state = {
				kind: 'verifying',
				secret: res.secret,
				provisioning_uri: res.provisioning_uri,
				recovery_codes: res.recovery_codes,
				code: '',
				error: null
			};
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : 'Setup failed. Please try again.';
			state = { kind: 'error', message: msg };
		}
	}

	async function submitEnable() {
		if (state.kind !== 'verifying') return;
		const { secret, provisioning_uri, recovery_codes, code } = state;
		state = { kind: 'verifying', secret, provisioning_uri, recovery_codes, code, error: null };
		try {
			await mfaEnable(code);
			const user = get(auth).user;
			if (user) setUser({ ...user, mfa_enabled: true });
			state = { kind: 'enabled' };
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : 'Invalid code. Please try again.';
			state = { kind: 'verifying', secret, provisioning_uri, recovery_codes, code, error: msg };
		}
	}

	function beginDisable() {
		state = { kind: 'disabling', password: '', code: '', error: null };
	}

	async function submitDisable() {
		if (state.kind !== 'disabling') return;
		const { password, code } = state;
		state = { kind: 'disabling', password, code, error: null };
		try {
			await mfaDisable(password, code);
			const user = get(auth).user;
			if (user) setUser({ ...user, mfa_enabled: false });
			state = { kind: 'idle', alreadyEnrolled: false };
		} catch (e: unknown) {
			state = {
				kind: 'disabling',
				password,
				code,
				error: 'Invalid credentials or MFA code. Please try again.'
			};
		}
	}

	function reset() {
		const user = get(auth).user;
		state = { kind: 'idle', alreadyEnrolled: user?.mfa_enabled ?? false };
	}

	async function copyToClipboard(text: string) {
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			// Clipboard unavailable; user can select text manually.
		}
	}

	$: verifying = state.kind === 'verifying' ? state : null;
	$: disabling = state.kind === 'disabling' ? state : null;
</script>

<div class="mfa-panel">
	{#if state.kind === 'idle'}
		{#if state.alreadyEnrolled}
			<div class="status-row status-row--enabled">
				<span class="status-badge status-badge--on">MFA enabled</span>
				<LqText as="p" size="14" tone="primary">Your account is protected with a time-based one-time password (TOTP).</LqText>
				<button type="button" class="lq-btn-secondary" on:click={beginDisable}>
					Disable MFA
				</button>
			</div>
		{:else}
			<div class="status-row">
				<span class="status-badge status-badge--off">MFA not enabled</span>
				<LqText as="p" size="14" tone="primary">Add a second factor to protect your account with an authenticator app.</LqText>
				<button type="button" class="lq-btn-primary" on:click={startSetup}>
					Set up MFA
				</button>
			</div>
		{/if}

	{:else if state.kind === 'setting-up'}
		<LqText as="p" size="14" tone="secondary">Generating your TOTP secret…</LqText>

	{:else if state.kind === 'verifying' && verifying}
		<div class="verify-section">
			<LqText as="p" size="14" tone="primary" style="margin-bottom: var(--lq-space-4);">
				Scan with your authenticator app, or enter the secret manually.
			</LqText>

			<div class="secret-block">
				<p class="field-label">Authenticator URI</p>
				<div class="code-row">
					<code class="mono-block">{verifying.provisioning_uri}</code>
					<button
						type="button"
						class="lq-btn-ghost copy-btn"
						on:click={() => copyToClipboard(verifying!.provisioning_uri)}
					>
						Copy URI
					</button>
				</div>

				<p class="field-label" style="margin-top: var(--lq-space-3);">Manual entry secret</p>
				<div class="code-row">
					<code class="mono-block">{verifying.secret}</code>
					<button
						type="button"
						class="lq-btn-ghost copy-btn"
						on:click={() => copyToClipboard(verifying!.secret)}
					>
						Copy
					</button>
				</div>
			</div>

			<div class="recovery-section">
				<p class="field-label">Recovery codes — print or save these now</p>
				<LqText as="p" size="12" tone="secondary" style="margin-bottom: var(--lq-space-2);">
					Each code can only be used once. Store them somewhere safe — you cannot view them again.
				</LqText>
				<div class="recovery-grid">
					{#each verifying.recovery_codes as rc}
						<code class="mono-block mono-block--sm">{rc}</code>
					{/each}
				</div>
			</div>

			<div class="verify-form">
				<label class="field-label" for="mfa-code">Enter the 6-digit code from your app to confirm</label>
				<div class="input-row">
					<input
						id="mfa-code"
						type="text"
						inputmode="numeric"
						autocomplete="one-time-code"
						maxlength="6"
						class="lq-input"
						placeholder="000000"
						bind:value={verifying.code}
						on:keydown={(e) => e.key === 'Enter' && submitEnable()}
					/>
					<button
						type="button"
						class="lq-btn-primary"
						disabled={verifying.code.length !== 6}
						on:click={submitEnable}
					>
						Verify and enable
					</button>
				</div>
				{#if verifying.error}
					<p class="error-msg">{verifying.error}</p>
				{/if}
			</div>
		</div>

	{:else if state.kind === 'enabled'}
		<div class="status-row status-row--enabled">
			<span class="status-badge status-badge--on">MFA enabled</span>
			<LqText as="p" size="14" tone="primary">Your account is protected with a time-based one-time password (TOTP).</LqText>
			<button type="button" class="lq-btn-secondary" on:click={beginDisable}>
				Disable MFA
			</button>
		</div>

	{:else if state.kind === 'disabling' && disabling}
		<div class="disable-form">
			<LqText as="p" size="14" tone="primary" style="margin-bottom: var(--lq-space-4);">
				Enter your current password and an active MFA code to disable two-factor authentication.
			</LqText>
			<label class="field-label" for="dis-password">Current password</label>
			<input
				id="dis-password"
				type="password"
				class="lq-input"
				autocomplete="current-password"
				bind:value={disabling.password}
				style="margin-bottom: var(--lq-space-3);"
			/>

			<label class="field-label" for="dis-code">MFA code</label>
			<input
				id="dis-code"
				type="text"
				inputmode="numeric"
				autocomplete="one-time-code"
				maxlength="6"
				class="lq-input"
				placeholder="000000"
				bind:value={disabling.code}
				on:keydown={(e) => e.key === 'Enter' && submitDisable()}
			/>

			{#if disabling.error}
				<p class="error-msg" style="margin-top: var(--lq-space-2);">{disabling.error}</p>
			{/if}

			<div class="action-row" style="margin-top: var(--lq-space-4);">
				<button
					type="button"
					class="lq-btn-primary"
					disabled={!disabling.password || disabling.code.length !== 6}
					on:click={submitDisable}
				>
					Disable MFA
				</button>
				<button type="button" class="lq-btn-ghost" on:click={reset}>Cancel</button>
			</div>
		</div>

	{:else if state.kind === 'error'}
		<p class="error-msg">{state.message}</p>
		<button type="button" class="lq-btn-secondary" style="margin-top: var(--lq-space-3);" on:click={reset}>
			Try again
		</button>
	{/if}
</div>

<style>
	.mfa-panel {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.status-row {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.status-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		font-weight: 600;
		padding: 2px 8px;
		border-radius: var(--lq-radius-pill);
		width: fit-content;
	}
	.status-badge--on {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
	}
	.status-badge--off {
		background: var(--lq-inset);
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
	}

	.secret-block {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-3);
		margin-bottom: var(--lq-space-4);
	}

	.code-row {
		display: flex;
		align-items: flex-start;
		gap: var(--lq-space-2);
		flex-wrap: wrap;
	}

	.mono-block {
		font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
		font-size: 12px;
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		padding: 2px 6px;
		word-break: break-all;
		user-select: all;
		flex: 1;
	}

	.mono-block--sm {
		flex: none;
		user-select: all;
		font-size: 11px;
	}

	.recovery-section {
		margin-bottom: var(--lq-space-4);
	}

	.recovery-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--lq-space-2);
		margin-top: var(--lq-space-2);
	}

	.field-label {
		display: block;
		font-size: 12px;
		font-weight: 600;
		color: var(--lq-text-secondary);
		margin-bottom: var(--lq-space-1);
	}

	.lq-input {
		display: block;
		width: 100%;
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border-strong);
		border-radius: var(--lq-radius);
		font-size: 14px;
		color: var(--lq-text);
		background: var(--lq-canvas);
		box-sizing: border-box;
	}
	.lq-input:focus {
		outline: 2px solid var(--lq-accent);
		outline-offset: 1px;
	}

	.input-row {
		display: flex;
		gap: var(--lq-space-2);
		align-items: flex-start;
	}
	.input-row .lq-input {
		width: 120px;
		flex-shrink: 0;
	}

	.action-row {
		display: flex;
		gap: var(--lq-space-2);
		align-items: center;
	}

	.error-msg {
		font-size: 13px;
		color: var(--lq-error);
		margin-top: var(--lq-space-1);
	}

	.copy-btn {
		flex-shrink: 0;
	}

	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:hover { opacity: 0.85; }
	.lq-btn-primary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }
	.lq-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

	.lq-btn-secondary {
		background: var(--lq-canvas);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-secondary:hover { background: var(--lq-accent-soft); }
	.lq-btn-secondary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }

	.lq-btn-ghost {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		cursor: pointer;
	}
	.lq-btn-ghost:hover { background: var(--lq-inset); }
	.lq-btn-ghost:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }

	.verify-form { margin-top: var(--lq-space-2); }
	.verify-section { display: flex; flex-direction: column; gap: 0; }
	.disable-form { display: flex; flex-direction: column; }
</style>
