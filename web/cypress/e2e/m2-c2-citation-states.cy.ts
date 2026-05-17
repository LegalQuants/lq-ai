/**
 * M2-C2 — Citation Engine UI: end-to-end render coverage for the 4 currently-
 * emitted citation states (verified-exact, verified-tolerant,
 * verified-paraphrase, unverified). State 5 (system-error) is deferred to
 * M2-D per the M2-C2 decision matrix and is not exercised here.
 *
 * Strategy: log in, create a real matter + chat (the chat shell needs a
 * real session and a real chat-id to drive the load path), then intercept
 * the two endpoints the message-render pipeline reads from:
 *
 *   GET /api/v1/chats/{chat_id}/messages          → synthetic message list
 *   GET /api/v1/chats/{chat_id}/messages/{id}/citations
 *                                                 → synthetic citation rows
 *
 * The synthetic assistant message embeds 4 `"<quote>" (Source: [N])`
 * markers that match (or fail to match) the synthetic citation rows so
 * the renderer hits each of the 4 states in a single page load. The
 * fourth marker has no citation row — per the api's `_persist_message_citations`
 * docstring, the absence of a row is the unverified signal.
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   cd web && npx cypress run --spec 'cypress/e2e/m2-c2-citation-states.cy.ts'
 */

/// <reference types="cypress" />

import { login, createSampleMatter } from '../support/lq-ai-helpers';

const ADMIN_EMAIL = () => Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai';
const ADMIN_PASSWORD = () => Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!';

// Synthetic content the assistant "produced". Quotes match the citation
// source_text values below, except for the 4th marker (no matching row →
// renders as unverified).
const ASSISTANT_CONTENT = [
	'The clause is clear: "exact verbatim verified text" (Source: [1]). ',
	'A second passage reads "tolerant match verified" (Source: [2]). ',
	'The judge confirmed "paraphrase judge verified" (Source: [3]). ',
	'However, "unverifiable claim no source supports" (Source: [4]) is not in any retrieved document.'
].join('');

const SYNTHETIC_USER_ID = '11111111-1111-1111-1111-111111111111';
const SYNTHETIC_ASSISTANT_ID = '22222222-2222-2222-2222-222222222222';

function syntheticMessages(chatId: string) {
	return {
		items: [
			{
				id: SYNTHETIC_USER_ID,
				chat_id: chatId,
				role: 'user',
				kind: 'user',
				content: 'Cite the relevant passages from the contract.',
				created_at: '2026-05-16T10:00:00.000Z'
			},
			{
				id: SYNTHETIC_ASSISTANT_ID,
				chat_id: chatId,
				role: 'assistant',
				kind: 'ai',
				content: ASSISTANT_CONTENT,
				applied_skills: [],
				routed_inference_tier: 2,
				routed_provider: 'synthetic-test-provider',
				routed_model: 'synthetic-test-model',
				created_at: '2026-05-16T10:00:01.000Z'
			}
		],
		next_cursor: null
	};
}

const SYNTHETIC_CITATIONS = [
	{
		id: 'aaaa1111-aaaa-1111-aaaa-111111111111',
		source_file_id: 'ffff0001-ffff-0001-ffff-000111111111',
		source_offset_start: 0,
		source_offset_end: 32,
		source_page: 1,
		source_text: 'exact verbatim verified text',
		verified: true,
		verification_method: 'exact_match',
		verification_confidence: 1.0,
		partial: false,
		created_at: '2026-05-16T10:00:01.500Z'
	},
	{
		id: 'aaaa2222-aaaa-2222-aaaa-222222222222',
		source_file_id: 'ffff0001-ffff-0001-ffff-000111111111',
		source_offset_start: 64,
		source_offset_end: 100,
		source_page: 1,
		source_text: 'tolerant match verified',
		verified: true,
		verification_method: 'tolerant_match',
		verification_confidence: 0.96,
		partial: false,
		created_at: '2026-05-16T10:00:01.600Z'
	},
	{
		id: 'aaaa3333-aaaa-3333-aaaa-333333333333',
		source_file_id: 'ffff0001-ffff-0001-ffff-000111111111',
		source_offset_start: 128,
		source_offset_end: 165,
		source_page: 2,
		source_text: 'paraphrase judge verified',
		verified: true,
		verification_method: 'paraphrase_judge',
		verification_confidence: 0.9,
		partial: false,
		created_at: '2026-05-16T10:00:01.700Z'
	}
	// Intentionally NO row for "unverifiable claim no source supports" —
	// absence of a row is the unverified signal (per
	// api/app/api/chats.py _persist_message_citations).
];

