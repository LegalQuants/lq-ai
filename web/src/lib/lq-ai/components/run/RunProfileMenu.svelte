<script lang="ts">
	/**
	 * The composer's "Run" control, beside the model picker (ADR 0038 D1).
	 *
	 * Lists the operator-enabled run profiles for this chat. A profile that cannot be
	 * used here is shown disabled with the reason beside it, in the server's words,
	 * so the composer always says why. Choosing one puts the composer in run mode.
	 *
	 * An unavailable option uses `aria-disabled` rather than `disabled` so it stays
	 * focusable and its reason is read out; activating it does nothing.
	 */
	import type { ProfileAvailability } from '$lib/lq-ai/api/orchestration';
	import { unavailableReason } from '$lib/lq-ai/run/composer';

	export let profiles: ProfileAvailability[] = [];
	export let selectedId: string | null = null;
	export let loading = false;
	/** Why the profiles could not be read, or null. */
	export let error: string | null = null;
	export let onSelect: (profileId: string) => void = () => undefined;

	let open = false;
	let root: HTMLDivElement | undefined;
	let toggle: HTMLButtonElement | undefined;

	$: selected = profiles.find((profile) => profile.profile === selectedId) ?? null;

	function choose(profile: ProfileAvailability): void {
		if (unavailableReason(profile)) return;
		open = false;
		onSelect(profile.profile);
	}

	function onWindowClick(event: MouseEvent): void {
		if (open && root && event.target instanceof Node && !root.contains(event.target)) open = false;
	}

	function onWindowKeydown(event: KeyboardEvent): void {
		if (open && event.key === 'Escape') {
			open = false;
			toggle?.focus();
		}
	}
</script>

<svelte:window on:click={onWindowClick} on:keydown={onWindowKeydown} />

<div class="relative inline-block" bind:this={root} data-testid="lq-ai-run-profile-menu">
	<button
		type="button"
		class="lq-run-pill"
		class:lq-run-pill--active={selected !== null}
		bind:this={toggle}
		aria-expanded={open}
		aria-controls="lq-ai-run-profile-list"
		data-testid="lq-ai-run-profile-toggle"
		title="Run a governed task: a model proposes a plan, you approve it, then it runs."
		on:click={() => (open = !open)}
	>
		<span class="font-medium">Run</span>
		{#if selected}<span class="ml-1">· {selected.title}</span>{/if}
	</button>

	{#if open}
		<div
			id="lq-ai-run-profile-list"
			class="lq-run-dropdown absolute z-10 mt-1 w-80 max-w-[85vw] max-h-96 overflow-auto rounded-md shadow-lg"
			role="group"
			aria-label="Governed runs"
			data-testid="lq-ai-run-profile-list"
		>
			<p class="intro">
				A model proposes a plan. Nothing runs until you approve that exact plan.
			</p>
			{#if loading && profiles.length === 0}
				<p class="state" role="status">Loading runs…</p>
			{:else if error && profiles.length === 0}
				<p class="state error" role="alert">{error}</p>
			{:else if profiles.length === 0}
				<p class="state">No runs are set up on this deployment.</p>
			{:else}
				<ul class="options">
					{#each profiles as profile (profile.profile)}
						{@const reason = unavailableReason(profile)}
						<li>
							<button
								type="button"
								class="option"
								class:option--selected={profile.profile === selectedId}
								class:option--off={reason !== null}
								aria-disabled={reason ? 'true' : undefined}
								aria-describedby={`lq-ai-run-profile-note-${profile.profile}`}
								data-testid={`lq-ai-run-profile-option-${profile.profile}`}
								on:click={() => choose(profile)}
							>
								<span class="name">{profile.title}</span>
								<span class="note" id={`lq-ai-run-profile-note-${profile.profile}`}>
									{profile.summary}
								</span>
								{#if reason}
									<span class="reason" data-testid={`lq-ai-run-profile-reason-${profile.profile}`}>
										{reason}
									</span>
								{/if}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
</div>

<style>
	@import '../../styles/practice.css';

	.lq-run-pill {
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		padding: 4px 10px;
		border-radius: var(--lq-radius);
		font-size: 12px;
		cursor: pointer;
	}
	.lq-run-pill:hover {
		filter: brightness(0.97);
	}
	.lq-run-pill:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.lq-run-pill--active {
		background: var(--lq-accent);
		color: white;
	}

	.lq-run-dropdown {
		border: 1px solid var(--lq-border);
		background: var(--lq-canvas);
	}
	.intro {
		margin: 0;
		padding: 8px 12px 4px;
		font-size: 11px;
		color: var(--lq-text-secondary);
		line-height: 1.5;
	}
	.state {
		margin: 0;
		padding: 8px 12px;
		font-size: 12px;
		color: var(--lq-text-tertiary);
	}
	.state.error {
		color: var(--lq-error);
	}
	.options {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.option {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
		width: 100%;
		padding: 8px 12px;
		background: transparent;
		border: 0;
		border-top: 1px solid var(--lq-border);
		text-align: left;
		cursor: pointer;
	}
	.option:hover {
		background: var(--lq-accent-soft);
	}
	.option:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: -2px;
	}
	.option--selected {
		background: var(--lq-accent-soft);
	}
	.option--off {
		cursor: not-allowed;
	}
	.option--off:hover {
		background: transparent;
	}
	.option--off .name {
		color: var(--lq-text-tertiary);
	}
	.name {
		font-size: 13px;
		font-weight: 600;
		color: var(--lq-text);
	}
	.note {
		font-size: 11px;
		color: var(--lq-text-secondary);
		line-height: 1.4;
	}
	.reason {
		font-size: 11px;
		line-height: 1.4;
		color: var(--lq-warn);
	}
</style>
