// eslint-disable-next-line @typescript-eslint/triple-slash-reference
/// <reference path="../support/index.d.ts" />

type ChatStub = {
	id: string;
	title: string;
	owner_id: string;
	project_id: string | null;
	created_at: string;
	updated_at: string;
	sticky_skills: string[];
};

const now = '2026-07-03T00:00:00.000Z';
const projectId = 'proj-1';
const chatId = 'chat-1';

// This spec is fully API-stubbed. The shared support hook only skips its
// upstream live signup bootstrap for wave-/lq-ai-/m*-named specs, so keep this
// referenced-files spec from making an unstubbed /auths/signup request before tests run.
Cypress.Commands.overwrite('registerAdmin', () => cy.wrap(Cypress.$('<div />')[0], { log: false }));

const user = {
	id: 'user-1',
	email: 'admin@lq.ai',
	name: 'Admin User',
	role: 'admin',
	is_admin: true,
	must_change_password: false
};

const project = {
	id: projectId,
	name: 'Cypress Matter',
	slug: 'cypress-matter',
	description: null,
	context_md: null,
	owner_id: 'user-1',
	privileged: false,
	minimum_inference_tier: null,
	attached_skill_names: [],
	attached_file_ids: [],
	attached_knowledge_base_ids: ['kb-1'],
	archived_at: null,
	created_at: now,
	updated_at: now
};

const referenceableFiles = [
	{
		id: 'file-1',
		owner_id: 'user-1',
		project_id: projectId,
		filename: 'master-agreement.pdf',
		mime_type: 'application/pdf',
		size_bytes: 1000,
		hash_sha256: 'hash-file-1',
		ingestion_status: 'ready',
		ingestion_error: null,
		document_id: 'doc-1',
		attached_at: now,
		created_at: now
	},
	{
		id: 'file-2',
		owner_id: 'user-1',
		project_id: projectId,
		filename: 'exhibit-a.pdf',
		mime_type: 'application/pdf',
		size_bytes: 1000,
		hash_sha256: 'hash-file-2',
		ingestion_status: 'ready',
		ingestion_error: null,
		document_id: 'doc-2',
		attached_at: now,
		created_at: now
	},
	{
		id: 'file-3',
		owner_id: 'user-1',
		project_id: projectId,
		filename: 'pending-upload.pdf',
		mime_type: 'application/pdf',
		size_bytes: 1000,
		hash_sha256: 'hash-file-3',
		ingestion_status: 'processing',
		ingestion_error: null,
		document_id: null,
		attached_at: now,
		created_at: now
	}
];

function chat(overrides: Partial<ChatStub> = {}): ChatStub {
	return {
		id: chatId,
		title: 'Referenced files test chat',
		owner_id: 'user-1',
		project_id: projectId,
		created_at: now,
		updated_at: now,
		sticky_skills: [],
		...overrides
	};
}

function sseBody(appliedReferencedFileIds: string[] = []): string {
	const assistant = {
		id: 'assistant-1',
		chat_id: chatId,
		role: 'assistant',
		content: 'Done.',
		applied_skills: [],
		created_at: now,
		citations: []
	};

	return [
		`data: ${JSON.stringify({ type: 'start', lq_ai_message_id: assistant.id, chat_id: chatId })}`,
		`data: ${JSON.stringify({ type: 'delta', delta: 'Done.' })}`,
		`data: ${JSON.stringify({ type: 'complete', lq_ai_message_id: assistant.id, message: assistant, citations: [], applied_referenced_file_ids: appliedReferencedFileIds })}`,
		'data: [DONE]',
		''
	].join('\n\n');
}

function stubApis(activeChat: ChatStub = chat()): void {
	cy.intercept('GET', '**/api/v1/users/me', user);
	cy.intercept('GET', '**/api/v1/models', {
		object: 'list',
		data: [
			{
				id: 'smart',
				object: 'model',
				created: 0,
				owned_by: 'lq-ai',
				lq_ai_kind: 'alias',
				lq_ai_resolves_to: 'test/model',
				lq_ai_fallback_count: 0
			}
		]
	});
	cy.intercept('GET', '**/api/v1/skills*', []);
	cy.intercept('GET', /\/api\/v1\/projects(?:\?.*)?$/, activeChat.project_id ? [project] : []);
	cy.intercept('GET', `**/api/v1/projects/${projectId}`, project).as('project');
	cy.intercept('GET', /\/api\/v1\/chats(?:\?.*)?$/, {
		items: [activeChat],
		next_cursor: null
	});
	cy.intercept('GET', `**/api/v1/chats/${activeChat.id}/messages*`, {
		items: [],
		next_cursor: null
	});
	cy.intercept('GET', '**/api/v1/knowledge-bases/kb-1/files', referenceableFiles).as('kbFiles');
	cy.intercept('POST', /\/api\/v1\/chats\/[^/]+\/messages$/, (req) => {
		const ids = (req.body as { referenced_file_ids?: string[] }).referenced_file_ids ?? [];
		req.reply({
			statusCode: 200,
			headers: { 'content-type': 'text/event-stream' },
			body: sseBody(ids)
		});
	}).as('send');
}

function visitChat(activeChat: ChatStub = chat()): void {
	stubApis(activeChat);
	cy.visit(`/lq-ai/chats?id=${activeChat.id}`, {
		onBeforeLoad(win) {
			win.localStorage.setItem(
				'lq_ai_auth',
				JSON.stringify({
					access_token: 'test-access-token',
					refresh_token: 'test-refresh-token',
					expires_at: Date.now() + 60 * 60 * 1000,
					user
				})
			);
		}
	});
	cy.get('[data-testid="lq-ai-composer-input"]', { timeout: 10000 }).should('be.visible');
}

