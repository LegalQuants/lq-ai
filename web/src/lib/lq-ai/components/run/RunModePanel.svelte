<script lang="ts">
	/**
	 * The strip above the composer while New harness is the chat's model (ADR 0038
	 * D1): one line, what a request may spend, shown before anything is sent. Send
	 * authorizes one planning call within the displayed total cap; the tasks need
	 * approval of the exact plan afterwards.
	 *
	 * Everything else is one fold away, and in it: what a request reads, what Send
	 * does (the profile's own notice of what the planning call receives), the route (the model and the
	 * inference tier), whether text is pseudonymized on its way there, the system
	 * prompts that instruct the run, each of which is read from the server only when it is
	 * opened, and, where the orchestrator may answer a request by itself, that such an answer
	 * is not put to the owner for approval. A slot below takes the document picker and the
	 * line about the knowledge bases a task may search. Leaving is done in the model picker,
	 * by choosing another model.
	 */
	import { orchestrationApi } from '$lib/lq-ai/api/orchestration';
	import type { ProfileAvailability, RunDocumentsRead } from '$lib/lq-ai/api/orchestration';
	import {
		answersDirectlyText,
		instructionRows,
		pseudonymizationText,
		runModeFacts,
		spendSummary,
		toolLabelList,
		toolsOffered,
		unavailableReason
	} from '$lib/lq-ai/run/composer';
	import RunPromptRow from './RunPromptRow.svelte';

	export let profile: ProfileAvailability;
	/** Reads a prompt file's text by name; the real API unless a test passes a stub. */
	export let fetchPrompt: typeof orchestrationApi.prompt = orchestrationApi.prompt;
	/**
	 * The `run-documents` read for this chat, or null until it has come back. It says whether the
	 * matter has knowledge bases to search, which the list of tools below depends on.
	 */
	export let documentsRead: Pick<RunDocumentsRead, 'knowledge_bases'> | null = null;
	/**
	 * How many documents are selected for the request, or null where that is not known. A profile
	 * whose documents are optional is offered no tool to read one while none is selected.
	 */
	export let selectedDocuments: number | null = null;

	$: facts = runModeFacts(profile);
	$: pseudonymization = pseudonymizationText(profile);
	$: instructions = instructionRows(profile);
	// The profile lists every tool for every chat; a run is offered only the ones that could do
	// something. The search of knowledge bases only where the matter has some (not listed before that
	// is known), and the read of a document only where one is selected.
	$: tools = toolLabelList(
		toolsOffered(
			profile.tools,
			documentsRead,
			selectedDocuments === null ? null : { policy: profile.documents, count: selectedDocuments }
		)
	);
	// An active run is named, with what to do about it, by the notice above this
	// strip. Saying it again here would show one fact twice.
	$: unavailable = profile.reason === 'active_run' ? null : unavailableReason(profile);
	$: spend = spendSummary(profile);
	// Where the orchestrator may answer by itself, that answer comes with no plan to approve.
	$: answersDirectly = answersDirectlyText(profile);
</script>

<section class="strip" data-testid="lq-ai-run-mode-panel" aria-label="New harness">
	{#if unavailable}<p class="unavailable" role="alert">{unavailable}</p>{/if}

	<details class="limits" data-testid="lq-ai-run-mode-limits">
		<summary>
			Limits and tools
			{#if spend.length > 0}
				<span class="spend" data-testid="lq-ai-run-mode-spend">{spend.join(' · ')}</span>
			{/if}
		</summary>
		<dl class="facts">
			<div class="wide">
				<dt>What a request reads</dt>
				<dd data-testid="lq-ai-run-mode-reads">{profile.reads}</dd>
			</div>
			<div class="wide">
				<dt>What Send does</dt>
				<dd data-testid="lq-ai-run-planning-notice">{profile.planning_notice}</dd>
			</div>
			{#each facts as fact}
				<div>
					<dt>{fact.label}</dt>
					<dd>{fact.value}</dd>
				</div>
			{/each}
			{#if pseudonymization}
				<div class="wide">
					<dt>Pseudonymization</dt>
					<dd data-testid="lq-ai-run-mode-pseudonymization">{pseudonymization}</dd>
				</div>
			{/if}
			<div class="wide">
				<dt>Tools the tasks may use</dt>
				<dd>
					{#if tools.length > 0}{tools.join(', ')}{:else}none{/if}
				</dd>
			</div>
			{#if instructions.length > 0}
				<div class="wide">
					<dt>{instructions.some((row) => row.kind === 'prompt') ? 'System prompts' : 'Skills'}</dt>
					<dd>
						<ul class="prompts" data-testid="lq-ai-run-mode-prompts">
							{#each instructions as row}
								<li>
									{#if row.kind === 'prompt'}
										{#key row.name}
											<RunPromptRow name={row.name} label={row.label} {fetchPrompt} />
										{/key}
									{:else}
										<span class="skill" data-testid="lq-ai-run-mode-skill"
											>{row.label}: {row.detail}</span
										>
									{/if}
								</li>
							{/each}
						</ul>
					</dd>
				</div>
			{/if}
			<div class="wide">
				<dt>What this does</dt>
				<dd>{profile.summary}</dd>
			</div>
			{#if answersDirectly}
				<div class="wide">
					<dt>Direct answers</dt>
					<dd data-testid="lq-ai-run-mode-answers-directly">{answersDirectly}</dd>
				</div>
			{/if}
		</dl>
	</details>

	<slot />
</section>

<style>
	@import '../../styles/practice.css';

	.strip {
		padding: 0.4rem 0.6rem;
		border-left: 3px solid var(--lq-accent);
		background: var(--lq-inset-secure);
		border-radius: var(--lq-radius);
		font-size: 0.8rem;
		line-height: 1.5;
	}
	p {
		margin: 0;
	}
	.spend {
		margin-left: 0.75rem;
		font-variant-numeric: tabular-nums;
	}
	.unavailable {
		margin: 0.35rem 0;
		padding: 0.35rem 0.55rem;
		color: var(--lq-warn);
		background: var(--lq-warn-soft);
		border: 1px solid var(--lq-warn-border);
		border-radius: var(--lq-radius);
	}
	summary {
		cursor: pointer;
		font-size: 0.75rem;
		color: var(--lq-text-secondary);
	}
	summary:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.facts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
		gap: 0.35rem 1rem;
		margin: 0.35rem 0 0.15rem;
	}
	.wide {
		grid-column: 1 / -1;
	}
	dt {
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
	dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.prompts {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.15rem;
	}
	.skill {
		font-size: 0.78rem;
	}
</style>
