import { readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Every checked-in spec belongs to exactly one track, or has an explicit
// exclusion. Validate these exact paths before Cypress can silently ignore one.
export const DETERMINISTIC_SPECS = [
	'cypress/e2e/m3-0-fresh-install-login.cy.ts',
	'cypress/e2e/m3-a4-playbook-execution.cy.ts',
	'cypress/e2e/m3-a6-easy-playbook-wizard.cy.ts',
	'cypress/e2e/m3-b2-word-addin-oauth.cy.ts',
	'cypress/e2e/m3-c-tabular-review.cy.ts',
	'cypress/e2e/m4-autonomous.cy.ts',
	'cypress/e2e/lq-ai-skill-workspaces.cy.ts',
	'cypress/e2e/matter-intake.cy.ts',
	'cypress/e2e/lq-ai-matter-proposals.cy.ts',
	'cypress/e2e/de263-community-skills.cy.ts',
	// Real login/CRUD, with inference responses intercepted.
	'cypress/e2e/m2-c2-citation-states.cy.ts',
	'cypress/e2e/wave-b-surfaces.cy.ts',
	'cypress/e2e/wave-c-matters.cy.ts'
];

export const LLM_SPECS = [
	'cypress/e2e/wave-d1-power-features.cy.ts',
	'cypress/e2e/wave-d2-skill-creator.cy.ts',
	'cypress/e2e/wave-m1-final-surfaces.cy.ts'
];

export const EXCLUDED_SPECS = {
	'cypress/e2e/wave-a-chrome.cy.ts':
		'Stale ComingSoonModal assertions for shipped Matters/Knowledge routes; current route coverage is in wave-b/wave-c.',
	'cypress/e2e/lq-ai-a11y.cy.ts':
		'Dedicated accessibility workflow/runner owns its state, viewport, theme and injected-violation matrix.'
};

export const SPEC_TRACKS = {
	deterministic: DETERMINISTIC_SPECS,
	llm: LLM_SPECS,
	excluded: Object.keys(EXCLUDED_SPECS)
};

export function validateSpecInventory(
	available: string[],
	tracks: Record<string, readonly string[]> = SPEC_TRACKS
): void {
	const declared = Object.values(tracks).flat();
	const duplicates = declared.filter((name, i) => declared.indexOf(name) !== i);
	const missing = declared.filter((name) => !available.includes(name));
	const unclassified = available.filter((name) => !declared.includes(name));
	const errors = [
		duplicates.length && 'Duplicate spec assignments: ' + duplicates.join(', '),
		missing.length && 'Missing declared specs: ' + missing.join(', '),
		unclassified.length && 'Unclassified specs: ' + unclassified.join(', ')
	].filter(Boolean);
	if (errors.length) throw new Error(errors.join('\n'));
}

export function checkSpecInventory(): void {
	const root = fileURLToPath(new URL('./e2e/', import.meta.url));
	function walk(dir: string): string[] {
		return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
			const relative = join(dir, entry.name);
			return entry.isDirectory() ? walk(relative) : [relative];
		});
	}
	const available = walk(root)
		.filter((name) => name.endsWith('.cy.ts'))
		.map((name) => 'cypress/e2e/' + name.slice(root.length).replaceAll('\\', '/'));
	validateSpecInventory(available);
}
