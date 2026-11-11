/** Exercise the edit page's actual PATCH builder without mounting the UI. */
import { describe, expect, it } from 'vitest';
import {
	buildEditChangeSet,
	type SkillEditForm
} from '../../../routes/lq-ai/skills/[id]/edit/+page.svelte';
import { columnsFromRaw, modeFromExtra, newEditableColumn } from '../skills/tableColumns';
import type { UserSkill } from '../types';

function skill(extra: Record<string, unknown>): UserSkill {
	return {
		id: 'skill-1',
		scope: 'user',
		owner_user_id: 'user-1',
		owner_team_id: null,
		slug: 'test-skill',
		display_name: 'Test skill',
		description: 'Description',
		version: '1.0.0',
		tags: ['test'],
		frontmatter_extra: extra,
		body: '  # Original body\r\n\r\nKeep trailing spaces.  \r\n',
		slash_alias: null,
		forked_from: 'original-skill',
		archived_at: null,
		created_at: '2026-11-01T00:00:00Z',
		updated_at: '2026-11-01T00:00:00Z'
	};
}

function form(row: UserSkill): SkillEditForm {
	const parsed = columnsFromRaw(row.frontmatter_extra.columns);
	return {
		displayName: row.display_name,
		description: row.description,
		version: row.version,
		tagsInput: row.tags.join(', '),
		body: row.body,
		outputMode: modeFromExtra(row.frontmatter_extra),
		columns: parsed?.length ? parsed : [newEditableColumn()]
	};
}

const rawColumns = [
	{
		query: '  Original query\n',
		name: ' Term ',
		ensemble_verification: null,
		minimum_inference_tier: null,
		custom: { retain: true }
	}
];

describe('skill edit PATCH preservation', () => {
	it.each(['table', 'report', 'issues_list'])(
		'omits untouched spec and body for %s metadata edits',
		(output_format) => {
			const row = skill({ output_format, columns: rawColumns, custom: { nested: ['keep'] } });
			const before = JSON.stringify(row);
			expect(buildEditChangeSet(row, form(row))).toEqual({});
			expect(buildEditChangeSet(row, { ...form(row), displayName: 'New title' })).toEqual({
				display_name: 'New title'
			});
			expect(buildEditChangeSet(row, { ...form(row), description: 'New description' })).toEqual({
				description: 'New description'
			});
			expect(JSON.stringify(row)).toBe(before);
		}
	);

	it('omits an untouched legacy spec with duplicate names on a metadata-only save', () => {
		const row = skill({
			output_format: 'table',
			columns: [
				{ name: 'Term', query: 'First query' },
				{ name: ' term ', query: 'Second query' }
			]
		});
		expect(buildEditChangeSet(row, { ...form(row), displayName: 'New title' })).toEqual({
			display_name: 'New title'
		});
	});

	it('preserves the exact body when switching to table or prose', () => {
		for (const output_format of ['table', 'report']) {
			const row = skill({ output_format, columns: rawColumns, icon: 'keep' });
			const patch = buildEditChangeSet(row, {
				...form(row),
				outputMode: output_format === 'table' ? 'prose' : 'table'
			});
			expect(patch).not.toHaveProperty('body');
			expect(patch.frontmatter_extra?.icon).toBe('keep');
			if (output_format === 'table') expect(patch.frontmatter_extra).toEqual({ icon: 'keep' });
			else expect(patch.frontmatter_extra?.output_format).toBe('table');
		}
	});

	it('sends an intentional body change without trimming or changing metadata', () => {
		const row = skill({ output_format: 'report', columns: rawColumns });
		const body = '  New body\r\n\n  ';
		expect(buildEditChangeSet(row, { ...form(row), body })).toEqual({ body });
	});

	it('sends a column edit while retaining unrelated frontmatter and the body', () => {
		const row = skill({ output_format: 'table', columns: rawColumns, icon: 'keep' });
		const edited = form(row);
		edited.columns[0].query = 'Updated query';
		expect(buildEditChangeSet(row, edited)).toEqual({
			frontmatter_extra: {
				output_format: 'table',
				columns: [{ name: 'Term', query: 'Updated query' }],
				icon: 'keep'
			}
		});
	});
});
