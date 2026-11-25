/// <reference types="cypress" />
import { rejectUnexpectedApiRequests } from '../support/mocked-api';

const user = {
	id: 'reviewer',
	display_name: 'Reviewer',
	role: 'admin',
	is_admin: true,
	must_change_password: false
};
const position = {
	position_id: 'notice',
	issue: 'Notice period',
	severity_if_missing: 'high',
	verdict: 'deviates',
	confidence: 0.9,
	cited_chunk_ids: [],
	matched_text: 'Thirty days of written notice.',
	justification: 'Compare the notice period.'
};

function visit(path: string, width: number) {
	rejectUnexpectedApiRequests();
	cy.intercept('GET', '**/api/config', {
		body: { name: 'LQ.AI', features: { enable_websocket: false } }
	});
	cy.intercept('GET', '**/api/version', { body: { version: 'test' } });
	cy.intercept('GET', '**/api/v1/users/me', { body: user });
	cy.intercept('GET', '**/api/v1/users/me/preferences', { body: { autonomous_enabled: false } });
	cy.intercept('GET', '**/api/v1/projects*', { body: [] });
	cy.intercept('GET', '**/api/v1/chats*', { body: { items: [], next_cursor: null } });
	cy.intercept('GET', '**/api/v1/knowledge-bases*', { body: [] });
	cy.intercept('GET', '**/api/v1/playbooks/review', {
		body: { id: 'review', name: 'Contract review', positions: [] }
	});
	cy.intercept('GET', '**/api/v1/playbook-executions/complete', {
		body: {
			id: 'complete',
			playbook_id: 'review',
			status: 'completed',
			created_at: '2026-01-12T08:00:00Z',
			results: {
				positions: [
					position,
					{
						...position,
						position_id: 'renew',
						issue: 'Renewal and termination notice',
						verdict: 'matches_fallback'
					}
				],
				summary: { matches_standard: 0, matches_fallback: 1, deviates: 1, missing: 0 }
			}
		}
	});
	cy.viewport(width, width === 390 ? 844 : width === 768 ? 1024 : 900);
	cy.visit(path, {
		onBeforeLoad(win) {
			win.localStorage.setItem('lq-ai.shell', 'sidebar');
			win.localStorage.setItem(
				'lq_ai_auth',
				JSON.stringify({ user, access_token: 'fixture', expires_at: Date.now() + 3600000 })
			);
		}
	});
}

// Measure the painted label itself. A label's box also includes its select.
function textRects(el: Element) {
	const node = Array.from(el.childNodes).find(
		(n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim()
	);
	expect(node, el.textContent).to.exist;
	const range = el.ownerDocument.createRange();
	range.selectNodeContents(node!);
	return Array.from(range.getClientRects()).filter((r) => r.width && r.height);
}
function checkPageWidth() {
	cy.get('html, #lq-main').each(($el) =>
		expect($el[0].scrollWidth).to.be.at.most($el[0].clientWidth + 1)
	);
}

for (const width of [390, 768, 1440]) {
	describe('Result and Knowledge layouts at ' + width + 'px', () => {
		it('keeps playbook labels and columns readable and retains access to every position', () => {
			visit('/lq-ai/playbook-executions/complete', width);
			cy.get('.lq-pbx-filters label, .lq-pbx-filters__count')
				.should('have.length', 3)
				.each(($el) => {
					expect(textRects($el[0]), $el.text()).to.have.length(1);
				});
			cy.get('.lq-pbx-summary__label').each(($el) =>
				expect(textRects($el[0]).length).to.be.at.most(2)
			);
			cy.get('table.lq-pbx-table th[scope="col"]')
				.should('have.length', 5)
				.not(':first')
				.each(($el) => expect(textRects($el[0])).to.have.length(1));
			cy.contains('.lq-pbx-table__issue', 'Notice period').should(($td) =>
				expect(textRects($td[0]).length).to.be.at.most(2)
			);
			cy.get('[data-testid="lq-pbx-filter-outcome"]').select('deviates');
			cy.contains('.lq-pbx-filters__count', '1 of 2 positions').should('be.visible');
			const region = '[role="region"][aria-label="Playbook positions"]';
			if (width === 390) {
				cy.get(region).should('have.attr', 'tabindex', '0');
				cy.get(region).focus().should('be.focused').scrollTo('right');
				cy.contains('th', 'Citations').should(($th) => {
					const port = $th.closest(region)[0].getBoundingClientRect();
					const cell = $th[0].getBoundingClientRect();
					expect(cell.left).to.be.at.least(port.left);
					expect(cell.right).to.be.at.most(port.right + 1);
				});
				cy.get(region).scrollTo('left');
			} else {
				cy.get(region + '[tabindex="0"]').should('not.exist');
			}
			cy.get('button[aria-label="Expand details for Notice period"]').focus().type('{enter}');
			cy.contains('#lq-pbx-detail-notice', 'Thirty days of written notice.').should('be.visible');
			cy.get('button[aria-label="Collapse details for Notice period"]')
				.should('have.focus')
				.type('{enter}');
			cy.get('#lq-pbx-detail-notice').should('not.exist');
			checkPageWidth();
		});
		it('gives the Knowledge introduction readable lines and keeps both actions usable', () => {
			visit('/lq-ai/knowledge', width);
			cy.get('.lq-page-intro').should(($intro) => {
				const rects = textRects($intro[0]);
				expect(rects.length).to.be.at.most(6);
				expect(Math.max(...rects.map((r) => r.width))).to.be.greaterThan(240);
			});
			cy.contains('.lq-page-header a', 'Back to chat').should('have.attr', 'href', '/lq-ai');
			cy.get('[data-testid="lq-ai-knowledge-new-btn"]').focus().type('{enter}');
			cy.get('[data-testid="lq-ai-knowledge-create-name"]').type('Notice library');
			cy.get('[data-testid="lq-ai-knowledge-create-submit"]').should('be.enabled');
			cy.contains('button', 'Cancel').click();
			cy.get('[data-testid="lq-ai-knowledge-create-form"]').should('not.exist');
			checkPageWidth();
		});
	});
}
