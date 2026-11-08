<!--
  SkillWizardSection.svelte

  Used by SkillWizard (Task 4.2) for its 4 numbered sections. Design-token swap
  follows Wave D.2 convention — see AttachedSkillPill.svelte / SlashPopover.svelte
  for the rationale.
-->
<script lang="ts">
	export let index: number;
	export let title: string;
	export let hint: string = '';
</script>

<section class="lq-wiz-section">
	<header>
		<span class="num">{index}</span>
		<h3>{title}</h3>
	</header>
	{#if hint}
		<p class="hint">{hint}</p>
	{/if}
	<div class="body">
		<slot />
	</div>
</section>

<style>
	.lq-wiz-section {
		border-bottom: 1px solid var(--lq-border);
		padding: 24px 0;
	}
	header {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 6px;
	}
	.num {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 50%;
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		font-weight: 600;
		font-size: 13px;
	}
	h3 {
		margin: 0;
		font-size: 18px;
		font-weight: 600;
	}
	.hint {
		color: var(--lq-text-tertiary);
		font-size: 13px;
		margin: 0 0 12px 0;
	}
</style>