describe('M2-C2 — Citation Engine UI renders all four states', () => {
	beforeEach(() => {
		login(ADMIN_EMAIL(), ADMIN_PASSWORD());
	});

	it('renders 4 state-classified chips + 4 inline-decorated spans in one message', () => {
		// Set up the listMessages intercept BEFORE creating the matter so it
		// matches the first chat-load call. URL pattern: `/chats/{id}/messages`
		// (the API client base prefixes `/api/v1`).
		cy.intercept(
			{ method: 'GET', url: /\/api\/v1\/chats\/[a-f0-9-]+\/messages(\?|$)/ },
			(req) => {
				const m = req.url.match(/chats\/([a-f0-9-]+)\/messages/);
				const chatId = m ? m[1] : 'synthetic-chat-id';
				req.reply(syntheticMessages(chatId));
			}
		).as('listMessages');

		cy.intercept(
			{
				method: 'GET',
				url: new RegExp(
					`/api/v1/chats/[a-f0-9-]+/messages/${SYNTHETIC_ASSISTANT_ID}/citations(\\?|$)`
				)
			},
			(req) => {
				req.reply(SYNTHETIC_CITATIONS);
			}
		).as('getCitations');

		createSampleMatter('M2-C2 Citation Render');

		// createSampleMatter clicks "+ New Chat" which triggers selectChat
		// → listMessages. The intercept fires; the synthetic assistant
		// message lands in the message list and renders.
		cy.wait('@listMessages', { timeout: 15000 });

		// Wait for the assistant message bubble.
		cy.get(`[data-testid="lq-ai-message-${SYNTHETIC_ASSISTANT_ID}"]`, { timeout: 15000 }).should(
			'exist'
		);

		// Lazy-fetch fires once the bubble mounts and isStreaming=false.
		cy.wait('@getCitations', { timeout: 15000 });

		// ── Sidecar chips: 4 buttons, one per marker, each carrying its state ──
		cy.get('[data-testid="m2-citations"]').should('exist');
		cy.get('[data-testid="m2-citations"] button.lq-m2-cite-chip').should('have.length', 4);

		cy.get('[data-testid="m2-citations"] button[data-state="verified-exact"]').should(
			'have.length',
			1
		);
		cy.get('[data-testid="m2-citations"] button[data-state="verified-tolerant"]').should(
			'have.length',
			1
		);
		cy.get('[data-testid="m2-citations"] button[data-state="verified-paraphrase"]').should(
			'have.length',
			1
		);
		cy.get('[data-testid="m2-citations"] button[data-state="unverified"]').should(
			'have.length',
			1
		);

		// The unverified chip is non-interactive (the source viewer doesn't
		// have a row to highlight); the three verified chips are buttons.
		cy.get('[data-testid="m2-citations"] button[data-state="unverified"]').should(
			'be.disabled'
		);
		cy.get('[data-testid="m2-citations"] button[data-state="verified-exact"]').should(
			'not.be.disabled'
		);

		// Each chip carries a tooltip via the `title` attribute. The
		// procurement-reviewer test wants the visual to be scannable
		// without reading tooltips, but the tooltips still have to be
		// wired for screen-reader and hover paths.
		cy.get('[data-testid="m2-citations"] button[data-state="verified-exact"]')
			.invoke('attr', 'title')
			.should('contain', 'Verified verbatim');
		cy.get('[data-testid="m2-citations"] button[data-state="verified-paraphrase"]')
			.invoke('attr', 'title')
			.should('contain', 'judge');
		cy.get('[data-testid="m2-citations"] button[data-state="unverified"]')
			.invoke('attr', 'title')
			.should('contain', 'Could not verify');

		// ── Inline decoration: 4 quoted spans wrapped with state classes ──
		const bubble = `[data-testid="lq-ai-message-${SYNTHETIC_ASSISTANT_ID}"]`;
		cy.get(`${bubble} span.lq-cite-inline`).should('have.length', 4);
		cy.get(`${bubble} span.lq-cite-inline-verified-exact`)
			.should('have.length', 1)
			.invoke('text')
			.should('equal', 'exact verbatim verified text');
		cy.get(`${bubble} span.lq-cite-inline-verified-tolerant`)
			.should('have.length', 1)
			.invoke('text')
			.should('equal', 'tolerant match verified');
		cy.get(`${bubble} span.lq-cite-inline-verified-paraphrase`)
			.should('have.length', 1)
			.invoke('text')
			.should('equal', 'paraphrase judge verified');
		cy.get(`${bubble} span.lq-cite-inline-unverified`)
			.should('have.length', 1)
			.invoke('text')
			.should('equal', 'unverifiable claim no source supports');

		// Screenshot for visual review — the procurement-reviewer test
		// argues the differences must be scannable; the screenshot is the
		// archived evidence the reviewer can flip through during PR review.
		cy.screenshot('m2-c2-four-citation-states', { capture: 'fullPage' });
	});
});
