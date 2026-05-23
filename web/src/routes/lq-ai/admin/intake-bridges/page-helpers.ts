/**
 * Pure helpers for the M3-D4 admin intake-bridges page.
 *
 * Extracted out of `+page.svelte` so vitest can exercise them without a
 * SvelteKit runtime. The helpers cover:
 *
 *   - formatting `installed_at` ISO strings into a short relative form
 *   - deciding which bridge sections render their "empty state"
 *   - building the install-redirect URL operators click through to start
 *     the OAuth flow on each bridge service
 */

import type {
	IntakeBridgesList,
	SlackWorkspaceSummary,
	TeamsTenantSummary
} from '$lib/lq-ai/api/intakeBridges';

export interface BridgeSectionsView {
	slackInstalled: boolean;
	teamsInstalled: boolean;
	slackEmpty: boolean;
	teamsEmpty: boolean;
}

/** Decide which sections render their empty-state copy. */
export function deriveSectionsView(list: IntakeBridgesList | null): BridgeSectionsView {
	if (list === null) {
		return { slackInstalled: false, teamsInstalled: false, slackEmpty: false, teamsEmpty: false };
	}
	const slackInstalled = list.slack_workspaces.length > 0;
	const teamsInstalled = list.teams_tenants.length > 0;
	return {
		slackInstalled,
		teamsInstalled,
		slackEmpty: !slackInstalled,
		teamsEmpty: !teamsInstalled
	};
}

/** Build the slack-bridge install URL the operator clicks through. */
export function buildSlackInstallUrl(slackBridgePublicUrl: string): string {
	return `${trimTrailingSlash(slackBridgePublicUrl)}/slack/oauth/install`;
}

/** Build the teams-bridge install URL the operator clicks through. */
export function buildTeamsInstallUrl(teamsBridgePublicUrl: string): string {
	return `${trimTrailingSlash(teamsBridgePublicUrl)}/teams/oauth/install`;
}

function trimTrailingSlash(s: string): string {
	return s.endsWith('/') ? s.slice(0, -1) : s;
}

/** Short "2 days ago" / "2026-01-15" formatter for installed_at. */
export function formatInstalledAt(iso: string, now: Date = new Date()): string {
	const installed = new Date(iso);
	if (Number.isNaN(installed.getTime())) {
		return iso;
	}
	const deltaMs = now.getTime() - installed.getTime();
	const deltaHours = Math.floor(deltaMs / (60 * 60 * 1000));
	if (deltaHours < 1) return 'just now';
	if (deltaHours < 24) return `${deltaHours} hour${deltaHours === 1 ? '' : 's'} ago`;
	const deltaDays = Math.floor(deltaHours / 24);
	if (deltaDays < 14) return `${deltaDays} day${deltaDays === 1 ? '' : 's'} ago`;
	// > 2 weeks: render YYYY-MM-DD
	return installed.toISOString().slice(0, 10);
}

/** Display-name picker — gives the UI a non-empty string for either bridge. */
export function slackDisplayName(row: SlackWorkspaceSummary): string {
	return row.team_name.trim() || row.team_id;
}

export function teamsDisplayName(row: TeamsTenantSummary): string {
	return row.tenant_name.trim() || row.tenant_id;
}
