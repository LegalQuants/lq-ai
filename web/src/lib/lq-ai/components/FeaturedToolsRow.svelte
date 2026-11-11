<script lang="ts">
	import { preferences } from '$lib/lq-ai/stores/preferences';
	import LqText from './shared/LqText.svelte';
	import {
		IconBooks,
		IconClipboardList,
		IconPlayerPlay,
		IconRobot,
		IconSparkles,
		IconTable,
		IconTool
	} from '@tabler/icons-svelte';

	$: mode = $preferences.featured_tools;

	// Autonomous is opt-in / off by default. Surface it for everyone, but route
	// a not-yet-enabled user to the Settings opt-in (so they can reach the toggle
	// without hunting the gear icon) and an enabled user straight to the layer.
	$: autonomousHref = $preferences.autonomous_enabled
		? '/lq-ai/autonomous'
		: '/lq-ai/settings/autonomous';

	// The cards carry no aria-label: each link is named by its visible text, so
	// the name a screen reader announces contains the words on the card
	// (WCAG 2.5.3, label in name; axe `label-content-name-mismatch`).
	$: tools = [
		{
			id: 'enhance',
			title: 'Enhance Prompt',
			icon: IconSparkles,
			description: 'Rewrite and strengthen your prompt before sending.',
			cta: 'Try it',
			href: '/lq-ai/chats'
		},
		{
			id: 'skill-creator',
			title: 'Skill Creator',
			icon: IconTool,
			description: 'Build a reusable skill from any prompt or template.',
			cta: 'Create',
			href: '/lq-ai/skills/new'
		},
		{
			id: 'knowledge',
			title: 'Knowledge',
			icon: IconBooks,
			description: 'Attach a knowledge base to ground responses in your docs.',
			cta: 'Browse',
			href: '/lq-ai/knowledge'
		},
		{
			id: 'playbooks',
			title: 'Playbooks',
			icon: IconClipboardList,
			description: 'Review a contract against your standard positions with citations and redlines.',
			cta: 'Run',
			href: '/lq-ai/playbooks'
		},
		{
			id: 'tabular',
			title: 'Tabular Review',
			icon: IconTable,
			description: 'Run a column spec across multiple documents — every cell grounded by the Citation Engine.',
			cta: 'Start',
			href: '/lq-ai/tabular'
		},
		{
			id: 'apply-skill',
			title: 'Apply a Skill',
			icon: IconPlayerPlay,
			description: 'Run a saved skill on a document or message.',
			cta: 'Apply',
			href: '/lq-ai/skills'
		},
		{
			id: 'autonomous',
			title: 'Autonomous',
			icon: IconRobot,
			description:
				'Let LQ.AI run a skill or playbook on a schedule or when documents arrive (opt-in, off by default).',
			cta: $preferences.autonomous_enabled ? 'Open' : 'Turn on',
			href: autonomousHref
		}
	];
</script>

{#if mode === 'prominent'}
	<section style="margin-bottom: var(--lq-space-6);">
		<LqText as="p" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" style="margin-bottom: var(--lq-space-3);">Featured tools</LqText>
		<div class="tools-grid">
			{#each tools as tool (tool.id)}
				<a
					href={tool.href}
					class="tool-card"
					data-testid="lq-nav-{tool.id}"
				>
					<span class="tool-icon" aria-hidden="true"><svelte:component this={tool.icon} size={20} stroke={1.75} /></span>
					<LqText as="strong" size="16" weight="semibold" tone="primary" style="display: block; margin-bottom: var(--lq-space-1);"
						>{tool.title}</LqText>
					<LqText as="p" size="13.5" tone="secondary"
						style="margin-bottom: var(--lq-space-3);"
					>
						{tool.description}
					</LqText>
					<span class="tool-cta">{tool.cta} →</span>
				</a>
			{/each}
		</div>
	</section>
{:else}
	<section
		style="margin-bottom: var(--lq-space-6); display: flex; gap: var(--lq-space-2); flex-wrap: wrap; align-items: center;"
	>
		<LqText as="span" size="12" weight="semibold" tone="tertiary" transform="uppercase" tracking="wide" style="margin-right: var(--lq-space-1);">Tools:</LqText>
		{#each tools as tool (tool.id)}
			<a
				href={tool.href}
				class="tool-inline-btn"
				data-testid="lq-nav-{tool.id}"
			>
				<span class="tool-icon-inline" aria-hidden="true"><svelte:component this={tool.icon} size={14} stroke={1.75} /></span>
				{tool.title}
			</a>
		{/each}
	</section>
{/if}

<style>
	.tools-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: var(--lq-space-4);
	}

	.tool-card {
		display: flex;
		flex-direction: column;
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-4);
		text-decoration: none;
		color: var(--lq-text);
		transition: border-color 0.15s;
	}
	.tool-card:hover {
		border-color: var(--lq-accent-border);
	}

	.tool-icon-inline {
		display: inline-flex;
		vertical-align: -2px;
	}
	.tool-icon {
		margin-bottom: var(--lq-space-2);
		display: block;
	}

	.tool-cta {
		font-size: 13.5px;
		font-weight: 500;
		color: var(--lq-accent);
		margin-top: auto;
	}

	.tool-inline-btn {
		display: inline-flex;
		align-items: center;
		gap: var(--lq-space-1);
		padding: var(--lq-space-1) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		background: var(--lq-canvas);
		font-size: 13.5px;
		color: var(--lq-text);
		text-decoration: none;
		transition: border-color 0.15s;
	}
	.tool-inline-btn:hover {
		border-color: var(--lq-accent-border);
		color: var(--lq-accent);
	}
</style>
