<script lang="ts">
	/**
	 * /lq-ai/admin/intake-bridges — M3-D4 admin shell for Slack + Teams installs.
	 *
	 * Surfaces what's currently connected (live, non-soft-deleted) and lets
	 * an admin trigger install (opens the bridge's OAuth flow in a new tab)
	 * or uninstall (soft-deletes the row server-side).
	 *
	 * The "configure quick-ask skill" dropdown UI + audit-log shell are
	 * intentionally visible-but-disabled at v0.3.0 with a tooltip pointing
	 * at DE-288 (slash-command surface deferred to M4 / community
	 * contribution). Surfacing them now keeps the admin UI from churning
	 * when the slash-command surface eventually lands.
	 */
	import { onMount } from 'svelte';

	import { intakeBridgesApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
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
	} from './page-helpers';

	let list: IntakeBridgesList | null = null;
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;
	let pendingDeleteId: string | null = null;

	// The bridge install URLs are documented; admins typically front the
	// bridges behind their reverse proxy. These fields let an admin
	// override the deployment default for the click-through. They're
	// hints, not config — the actual URL is whatever the operator
	// configured as LQ_AI_BRIDGE_PUBLIC_URL / LQ_AI_TEAMS_BRIDGE_PUBLIC_URL.
	let slackBridgePublicUrl = '';
	let teamsBridgePublicUrl = '';

	$: sectionsView = deriveSectionsView(list);

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			list = await intakeBridgesApi.listIntakeBridges();
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need admin access to view intake bridges.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	async function uninstallSlack(row: SlackWorkspaceSummary): Promise<void> {
		const confirmed = confirm(
			`Disconnect Slack workspace "${slackDisplayName(row)}"? The bot ` +
				`will stop responding immediately. Re-install via OAuth restores ` +
				`the row in place (the install history is preserved).`
		);
		if (!confirmed) return;
		pendingDeleteId = row.id;
		actionError = null;
		actionSuccess = null;
		try {
			await intakeBridgesApi.deleteSlackWorkspace(row.id);
			actionSuccess = `Disconnected Slack workspace "${slackDisplayName(row)}".`;
			await load();
		} catch (err) {
			actionError = err instanceof Error ? err.message : String(err);
		} finally {
			pendingDeleteId = null;
		}
	}

	async function uninstallTeams(row: TeamsTenantSummary): Promise<void> {
		const confirmed = confirm(
			`Disconnect Microsoft 365 tenant "${teamsDisplayName(row)}"? The bot ` +
				`will stop responding immediately. Re-install via OAuth restores ` +
				`the row in place.`
		);
		if (!confirmed) return;
		pendingDeleteId = row.id;
		actionError = null;
		actionSuccess = null;
		try {
			await intakeBridgesApi.deleteTeamsTenant(row.id);
			actionSuccess = `Disconnected Microsoft 365 tenant "${teamsDisplayName(row)}".`;
			await load();
		} catch (err) {
			actionError = err instanceof Error ? err.message : String(err);
		} finally {
			pendingDeleteId = null;
		}
	}

	function openSlackInstall(): void {
		if (!slackBridgePublicUrl.trim()) {
			actionError = 'Set the Slack bridge public URL to open the OAuth flow.';
			return;
		}
		actionError = null;
		const url = buildSlackInstallUrl(slackBridgePublicUrl.trim());
		window.open(url, '_blank', 'noopener,noreferrer');
	}

	function openTeamsInstall(): void {
		if (!teamsBridgePublicUrl.trim()) {
			actionError = 'Set the Teams bridge public URL to open the OAuth flow.';
			return;
		}
		actionError = null;
		const url = buildTeamsInstallUrl(teamsBridgePublicUrl.trim());
		window.open(url, '_blank', 'noopener,noreferrer');
	}
</script>

