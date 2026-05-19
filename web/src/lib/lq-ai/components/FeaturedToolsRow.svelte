<script lang="ts">
	import { preferences } from '$lib/lq-ai/stores/preferences';

	$: mode = $preferences.featured_tools;

	const tools = [
		{
			id: 'enhance',
			title: 'Enhance Prompt',
			icon: '✨',
			description: 'Rewrite and strengthen your prompt before sending.',
			cta: 'Try it',
			href: '/lq-ai/chats'
		},
		{
			id: 'skill-creator',
			title: 'Skill Creator',
			icon: '🛠',
			description: 'Build a reusable skill from any prompt or template.',
			cta: 'Create',
			href: '/lq-ai/skills/new'
		},
		{
			id: 'knowledge',
			title: 'Knowledge',
			icon: '📚',
			description: 'Attach a knowledge base to ground responses in your docs.',
			cta: 'Browse',
			href: '/lq-ai/knowledge'
		},
		{
			id: 'playbooks',
			title: 'Playbooks',
			icon: '📋',
			description: 'Review a contract against your standard positions with citations and redlines.',
			cta: 'Run',
			href: '/lq-ai/playbooks'
		},
		{
			id: 'apply-skill',
			title: 'Apply a Skill',
			icon: '▶',
			description: 'Run a saved skill on a document or message.',
			cta: 'Apply',
			href: '/lq-ai/skills'
		}
	] as const;
</script>

{#if mode === 'prominent'}
	<section style="margin-bottom: var(--lq-space-6);">
		<p class="lq-text-label" style="margin-bottom: var(--lq-space-3);">Featured tools</p>
		<div class="tools-grid">
			{#each tools as tool (tool.id)}
				<a
					href={tool.href}
					class="tool-card"
					aria-label={tool.title}
					data-testid="lq-nav-{tool.id}"
				>
					<span class="tool-icon" aria-hidden="true">{tool.icon}</span>
					<strong class="lq-text-panel-h" style="display: block; margin-bottom: var(--lq-space-1);"
						>{tool.title}</strong
					>
					<p
						class="lq-text-body-sm"
						style="color: var(--lq-text-secondary); margin-bottom: var(--lq-space-3);"
					>
						{tool.description}
					</p>
					<span class="tool-cta">{tool.cta} →</span>
				</a>
			{/each}
		</div>
	</section>
{:else}
	<section
		style="margin-bottom: var(--lq-space-6); display: flex; gap: var(--lq-space-2); flex-wrap: wrap; align-items: center;"
	>
		<span class="lq-text-label" style="margin-right: var(--lq-space-1);">Tools:</span>
		{#each tools as tool (tool.id)}
			<a
				href={tool.href}
				class="tool-inline-btn"
				aria-label={tool.title}
				data-testid="lq-nav-{tool.id}"
			>
				<span aria-hidden="true">{tool.icon}</span>
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

	.tool-icon {
		font-size: 20px;
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
		border-radius: var(--lq-radius);
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
