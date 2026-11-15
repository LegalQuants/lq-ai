/**
 * Wave D.2 — Skill Creator (Wave 8 E2E suite).
 *
 * Covers the Skill Creator surface that shipped through Wave D.2:
 *
 *   1. Capture happy path (Task 8.2)    — AI reply → modal → save → skill in list
 *   2. Wizard from scratch (Task 8.2)   — blank → fill 3 sections → set slash_alias → save
 *   3. Fork flow (Task 8.3)             — detail page → fork → wizard pre-populated → save
 *   4. Slash invocation (Task 8.4)      — type "/" in composer → popover → pick → pill → send
 *   5. Try-it sandbox (Task 8.4)        — detail Try-it tab → ensure sandbox → send → LLM reply renders
 *   6. Versions + slash_alias collision (Task 8.3) — edit twice → tab shows 3 rows; collision → inline error
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   docker compose exec api python -m app.cli reset-admin-password \
 *     --email admin@lq.ai --password 'LQ-AI-smoke-test-Pw1!' --no-force-change
 *   cd web && npx cypress run --spec 'cypress/e2e/wave-d2-skill-creator.cy.ts'
 */

/// <reference types="cypress" />

import { login, createSampleMatter, getBearerToken } from '../support/lq-ai-helpers';

const ADMIN_EMAIL = () => Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai';
const ADMIN_PASSWORD = () => Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!';
/** Direct API base — bypasses the SvelteKit web container which has no POST proxy for user-skills routes. */
const API_BASE = () => Cypress.env('LQAI_API_BASE') ?? 'http://localhost:8000';

