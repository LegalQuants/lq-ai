/// <reference types="cypress" />

/** Register first: Cypress tries later, contract-specific intercepts first.
 * A fake-token UI spec must fail instead of leaking an unmocked call to a
 * live backend (whose real 401 handling can correctly clear that session).
 */
export function rejectUnexpectedApiRequests(): void {
	cy.intercept({ pathname: '/api/**' }, (req) => {
		throw new Error('Unmocked API request in deterministic fixture: ' + req.method + ' ' + req.url);
	});
}
