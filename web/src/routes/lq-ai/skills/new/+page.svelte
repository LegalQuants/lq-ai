<script lang="ts">
	/**
	 * /lq-ai/skills/new — Wave D.2 Skill Creator wizard entry point.
	 *
	 * Thin wrapper around ``SkillWizard`` (Task 4.2). Supports four entry
	 * modes via query params, plus an orthogonal team-scope seed:
	 *
	 *   blank          (no params)          fresh wizard, fresh draft key
	 *   ?fork=<slug>                        pre-populate from a source skill via
	 *                                       GET /skills/{slug}; uses a fork-scoped
	 *                                       draft key so the source's autosave
	 *                                       doesn't collide with other drafts.
	 *   ?capture=<key>                      pre-populate from a localStorage stash
	 *                                       at ``lq-ai:capture-stash:<key>``; the
	 *                                       stash entry is removed after read so
	 *                                       a refresh resumes from the draft, not
	 *                                       the stash. Uses ``<key>`` as the draft key.
	 *   ?draft=<key>                        resume an in-progress wizard draft
	 *                                       (the wizard's own autosave key).
	 *   ?scope=team&team=<uuid>             (orthogonal to the above modes) seed
	 *                                       the wizard with team scope and
	 *                                       ``ownerTeamId``. Required for
	 *                                       team-admins creating team-scope
	 *                                       skills, since the wizard itself has
	 *                                       no scope picker. The backend's
	 *                                       POST /user-skills is the
	 *                                       authoritative admin gate (403 on
	 *                                       non-admin save attempts).
	 *
	 * Auth and force-change-password gating live in the parent ``/lq-ai``
	 * layout — this page has no auth logic of its own.
	 *
	 * Implementation notes:
	 *   - API imports are named functions per Wave D.2 convention.
	 *   - ``initial`` intentionally omits ``jurisdiction``: the wizard does
	 *     not surface that field (it would need to ride
	 *     ``frontmatter_extra.jurisdiction``, not a top-level field). If a
	 *     source skill has a jurisdiction set, it's dropped from the fork
	 *     seed for now — a Wave 4 wizard limitation, not a data loss
	 *     concern (the user can re-add it via the editor once
	 *     frontmatter-extra surfaces in the wizard).
	 *   - On ``?fork=`` 404 or capture-stash JSON parse failure, we set
	 *     ``loadError`` AND fall through to a blank wizard so the user is
	 *     never stuck on an error screen.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { getSkill } from '$lib/lq-ai/api/skills';
	import { listUserSkills, createUserSkill } from '$lib/lq-ai/api/userSkills';
	import SkillWizard from '$lib/lq-ai/components/SkillWizard.svelte';
	import { stashStorageKey } from '$lib/lq-ai/components/CaptureSkillModal.svelte';
	import { forkTableSeed } from '$lib/lq-ai/skills/builtinsBrowser';
	import type { EditableColumn, SkillOutputMode } from '$lib/lq-ai/skills/tableColumns';
	import type { UserSkillCreate } from '$lib/lq-ai/types';

	interface WizardInitial {
		slug?: string;
		displayName?: string;
		description?: string;
		body?: string;
		tags?: string[];
		slashAlias?: string | null;
		version?: string;
		scope?: 'user' | 'team';
		ownerTeamId?: string;
		forkedFrom?: string | null;
		/** DE-298 — table-mode fork seed (mode + columns from the source). */
		outputMode?: SkillOutputMode;
		columns?: EditableColumn[];
	}

	let initial: WizardInitial = {};
	let draftKey: string | null = null;
	let loadError: string | null = null;
	let loading = true;

	$: forkSlug = $page.url.searchParams.get('fork');
	$: captureKey = $page.url.searchParams.get('capture');
	$: explicitDraftKey = $page.url.searchParams.get('draft');
	$: scopeParam = $page.url.searchParams.get('scope');
	$: teamParam = $page.url.searchParams.get('team');

	function newDraftKey(): string {
		// `crypto.randomUUID` is available in every browser we target; the
		// fallback exists only as a safety net for older / non-secure-context
		// environments where the API may be missing.
		if (typeof globalThis !== 'undefined' && globalThis.crypto?.randomUUID) {
			return globalThis.crypto.randomUUID();
		}
		return `draft-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
	}

	/**
	 * Cheap dedup against the caller's existing user / team skills: append
	 * -2, -3, etc. when the base slug is already taken. The server still
	 * returns 409 on a save-time collision (the truth source); this is a
	 * UX nicety so the wizard doesn't open with a slug that obviously
	 * collides with one of the caller's own rows.
	 */
	async function uniqueSlug(base: string): Promise<string> {
		try {
			const mine = await listUserSkills('all');
			const taken = new Set(mine.map((s) => s.slug));
			if (!taken.has(base)) return base;
			for (let i = 2; i < 100; i++) {
				const candidate = `${base}-${i}`;
				if (!taken.has(candidate)) return candidate;
			}
			return `${base}-${newDraftKey().slice(0, 6)}`;
		} catch (e) {
			// Listing failed — fall back to the base slug. The server's 409
			// path will surface any collision when the user clicks Save.
			console.warn('skills/new: uniqueSlug fallback (listUserSkills failed)', e);
			return base;
		}
	}

	onMount(async () => {
		try {
			if (forkSlug) {
				const source = await getSkill(forkSlug);
				// `source.name` IS the slug (the SkillSummary field is named
				// "name" but holds the slug — see types.ts:354). We use it
				// for both the slug seed and the `forked_from` audit field.
				const baseSlug = await uniqueSlug(`${source.name}-fork`);
				// DE-298 — a table-mode source seeds the wizard's column
				// editor from the source's `lq_ai.columns` frontmatter (the
				// only wire surface where built-ins carry their column spec).
				// Prose sources — and table sources whose columns can't be
				// parsed — yield null and the wizard opens in prose mode.
				const tableSeed = forkTableSeed(source);
				initial = {
					slug: baseSlug,
					displayName: `${source.title ?? source.name} (fork)`,
					description: source.description ?? '',
					body: source.content_md ?? '',
					tags: source.tags ?? [],
					slashAlias: null,
					version: '1.0.0',
					scope: 'user',
					forkedFrom: source.name,
					...(tableSeed ?? {})
				};
				// Intentionally NOT seeding `jurisdiction` from the source —
				// the wizard doesn't surface that field today (see header
				// comment for the rationale).
				draftKey = `fork-${forkSlug}-${newDraftKey()}`;
			} else if (captureKey) {
				try {
					const stash = localStorage.getItem(stashStorageKey(captureKey));
					if (stash) {
						const parsed = JSON.parse(stash) as unknown;
						if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
							initial = parsed as WizardInitial;
						}
						localStorage.removeItem(stashStorageKey(captureKey));
					}
				} catch (e) {
					console.error('skills/new: failed to parse capture stash', e);
					loadError =
						e instanceof Error
							? `capture stash: ${e.message}`
							: 'capture stash could not be parsed';
				}
				draftKey = captureKey;
			} else if (explicitDraftKey) {
				draftKey = explicitDraftKey;
			} else {
				draftKey = newDraftKey();
			}

			// Orthogonal team-scope seed. Layered AFTER fork/capture/draft so
			// it overrides any source-derived scope (forks default to 'user').
			// Backend POST /user-skills enforces admin membership; we do not
			// validate it here.
			if (scopeParam === 'team') {
				if (teamParam && /^[0-9a-f-]{36}$/i.test(teamParam)) {
					initial = { ...initial, scope: 'team', ownerTeamId: teamParam };
				} else {
					loadError =
						'Team scope requires a valid ?team=<uuid> parameter. Starting as user-scope.';
					initial = { ...initial, scope: 'user', ownerTeamId: undefined };
				}
			}
		} catch (e) {
			console.error('skills/new: failed to prepare initial wizard state', e);
			loadError = e instanceof Error ? e.message : 'Failed to load source';
			// Fall through to a blank wizard so the user is never stuck.
			if (!draftKey) draftKey = newDraftKey();
		} finally {
			loading = false;
		}
	});

	async function onSave(payload: UserSkillCreate): Promise<string> {
		const created = await createUserSkill(payload);
		// UserSkill has both `id` and `slug`; the public detail route is
		// slug-keyed (matches the chat-time invocation surface).
		await goto(`/lq-ai/skills/${encodeURIComponent(created.slug)}?just_saved=1`);
		return created.id;
	}

	function onDiscard(): void {
		goto('/lq-ai/skills');
	}
</script>

<main class="lq-skills-new" data-testid="lq-ai-user-skill-new">
	{#if loading}
		<p class="lq-text-body" data-testid="lq-ai-user-skill-new-loading">Loading…</p>
	{:else}
		{#if loadError}
			<div class="banner" role="status" data-testid="lq-ai-user-skill-new-load-error">
				Couldn't load source skill ({loadError}). Starting blank.
				<a href="/lq-ai/skills">Pick a different source</a>
			</div>
		{/if}
		<SkillWizard {initial} {draftKey} {onSave} {onDiscard} />
	{/if}
</main>

<style>
	.lq-skills-new {
		padding: 32px 24px;
	}
	.banner {
		background: rgba(234, 179, 8, 0.1);
		padding: 12px 16px;
		border-radius: 6px;
		margin-bottom: 16px;
	}
	.banner a {
		margin-left: 8px;
		text-decoration: underline;
	}
</style>