<div class="intake-bridges-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Intake bridges</h1>
		<p class="page-intro">
			Connect Slack workspaces and Microsoft Teams tenants to this LQ.AI deployment. The slash
			command surface (<code>/lq</code> and <code>/lq ask</code>) is descoped to M4 / community
			contribution per
			<a
				href="https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#de-288--slackteams-lq-slash-command--quick-skill-flow--deferred-to-m4--community-contribution"
				target="_blank"
				rel="noopener noreferrer">DE-288</a
			>. At v0.3.0 the bridges are installable + OAuth-bound; the bot is otherwise inert until
			DE-288 ships.
		</p>
	</header>

	{#if listError}
		<div class="error-banner" role="alert">{listError}</div>
	{/if}
	{#if actionError}
		<div class="error-banner" role="alert">{actionError}</div>
	{/if}
	{#if actionSuccess}
		<div class="success-banner" role="status">{actionSuccess}</div>
	{/if}

	{#if loading && list === null}
		<p class="loading">Loading intake bridges…</p>
	{/if}

	<!-- ============================================================ -->
	<!-- Slack section                                                -->
	<!-- ============================================================ -->

	<section class="bridge-section" aria-label="Slack">
		<div class="bridge-section-head">
			<h2 class="bridge-section-title">Slack</h2>
		</div>

		<div class="install-row">
			<label for="slack-public-url" class="install-label">
				Slack bridge public URL
				<input
					id="slack-public-url"
					type="url"
					placeholder="https://lqai.example.com/slack"
					bind:value={slackBridgePublicUrl}
					class="install-input"
				/>
			</label>
			<button
				type="button"
				class="install-button"
				on:click={openSlackInstall}
				disabled={!slackBridgePublicUrl.trim()}
			>
				Open Slack install →
			</button>
		</div>

		{#if sectionsView.slackEmpty && !loading}
			<p class="empty-state">No Slack workspaces connected yet.</p>
		{/if}

		{#if list && list.slack_workspaces.length > 0}
			<table class="bridge-table">
				<thead>
					<tr>
						<th>Workspace</th>
						<th>Slack team id</th>
						<th>Installed</th>
						<th>Linked users</th>
						<th>Quick-ask skill</th>
						<th class="bridge-table-actions">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each list.slack_workspaces as row (row.id)}
						<tr>
							<td>{slackDisplayName(row)}</td>
							<td><code>{row.team_id}</code></td>
							<td>{formatInstalledAt(row.installed_at)}</td>
							<td><span class="muted">— (DE-288)</span></td>
							<td>
								<select
									disabled
									aria-disabled="true"
									title="Quick-ask skill picker lands with DE-288's slash-command surface."
								>
									<option>— deferred to DE-288 —</option>
								</select>
							</td>
							<td class="bridge-table-actions">
								<button
									type="button"
									class="action-button danger"
									on:click={() => uninstallSlack(row)}
									disabled={pendingDeleteId === row.id}
								>
									{pendingDeleteId === row.id ? 'Disconnecting…' : 'Disconnect'}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>

	<!-- ============================================================ -->
	<!-- Teams section                                                -->
	<!-- ============================================================ -->

	<section class="bridge-section" aria-label="Microsoft Teams">
		<div class="bridge-section-head">
			<h2 class="bridge-section-title">Microsoft Teams</h2>
		</div>

		<div class="install-row">
			<label for="teams-public-url" class="install-label">
				Teams bridge public URL
				<input
					id="teams-public-url"
					type="url"
					placeholder="https://lqai.example.com/teams"
					bind:value={teamsBridgePublicUrl}
					class="install-input"
				/>
			</label>
			<button
				type="button"
				class="install-button"
				on:click={openTeamsInstall}
				disabled={!teamsBridgePublicUrl.trim()}
			>
				Open Teams install →
			</button>
		</div>

		{#if sectionsView.teamsEmpty && !loading}
			<p class="empty-state">No Microsoft 365 tenants connected yet.</p>
		{/if}

		{#if list && list.teams_tenants.length > 0}
			<table class="bridge-table">
				<thead>
					<tr>
						<th>Tenant</th>
						<th>Tenant id</th>
						<th>Installed</th>
						<th>Linked users</th>
						<th>Quick-ask skill</th>
						<th class="bridge-table-actions">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each list.teams_tenants as row (row.id)}
						<tr>
							<td>{teamsDisplayName(row)}</td>
							<td><code>{row.tenant_id}</code></td>
							<td>{formatInstalledAt(row.installed_at)}</td>
							<td><span class="muted">— (DE-288)</span></td>
							<td>
								<select
									disabled
									aria-disabled="true"
									title="Quick-ask skill picker lands with DE-288's slash-command surface."
								>
									<option>— deferred to DE-288 —</option>
								</select>
							</td>
							<td class="bridge-table-actions">
								<button
									type="button"
									class="action-button danger"
									on:click={() => uninstallTeams(row)}
									disabled={pendingDeleteId === row.id}
								>
									{pendingDeleteId === row.id ? 'Disconnecting…' : 'Disconnect'}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>

	<!-- ============================================================ -->
	<!-- Audit-log shell                                              -->
	<!-- ============================================================ -->

	<section class="bridge-section" aria-label="Recent /lq invocations">
		<div class="bridge-section-head">
			<h2 class="bridge-section-title">Recent <code>/lq</code> invocations</h2>
		</div>
		<p class="empty-state">
			Slash-command invocations will appear here once
			<a
				href="https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#de-288--slackteams-lq-slash-command--quick-skill-flow--deferred-to-m4--community-contribution"
				target="_blank"
				rel="noopener noreferrer">DE-288</a
			> lands.
		</p>
	</section>
</div>

<style>
	.intake-bridges-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-intro {
		color: var(--lq-text-secondary);
		max-width: 60rem;
		font-size: 14px;
		line-height: 1.5;
	}

	.error-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-error-bg, #fee);
		color: var(--lq-error-text, #800);
		border-radius: 6px;
		border: 1px solid var(--lq-error-border, #fbb);
	}

	.success-banner {
		padding: var(--lq-space-3) var(--lq-space-4);
		background: var(--lq-success-bg, #efe);
		color: var(--lq-success-text, #060);
		border-radius: 6px;
		border: 1px solid var(--lq-success-border, #bfb);
	}

	.loading {
		color: var(--lq-text-secondary);
		padding: var(--lq-space-3);
	}

	.bridge-section {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
		padding: var(--lq-space-4);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		background: var(--lq-surface);
	}

	.bridge-section-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}

	.bridge-section-title {
		margin: 0;
		font-size: 18px;
		font-weight: 600;
	}

	.install-row {
		display: flex;
		gap: var(--lq-space-3);
		align-items: flex-end;
		flex-wrap: wrap;
	}

	.install-label {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
		flex: 1;
		min-width: 20rem;
		font-size: 13px;
		color: var(--lq-text-secondary);
	}

	.install-input {
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		background: var(--lq-bg, #fff);
		font-size: 14px;
	}

	.install-button {
		padding: var(--lq-space-2) var(--lq-space-4);
		background: var(--lq-accent);
		color: white;
		border: none;
		border-radius: 6px;
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}

	.install-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.empty-state {
		color: var(--lq-text-secondary);
		font-style: italic;
		margin: 0;
	}

	.bridge-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 14px;
	}

	.bridge-table th,
	.bridge-table td {
		text-align: left;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
	}

	.bridge-table th {
		font-weight: 600;
		color: var(--lq-text-secondary);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.bridge-table-actions {
		text-align: right;
		width: 1px;
		white-space: nowrap;
	}

	.action-button {
		padding: var(--lq-space-1) var(--lq-space-3);
		border-radius: 6px;
		font-size: 13px;
		cursor: pointer;
		border: 1px solid var(--lq-border);
		background: transparent;
		color: var(--lq-text);
	}

	.action-button.danger {
		color: var(--lq-error-text, #b00);
		border-color: var(--lq-error-border, #fbb);
	}

	.action-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.muted {
		color: var(--lq-text-secondary);
		font-style: italic;
	}
</style>
