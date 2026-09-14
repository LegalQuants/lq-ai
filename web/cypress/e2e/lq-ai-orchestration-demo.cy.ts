/// <reference types="cypress" />

const rootId = '00000000-0000-4000-8000-000000000563';
const user = {
	id: 'demo-owner',
	email: 'demo@example.com',
	display_name: 'Demo owner',
	role: 'admin',
	is_admin: true,
	mfa_enabled: false,
	must_change_password: false
};
const preferences = {
	autonomous_enabled: true,
	reasoning_visibility: 'disclosure',
	featured_tools: 'prominent',
	workspace_layout: 'three_pane',
	trust_pills: 'labels',
	provenance_pills: 'always'
};
const base = '**/api/v1/autonomous/orchestration';

function fixture(status = 'awaiting_approval') {
	const child = (n: number) => ({
		session_id: `child-${n}`,
		status: 'pending',
		phase: 'intake',
		allocation_usd: '0.0000',
		spent_usd: '0.0000',
		reserved_usd: '0.0000',
		outcome: null,
		effects: []
	});
	return {
		root_id: rootId,
		status,
		stop_reason: null,
		mode: 'demonstration',
		verification: 'unverified',
		approved: status !== 'awaiting_approval',
		plan_hash: 'a'.repeat(64),
		plan: {
			revision: 1,
			goal: 'Demonstrate parallel work',
			budget_usd: '0.0000',
			root_allowance_usd: '0.0000',
			max_active_children: 2,
			deadline: '2026-09-15T00:00:00Z',
			root: { skill: { name: 'orchestrator-harness' } },
			children: ['Scope', 'Findings'].map((topic, index) => ({
				dispatch_id: `child-${index}`,
				budget_usd: '0.0000',
				task: {
					topic,
					question: `Sample work on ${topic}`,
					boundaries: 'Sample findings only.',
					stopping_condition: 'One outcome.'
				}
			}))
		},
		root: child(9),
		children: [child(0), child(1)],
		spent_usd: '0.0000',
		reserved_usd: '0.0000',
		result: null,
		partial_summary: null
	};
}

function setup(enabled = true, optedIn = true) {
	cy.intercept('http://127.0.0.1:8080/**', { statusCode: 404, body: {} });
	cy.intercept('GET', '**/api/config', {
		body: { name: 'LQ.AI', default_locale: 'en-US', features: { enable_websocket: false } }
	});
	// Catch every unmatched API request: this suite never contacts a live backend.
	cy.intercept('**/api/v1/**', { statusCode: 404, body: {} });
	cy.intercept('GET', '**/api/v1/users/me', { body: user });
	cy.intercept('GET', '**/api/v1/users/me/preferences', {
		body: { ...preferences, autonomous_enabled: optedIn }
	});
	cy.intercept('GET', '**/api/v1/admin/bootstrap-status', {
		body: { default_password_active: false, logs_hint: '' }
	});
	cy.intercept('GET', '**/api/v1/projects**', { body: [{ id: 'matter-1', name: 'Demo matter' }] });
	cy.intercept('GET', '**/api/v1/chats**', { body: { items: [], next_cursor: null } });
	for (const path of ['user-skills', 'saved-prompts', 'teams', 'skills'])
		cy.intercept('GET', `**/api/v1/${path}**`, { body: [] });
	cy.intercept('GET', '**/api/v1/autonomous/notifications**', {
		body: { notifications: [], total_count: 0 }
	});
	cy.intercept('GET', `${base}/capabilities`, {
		body: { enabled, deployment_children: enabled ? 2 : null, live_providers: false }
	});
	return (win: Window) => {
		win.localStorage.setItem(
			'lq_ai_auth',
			JSON.stringify({
				access_token: 'demo-fixture',
				refresh_token: null,
				expires_at: Date.now() + 3600000,
				user
			})
		);
		win.localStorage.setItem(
			'lq-ai:preferences-cache',
			JSON.stringify({ ...preferences, autonomous_enabled: optedIn })
		);
	};
}

