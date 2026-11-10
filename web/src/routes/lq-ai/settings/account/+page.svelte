<script lang="ts">
	import MfaEnrollmentPanel from '$lib/lq-ai/components/MfaEnrollmentPanel.svelte';
	import AccountExportDeletePanel from '$lib/lq-ai/components/AccountExportDeletePanel.svelte';
	import LqText from '$lib/lq-ai/components/shared/LqText.svelte';
	import LqTitle from '$lib/lq-ai/components/shared/LqTitle.svelte';
</script>

<LqTitle order={2} size="20" weight="bold" tone="primary" style="margin-bottom: var(--lq-space-6);">Account</LqTitle>

<!-- ── Multi-factor authentication ──────────────────── -->
<section class="account-section">
	<h3 class="section-heading">Multi-factor authentication</h3>
	<LqText as="p" size="14" tone="secondary" class="section-description">
		Protect your account with a TOTP authenticator app (Google Authenticator, Authy, 1Password, etc.).
	</LqText>
	<MfaEnrollmentPanel />
</section>

<div class="section-divider" role="separator"></div>

<!-- ── Change password ──────────────────────────────── -->
<section class="account-section">
	<h3 class="section-heading">Password</h3>
	<LqText as="p" size="14" tone="secondary" class="section-description">
		Update your login password. You will be signed out of all sessions after changing.
	</LqText>
	<a href="/lq-ai/change-password" class="lq-btn-secondary">Change password</a>
</section>

<div class="section-divider" role="separator"></div>

<!-- ── Your data ─────────────────────────────────────── -->
<section class="account-section">
	<h3 class="section-heading">Your data</h3>
	<AccountExportDeletePanel />
</section>

<style>
	.account-section {
		padding: var(--lq-space-4) 0;
	}

	.section-heading {
		font-size: 15px;
		font-weight: 600;
		color: var(--lq-text);
		margin-bottom: var(--lq-space-1);
	}

	.account-section :global(.section-description) {
		margin-bottom: var(--lq-space-3);
	}

	.section-divider {
		border-top: 1px solid var(--lq-border);
	}

	.lq-btn-secondary {
		display: inline-block;
		background: var(--lq-canvas);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		text-decoration: none;
		cursor: pointer;
	}
	.lq-btn-secondary:hover { background: var(--lq-accent-soft); }
	.lq-btn-secondary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }
</style>
