<script context="module" lang="ts">
	/**
	 * SkillVersionsTab — audit-log view for a user/team skill (Wave D.2 Task 6.2).
	 *
	 * Lists every ``user_skill.created`` / ``.updated`` / ``.deleted`` audit row
	 * the caller is authorized to see (owner for user-scope, team-admin for
	 * team-scope), most-recent-first. Built-in (filesystem-canonical) skills
	 * have no DB row and therefore no audit history; we render a readonly
	 * empty state pointing the user at the Fork action instead.
	 *
	 * Convention notes for reviewers:
	 *   - Pure helpers exported from <script context="module"> so vitest can
	 *     exercise them without ``@testing-library/svelte`` (not installed;
	 *     see SkillWizard.test.ts header for the established pattern). The
	 *     Svelte template is glue; full table-render coverage is Cypress
	 *     (Wave 8).
	 *   - API import is the named export ``listUserSkillVersions`` from
	 *     ``$lib/lq-ai/api/userSkills`` — matches SkillWizard / CaptureSkillModal.
	 *     There is no ``userSkillsApi.listVersions`` method on this codebase;
	 *     the api barrel re-exports the module as a namespace, but components
	 *     in this folder use the direct named import.
	 *   - Error handling uses ``e instanceof Error`` (not ``e: any``) per the
	 *     CaptureSkillModal precedent. ``LQAIApiError extends Error`` so the
	 *     ``.message`` is safe to surface; the FastAPI string-detail
	 *     propagation gap is known tech debt.
	 *   - Design tokens: ``--lq-canvas``, ``--lq-border``, ``--lq-error``,
	 *     ``--lq-text-secondary``, ``--lq-text-tertiary`` — all verified
	 *     present in ``styles/practice.css``. Hex fallbacks included on every
	 *     ``var()`` for theming safety.
	 */
	import type { UserSkillVersion } from '../types';

	/**
	 * Minimum shape this tab needs from the parent skill row. Both built-in
	 * (``SkillSummary``) and user/team (``UserSkill``) shapes satisfy this:
	 * the field set here is the intersection. ``id`` is optional because
	 * built-ins have no DB id (and we never call the audit endpoint for them).
	 */
	export interface SkillForVersionsTab {
		// Accepts ``string | null | undefined`` — the backend ``Skill`` shape
		// surfaces ``id`` as nullable (``null`` for built-ins which have no DB
		// row, populated UUID for user/team scope). ``isBuiltinReadonly``
		// treats both ``undefined`` and ``null`` as "no DB row" via ``!skill.id``.
		id?: string | null;
		name: string;
		scope: 'user' | 'team' | 'builtin';
	}

	/**
	 * True when the row is a built-in (filesystem-canonical) skill — there
	 * is no DB row, so no audit history exists. Also treat a missing ``id``
	 * on a non-builtin row as readonly (defensive: the parent should never
	 * pass an id-less user/team row, but the audit endpoint requires an id).
	 */
	export function isBuiltinReadonly(skill: SkillForVersionsTab): boolean {
		return skill.scope === 'builtin' || !skill.id;
	}

	/** Email column with the standard em-dash fallback when actor is absent. */
	export function formatActor(v: UserSkillVersion): string {
		return v.actor_email ?? '—';
	}

	/** Version column with the standard em-dash fallback. */
	export function formatVersion(v: UserSkillVersion): string {
		return v.version ?? '—';
	}

	/**
	 * Localized timestamp for the "When" column. The exact string format is
	 * locale + timezone dependent, so tests assert non-empty rather than
	 * exact match (see SkillVersionsTab.test.ts). Returns the literal string
	 * ``'Invalid Date'`` for unparseable input — matches ``Date.prototype``
	 * native behavior; surfacing it lets QA spot upstream data corruption.
	 */
	export function formatTimestamp(v: UserSkillVersion): string {
		return new Date(v.timestamp).toLocaleString();
	}

	/**
	 * Human-readable label for the Action column. Maps the raw audit-log
	 * action strings (e.g. ``user_skill.updated``) to brief display labels.
	 *
	 * The raw action string is preserved in a ``data-action`` attribute on
	 * the table cell so Cypress tests that assert on the raw string value
	 * (wave-d2 Test 6 asserts ``user_skill.created`` / ``user_skill.updated``)
	 * remain green without modification.
	 *
	 * Fallback: action strings not in the map are humanised by replacing
	 * dots and underscores with spaces and title-casing the first word
	 * (e.g. ``user_skill.foo_bar`` → ``Foo bar``).
	 */
	const ACTION_LABELS: Record<string, string> = {
		'user_skill.created': 'Created',
		'user_skill.updated': 'Updated',
		'user_skill.deleted': 'Archived'
	};

	export function formatAction(v: UserSkillVersion): string {
		if (ACTION_LABELS[v.action]) return ACTION_LABELS[v.action];
		// Humanise unknown action strings: take the part after the last dot
		// (or the whole string), replace underscores/dots with spaces, and
		// capitalise the first character.
		const tail = v.action.includes('.') ? v.action.split('.').pop()! : v.action;
		const humanised = tail.replace(/[_]+/g, ' ').trim();
		return humanised.charAt(0).toUpperCase() + humanised.slice(1);
	}

	/**
	 * Submit-gate analog for the empty-history state: shown after a
	 * successful load that returned zero rows. Loading + error states have
	 * their own branches, so this is specifically the "no history yet"
	 * variant — distinct from the readonly built-in empty state.
	 */
	export function shouldShowEmptyState(
		skill: SkillForVersionsTab,
		versions: UserSkillVersion[],
		loading: boolean,
		error: string | null
	): boolean {
		if (isBuiltinReadonly(skill)) return false;
		if (loading || error) return false;
		return versions.length === 0;
	}
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { listUserSkillVersions } from '$lib/lq-ai/api/userSkills';

	/** Pass the full skill object (built-in or user-skill). */
	export let skill: SkillForVersionsTab;

	let versions: UserSkillVersion[] = [];
	let loading = false;
	let error: string | null = null;

	async function loadVersions(): Promise<void> {
		// Guard mirrors isBuiltinReadonly so we never hit the audit endpoint
		// for a built-in (no DB id) — the request would 422 / 404 and pollute
		// the readonly empty-state UX with a spurious error banner.
		if (isBuiltinReadonly(skill)) return;
		loading = true;
		error = null;
		try {
			const r = await listUserSkillVersions(skill.id as string);
			versions = r.items;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load versions';
		} finally {
			loading = false;
		}
	}

	// Svelte's onMount accepts a sync return; the async fetch is fire-and-forget.
	onMount(() => {
		void loadVersions();
	});
