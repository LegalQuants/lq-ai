<script lang="ts">
	import LqButton from '../../components/shared/LqButton.svelte';
	import LqPill from '../../components/shared/LqPill.svelte';
	import LqSwitch from '../../components/shared/LqSwitch.svelte';
	import LqGroup from '../../components/shared/LqGroup.svelte';
	import LqStack from '../../components/shared/LqStack.svelte';
	import LqHoverCard from '../../components/shared/LqHoverCard';
	import { LQ_TONES } from '../../components/shared/types';
	import TierBadge from '../../components/TierBadge.svelte';
	import TierDetailsPanel from '../../components/TierDetailsPanel.svelte';
	import EnhancedDiffModal from '../../components/EnhancedDiffModal.svelte';
	import CitationLedgerPanel from '../../components/CitationLedgerPanel.svelte';

	let clicks = 0;
	let removals = 0;
	let checked = false;
	let changes = 0;
	let tierOpen = false;
	let diffOpen = false;
	let ledgerOpen = false;
</script>

<LqStack gap="md">
	<LqGroup gap="sm">
		{#each LQ_TONES as tone}
			<LqButton variant="subtle" {tone}>{tone}</LqButton>
		{/each}
	</LqGroup>
	<LqGroup gap="sm">
		<LqButton
			class="caller-class"
			data-testid="activate"
			aria-label="Activate"
			on:click={() => clicks++}>Activate</LqButton
		>
		<LqButton disabled data-testid="disabled" on:click={() => clicks++}>Disabled</LqButton>
		<LqPill text="Skill" data-testid="pill" onClick={() => clicks++} onRemove={() => removals++} />
		<LqSwitch
			class="caller-class"
			bind:checked
			aria-label="Keep skills on"
			data-testid="switch"
			onCheckedChange={() => changes++}
		/>
	</LqGroup>
	<p data-testid="counts">
		Clicks {clicks}; removals {removals}; checked {checked}; changes {changes}
	</p>
	<LqGroup gap="sm">
		<TierBadge tier={3} on:open={() => (tierOpen = true)} />
		<LqButton on:click={() => (diffOpen = true)}>Compare prompt</LqButton>
		<LqButton on:click={() => (ledgerOpen = true)}>Citation ledger</LqButton>
		<LqHoverCard>
			<LqHoverCard.Target><LqButton>Hover reference</LqButton></LqHoverCard.Target>
			<LqHoverCard.Dropdown data-testid="hover-content">Additional information</LqHoverCard.Dropdown
			>
		</LqHoverCard>
	</LqGroup>
</LqStack>
{#if tierOpen}<TierDetailsPanel
		tier={3}
		provider="Example provider"
		model="Example model"
		on:close={() => (tierOpen = false)}
	/>{/if}
{#if diffOpen}<EnhancedDiffModal
		original="Original prompt"
		enhanced="Enhanced prompt"
		on:close={() => (diffOpen = false)}
	/>{/if}
<CitationLedgerPanel open={ledgerOpen} entries={[]} onClose={() => (ledgerOpen = false)} />
