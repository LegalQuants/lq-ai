<script lang="ts">
	export let id: string;
	export let title: string;
	export let enabled = true;
	export let spaced = false;
	let expanded = false;
</script>

<div class="compact-panel" class:enabled class:spaced>
	<button
		id={`${id}-toggle`}
		type="button"
		class="panel-toggle"
		aria-expanded={expanded}
		aria-controls={`${id}-content`}
		on:click={() => (expanded = !expanded)}
	>
		<span>{title}</span>
		<span aria-hidden="true">{expanded ? '−' : '+'}</span>
	</button>
	<div id={`${id}-content`} class="panel-content" class:collapsed={!expanded}>
		<slot />
	</div>
</div>

<style>
	.compact-panel,
	.panel-content {
		display: contents;
	}

	.panel-toggle {
		display: none;
	}

	.spaced > .panel-content > :global(* + *) {
		margin-top: 8px;
	}

	@media (max-width: 1279px) {
		.enabled {
			display: block;
			flex-shrink: 0;
			min-width: 0;
		}

		.enabled > .panel-toggle {
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 8px;
			width: 100%;
			padding: 6px 12px;
			border-bottom: 1px solid var(--lq-border);
			background: var(--lq-inset);
			color: var(--lq-text);
			font-size: 13px;
			text-align: left;
		}

		.panel-toggle:focus-visible {
			outline: 2px solid var(--lq-accent);
			outline-offset: -2px;
		}

		.enabled > .panel-content {
			display: block;
			max-height: min(25vh, 12rem);
			overflow: auto;
		}

		.enabled > .panel-content.collapsed {
			display: none;
		}

		.enabled > .panel-content > :global(*) {
			max-width: 100%;
		}
	}
</style>
