import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkSpecInventory, validateSpecInventory } from '../../cypress/spec-tracks.ts';

test('every checked-in Cypress spec has a real, unique track assignment', () => {
	checkSpecInventory();
});

test('a deleted or misspelled selected spec fails before Cypress selection', () => {
	assert.throws(
		() => validateSpecInventory([], { deterministic: ['missing.cy.ts'] }),
		/Missing declared specs: missing/
	);
});

test('a newly added spec cannot silently remain outside all tracks', () => {
	assert.throws(
		() => validateSpecInventory(['new.cy.ts'], { deterministic: [] }),
		/Unclassified specs: new/
	);
});

test('one spec cannot run twice or belong to incompatible tracks', () => {
	assert.throws(
		() =>
			validateSpecInventory(['a.cy.ts'], {
				deterministic: ['a.cy.ts'],
				llm: ['a.cy.ts']
			}),
		/Duplicate spec assignments: a/
	);
});