describe('Orchestration demonstration', () => {
	it('prepares, approves, shows overlapping progress and an unverified synthesis', () => {
		const onBeforeLoad = setup();
		let current: any = fixture();
		cy.intercept('POST', `${base}/plans`, (req) => {
			expect(req.body.project_id).eq('matter-1');
			expect(req.body.topics).deep.eq(['Scope', 'Findings']);
			req.reply({ statusCode: 201, body: current });
		}).as('prepare');
		cy.intercept('GET', `${base}/${rootId}/tree`, (req) => req.reply(current)).as('tree');
		cy.intercept('POST', `${base}/${rootId}/approve`, (req) => {
			expect(req.body).deep.eq({ revision: 1, plan_hash: 'a'.repeat(64) });
			current = {
				...current,
				status: 'waiting_children',
				approved: true,
				children: current.children.map((child: any) => ({
					...child,
					status: 'running',
					phase: 'analysis'
				}))
			};
			req.reply(current);
		}).as('approve');
		cy.visit('/lq-ai/autonomous/orchestration', { onBeforeLoad });
		cy.contains('label', 'Matter').find('select').select('matter-1');
		cy.contains('label', 'Goal').find('textarea').type('Demonstrate parallel work');
		cy.contains('label', 'Topics').find('textarea').clear().type('Scope\nFindings');
		cy.contains('button', 'Prepare plan').click();
		cy.wait('@prepare');
		cy.wait('@tree');
		cy.contains('button', 'Approve plan').click();
		cy.wait('@approve');
		cy.get('[aria-label="Topic progress"] article').each((el) =>
			cy.wrap(el).contains('Phase: analysis')
		);
		cy.then(() => {
			current = {
				...current,
				status: 'completed',
				result: {
					summary: 'Sample work combined from both topics.',
					coverage: 'complete',
					verification: 'unverified'
				},
				children: current.children.map((child: any) => ({
					...child,
					status: 'completed',
					phase: 'delivery'
				}))
			};
		});
		cy.contains('button', 'Refresh').click();
		cy.wait('@tree');
		cy.contains('Sample work combined from both topics.').scrollIntoView().should('be.visible');
		cy.contains('Verification: unverified').scrollIntoView().should('be.visible');
		cy.screenshot('orchestration-demonstration-synthesis');
		cy.contains('button', 'Halt run').should('not.exist');
	});

	it('rejects a plan without starting children', () => {
		const onBeforeLoad = setup();
		cy.intercept('GET', `${base}/${rootId}/tree`, { body: fixture() });
		cy.intercept('POST', `${base}/${rootId}/reject`, { body: fixture('rejected') }).as('reject');
		cy.visit(`/lq-ai/autonomous/orchestration/${rootId}`, { onBeforeLoad });
		cy.contains('button', 'Reject plan').click();
		cy.wait('@reject');
		cy.contains('Status: rejected').should('be.visible');
		cy.contains('button', 'Approve plan').should('not.exist');
	});

	it('halts to partial results and permits inspection after opt-out', () => {
		const onBeforeLoad = setup(false, false);
		cy.intercept('GET', `${base}/${rootId}/tree`, { body: fixture('running') });
		cy.intercept('POST', `${base}/${rootId}/halt`, {
			body: {
				...fixture('halted'),
				partial_summary: 'Available sample findings. Other topics did not finish.'
			}
		}).as('halt');
		cy.visit(`/lq-ai/autonomous/orchestration/${rootId}`, { onBeforeLoad });
		cy.contains('button', 'Halt run').click();
		cy.wait('@halt');
		cy.contains('Available sample findings. Other topics did not finish.')
			.scrollIntoView()
			.should('be.visible');
		cy.contains('Status: halted').scrollIntoView().should('be.visible');
	});

	it('keeps the feature disabled until the operator enables it', () => {
		const onBeforeLoad = setup(false);
		cy.visit('/lq-ai/autonomous/orchestration', { onBeforeLoad });
		cy.contains('The operator has not enabled').should('be.visible');
		cy.contains('button', 'Prepare plan').should('not.exist');
	});

	it('shows saved working files after halt without treating their text as HTML', () => {
		const onBeforeLoad = setup(false, false);
		const tree: any = fixture('halted');
		tree.children[0].files = [
			{
				session_id: 'child-0',
				name: 'notes.md',
				revision: 2,
				digest: 'a'.repeat(64),
				size_bytes: 42,
				shared: false,
				updated_at: '2026-09-14T00:00:00Z'
			}
		];
		cy.intercept('GET', `${base}/${rootId}/tree`, { body: tree });
		cy.intercept('GET', `${base}/${rootId}/files/child-0/notes.md`, {
			body: {
				...tree.children[0].files[0],
				content: 'Saved WIP <script>window.bad = true</script>'
			}
		}).as('file');
		cy.visit(`/lq-ai/autonomous/orchestration/${rootId}`, { onBeforeLoad });
		cy.contains('button', 'notes.md').scrollIntoView().click();
		cy.wait('@file');
		cy.get('[aria-label="Working file content"]')
			.scrollIntoView()
			.should('contain.text', 'Saved WIP <script>');
		cy.window().its('bad').should('not.exist');
	});

	it('shows stale consent errors without automatically approving again', () => {
		const onBeforeLoad = setup();
		cy.intercept('GET', `${base}/${rootId}/tree`, { body: fixture() });
		cy.intercept('POST', `${base}/${rootId}/approve`, {
			statusCode: 409,
			body: { detail: { code: 'conflict', message: 'Approval refers to a stale plan' } }
		}).as('approve');
		cy.visit(`/lq-ai/autonomous/orchestration/${rootId}`, { onBeforeLoad });
		cy.contains('button', 'Approve plan').click();
		cy.wait('@approve');
		cy.get('[role="alert"]').contains('stale plan');
		cy.contains('button', 'Refresh').should('be.enabled');
	});
});