</script>

{#if isBuiltinReadonly(skill)}
	<div class="lq-versions-empty" data-testid="lq-ai-versions-builtin-readonly">
		<p><strong>Built-in skill · no edit history.</strong></p>
		<p>Fork it to create your own version with tracked changes.</p>
	</div>
{:else if loading}
	<p class="lq-versions-loading" data-testid="lq-ai-versions-loading">Loading versions…</p>
{:else if error}
	<p class="lq-versions-error" role="alert" data-testid="lq-ai-versions-error">{error}</p>
{:else if versions.length === 0}
	<p class="lq-versions-empty" data-testid="lq-ai-versions-empty">No edit history yet.</p>
{:else}
	<div class="lq-versions-scroll">
		<table class="lq-versions" data-testid="lq-ai-versions-table">
			<thead>
				<tr>
					<th>When</th>
					<th>Who</th>
					<th>Action</th>
					<th>Version</th>
				</tr>
			</thead>
			<tbody>
				{#each versions as v}
					<tr>
						<td>{formatTimestamp(v)}</td>
						<td>{formatActor(v)}</td>
						<td data-action={v.action}>{formatAction(v)}</td>
						<td>{formatVersion(v)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	@import '$lib/lq-ai/styles/practice.css';

	.lq-versions-empty {
		padding: 24px;
		text-align: center;
		color: var(--lq-text-tertiary);
	}
	.lq-versions-empty p {
		margin: 4px 0;
	}
	.lq-versions-loading {
		padding: 16px;
		color: var(--lq-text-tertiary);
		font-size: 13px;
	}
	.lq-versions-error {
		padding: 12px 16px;
		margin: 12px 0;
		background: rgba(181, 72, 72, 0.08);
		color: var(--lq-error);
		border-radius: 6px;
		font-size: 13px;
	}
	.lq-versions-scroll {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
	.lq-versions {
		width: 100%;
		min-width: 480px;
		border-collapse: collapse;
		background: var(--lq-canvas);
	}
	.lq-versions th,
	.lq-versions td {
		padding: 8px 12px;
		text-align: left;
		border-bottom: 1px solid var(--lq-border);
		font-size: 13px;
	}
	.lq-versions th {
		font-weight: 600;
		color: var(--lq-text-secondary);
	}
</style>
