<script context="module" lang="ts">
	/**
	 * AttachedSkillPill — small pill rendered alongside the composer (and
	 * eventually inside message bubbles) to show that a skill is attached
	 * to the current turn. Tasks 3.3 (SlashPopover) and 7.1 (composer
	 * wiring) consume this.
	 *
	 * Convention notes for reviewers:
	 *   - Callback prop (onRemove), matching SkillPicker / AttachKBModal /
	 *     NewMatterModal — not createEventDispatcher.
	 *   - Pure helpers exported from <script context="module"> so vitest
	 *     can exercise them without @testing-library/svelte (which is not
	 *     installed; see AttachKBModal.test.ts header comment).
	 *   - Styling tokens: the design spec called for `--lq-secure-*` but
	 *     those don't exist; the "secure / sage" tone in TrustPill maps to
	 *     `--lq-accent-soft / --lq-accent / --lq-accent-border` defined in
	 *     styles/practice.css. Using those keeps the pill consistent with
	 *     the existing "secure" trust pill.
	 */
	export interface AttachedSkill {
		slug: string;
		title: string;
		icon?: string | null;
	}

	/** A11y contract: aria-label on the remove button. */
	export function removeAriaLabel(title: string): string {
		return `Remove ${title}`;
	}

	/**
	 * The skill's own icon, exactly as the skill author wrote it (skill data), or null when
	 * it has none; the pill then draws the Tabler fallback (ADR 0045 §5).
	 */
	export function displayIcon(icon: string | null | undefined): string | null {
		return icon ? icon : null;
	}

	/**
	 * Invoke the onRemove callback with the skill's slug. Defensive: skips
	 * the call when the consumer didn't wire a handler (matches the
	 * default-no-op style used by SkillPicker.svelte).
	 */
	export function handleRemove(
		skill: AttachedSkill,
		onRemove: ((slug: string) => void) | undefined
	): void {
		if (!onRemove) return;
		onRemove(skill.slug);
	}
</script>

<script lang="ts">
	import { IconTool, IconX } from '@tabler/icons-svelte';
	export let skill: AttachedSkill;
	export let onRemove: ((slug: string) => void) | undefined = undefined;

	$: icon = displayIcon(skill.icon);
	$: ariaLabel = removeAriaLabel(skill.title);
</script>

<span class="lq-skill-pill" role="status">
	<span class="lq-skill-pill__icon" aria-hidden="true"
		>{#if icon}{icon}{:else}<IconTool size={12} stroke={1.75} />{/if}</span
	>
	<span class="lq-skill-pill__title">{skill.title}</span>
	<button
		type="button"
		class="lq-skill-pill__remove"
		aria-label={ariaLabel}
		on:click={() => handleRemove(skill, onRemove)}
		><IconX size={12} stroke={1.75} aria-hidden="true" /></button
	>
</span>

<style>
	.lq-skill-pill {
		display: inline-flex;
		align-items: center;
		gap: var(--lq-space-1);
		background: var(--lq-accent-soft);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius-pill);
		padding: 2px 8px;
		font-family: var(--lq-font-sans);
		font-size: 12px;
		font-weight: 500;
		line-height: 1.4;
	}

	.lq-skill-pill__icon {
		font-size: 12px;
	}

	.lq-skill-pill__title {
		white-space: nowrap;
	}

	.lq-skill-pill__remove {
		background: none;
		border: 0;
		padding: 0 2px;
		margin-left: 2px;
		color: inherit;
		font: inherit;
		line-height: 1;
		cursor: pointer;
		opacity: 0.6;
		border-radius: var(--lq-radius-pill);
	}

	.lq-skill-pill__remove:hover {
		opacity: 1;
	}

	.lq-skill-pill__remove:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
		opacity: 1;
	}
</style>