function openPicker(): void {
	cy.get('[data-testid="lq-ai-file-picker-btn"]').click();
	cy.get('[data-testid="lq-ai-file-picker"]').should('be.visible');
	cy.wait('@kbFiles');
}

function selectPickerRow(filename: string): void {
	cy.contains('[data-testid="lq-ai-file-picker-row"]', filename)
		.find('input[type="checkbox"]')
		.check({ force: true });
}

describe('referenced-files referenced files', () => {
	it('picker flow: select two files, chips render, send carries both ids, set clears', () => {
		visitChat();

		openPicker();
		cy.get('[data-testid="lq-ai-file-picker-search"]').type('agreement');
		selectPickerRow('master-agreement.pdf');
		cy.get('[data-testid="lq-ai-file-picker-search"]').clear();
		selectPickerRow('exhibit-a.pdf');
		cy.get('[data-testid="lq-ai-file-picker-done"]').click();

		cy.get('[data-testid="lq-ai-referenced-chip"]').should('have.length', 2);
		cy.contains('[data-testid="lq-ai-referenced-chip"]', 'master-agreement.pdf').should(
			'be.visible'
		);
		cy.contains('[data-testid="lq-ai-referenced-chip"]', 'exhibit-a.pdf').should('be.visible');

		cy.get('[data-testid="lq-ai-composer-input"]').type('Summarize these documents.');
		cy.get('[data-testid="lq-ai-send-btn"]').click();

		cy.wait('@send')
			.its('request.body')
			.should((body) => {
				const payload = body as { referenced_file_ids?: string[] };
				expect(payload.referenced_file_ids).to.deep.equal(['file-1', 'file-2']);
			});
		cy.get('@send')
			.its('response.body')
			.should((body: string) => {
				expect(body).to.contain('"applied_referenced_file_ids":["file-1","file-2"]');
			});
		cy.get('[data-testid="lq-ai-referenced-row"]').should('contain', 'master-agreement.pdf');
		cy.get('[data-testid="lq-ai-referenced-chips"]').should('not.exist');
	});

	it('mention flow: typing @exh opens the popover, Enter completes the mention inline and adds a chip', () => {
		visitChat();

		cy.get('[data-testid="lq-ai-composer-input"]').type('summarize @exh');
		cy.wait('@kbFiles');
		cy.get('[data-testid="lq-ai-mention-popover"]').should('be.visible');
		cy.contains('[data-testid="lq-ai-mention-row"]', 'exhibit-a.pdf').should('be.visible');

		cy.get('[data-testid="lq-ai-composer-input"]').type('{enter}');

		cy.get('[data-testid="lq-ai-composer-input"]').should(
			'have.value',
			'summarize @exhibit-a.pdf '
		);
		cy.contains('[data-testid="lq-ai-referenced-chip"]', 'exhibit-a.pdf').should('be.visible');
		cy.get('[data-testid="lq-ai-mention-popover"]').should('not.exist');
		cy.get('[data-testid="lq-ai-composer-input"]').type('on causation');
		cy.get('[data-testid="lq-ai-send-btn"]').click();
		cy.wait('@send')
			.its('request.body')
			.should((body) => {
				const payload = body as { content: string; referenced_file_ids?: string[] };
				expect(payload.content).to.equal('summarize @exhibit-a.pdf on causation');
				expect(payload.referenced_file_ids).to.deep.equal(['file-2']);
			});
	});

	it('non-ready file shows a disabled "Preparing…" row in the picker and is absent from the mention popover', () => {
		visitChat();

		openPicker();
		cy.contains('[data-testid="lq-ai-file-picker-row"]', 'pending-upload.pdf').within(() => {
			cy.get('input[type="checkbox"]').should('be.disabled');
			cy.contains('Preparing…').should('be.visible');
		});
		cy.get('[data-testid="lq-ai-file-picker-done"]').click();

		cy.get('[data-testid="lq-ai-composer-input"]').type('@pending');
		cy.get('[data-testid="lq-ai-mention-popover"]').should('be.visible');
		cy.get('[data-testid="lq-ai-mention-popover"]').should('not.contain', 'pending-upload.pdf');
		cy.contains('[data-testid="lq-ai-mention-popover"]', 'No matching documents').should(
			'be.visible'
		);
	});

	it('chip remove (×) drops the file from the set', () => {
		visitChat();

		openPicker();
		selectPickerRow('master-agreement.pdf');
		cy.get('[data-testid="lq-ai-file-picker-done"]').click();
		cy.contains('[data-testid="lq-ai-referenced-chip"]', 'master-agreement.pdf').should(
			'be.visible'
		);

		cy.get('button[aria-label="Remove master-agreement.pdf"]').click();
		cy.get('[data-testid="lq-ai-referenced-chips"]').should('not.exist');

		cy.get('[data-testid="lq-ai-composer-input"]').type('Send without references.');
		cy.get('[data-testid="lq-ai-send-btn"]').click();
		cy.wait('@send')
			.its('request.body')
			.should((body) => {
				const payload = body as { referenced_file_ids?: string[] };
				expect(payload).not.to.have.property('referenced_file_ids');
			});
	});

	it('projectless chat: no picker button, @ never opens the popover', () => {
		visitChat(chat({ project_id: null }));

		cy.get('[data-testid="lq-ai-composer-input"]').should('be.visible');
		cy.get('[data-testid="lq-ai-file-picker-btn"]').should('not.exist');
		cy.get('[data-testid="lq-ai-composer-input"]').type('@doc');
		cy.get('[data-testid="lq-ai-mention-popover-anchor"]').should('not.exist');
	});
});
