/**
 * Wave C — Matters surface smoke tests.
 *
 * Covers the five new surfaces that shipped in Wave C:
 *
 *   1. Matters tab routes to /lq-ai/matters — no ComingSoonModal; h1 renders
 *   2. "+ New matter" button opens NewMatterModal; Cancel dismisses it
 *   3. Create matter → redirect to workspace → MatterRail + ChatPanel render
 *   4. Create chat in matter → new entry appears in MatterRail Chats section
 *   5. Privileged matter without tier floor shows validation error
 *
 * Run requires a live stack:
 *   docker compose up -d
 *   docker compose exec api python -m app.cli reset-admin-password
 *   (note the printed password; export LQAI_ADMIN_PASSWORD or update env)
 *   cd web && npx cypress run --spec 'cypress/e2e/wave-c-matters.cy.ts'
 */
describe('Wave C — Matters surfaces', () => {
  beforeEach(() => {
    cy.visit('/lq-ai/login');
    cy.get('input[type="email"]').type(Cypress.env('LQAI_ADMIN_EMAIL') || 'admin@lq.ai');
    cy.get('input[type="password"]').type(
      Cypress.env('LQAI_ADMIN_PASSWORD') || 'LQ-AI-smoke-test-Pw1!'
    );
    cy.intercept('POST', '**/api/v1/auth/login').as('login');
    cy.get('button[type="submit"]').click();
    cy.wait('@login', { timeout: 30000 }).its('response.statusCode').should('eq', 200);
    cy.url({ timeout: 15000 }).should('not.include', '/login');
  });

  // ── Test 1 ───────────────────────────────────────────────────────────────────
  // Matters tab is now available=true; clicking it routes to /lq-ai/matters
  // and shows the Matters page heading — no ComingSoonModal.
  it('Matters tab routes to /lq-ai/matters with no ComingSoonModal', () => {
    cy.contains('nav[aria-label="Primary"] button', 'Matters').click();
    cy.url().should('include', '/lq-ai/matters');
    // No dialog should be present (was the ComingSoonModal path).
    cy.get('[role="dialog"]').should('not.exist');
    // Matters page h1 must be visible.
    cy.contains('h1', /matters/i).should('be.visible');
  });

  // ── Test 2 ───────────────────────────────────────────────────────────────────
  // The always-visible "+ New matter" button opens NewMatterModal; Cancel
  // dismisses the dialog. Tests modal open/close independent of existing-matters
  // state so the test is not polluted by prior runs.
  it('+ New matter button opens NewMatterModal; Cancel dismisses it', () => {
    cy.visit('/lq-ai/matters');
    // The header "+ New matter" button is always visible regardless of list state.
    cy.contains('button', '+ New matter').first().click();
    // NewMatterModal renders as role="dialog" with h2 "New matter".
    cy.get('[role="dialog"]').should('exist');
    cy.contains('h2', 'New matter').should('be.visible');
    // Cancel closes the modal.
    cy.contains('button', 'Cancel').click();
    cy.get('[role="dialog"]').should('not.exist');
  });

  // ── Test 3 ───────────────────────────────────────────────────────────────────
  // Create a matter → modal calls the API → redirects to the matter workspace
  // at /lq-ai/matters/{id} → MatterRail sidebar renders the matter name and
  // the ChatPanel shell is mounted.
  it('Create matter → redirects to workspace; MatterRail + ChatPanel render', () => {
    cy.visit('/lq-ai/matters');
    cy.contains('button', '+ New matter').first().click();
    cy.get('[role="dialog"]').should('exist');

    const matterName = `Cypress Test Matter ${Date.now()}`;
    // The name input is the first text input inside the modal (id="nmm-name").
    cy.get('[role="dialog"]').find('input[type="text"]').first().clear().type(matterName);
    cy.intercept('POST', '**/api/v1/projects').as('createMatter');
    cy.contains('button', 'Create matter').click();
    cy.wait('@createMatter', { timeout: 60000 }).its('response.statusCode').should('eq', 201);

    // After creation, NewMatterModal calls goto(/lq-ai/matters/{id}).
    cy.url({ timeout: 15000 }).should('match', /\/lq-ai\/matters\/[a-f0-9-]+$/);

    // MatterRail renders the matter name (visible in MatterRailMetadata header).
    cy.contains(matterName).should('be.visible');

    // ChatPanel shell must be mounted.
    cy.get('[data-testid="lq-ai-chat-shell"]').should('exist');
  });

  // ── Test 4 ───────────────────────────────────────────────────────────────────
  // Within a matter workspace, clicking the MatterRail "+ New" chat button
  // creates a chat and the title appears in the rail's chat list.
  it('Create chat in matter → new entry appears in MatterRail Chats section', () => {
    // Create a fresh matter so we start with zero chats.
    cy.visit('/lq-ai/matters');
    cy.contains('button', '+ New matter').first().click();
    const matterName = `Cypress Chat Test ${Date.now()}`;
    cy.get('[role="dialog"]').find('input[type="text"]').first().clear().type(matterName);
    cy.intercept('POST', '**/api/v1/projects').as('createMatter');
    cy.contains('button', 'Create matter').click();
    cy.wait('@createMatter', { timeout: 60000 }).its('response.statusCode').should('eq', 201);
    cy.url({ timeout: 15000 }).should('match', /\/lq-ai\/matters\/[a-f0-9-]+$/);

    // The Chats section in MatterRail has a "+ New" button (rail-btn-sm).
    // The rail section header shows h3 "Chats" followed by the "+ New" button.
    cy.intercept('POST', '**/api/v1/chats').as('createChat');
    cy.contains('h3', 'Chats')
      .parent()
      .contains('button', '+ New')
      .click();
    cy.wait('@createChat', { timeout: 60000 }).its('response.statusCode').should('eq', 201);

    // The API assigns "New chat" to a chat with no messages yet.
    cy.get('ul[aria-label="Matter chats"] li[role="option"]')
      .should('have.length', 1)
      .contains('New chat')
      .should('be.visible');
  });

  // ── Test 5 ───────────────────────────────────────────────────────────────────
  // Attempting to create a privileged matter without selecting a tier floor
  // triggers client-side validation: the tier error message appears and the
  // modal is NOT dismissed (form is invalid so the API is never called).
  it('Privileged matter without tier floor shows validation error', () => {
    cy.visit('/lq-ai/matters');
    cy.contains('button', '+ New matter').first().click();
    cy.get('[role="dialog"]').should('exist');

    // Fill in a name so only the tier validation fires.
    cy.get('[role="dialog"]').find('input[type="text"]').first().clear().type('Privileged validation test');

    // Check the "Attorney-client privileged" checkbox (id="nmm-privileged").
    cy.get('#nmm-privileged').check();

    // Tier floor select should now be visible (conditionally rendered when privileged).
    cy.get('#nmm-tier').should('exist');

    // Submit without selecting a tier floor — tier floor select remains at "(none)".
    cy.contains('button', 'Create matter').click();

    // Validation error: "Privileged matters require a minimum tier floor"
    cy.contains(/privileged matters require a minimum tier floor/i).should('be.visible');

    // Dialog must still be open (form was rejected, no navigation occurred).
    cy.get('[role="dialog"]').should('exist');

    cy.contains('button', 'Cancel').click();
    cy.get('[role="dialog"]').should('not.exist');
  });
});
