/**
 * Pure-helper tests for the M3-D4 admin intake-bridges page.
 *
 * The helpers are extracted into a sibling `page-helpers.ts` so vitest
 * can exercise them without the svelte transformer.
 */
import { describe, expect, it } from 'vitest';

import type {
	IntakeBridgesList,
	SlackWorkspaceSummary,
	TeamsTenantSummary
} from '$lib/lq-ai/api/intakeBridges';
import {
	buildSlackInstallUrl,
	buildTeamsInstallUrl,
	deriveSectionsView,
	formatInstalledAt,
	slackDisplayName,
	teamsDisplayName
} from '../page-helpers';

function slackRow(over: Partial<SlackWorkspaceSummary> = {}): SlackWorkspaceSummary {
	return {
		id: '00000000-0000-0000-0000-000000000001',
		team_id: 'T01',
		team_name: 'Acme Legal',
		installer_slack_user_id: 'U-installer',
		installed_at: '2026-01-01T00:00:00Z',
		...over
	};
}

function teamsRow(over: Partial<TeamsTenantSummary> = {}): TeamsTenantSummary {
	return {
		id: '00000000-0000-0000-0000-000000000002',
		tenant_id: '00000000-0000-0000-0000-aaaaaaaaaaaa',
		tenant_name: 'Acme Legal LLP',
		installer_oid: 'oid-fixture',
		installed_at: '2026-01-01T00:00:00Z',
		...over
	};
}

describe('deriveSectionsView', () => {
	it('returns all-empty when the list is null (loading state)', () => {
		const v = deriveSectionsView(null);
		expect(v).toEqual({
			slackInstalled: false,
			teamsInstalled: false,
			slackEmpty: false,
			teamsEmpty: false
		});
	});

	it('reports both empty when no bridges connected', () => {
		const list: IntakeBridgesList = { slack_workspaces: [], teams_tenants: [] };
		expect(deriveSectionsView(list)).toEqual({
			slackInstalled: false,
			teamsInstalled: false,
			slackEmpty: true,
			teamsEmpty: true
		});
	});

	it('reports slack installed when at least one workspace exists', () => {
		const list: IntakeBridgesList = {
			slack_workspaces: [slackRow()],
			teams_tenants: []
		};
		const v = deriveSectionsView(list);
		expect(v.slackInstalled).toBe(true);
		expect(v.slackEmpty).toBe(false);
		expect(v.teamsEmpty).toBe(true);
	});

	it('reports teams installed when at least one tenant exists', () => {
		const list: IntakeBridgesList = {
			slack_workspaces: [],
			teams_tenants: [teamsRow()]
		};
		const v = deriveSectionsView(list);
		expect(v.teamsInstalled).toBe(true);
		expect(v.teamsEmpty).toBe(false);
		expect(v.slackEmpty).toBe(true);
	});
});

describe('buildSlackInstallUrl', () => {
	it('appends /slack/oauth/install with no trailing slash', () => {
		expect(buildSlackInstallUrl('https://lqai.example.com/slack')).toBe(
			'https://lqai.example.com/slack/slack/oauth/install'
		);
	});

	it('trims a trailing slash before appending', () => {
		expect(buildSlackInstallUrl('https://lqai.example.com/slack/')).toBe(
			'https://lqai.example.com/slack/slack/oauth/install'
		);
	});
});

describe('buildTeamsInstallUrl', () => {
	it('appends /teams/oauth/install', () => {
		expect(buildTeamsInstallUrl('https://lqai.example.com/teams')).toBe(
			'https://lqai.example.com/teams/teams/oauth/install'
		);
	});

	it('trims a trailing slash before appending', () => {
		expect(buildTeamsInstallUrl('https://lqai.example.com/teams/')).toBe(
			'https://lqai.example.com/teams/teams/oauth/install'
		);
	});
});

describe('formatInstalledAt', () => {
	const now = new Date('2026-05-23T12:00:00Z');

	it('returns "just now" for installs under an hour old', () => {
		expect(formatInstalledAt('2026-05-23T11:30:00Z', now)).toBe('just now');
	});

	it('returns "N hours ago" for installs within today', () => {
		expect(formatInstalledAt('2026-05-23T08:00:00Z', now)).toBe('4 hours ago');
	});

	it('returns "1 hour ago" with singular for exactly one hour', () => {
		expect(formatInstalledAt('2026-05-23T11:00:00Z', now)).toBe('1 hour ago');
	});

	it('returns "N days ago" for installs within two weeks', () => {
		expect(formatInstalledAt('2026-05-20T12:00:00Z', now)).toBe('3 days ago');
	});

	it('returns "1 day ago" with singular for exactly one day', () => {
		expect(formatInstalledAt('2026-05-22T12:00:00Z', now)).toBe('1 day ago');
	});

	it('returns ISO date for installs older than two weeks', () => {
		expect(formatInstalledAt('2026-01-15T08:00:00Z', now)).toBe('2026-01-15');
	});

	it('returns the input verbatim when not parseable', () => {
		expect(formatInstalledAt('not-a-date', now)).toBe('not-a-date');
	});
});

describe('slackDisplayName', () => {
	it('prefers team_name when non-empty', () => {
		expect(slackDisplayName(slackRow({ team_name: 'Acme', team_id: 'T01' }))).toBe('Acme');
	});

	it('falls back to team_id when team_name is empty', () => {
		expect(slackDisplayName(slackRow({ team_name: '', team_id: 'T01' }))).toBe('T01');
	});

	it('falls back to team_id when team_name is whitespace', () => {
		expect(slackDisplayName(slackRow({ team_name: '   ', team_id: 'T01' }))).toBe('T01');
	});
});

describe('teamsDisplayName', () => {
	it('prefers tenant_name when non-empty', () => {
		expect(teamsDisplayName(teamsRow({ tenant_name: 'Acme LLP', tenant_id: 'tid' }))).toBe(
			'Acme LLP'
		);
	});

	it('falls back to tenant_id when tenant_name is empty', () => {
		expect(teamsDisplayName(teamsRow({ tenant_name: '', tenant_id: 'tid' }))).toBe('tid');
	});
});
