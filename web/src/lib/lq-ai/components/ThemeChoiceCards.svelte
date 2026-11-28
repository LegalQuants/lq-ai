<!--
  The theme choice in Account settings › Appearance (ADR 0045 §2; board S46).
  Three cards, each a real radio with a small preview of its theme. A preview
  shows its own theme whatever the page is in, so it reads the fixed
  `--lq-preview-*` tokens, not the theme's own.
-->
<script lang="ts">
	import { chooseTheme } from '$lib/lq-ai/stores/preferences';
	import { themeChoice } from '$lib/lq-ai/stores/theme';
	import { LQAI_THEME_CHOICES, LQAI_THEME_LABEL, type LQAIThemeChoice } from '$lib/lq-ai/theme';
	import LqText from './shared/LqText.svelte';
	import LqTitle from './shared/LqTitle.svelte';

	const NOTE: Record<LQAIThemeChoice, string> = {
		light: 'White, black text',
		dark: 'Black, white text',
		system: 'Follows your device'
	};
</script>

<section class="lq-theme" data-testid="lq-theme-choice">
	<LqTitle order={3} size="16" weight="semibold" tone="primary" id="lq-theme-title">Theme</LqTitle>
	<LqText as="p" size="13.5" tone="secondary" id="lq-theme-hint">
		Light keeps the familiar white look; Dark is all black. Match system follows your device.
	</LqText>
	<div
		class="lq-theme-cards"
		role="radiogroup"
		aria-labelledby="lq-theme-title"
		aria-describedby="lq-theme-hint"
	>
		{#each LQAI_THEME_CHOICES as choice (choice)}
			<label
				class="lq-theme-card"
				class:lq-theme-card-on={$themeChoice === choice}
				data-testid="lq-theme-card-{choice}"
			>
				<span class="lq-theme-preview lq-theme-preview-{choice}" aria-hidden="true">
					{#if choice !== 'system'}
						<span class="lq-theme-preview-side"><i></i><i></i><i></i></span>
						<span class="lq-theme-preview-main"><i></i></span>
					{/if}
				</span>
				<span class="lq-theme-name">
					<input
						type="radio"
						name="lq-theme"
						value={choice}
						checked={$themeChoice === choice}
						on:change={() => void chooseTheme(choice)}
					/>
					<LqText as="span" size="14" weight="semibold" tone="primary"
						>{LQAI_THEME_LABEL[choice]}</LqText
					>
				</span>
				<LqText as="span" size="12.5" tone="secondary">{NOTE[choice]}</LqText>
			</label>
		{/each}
	</div>
</section>

<style>
	.lq-theme {
		display: flex;
		flex-direction: column;
		gap: 10px;
		margin-bottom: var(--lq-space-6);
	}
	.lq-theme-cards {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}
	.lq-theme-card {
		flex: 1 1 150px;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
		/* One pixel more padding than the chosen card, whose border is one pixel wider. */
		padding: 14px;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-card);
		background: var(--lq-raised);
		cursor: pointer;
	}
	.lq-theme-card-on {
		padding: 13px;
		border: 2px solid var(--lq-text);
	}
	.lq-theme-card:focus-within {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.lq-theme-name {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.lq-theme-name input {
		margin: 0;
		accent-color: var(--lq-text);
	}
	.lq-theme-name input:focus-visible {
		/* The card shows the focus. */
		outline: none;
	}

	.lq-theme-preview {
		height: 64px;
		display: flex;
		overflow: hidden;
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-tile);
	}
	.lq-theme-preview-light {
		--preview-canvas: var(--lq-preview-light-canvas);
		--preview-inset: var(--lq-preview-light-inset);
		--preview-text: var(--lq-preview-light-text);
		background: var(--preview-canvas);
	}
	.lq-theme-preview-dark {
		--preview-canvas: var(--lq-preview-dark-canvas);
		--preview-inset: var(--lq-preview-dark-inset);
		--preview-text: var(--lq-preview-dark-text);
		background: var(--preview-canvas);
	}
	.lq-theme-preview-system {
		background: linear-gradient(
			90deg,
			var(--lq-preview-light-canvas) 50%,
			var(--lq-preview-dark-canvas) 50%
		);
	}
	.lq-theme-preview-side {
		width: 26%;
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 6px;
		background: var(--preview-inset);
	}
	.lq-theme-preview-side i {
		height: 4px;
		border-radius: var(--lq-radius-pill);
		background: var(--preview-text);
		opacity: 0.35;
	}
	.lq-theme-preview-side i:first-child {
		width: 70%;
		height: 6px;
		opacity: 1;
	}
	.lq-theme-preview-main {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		padding: 8px;
	}
	.lq-theme-preview-main i {
		height: 14px;
		border: 1px solid var(--preview-text);
		border-radius: var(--lq-radius-pill);
		opacity: 0.5;
	}
</style>
