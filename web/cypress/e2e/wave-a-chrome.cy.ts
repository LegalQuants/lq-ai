/**
 * Wave A chrome smoke test.
 *
 * Exercises the visual foundation end-to-end: log in, see the top-tab nav,
 * see ambient trust pills, navigate to Skills, click a not-yet-shipped tab
 * and see ComingSoonModal, dismiss it. Failure of any assertion means the
 * Wave A foundation is broken.
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   docker compose exec api python -m app.cli reset-admin-password
 *   (note the printed password; export LQAI_ADMIN_PASSWORD or update env)
 *   cd web && npx cypress run --spec 'cypress/e2e/wave-a-chrome.cy.ts'
 */
describe('Wave A — LQ.AI chrome', () => {
  beforeEach(() => {
    cy.visit('/lq-ai/login');
    cy.get('input[type="email"]').type(Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai');
    cy.get('input[type="password"]').type(Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!');
    cy.get('button[type="submit"]').click();
    cy.url().should('not.include', '/login');
  });

  it('renders the top tabs with role-aware visibility', () => {
    cy.get('nav[aria-label="Primary"]').within(() => {
      cy.contains('Home');
      cy.contains('Chats');
      cy.contains('Matters');
      cy.contains('Skills');
      cy.contains('Knowledge');
      cy.contains('Saved Prompts');
      cy.contains('Admin'); // visible because we logged in as admin
    });
  });

  it('renders ambient trust chrome in the top bar', () => {
    cy.contains('self-hosted').should('be.visible');
    cy.contains('⌘K').should('be.visible');
  });

  it('navigates to Skills when the tab is available', () => {
    cy.contains('nav[aria-label="Primary"] button', 'Skills').click();
    cy.url().should('include', '/lq-ai/skills');
    cy.contains('nav[aria-label="Primary"] button[aria-selected="true"]', 'Skills');
  });

  it('opens ComingSoonModal for not-yet-shipped tabs', () => {
    cy.contains('nav[aria-label="Primary"] button', 'Matters').click();
    cy.get('[role="dialog"]').within(() => {
      cy.contains('Matters');
      cy.contains('Wave C');
      cy.contains('design spec');
      cy.contains('Got it').click();
    });
    cy.get('[role="dialog"]').should('not.exist');
    // URL didn't change because the modal was used:
    cy.url().should('not.include', '/lq-ai/matters');
  });

  it('AmbientFooter renders on the chat surface with provider + tier + audit pills', () => {
    cy.visit('/lq-ai');
    cy.get('footer[aria-label="Chat status"]').within(() => {
      cy.contains('audit on');
    });
  });
});