describe('Wave D.2 — Skill Creator', () => {
	beforeEach(() => {
		login(ADMIN_EMAIL(), ADMIN_PASSWORD());
	});

	it('1. Capture happy path: AI reply → modal → save → skill in list', () => {
		// Timestamp suffix makes name/slug unique across repeated runs so we
		// never get a 409 from a prior run's stale row.
		const ts = Date.now();
		const skillName = `Sales Contract Structure ${ts}`;
		const skillSlug = `sales-contract-structure-${ts}`;

		createSampleMatter('Capture Test Matter');

		// createSampleMatter lands on the matter workspace with the composer
		// visible. Type a prompt and send it via the Send button.
		cy.get('[data-testid="lq-ai-composer-input"]').first().type('Summarize the typical structure of a sales contract.');
		cy.get('[data-testid="lq-ai-send-btn"]').click();

		// Wait for an AI reply — the inline capture button mounts immediately on
		// assistant messages but stays disabled while streaming. Poll until it
		// becomes enabled (streaming complete) then click. 90s accommodates
		// slow LLM round-trips. The `:not([disabled])` CSS pseudo-class causes
		// cy.get to retry until a matching (enabled) element exists.
		cy.get('[data-testid="lq-ai-message-capture-inline"]:not([disabled])', { timeout: 90000 })
			.first()
			.click();

		// Capture modal mounts.
		cy.get('[data-testid="lq-ai-capture-skill-modal"]').should('exist');

		// Override the auto-derived name and slug with known values so the
		// list assertion below is deterministic.
		cy.get('[data-testid="lq-ai-capture-name"]').clear().type(skillName);
		cy.get('[data-testid="lq-ai-capture-slug"]').clear().type(skillSlug);

		// Intercept BEFORE the save click — once the button fires the POST
		// the alias must already be registered.
		cy.intercept('POST', '/api/v1/user-skills').as('createSkill');
		cy.get('[data-testid="lq-ai-capture-save"]').click();
		cy.wait('@createSkill').its('response.statusCode').should('eq', 201);

		// Navigate to the skills list and confirm the new skill row is present.
		cy.visit('/lq-ai/skills');
		cy.contains('[data-testid="lq-ai-user-skill-row"]', skillName).should('exist');
	});

	it('2. Wizard from scratch: blank → fill 3 sections → set slash_alias → save', () => {
		// Use a timestamp suffix to avoid 409 collisions on repeated runs.
		const ts = Date.now();
		const displayName = `D.2 Test Skill ${ts}`;
		// kebab('D.2 Test Skill <ts>') → 'd-2-test-skill-<ts>' (dots and spaces
		// → dashes, trimmed). The slug auto-derives reactively from the display name.
		const expectedSlug = `d-2-test-skill-${ts}`;

		cy.visit('/lq-ai/skills');
		cy.get('[data-testid="lq-ai-user-skills-new-link"]').click();
		cy.url().should('include', '/lq-ai/skills/new');

		// Section 1 — display name (slug auto-derives until user touches the slug field).
		cy.get('[data-testid="lq-ai-wizard-display-name"]').type(displayName);
		// Assert the reactive slug matches the kebab-derived value.
		cy.get('[data-testid="lq-ai-wizard-slug"]').should('have.value', expectedSlug);

		// Section 1 continued — description.
		cy.get('[data-testid="lq-ai-wizard-description"]').type('Test skill for Wave D.2 Cypress spec.');

		// Slash alias (Section 2 area in the wizard). Include ts suffix to
		// avoid the slash_alias partial-unique constraint on repeated runs.
		cy.get('[data-testid="lq-ai-wizard-slash-alias"]').type(`/d2-test-${ts}`);

		// Section 3 — body (required for canSave to return true).
		cy.get('[data-testid="lq-ai-wizard-body"]').type('# D.2 test\nThis skill is a Cypress fixture.');

		// Intercept BEFORE the save click.
		cy.intercept('POST', '/api/v1/user-skills').as('createSkill');
		cy.get('[data-testid="lq-ai-wizard-save"]').click();
		cy.wait('@createSkill').its('response.statusCode').should('eq', 201);

		// onSave navigates to /lq-ai/skills/{slug}?just_saved=1.
		cy.url({ timeout: 10000 }).should('include', `/lq-ai/skills/${expectedSlug}`);

		// The skill detail page renders SkillDetailTabs which always has a
		// "Use it" tab label — presence confirms the detail page loaded.
		cy.contains(/use it/i, { timeout: 10000 }).should('exist');
	});

	it('2b. Table-mode wizard (DE-297): pick Table → column list → save → frontmatter_extra persisted', () => {
		const ts = Date.now();
		const displayName = `Table Grid Skill ${ts}`;
		const expectedSlug = `table-grid-skill-${ts}`;

		cy.visit('/lq-ai/skills/new');

		// Sections 1-2.
		cy.get('[data-testid="lq-ai-wizard-display-name"]').type(displayName);
		cy.get('[data-testid="lq-ai-wizard-description"]').type(
			'DE-297 Cypress fixture: table-mode skill.'
		);

		// Section 3 — switch to table mode; the body editor is swapped for
		// the column list (one blank column row is pre-seeded).
		cy.get('[data-testid="lq-ai-wizard-mode-table"]').check();
		cy.get('[data-testid="lq-ai-wizard-body"]').should('not.exist');
		cy.get('[data-testid="lq-ai-column-row"]').should('have.length', 1);

		// Inline empty-query validation: blur the empty query field.
		cy.get('[data-testid="lq-ai-column-query"]').first().focus();
		cy.get('[data-testid="lq-ai-column-query"]').first().blur();
		cy.get('[data-testid="lq-ai-column-query-error"]').should('exist');

		// Fill the first column and add a second.
		cy.get('[data-testid="lq-ai-column-name"]').first().type('Term');
		cy.get('[data-testid="lq-ai-column-query"]').first().type('What is the term?');
		cy.get('[data-testid="lq-ai-column-query-error"]').should('not.exist');
		cy.get('[data-testid="lq-ai-column-add"]').click();
		cy.get('[data-testid="lq-ai-column-row"]').should('have.length', 2);
		cy.get('[data-testid="lq-ai-column-name"]').eq(1).type('Governing law');
		cy.get('[data-testid="lq-ai-column-query"]').eq(1).type('Which law governs?');

		// Save; the POST body must carry output_format=table + both columns.
		cy.intercept('POST', '/api/v1/user-skills').as('createTableSkill');
		cy.get('[data-testid="lq-ai-wizard-save"]').click();
		cy.wait('@createTableSkill').then((interception) => {
			expect(interception.response?.statusCode).to.eq(201);
			const extra = interception.request.body.frontmatter_extra;
			expect(extra.output_format).to.eq('table');
			expect(extra.columns.map((c: { name: string }) => c.name)).to.deep.eq([
				'Term',
				'Governing law'
			]);
		});
		cy.url({ timeout: 10000 }).should('include', `/lq-ai/skills/${expectedSlug}`);
	});

	it('3. Fork flow: detail page → fork → wizard pre-populated → save', () => {
		// Timestamp suffix makes the forked slug unique across reruns so the
		// uniqueSlug dedup in skills/new/+page.svelte doesn't silently append -2.
		const ts = Date.now();
		const forkSlug = `nda-review-fork-${ts}`;

		// Navigate to the nda-review built-in detail page. The detail page
		// renders a "🔱 Fork as my own" anchor with aria-label
		// "Fork nda-review as my own" (per +page.svelte line ~58-62).
		cy.visit('/lq-ai/skills/nda-review');

		// Wait for the skill to load — the header h1 mounts once `skill` is set.
		cy.contains('h1', /nda/i, { timeout: 10000 }).should('exist');

		// Click the fork link. The link href is
		// `/lq-ai/skills/new?fork=nda-review`; no need for cy.url() assertion
		// since clicking an <a> navigates directly.
		cy.contains('a', /fork as my own/i).click();

		// Wait for the wizard to mount (the display-name input must be visible
		// before we assert its value, since the fork data is loaded async in
		// onMount of +page.svelte).
		cy.get('[data-testid="lq-ai-wizard-display-name"]', { timeout: 10000 }).should('be.visible');

		// The wizard's onMount sets displayName = `${source.title ?? source.name} (fork)`
		// and slug = await uniqueSlug(`${source.name}-fork`) → "nda-review-fork"
		// (possibly -2 on reruns but we are not asserting exact slug, we override it).
		cy.get('[data-testid="lq-ai-wizard-display-name"]').should(($el) => {
			const val = ($el.val() as string) ?? '';
			expect(val.toLowerCase()).to.match(/\(fork\)$/);
		});

		// Description must be non-empty (seeded from source.description).
		cy.get('[data-testid="lq-ai-wizard-description"]').should(($el) => {
			const val = ($el.val() as string) ?? '';
			expect(val.trim()).to.not.equal('');
		});

		// Override the auto-derived slug with a timestamped one so this test
		// is idempotent across reruns. cy.clear() resets slugTouched via the
		// on:input handler, then type() arms slugTouched so auto-derive stops.
		cy.get('[data-testid="lq-ai-wizard-slug"]').clear().type(forkSlug);

		// Intercept BEFORE the save click.
		cy.intercept('POST', '/api/v1/user-skills').as('saveFork');
		cy.get('[data-testid="lq-ai-wizard-save"]:not([disabled])').click();
		cy.wait('@saveFork').then((interception) => {
			expect(interception.response?.statusCode).to.eq(201);
			// forked_from field is set in buildPayload → POST body.
			expect(interception.request.body.forked_from).to.eq('nda-review');
		});

		// onSave navigates to /lq-ai/skills/{slug}?just_saved=1.
		cy.url({ timeout: 10000 }).should('include', `/lq-ai/skills/${forkSlug}`);
	});

	it('4. Slash invocation: type "/" in composer → popover → pick → pill → send', () => {
		// Timestamp suffix ensures the slug + slash_alias are unique across reruns
		// so repeated CI runs never hit a 409 on the pre-seed POST.
		const ts = Date.now();
		const skillSlug = `d2-slash-${ts}`;
		const skillTitle = `D2 Slash ${ts}`;
		const slashAlias = `/d2s${ts}`.slice(0, 33); // backend max 32 chars after /

		// ── Pre-seed the slash skill via direct API call ─────────────────────
		// cy.request fires outside the browser fetch context, so we carry the
		// auth token from localStorage explicitly (same pattern as Test 6).
		getBearerToken((token) => {
			cy.request({
				method: 'POST',
				url: `${API_BASE()}/api/v1/user-skills`,
				headers: { Authorization: `Bearer ${token}` },
				body: {
					scope: 'user',
					slug: skillSlug,
					display_name: skillTitle,
					description: 'Slash-invocation cypress fixture',
					body: 'echo: respond with "skill applied"',
					version: '1.0.0',
					slash_alias: slashAlias
				}
			})
				.its('status')
				.should('eq', 201);
		});

		// Create a matter + new chat so the composer is visible.
		createSampleMatter('Slash Test Matter');

		// ── Type "/" into the composer and wait for the popover ──────────────
		// The popover anchor mounts when `slashOpen` becomes true in ChatPanel
		// (onComposerInput sets it when a '/' is detected as the first char of
		// a word). We assert the anchor then the listbox inside it.
		cy.get('[data-testid="lq-ai-composer-input"]').first().type('/');
		cy.get('[data-testid="lq-ai-slash-popover-anchor"]', { timeout: 5000 }).should('exist');
		cy.get('[data-testid="lq-ai-slash-popover-anchor"] [role="listbox"]').should('exist');

		// Type the rest of the query so the autocomplete narrows to our skill.
		// The ts suffix is too long to type; type just 'd2s' (prefix of the alias
		// slug which contains 'd2s<ts>') — or type the display_name prefix.
		// The autocomplete ranks by: slash_alias prefix (score 3) > slug prefix (score 2) >
		// title substring (score 1). On a dirty DB, prior-run d2s* skills also match —
		// click the row by title to target the current run's skill unambiguously.
		cy.get('[data-testid="lq-ai-composer-input"]').first().type('d2s');

		// Wait for the title span to appear inside the listbox.
		cy.get('[data-testid="lq-ai-slash-popover-anchor"] [role="listbox"]')
			.contains(skillTitle, { timeout: 10000 })
			.should('exist');

		// Pick the skill by clicking the row matching the current run's title.
		// The slash popover sorts by ranking score with stable insertion order for ties.
		// With a dirty DB containing prior runs' d2s<ts> skills, activeIndex defaults to 0
		// and {enter} would pick the OLDEST matching skill, not the current run's freshly-created one.
		cy.get('[data-testid="lq-ai-slash-popover-anchor"]')
			.contains('[role="option"]', skillTitle)
			.click();

		// ── Assert the attached-skill pill renders in SkillPicker ────────────
		// SkillPicker renders a detach button with data-testid
		// "lq-ai-skill-detach-{slug}" (SkillPicker.svelte line ~85).
		// The plan's `aria-label="remove <title>"` is from AttachedSkillPill.svelte,
		// but the composer uses SkillPicker for the attached skill display, not
		// AttachedSkillPill. Selector is the stable data-testid on the Detach btn.
		cy.get(`[data-testid="lq-ai-skill-detach-${skillSlug}"]`, { timeout: 5000 }).should('exist');

		// Composer text should now be empty (the slash query was removed by
		// onSlashSelect's composerText splice in ChatPanel.svelte).
		cy.get('[data-testid="lq-ai-composer-input"]').first().should('have.value', '');

		// ── Send the message and assert the attached_skills payload ──────────
		// ChatPanel uses sendMessageStream (streaming POST). Intercept BEFORE
		// the click so the alias is registered when the request fires.
		cy.intercept('POST', '**/messages').as('sendMessage');
		cy.get('[data-testid="lq-ai-composer-input"]').first().type('test prompt');
		cy.get('[data-testid="lq-ai-send-btn"]').click();

		// 60s timeout: this is a real LLM round-trip. We assert only on the
		// request body (not the streamed reply) so we don't depend on LLM output.
		cy.wait('@sendMessage', { timeout: 60000 })
			.its('request.body.attached_skills')
			.should('deep.include', { slug: skillSlug, source: 'slash' });
	});

	it('5. Try-it sandbox: detail Try-it tab → ensure sandbox → send → LLM reply renders', () => {
		// Timestamp suffix ensures the slug is unique across reruns.
		const ts = Date.now();
		const skillSlug = `d2-tryit-${ts}`;

		// ── Pre-seed the try-it skill via direct API call ─────────────────────
		getBearerToken((token) => {
			cy.request({
				method: 'POST',
				url: `${API_BASE()}/api/v1/user-skills`,
				headers: { Authorization: `Bearer ${token}` },
				body: {
					scope: 'user',
					slug: skillSlug,
					display_name: `D2 Try-it ${ts}`,
					description: 'Try-it sandbox cypress fixture',
					body: 'respond briefly with "sandbox ok"',
					version: '1.0.0'
				}
			})
				.its('status')
				.should('eq', 201);
		});

		// Intercept BEFORE visiting the page — the pane's onMount calls
		// ensureSandbox() which hits POST /api/v1/projects/sandbox/ensure.
		// The alias must exist before the navigation triggers the mount.
		cy.intercept('POST', '**/projects/sandbox/ensure').as('sandboxEnsure');

		cy.visit(`/lq-ai/skills/${skillSlug}?tab=try`);

		// Wait for sandbox ensure — 200 if already exists, 201 on first call.
		cy.wait('@sandboxEnsure', { timeout: 15000 })
			.its('response.statusCode')
			.should('be.oneOf', [200, 201]);

		// The pane enters the ready state once both sandbox + chatId are set
		// (the loading placeholder disappears and the composer renders).
		cy.get('[data-testid="lq-ai-tryit-composer"]', { timeout: 15000 }).should('exist');

		// Send a prompt and wait for the LLM reply to appear in the message list.
		// Intercept the sendMessage POST for the timeout — SkillTryItPane calls
		// the non-streaming sendMessage (POST **/messages with stream:false).
		cy.intercept('POST', '**/messages').as('trySend');
		cy.get('[data-testid="lq-ai-tryit-composer"]').type('hello sandbox');
		cy.get('[data-testid="lq-ai-tryit-send"]').click();

		// 60s timeout: real LLM round-trip. Assert the user message appears first
		// (optimistic render fires before the request lands). Then wait for the
		// LLM reply — the message list grows from 1 (user) to 2 (user + assistant).
		cy.wait('@trySend', { timeout: 60000 });
		// The user message is rendered optimistically; the assistant reply
		// appends on success. Assert the message area has at least 2 msg divs
		// (user + assistant) and that the user turn text is present.
		cy.get('[data-testid="lq-ai-tryit-messages"] .msg', { timeout: 60000 }).should(
			'have.length.gte',
			2
		);
		cy.get('[data-testid="lq-ai-tryit-messages"]').should('contain.text', 'hello sandbox');

		// ── Deviation from plan: NO tab-switch persistence assertion ──────────
		// SkillTryItPane holds messages in local Svelte component state.
		// The skill detail page mounts/unmounts SkillTryItTab via a Svelte
		// {#if activeTab === 'try'} block (+page.svelte line ~81), so switching
		// tabs destroys the component and discards state. The plan's "visit
		// ?tab=use → visit ?tab=try → assert 'hello sandbox' exists" would fail
		// because the remounted pane starts with a fresh message list and a new
		// chatId. This is a DONE_WITH_CONCERNS escalation — client-only state;
		// server-side chat reload across tab switches is out of M1 scope.
		// (See SkillTryItPane.svelte reset() comment: "M1 limitation: server-side
		// chat reset is out of scope".)
	});

	it('6. Versions tab + slash_alias collision: edit twice → tab shows 3 rows; collision → inline error', () => {
		// Timestamp suffix makes slug and slash_alias unique across reruns so
		// the pre-seed never collides with a prior run's stale row.
		const ts = Date.now();
		const targetSlug = `d2-versions-${ts}`;
		const targetAlias = `/d2t${ts}`.slice(0, 33); // backend max 32 chars after /

		// ── Pre-seed: create skill + 2 edits via cy.request ─────────────────
		// cy.request fires outside the browser session's fetch, so we must
		// carry the bearer token ourselves. The LQ.AI auth store writes the
		// session under the key `lq_ai_auth` in localStorage as a JSON object
		// with an `access_token` field (api/client.ts + auth/store.ts).

		getBearerToken((token) => {
			const headers = { Authorization: `Bearer ${token}` };

			// Create the skill
			cy.request({
				method: 'POST',
				url: `${API_BASE()}/api/v1/user-skills`,
				headers,
				body: {
					scope: 'user',
					slug: targetSlug,
					display_name: 'D2 Versions Target',
					description: 'd',
					body: 'b',
					version: '1.0.0',
					slash_alias: targetAlias
				}
			})
				.its('body.id')
				.then((skillId: string) => {
					// Edit 1: update description
					cy.request({
						method: 'PATCH',
						url: `${API_BASE()}/api/v1/user-skills/${skillId}`,
						headers,
						body: { description: 'd2' }
					});
					// Edit 2: update body (column is `body` on PATCH too, per
					// UserSkillUpdate in user_skills.py)
					cy.request({
						method: 'PATCH',
						url: `${API_BASE()}/api/v1/user-skills/${skillId}`,
						headers,
						body: { body: 'b2' }
					});
				});
		});

		// ── Versions tab: expect 3 audit rows ────────────────────────────────
		// The Versions tab renders the audit log with `{v.action}` directly in
		// the Action column (SkillVersionsTab.svelte line ~157). Actions are
		// `user_skill.created` and `user_skill.updated` (api/user_skills.py).
		cy.visit(`/lq-ai/skills/${targetSlug}?tab=versions`);

		// Wait for the versions table to appear.
		cy.get('[data-testid="lq-ai-versions-table"]', { timeout: 10000 }).should('exist');

		// 1 created + 2 updated = 3 rows in the tbody.
		cy.get('[data-testid="lq-ai-versions-table"] tbody tr', { timeout: 10000 }).should('have.length', 3);

		// The table's Action column shows the raw action string from the
		// audit log (`user_skill.created` / `user_skill.updated`).
		cy.contains('[data-testid="lq-ai-versions-table"]', 'user_skill.created').should('exist');
		cy.contains('[data-testid="lq-ai-versions-table"]', 'user_skill.updated').should('exist');

		// ── Collision: try to create a new skill with the same slash_alias ───
		// The backend returns 422 with
		// `"slash_alias '<alias>' is already used by another of your skills."`.
		// SkillWizard catches the 422, checks for "slash_alias" in the error
		// string, and populates `slashAliasError` (rendered inline near the
		// alias input via the `{#if slashAliasError}` block — not via the
		// `lq-ai-wizard-save-error` banner).
		cy.visit('/lq-ai/skills/new');
		cy.get('[data-testid="lq-ai-wizard-display-name"]').type(`Collision Test ${ts}`);
		cy.get('[data-testid="lq-ai-wizard-description"]').type('collision description');
		cy.get('[data-testid="lq-ai-wizard-body"]').type('collision body');
		cy.get('[data-testid="lq-ai-wizard-slash-alias"]').type(targetAlias);

		cy.intercept('POST', '/api/v1/user-skills').as('collide');
		cy.get('[data-testid="lq-ai-wizard-save"]:not([disabled])').click();
		cy.wait('@collide').its('response.statusCode').should('eq', 422);

		// SkillWizard renders the slash_alias inline error (not the banner)
		// when the 422 detail contains "slash_alias". The fallback text is
		// "That slash alias is already used by another of your skills (slash_alias /...)".
		// Both the fallback and the raw backend string contain "already used".
		cy.contains(/already used/i, { timeout: 5000 }).should('exist');
	});
});
