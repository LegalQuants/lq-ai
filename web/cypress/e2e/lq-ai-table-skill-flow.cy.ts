/// <reference types="cypress" />

/**
 * DE-297 + DE-298 browser wiring regression, not live-backend UAT.
 * Stateful HTTP fixtures echo the submitted authoring payload into subsequent
 * detail/edit/execution responses. No database, worker, or model is exercised.
 * Unknown API calls fail closed instead of reaching a running local backend.
 */
import { stringify } from 'yaml';
import { rejectUnexpectedApiRequests } from '../support/mocked-api';
import type { UserSkill, TabularColumnSpec } from '../../src/lib/lq-ai/types';

const user = {
	id: 'u1',
	email: 'admin@lq.ai',
	display_name: 'Admin',
	is_admin: true,
	role: 'admin',
	mfa_enabled: false,
	must_change_password: false,
	created_at: '2026-01-01T00:00:00Z'
};
const columns: TabularColumnSpec[] = [
	{
		name: 'Term',
		query: 'What is the term?',
		ensemble_verification: false,
		minimum_inference_tier: 2
	},
	{
		name: 'Governing law',
		query: 'Which law governs?',
		ensemble_verification: true,
		minimum_inference_tier: 4
	}
];
const builtin = (name: string, title: string) => ({
	name,
	title,
	scope: 'builtin',
	version: '1.0.0',
	description: 'Table extraction fixture',
	output_format: 'table',
	content_md: 'Extract the requested columns.',
	content_yaml: stringify({
		name,
		lq_ai: {
			output_format: 'table',
			columns,
			ensemble_verification: true,
			minimum_inference_tier: 3
		}
	})
});
const builtins = [
	builtin('alpha-table', 'Alpha Table'),
	builtin('zulu-table', 'Zulu Table'),
	{ ...builtin('prose-skill', 'Prose Skill'), output_format: 'prose' }
];
const byTestId = (id: string) => cy.get(`[data-testid="${id}"]`);

function visit(path: string) {
	cy.visit(path, {
		onBeforeLoad(win) {
			win.localStorage.setItem(
				'lq_ai_auth',
				JSON.stringify({
					access_token: 'fake-table-flow-token',
					refresh_token: null,
					expires_at: Date.now() + 3600000,
					user
				})
			);
		}
	});
}

function runTable(slug: string, names: string[], preselected = false) {
	byTestId('lq-tabwiz-kb-select').select('kb1');
	byTestId('lq-tabwiz-file-checkbox').check();
	byTestId('lq-tabwiz-next').click();
	if (preselected) byTestId('lq-tabwiz-skill-select').should('have.value', slug);
	else byTestId('lq-tabwiz-skill-select').select(slug);
	byTestId('lq-tabwiz-view-columns').should('have.attr', 'target', '_blank');
	byTestId('lq-tabwiz-view-columns').should('have.attr', 'rel', 'noopener');
	byTestId('lq-tabwiz-view-columns').should('have.attr', 'href', `/lq-ai/skills/${slug}`);
	byTestId('lq-tabwiz-next').click();
	cy.wait('@preview').its('request.body').should('include', { skill_name: slug });
	byTestId('lq-tabwiz-preview-cells').should('contain.text', '2');
	byTestId('lq-tabwiz-next').click();
	byTestId('lq-tabwiz-next').click();
	cy.wait('@execute').then(({ request }) => {
		expect(request.body.skill_name).to.equal(slug);
		expect(request.body.document_ids).to.deep.equal(['doc1']);
	});
	byTestId('lq-tabres-status').should('contain.text', 'Completed');
	byTestId('lq-tabgrid-header').should(($headers) => {
		expect([...$headers].map((el) => el.textContent?.trim())).to.deep.equal(names);
	});
	byTestId('lq-tabgrid-row').should('have.length', 1).and('contain.text', 'fixture-value');
}

