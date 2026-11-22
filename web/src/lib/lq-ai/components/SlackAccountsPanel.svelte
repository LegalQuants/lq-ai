<script lang="ts">
	import LqButton from '$lib/lq-ai/components/shared/LqButton.svelte';
	import { onMount } from 'svelte';
	import { slackAccounts, type SlackAccount } from '$lib/lq-ai/api/slack';
	let accounts: SlackAccount[] = [];
	let loading = true;
	let busy = '';
	let error = '';
	let notice = '';
	onMount(async () => {
		try {
			accounts = await slackAccounts.list();
		} catch {
			error = 'Unable to load linked Slack accounts. Reload to try again.';
		} finally {
			loading = false;
		}
	});
	async function unlink(id: string) {
		busy = id;
		error = '';
		notice = '';
		try {
			await slackAccounts.unlink(id);
			accounts = accounts.filter((account) => account.id !== id);
			notice = 'Slack account unlinked. Run /lq help in Slack to link it again.';
		} catch {
			error = 'Unable to unlink this Slack account. Reload and try again.';
		} finally {
			busy = '';
		}
	}
</script>

<p>Run <code>/lq help</code> in Slack, then sign in and confirm the private account link.</p>
{#if loading}<p role="status">Loading linked accounts…</p>
{:else if !error && accounts.length === 0}<p>No Slack accounts linked.</p>{/if}
<ul aria-label="Linked Slack accounts">
	{#each accounts as account (account.id)}
		<li>
			<span><strong>{account.team_name}</strong> ({account.team_id}) · {account.slack_user_id}</span
			>
			<LqButton
				variant="outline"
				disabled={!!busy}
				on:click={() => unlink(account.id)}
				aria-label={`Unlink ${account.slack_user_id} from ${account.team_name}`}
				>{busy === account.id ? 'Unlinking…' : 'Unlink'}</LqButton
			>
		</li>
	{/each}
</ul>
{#if notice}<p role="status">{notice}</p>{/if}
{#if error}<p role="alert">{error}</p>{/if}

<style>
	p {
		margin: var(--lq-space-3) 0;
	}
	li {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-3);
		padding: var(--lq-space-3) 0;
	}
</style>
