<script lang="ts">
	import LqButton from '$lib/lq-ai/components/shared/LqButton.svelte';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/lq-ai/auth/store';
	import { captureSlackLink, clearSlackLink } from '$lib/lq-ai/auth/slack-link';
	import { slackAccounts, type SlackLinkPreview } from '$lib/lq-ai/api/slack';
	let token: string | null = null;
	let preview: SlackLinkPreview | null = null;
	let error = '';
	let loading = true;
	let busy = false;
	let complete = false;
	onMount(async () => {
		token = captureSlackLink();
		if (!token) {
			error = 'Run /lq help in Slack to get a new account link.';
			loading = false;
			return;
		}
		try {
			preview = await slackAccounts.preview(token);
		} catch {
			error = 'This link is unavailable. Run /lq help in Slack for a new link.';
			clearSlackLink();
		} finally {
			loading = false;
		}
	});
	async function confirm() {
		if (!token || busy || complete) return;
		busy = true;
		error = '';
		try {
			await slackAccounts.confirm(token);
			complete = true;
			clearSlackLink();
			token = null;
		} catch {
			error =
				'Unable to link this account. It may already be linked or the link may have expired. Run /lq help for a new link.';
		} finally {
			busy = false;
		}
	}
	function cancel() {
		clearSlackLink();
		token = null;
		goto('/lq-ai/settings/account');
	}
</script>

<svelte:head
	><title>Link Slack account · LQ.AI</title><meta
		name="referrer"
		content="no-referrer"
	/></svelte:head
>
<section class="link-card" aria-labelledby="link-title">
	<h1 id="link-title" class="lq-text-page-h">Link your Slack account</h1>
	{#if loading}<p role="status">Checking your link…</p>
	{:else if complete}
		<p role="status">Your Slack account is linked.</p>
		<p>You can unlink it from your account settings at any time.</p>
		<a href="/lq-ai/settings/account">Manage linked accounts</a>
	{:else}
		{#if preview}
			<p>
				Link Slack user <strong>{preview.slack_user_id}</strong> in
				<strong>{preview.team_name}</strong>
				({preview.team_id}) to your LQ.AI account <strong>{$auth.user?.email}</strong>?
			</p>
			<p>
				Confirm only if you requested this link from your Slack account. It expires at {new Date(
					preview.expires_at
				).toLocaleTimeString()}.
			</p>
			<p>
				Future Slack requests will use your LQ.AI permissions. Linking does not grant access to
				additional matters.
			</p>
			<LqButton on:click={confirm} disabled={busy}
				>{busy ? 'Linking…' : 'Confirm account link'}</LqButton
			>
		{/if}
		<LqButton variant="outline" on:click={cancel} disabled={busy}>Cancel</LqButton>
	{/if}
	{#if error}<p role="alert">{error}</p>{/if}
</section>

<style>
	.link-card {
		max-width: 640px;
		margin: var(--lq-space-6) auto;
		padding: var(--lq-space-6);
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
	}
	p {
		margin: var(--lq-space-4) 0;
	}
</style>