describe('Table skill authoring and built-in discovery (mocked HTTP)', () => {
	beforeEach(() => {
		const rows: UserSkill[] = [];
		let execution: Record<string, unknown>;
		let executionCount = 0;
		rejectUnexpectedApiRequests();
		cy.intercept('GET', '**/api/config', {
			name: 'Open WebUI',
			default_locale: 'en-US',
			features: { enable_websocket: false }
		});
		cy.intercept('GET', '**/api/version', { version: 'test' });
		cy.intercept('GET', '**/api/v1/users/me', user);
		cy.intercept('GET', '**/api/v1/users/me/preferences', {});
		cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
			default_password_active: false,
			logs_hint: ''
		});
		for (const path of ['projects', 'teams', 'saved-prompts'])
			cy.intercept('GET', `**/api/v1/${path}*`, []);
		cy.intercept('GET', '**/api/v1/chats*', { items: [], next_cursor: null });
		cy.intercept('GET', '**/api/v1/user-skills*', (req) => req.reply(rows));
		cy.intercept('GET', '**/api/v1/user-skills/*', (req) => {
			const row = rows.find((r) => r.id === req.url.split('/').pop());
			req.reply(row ? { body: row } : { statusCode: 404, body: { detail: 'Unknown ID' } });
		});
		cy.intercept('POST', '**/api/v1/user-skills', (req) => {
			const row = {
				id: `skill-${rows.length + 1}`,
				owner_user_id: 'u1',
				owner_team_id: null,
				tags: [],
				slash_alias: null,
				forked_from: null,
				archived_at: null,
				created_at: '2026-11-01T00:00:00Z',
				updated_at: '2026-11-01T00:00:00Z',
				...req.body
			};
			rows.push(row);
			req.reply({ statusCode: 201, body: row });
		}).as('create');
		cy.intercept('PATCH', '**/api/v1/user-skills/*', (req) => {
			const index = rows.findIndex((r) => r.id === req.url.split('/').pop());
			expect(index, 'PATCH uses persistent ID').to.be.gte(0);
			rows[index] = { ...rows[index], ...req.body };
			req.reply(rows[index]);
		}).as('update');
		cy.intercept('DELETE', '**/api/v1/user-skills/*', (req) => {
			const index = rows.findIndex((r) => r.id === req.url.split('/').pop());
			expect(index, 'DELETE uses persistent ID').to.be.gte(0);
			rows.splice(index, 1);
			req.reply({ statusCode: 204 });
		}).as('archive');
		const summary = (row: UserSkill) => ({
			id: row.id,
			name: row.slug,
			title: row.display_name,
			scope: row.scope,
			version: row.version,
			description: row.description,
			output_format: row.frontmatter_extra.output_format
		});
		cy.intercept('GET', '**/api/v1/skills*', (req) => {
			if (req.query.recent_only === 'true') {
				req.reply([builtins[1]]);
			} else if (req.query.scope === 'builtin') {
				req.reply(builtins);
			} else {
				req.reply([...builtins.filter((b) => !rows.some((r) => r.slug === b.name)), ...rows.map(summary)]);
			}
		});
		cy.intercept('GET', '**/api/v1/skills/*', (req) => {
			const slug = req.url.split('/').pop();
			const row = rows.find((r) => r.slug === slug);
			req.reply(
				row
					? {
							...summary(row),
							content_md: row.body,
							content_yaml: stringify({ id: row.id, name: row.slug, lq_ai: row.frontmatter_extra })
						}
					: builtins.find((b) => b.name === slug)
			);
		});
		cy.intercept('GET', '**/api/v1/knowledge-bases', [{ id: 'kb1', name: 'Fixture documents' }]);
		cy.intercept('GET', '**/api/v1/knowledge-bases/kb1/files', [
			{
				id: 'file1',
				document_id: 'doc1',
				filename: 'contract.pdf',
				ingest_status: 'ok',
				ingestion_status: 'ready'
			}
		]);
		cy.intercept('POST', '**/api/v1/tabular/preview-cost', {
			cells_count: 2,
			estimated_tokens: 100,
			estimated_cost_usd: '0.01',
			per_tier_breakdown: {}
		}).as('preview');
		cy.intercept('POST', '**/api/v1/tabular/execute', (req) => {
			const row = rows.find((r) => r.slug === req.body.skill_name);
			expect(row, 'execution resolves the saved skill').not.to.equal(undefined);
			const savedColumns = row!.frontmatter_extra.columns as TabularColumnSpec[];
			execution = {
				id: `execution-${++executionCount}`,
				user_id: 'u1',
				parent_execution_id: null,
				skill_name: row!.slug,
				status: 'completed',
				document_ids: ['doc1'],
				columns: savedColumns,
				cost_estimate_usd: '0.01',
				cost_actual_usd: '0.01',
				error_text: null,
				created_at: '2026-11-01T00:00:00Z',
				started_at: '2026-11-01T00:00:00Z',
				completed_at: '2026-11-01T00:00:01Z',
				bulk_ops: [],
				results: {
					rows: [
						{
							document_id: 'doc1',
							document_name: 'contract.pdf',
							cells: Object.fromEntries(
								savedColumns.map((c) => [
									c.name,
									{
										value: 'fixture-value',
										confidence: 'high',
										citations: [],
										tier_used: 2,
										cost_usd: '0.005',
										error: null
									}
								])
							)
						}
					]
				}
			};
			req.reply({ statusCode: 202, body: execution });
		}).as('execute');
		cy.intercept('GET', '**/api/v1/tabular/executions/*', (req) => req.reply(execution));
	});

	it('creates, displays, runs, edits and reloads column flags/order, then runs the saved revision', () => {
		visit('/lq-ai/skills/new');
		byTestId('lq-ai-wizard-display-name').type('My Table');
		byTestId('lq-ai-wizard-description').type('Contract extraction');
		byTestId('lq-ai-wizard-mode-table').check();
		columns.forEach((col, index) => {
			if (index) byTestId('lq-ai-column-add').click();
			byTestId('lq-ai-column-name').eq(index).type(col.name);
			byTestId('lq-ai-column-query').eq(index).type(col.query);
			byTestId('lq-ai-column-ensemble').eq(index).select(String(col.ensemble_verification));
			byTestId('lq-ai-column-tier').eq(index).select(String(col.minimum_inference_tier));
		});
		// New specs must not silently overwrite same-named grid cells.
		byTestId('lq-ai-column-name').eq(1).clear().type('Term').blur();
		byTestId('lq-ai-wizard-save').should('be.disabled');
		byTestId('lq-ai-column-name-error').should('be.visible');
		cy.get('@create.all').should('have.length', 0);
		byTestId('lq-ai-column-name').eq(1).clear().type('Governing law').blur();
		byTestId('lq-ai-column-name-error').should('not.exist');
		byTestId('lq-ai-wizard-save').should('not.be.disabled').click();
		cy.wait('@create')
			.its('request.body.frontmatter_extra')
			.should('deep.equal', { output_format: 'table', columns });
		cy.location('pathname').should('eq', '/lq-ai/skills/my-table');
		byTestId('lq-ai-skill-column')
			.should('have.length', 2)
			.first()
			.should('contain.text', 'Term')
			.and('contain.text', 'ensemble: off');
		byTestId('lq-ai-skill-use-in-tabular').click();
		runTable('my-table', ['Term', 'Governing law'], true);
		visit('/lq-ai/skills/my-table');
		cy.contains('a', /^Edit$/)
			.should('have.attr', 'href', '/lq-ai/skills/skill-1/edit')
			.click();
		byTestId('lq-ai-user-skill-edit-mode-table').should('be.checked');
		byTestId('lq-ai-column-ensemble').first().should('have.value', 'false');
		byTestId('lq-ai-column-tier').eq(1).should('have.value', '4');
		byTestId('lq-ai-column-up').eq(1).click();
		byTestId('lq-ai-column-ensemble').first().select('false');
		byTestId('lq-ai-column-tier').first().select('5');
		byTestId('lq-ai-user-skill-edit-save-btn').click();
		const revised = [
			{ ...columns[1], ensemble_verification: false, minimum_inference_tier: 5 },
			columns[0]
		];
		cy.wait('@update').its('request.body.frontmatter_extra.columns').should('deep.equal', revised);
		cy.reload();
		byTestId('lq-ai-column-name').first().should('have.value', 'Governing law');
		byTestId('lq-ai-column-ensemble').first().should('have.value', 'false');
		byTestId('lq-ai-column-tier').first().should('have.value', '5');
		visit('/lq-ai/tabular/execution-1');
		byTestId('lq-tabres-rerun').click();
		runTable('my-table', ['Governing law', 'Term']);
		cy.location('pathname').should('eq', '/lq-ai/tabular/execution-2');
	});

	it('deep-links format/sort, changes ordering and forks a built-in with its table flags intact', () => {
		visit('/lq-ai/skills?format=table&sort=recent');
		byTestId('lq-ai-format-chip').contains('Table').should('have.attr', 'aria-pressed', 'true');
		byTestId('lq-ai-builtin-skill-link').first().should('contain.text', 'Zulu Table');
		byTestId('lq-ai-format-chip').contains('Prose').click();
		byTestId('lq-ai-builtin-table-skill')
			.should('have.length', 1)
			.and('contain.text', 'Prose Skill');
		cy.location('search').should('contain', 'format=prose');
		byTestId('lq-ai-format-chip').contains('Table').click();
		byTestId('lq-ai-builtin-table-skill').should('have.length', 2);
		byTestId('lq-ai-sort-name').click();
		cy.location('search').should('contain', 'sort=name').and('contain', 'format=table');
		cy.reload();
		byTestId('lq-ai-builtin-skill-link').first().should('contain.text', 'Alpha Table').click();
		byTestId('lq-ai-skill-fork-link').click();
		byTestId('lq-ai-wizard-mode-table').should('be.checked');
		byTestId('lq-ai-column-name').first().should('have.value', 'Term');
		byTestId('lq-ai-column-ensemble').first().should('have.value', 'false');
		byTestId('lq-ai-column-tier').eq(1).should('have.value', '4');
		byTestId('lq-ai-wizard-description').clear().type('Edited fork draft');
		byTestId('lq-ai-wizard-save-draft').click();
		cy.location('search').should('contain', 'draft=');
		cy.reload();
		byTestId('lq-ai-wizard-description').should('have.value', 'Edited fork draft');
		byTestId('lq-ai-wizard-mode-table').should('be.checked');
		byTestId('lq-ai-wizard-save').click();
		cy.wait('@create').then(({ request }) => {
			expect(request.body.forked_from).to.equal('alpha-table');
			expect(request.body.frontmatter_extra).to.deep.equal({
				output_format: 'table',
				columns,
				ensemble_verification: true,
				minimum_inference_tier: 3
			});
		});
		cy.location('pathname').should('eq', '/lq-ai/skills/alpha-table-fork');
		byTestId('lq-ai-skill-column').should('have.length', 2);
	});
	it('renders a legacy source with repeated column labels without crashing the detail page', () => {
		cy.intercept('GET', '**/api/v1/skills/alpha-table', {
			...builtins[0],
			content_yaml: stringify({
				lq_ai: { output_format: 'table', columns: [columns[0], { ...columns[1], name: 'Term' }] }
			})
		});
		visit('/lq-ai/skills/alpha-table');
		byTestId('lq-ai-skill-column').should('have.length', 2);
		byTestId('lq-ai-skill-column').eq(1).should('contain.text', 'Which law governs?');
		byTestId('lq-ai-skill-use-in-tabular').should('be.visible');
	});

	it('restores a fork draft with no columns without reseeding them', () => {
		visit('/lq-ai/skills/new?fork=alpha-table');
		byTestId('lq-ai-column-row').should('have.length', 2);
		byTestId('lq-ai-column-remove').first().click();
		byTestId('lq-ai-column-remove').first().click();
		byTestId('lq-ai-wizard-save-draft').click();
		cy.reload();
		byTestId('lq-ai-wizard-mode-table').should('be.checked');
		byTestId('lq-ai-column-row').should('not.exist');
		byTestId('lq-ai-column-list-error').should('be.visible');
		byTestId('lq-ai-wizard-save').should('be.disabled');
	});
	it('labels a shadow, opens its personal version, and restores the built-in after archive', () => {
		visit('/lq-ai/skills/new?fork=alpha-table');
		byTestId('lq-ai-wizard-slug').clear().type('alpha-table');
		byTestId('lq-ai-wizard-display-name').clear().type('Personal Alpha');
		byTestId('lq-ai-wizard-save').click();
		cy.wait('@create');
		cy.location('pathname').should('eq', '/lq-ai/skills/alpha-table');
		visit('/lq-ai/skills');
		byTestId('lq-ai-builtin-shadow-notice')
			.should('have.length', 1)
			.and('contain.text', 'Your personal version overrides this built-in.');
		byTestId('lq-ai-builtin-shadow-notice').contains('a', 'Open active version').click();
		cy.contains('h1', 'Personal Alpha').should('be.visible');
		cy.contains('a', /^Edit$/).should('have.attr', 'href', '/lq-ai/skills/skill-1/edit');
		visit('/lq-ai/skills');
		byTestId('lq-ai-builtin-shadow-notice').should('exist');
		cy.on('window:confirm', (message) => {
			expect(message).to.contain('Archive "Personal Alpha"');
			return true;
		});
		byTestId('lq-ai-user-skill-archive-btn').click();
		cy.wait('@archive').its('response.statusCode').should('eq', 204);
		// No navigation/reload: the catalog must refresh merged precedence itself.
		byTestId('lq-ai-user-skill-row').should('not.exist');
		byTestId('lq-ai-builtin-shadow-notice').should('not.exist');
		byTestId('lq-ai-builtin-skill-link').contains('Alpha Table').click();
		cy.contains('h1', 'Alpha Table').should('be.visible');
		cy.contains('a', /^Edit$/).should('not.exist');
	});
});
