import { defineConfig } from 'cypress';
import { checkSpecInventory, DETERMINISTIC_SPECS, LLM_SPECS } from './cypress/spec-tracks';

checkSpecInventory();

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
// Every checked-in spec must be selected or explicitly excluded in
// cypress/spec-tracks.ts. Missing and unclassified paths fail config loading.
// ---------------------------------------------------------------------------

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
