import { defineConfig } from 'cypress';

// ---------------------------------------------------------------------------
// Spec tracks (roadmap 4.2 — Cypress in CI)
//
// Specs are classified into explicit tracks so CI can run the deterministic
// subset against a virgin compose stack with NO provider keys. The track
// lists live here (single source of truth) rather than in the workflow so
// `npx cypress run` behaves identically locally and in CI.
//
// - DETERMINISTIC_SPECS: no live-LLM dependency. Either fully
//   cy.intercept-mocked, or live-backend but LLM-free (login + CRUD only).
//   Live-backend specs require the seeded admin fixture:
//     docker compose exec api python -m app.cli reset-admin-password \
//       --email admin@lq.ai --password 'LQ-AI-smoke-test-Pw1!' --no-force-change
//
// - LLM_SPECS: perform a real inference round-trip (send a message and wait
//   for an assistant reply / enhanced prompt / captured skill). They need
//   configured provider keys, so they are gated behind CYPRESS_LLM=1 until
//   a mock/echo provider exists (see DE-232 sequencing in docs).
//
// - Anything in neither list is quarantined and never runs:
//     chat.cy.ts          — upstream OpenWebUI; needs an Ollama model + LLM
//     registration.cy.ts  — upstream OpenWebUI signup flow; LQ.AI stacks
//                           disable open signup (403) so the flow 404s/fails
//     settings.cy.ts      — upstream OpenWebUI; depends on the
//                           admin@example.com bootstrap the LQ.AI stack blocks
//     wave-a-chrome.cy.ts — stale: asserts Matters opens ComingSoonModal,
//                           superseded by Wave C (tabs.ts: matters available)
//     documents.cy.ts     — empty spec (reference comment only)
//   Un-quarantine by fixing the spec and moving it into a track list.
// ---------------------------------------------------------------------------

const DETERMINISTIC_SPECS = [
	// Fully cy.intercept-mocked — no real backend writes, no seeded admin needed.
	'cypress/e2e/a11y.cy.ts',
	'cypress/e2e/m3-0-fresh-install-login.cy.ts',
	'cypress/e2e/m3-a4-playbook-execution.cy.ts',
	'cypress/e2e/m3-a6-easy-playbook-wizard.cy.ts',
	'cypress/e2e/m3-b2-word-addin-oauth.cy.ts',
	'cypress/e2e/m3-c-tabular-review.cy.ts',
	'cypress/e2e/m4-autonomous.cy.ts',
	// Live-backend but LLM-free — real login as the seeded admin; create
	// throwaway matters/chats; message/citation payloads are mocked.
	'cypress/e2e/m2-c2-citation-states.cy.ts',
	'cypress/e2e/wave-b-surfaces.cy.ts',
	'cypress/e2e/wave-c-matters.cy.ts'
];

const LLM_SPECS = [
	'cypress/e2e/wave-d1-power-features.cy.ts',
	'cypress/e2e/wave-d2-skill-creator.cy.ts',
	'cypress/e2e/wave-m1-final-surfaces.cy.ts'
];

// CYPRESS_LLM=1 widens the run to include the live-LLM specs (requires
// provider keys in the stack's .env). Default is the deterministic track.
const specPattern =
	process.env.CYPRESS_LLM === '1' ? [...DETERMINISTIC_SPECS, ...LLM_SPECS] : DETERMINISTIC_SPECS;

export default defineConfig({
	e2e: {
		// CYPRESS_BASE_URL env var overrides this natively (Cypress config
		// resolution) — no extra plumbing needed for CI vs local.
		baseUrl: 'http://localhost:3000',
		specPattern
	},
	// Desktop-realistic viewport so the matter workspace fits — the chat
	// shell + matter rail + composer don't fit in Cypress' 1000x660 default
	// and the composer textarea ends up clipped by overflow:hidden.
	viewportWidth: 1440,
	viewportHeight: 900,
	video: true,
	// KB-attach and ingest round-trips can exceed Cypress' default 5s
	// response timeout. 90s absorbs worst-case ingest latency without
	// masking genuine hangs (the per-test timeout is still the main guard).
	responseTimeout: 90000
});
