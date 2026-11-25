/// <reference types="cypress" />
import { rejectUnexpectedApiRequests } from '../support/mocked-api';

const admin = {
	id: 'audit-reader',
	email: 'reader@example.invalid',
	role: 'admin',
	is_admin: true,
	must_change_password: false
};
const entry = {
	id: 'audit-entry',
	timestamp: '2026-01-12T08:00:00Z',
	action: 'matter.document_disclosure_recorded',
	user_id: '161b633c-a7b1-4ba2-9e1e-63267cee8471',
	resource_type: 'matter',
	resource_id: '3d925cfa-bf03-4c0f-86da-fc9e92a53085',
	privilege_marked: true,
	privilege_basis: 'attorney-client',
	routed_inference_tier: 2,
	routed_provider: 'regional-review-provider',
	ip_address: '2001:db8::98',
	details: { reason: 'Disclosure review complete', reference: 'extended-audit-reference-123456789' }
};
const table = '[data-testid="lq-ai-admin-audit-log-table"]';

function visitAudit(items: (typeof entry)[], width: number) {
	rejectUnexpectedApiRequests();
	cy.intercept('GET', '**/api/config', {
		body: { name: 'LQ.AI', features: { enable_websocket: false } }
	});
	cy.intercept('GET', '**/api/version', { body: { version: 'test' } });
	cy.intercept('GET', '**/api/v1/users/me', { body: admin });
	cy.intercept('GET', '**/api/v1/users/me/preferences', { body: { autonomous_enabled: false } });
	cy.intercept('GET', '**/api/v1/chats*', { body: { items: [], next_cursor: null } });
	cy.intercept('GET', '**/api/v1/projects*', { body: [] });
	cy.intercept('GET', '**/api/v1/admin/audit-log*', { body: { items, next_cursor: null } });
	cy.viewport(width, 844);
	cy.visit('/lq-ai/admin/audit-log', {
		onBeforeLoad(win) {
			win.localStorage.setItem('lq-ai.shell', 'sidebar');
			win.localStorage.setItem(
				'lq_ai_auth',
				JSON.stringify({
					access_token: 'audit-fixture',
					expires_at: Date.now() + 3600000,
					user: admin
				})
			);
		}
	});
}

function textBounds(el: Element) {
	const range = el.ownerDocument.createRange();
	range.selectNodeContents(el);
	return range;
}

for (const width of [390, 768]) {
	describe(`Audit log at ${width}px`, () => {
		it('keeps headers and identifiers readable and scrolls to Details within the table', () => {
			visitAudit([entry], width);
			cy.contains(table + ' tbody td', entry.action).should(($cell) => {
				const lines = textBounds($cell[0]).getClientRects().length;
				expect(lines, 'action wraps in readable chunks').to.be.within(1, 4);
			});
			cy.get(table + ' th')
				.should('have.length', 9)
				.each(($th) => {
					expect(textBounds($th[0]).getClientRects().length, $th.text()).to.equal(1);
				});
			cy.contains(table + ' td span', entry.resource_id)
				.scrollIntoView()
				.should('be.visible')
				.should(($id) => {
					expect(textBounds($id[0]).getClientRects().length, 'full resource ID').to.be.within(1, 5);
				});
			const region = '[role="region"][aria-label="Audit log entries"]';
			cy.get(region).focus().should('have.focus').scrollTo('right');
			cy.get(table + ' td')
				.last()
				.should(($td) => {
					const port = $td.closest(region)[0].getBoundingClientRect();
					const cell = $td[0].getBoundingClientRect();
					expect(cell.left).to.be.at.least(port.left);
					expect(cell.right).to.be.at.most(port.right + 1);
					expect($td.text().trim()).to.equal(JSON.stringify(entry.details));
					expect($td[0].scrollWidth).to.be.at.most($td[0].clientWidth + 1);
				});
			cy.get('#lq-main, html').each(($el) => {
				expect($el[0].scrollWidth, 'outside the table').to.be.at.most($el[0].clientWidth + 1);
			});
		});

		it('shows the empty message inside its spanning cell at the initial scroll position', () => {
			visitAudit([], width);
			cy.contains(table + ' td', 'No audit entries match.').should(($td) => {
				expect(($td[0] as HTMLTableCellElement).colSpan).to.equal(9);
				const wrapper = $td.closest('table').parent()[0];
				expect(wrapper.scrollLeft).to.equal(0);
				const port = wrapper.getBoundingClientRect();
				const message = textBounds($td[0]).getBoundingClientRect();
				expect(message.left).to.be.at.least(port.left);
				expect(message.right).to.be.at.most(port.right);
				expect(message.left - port.left, 'message at the start of the region').to.be.lessThan(24);
			});
		});
	});
}
