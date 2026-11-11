<script lang="ts">
	import { authApi } from '../api';

	export let onComplete: () => void = () => undefined;

	let currentPassword = '';
	let newPassword = '';
	let confirmPassword = '';
	let busy = false;
	let error: string | null = null;

	async function submit() {
		error = null;
		if (newPassword.length < 12) {
			error = 'New password must be at least 12 characters.';
			return;
		}
		if (newPassword !== confirmPassword) {
			error = 'New password and confirmation do not match.';
			return;
		}
		if (newPassword === currentPassword) {
			error = 'New password must differ from the current password.';
			return;
		}
		busy = true;
		try {
			await authApi.changePassword({
				current_password: currentPassword,
				new_password: newPassword
			});
			// Server revoked our sessions; the auth store is now empty.
			onComplete();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to change password.';
		} finally {
			busy = false;
		}
	}
</script>

<form
	class="max-w-md mx-auto mt-12 p-6 rounded-lg shadow border lq-t-border lq-t-canvas space-y-3"
	on:submit|preventDefault={submit}
	data-testid="lq-ai-change-password-form"
>
	<h1 class="text-lg font-semibold lq-t-text">Change your password</h1>
	<p class="text-sm lq-t-text2">
		The first-run admin account requires a password change before any other action. Your new
		password must be at least 12 characters and differ from the current one.
	</p>

	<label class="block">
		<span class="text-sm lq-t-text2">Current password</span>
		<input
			type="password"
			class="mt-1 block w-full text-sm border lq-t-border-strong rounded px-2 py-1"
			bind:value={currentPassword}
			required
			data-testid="lq-ai-current-password"
		/>
	</label>

	<label class="block">
		<span class="text-sm lq-t-text2">New password</span>
		<input
			type="password"
			class="mt-1 block w-full text-sm border lq-t-border-strong rounded px-2 py-1"
			bind:value={newPassword}
			minlength="12"
			required
			data-testid="lq-ai-new-password"
		/>
	</label>

	<label class="block">
		<span class="text-sm lq-t-text2">Confirm new password</span>
		<input
			type="password"
			class="mt-1 block w-full text-sm border lq-t-border-strong rounded px-2 py-1"
			bind:value={confirmPassword}
			minlength="12"
			required
			data-testid="lq-ai-confirm-password"
		/>
	</label>

	{#if error}
		<div
			class="text-sm lq-t-error lq-t-error-bg border lq-t-error-border rounded px-2 py-1"
			data-testid="lq-ai-change-password-error"
		>
			{error}
		</div>
	{/if}

	<button
		type="submit"
		class="w-full px-3 py-2 rounded-md lq-t-primary-bg lq-t-on-accent lq-t-primary-hover disabled:opacity-50 text-sm font-medium"
		disabled={busy}
		data-testid="lq-ai-change-password-submit"
	>
		{busy ? 'Changing…' : 'Change password'}
	</button>
</form>

<style>
	/* Colour tokens replacing Tailwind palette utilities (S1-1b). */
	.lq-t-border {
		border-color: var(--lq-border);
	}
	.lq-t-border-strong {
		border-color: var(--lq-border-strong);
	}
	.lq-t-canvas {
		background-color: var(--lq-canvas);
	}
	.lq-t-error {
		color: var(--lq-error);
	}
	.lq-t-error-bg {
		background-color: var(--lq-error-bg);
	}
	.lq-t-error-border {
		border-color: var(--lq-error-border);
	}
	.lq-t-on-accent {
		color: var(--lq-on-accent);
	}
	.lq-t-primary-bg {
		background-color: var(--lq-accent);
	}
	.lq-t-primary-hover:hover {
		opacity: 0.85;
	}
	.lq-t-text {
		color: var(--lq-text);
	}
	.lq-t-text2 {
		color: var(--lq-text-secondary);
	}
</style>
