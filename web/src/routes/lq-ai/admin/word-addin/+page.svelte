<script lang="ts">
	import {
		fetchWordAddinManifest,
		downloadManifestFile,
		type WordAddinManifestOptions
	} from '$lib/lq-ai/api/wordAddin';

	// Form state — all three are optional overrides; backend defaults
	// apply when they're left blank.
	let deploymentOrigin = '';
	let displayName = '';
	let providerName = '';

	let generating = false;
	let lastError = '';
	let lastSuccess = '';

	async function handleGenerate() {
		generating = true;
		lastError = '';
		lastSuccess = '';
		try {
			const options: WordAddinManifestOptions = {};
			if (deploymentOrigin.trim()) options.deploymentOrigin = deploymentOrigin.trim();
			if (displayName.trim()) options.displayName = displayName.trim();
			if (providerName.trim()) options.providerName = providerName.trim();

			const result = await fetchWordAddinManifest(options);
			downloadManifestFile(result);
			lastSuccess = `Downloaded ${result.filename}. Sideload it via Microsoft 365 Admin Center → Settings → Integrated apps.`;
		} catch (err) {
			lastError = err instanceof Error ? err.message : String(err);
		} finally {
			generating = false;
		}
	}
</script>

<div class="word-addin-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Word add-in</h1>
		<p class="page-intro">
			Generate a deployment-specific Office Add-in manifest for sideload via Microsoft 365 Admin
			Center. Each download embeds your deployment's URL and a fresh per-install GUID.
		</p>
	</header>

	<section class="info-banner" aria-label="Scope notice">
		<h2 class="info-banner-title">M3-B1 plumbing — feature surface deferred</h2>
		<p>
			The installable manifest, OAuth handshake (M3-B2), and signed distribution package (M3-B7)
			ship with v0.3.0. The task pane's in-Word feature surfaces (chat against the open document,
			skills with tracked changes, playbook execution, the Inference Tier badge) are deferred to M4
			/ community contribution per
			<a
				href="https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution"
				target="_blank"
				rel="noopener noreferrer">DE-287</a
			>. Until those land, each tab in the task pane links the operator back to the equivalent
			web-app surface.
		</p>
	</section>

	<section class="generator-card">
		<h2 class="generator-title">Generate manifest</h2>
		<p class="generator-help">
			Leave any field blank to use the backend defaults. The deployment origin defaults to your
			reverse-proxy-reported public URL; override it only when generating a manifest for a different
			deployment than the one you're currently signed into.
		</p>

		<form class="generator-form" on:submit|preventDefault={handleGenerate}>
			<div class="form-row">
				<label for="deployment-origin">
					Deployment origin
					<span class="form-hint">e.g. https://lq.acme.example (no trailing slash)</span>
				</label>
				<input
					id="deployment-origin"
					type="url"
					placeholder="auto-detected from this request"
					bind:value={deploymentOrigin}
					disabled={generating}
				/>
			</div>

			<div class="form-row">
				<label for="display-name">
					Display name
					<span class="form-hint">surfaced inside Word's ribbon (default: LQ.AI)</span>
				</label>
				<input
					id="display-name"
					type="text"
					placeholder="LQ.AI"
					maxlength="64"
					bind:value={displayName}
					disabled={generating}
				/>
			</div>

			<div class="form-row">
				<label for="provider-name">
					Provider name
					<span class="form-hint">shown to M365 admins during install (default: LegalQuants)</span>
				</label>
				<input
					id="provider-name"
					type="text"
					placeholder="LegalQuants"
					maxlength="64"
					bind:value={providerName}
					disabled={generating}
				/>
			</div>

			<div class="form-actions">
				<button type="submit" class="generate-button" disabled={generating}>
					{generating ? 'Generating…' : 'Generate manifest'}
				</button>
			</div>

			{#if lastError}
				<p class="status status-error" role="alert">{lastError}</p>
			{/if}
			{#if lastSuccess}
				<p class="status status-success" role="status">{lastSuccess}</p>
			{/if}
		</form>
	</section>

	<section class="next-steps">
		<h2>Sideload via Microsoft 365 Admin Center</h2>
		<ol>
			<li>Generate the manifest above and download the XML file.</li>
			<li>
				Open
				<a
					href="https://admin.microsoft.com/Adminportal/Home#/Settings/IntegratedApps"
					target="_blank"
					rel="noopener noreferrer">Microsoft 365 Admin Center → Settings → Integrated apps</a
				>.
			</li>
			<li>
				Click <strong>Upload custom apps</strong>, choose <strong>Office Add-in</strong>, and upload
				the manifest.
			</li>
			<li>Assign the add-in to the users or groups who need it.</li>
			<li>Users see <strong>LQ.AI</strong> appear on Word's Home ribbon within a few minutes.</li>
		</ol>
		<p class="release-note">
			<strong>v0.3.0 manifest is unsigned.</strong> Signed manifests and the enterprise distribution
			package land with
			<a
				href="https://github.com/LegalQuants/lq-ai/blob/main/docs/M3-IMPLEMENTATION-PLAN.md#task-m3-b7--signed-manifest--enterprise-sideload-distribution-package"
				target="_blank"
				rel="noopener noreferrer">M3-B7</a
			>
			when the code-signing certificate procurement completes. Until then, Microsoft 365 Admin Center
			will warn that the add-in is unsigned during sideload.
		</p>
	</section>
</div>

<style>
	.word-addin-page {
		padding: var(--lq-space-6) var(--lq-space-5);
		max-width: 780px;
		margin: 0 auto;
		width: 100%;
	}

	.page-header {
		margin-bottom: var(--lq-space-5);
	}

	.page-intro {
		color: var(--lq-text-secondary);
		margin: var(--lq-space-2) 0 0;
		line-height: 1.5;
	}

	.info-banner {
		border: 1px solid var(--lq-border);
		border-left-width: 4px;
		border-left-color: var(--lq-accent);
		border-radius: 6px;
		background: var(--lq-surface);
		padding: var(--lq-space-4);
		margin-bottom: var(--lq-space-5);
	}

	.info-banner-title {
		margin: 0 0 var(--lq-space-2);
		font-size: 14px;
		font-weight: 600;
	}

	.info-banner p {
		margin: 0;
		color: var(--lq-text-secondary);
		font-size: 13px;
		line-height: 1.55;
	}

	.generator-card {
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		padding: var(--lq-space-5);
		margin-bottom: var(--lq-space-5);
	}

	.generator-title {
		margin: 0 0 var(--lq-space-2);
		font-size: 18px;
		font-weight: 600;
	}

	.generator-help {
		color: var(--lq-text-secondary);
		font-size: 13px;
		margin: 0 0 var(--lq-space-4);
		line-height: 1.5;
	}

	.generator-form {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-4);
	}

	.form-row {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.form-row label {
		font-weight: 500;
		font-size: 13px;
	}

	.form-hint {
		display: block;
		font-weight: 400;
		font-size: 12px;
		color: var(--lq-text-secondary);
		margin-top: 2px;
	}

	.form-row input {
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: 4px;
		background: var(--lq-bg);
		color: var(--lq-text);
		font-size: 14px;
		font-family: inherit;
	}

	.form-row input:focus {
		outline: 2px solid var(--lq-accent);
		outline-offset: -1px;
		border-color: var(--lq-accent);
	}

	.form-row input:disabled {
		background: var(--lq-surface);
		opacity: 0.7;
	}

	.form-actions {
		display: flex;
		justify-content: flex-end;
	}

	.generate-button {
		background: var(--lq-accent);
		color: var(--lq-on-accent, white);
		border: none;
		border-radius: 4px;
		padding: var(--lq-space-2) var(--lq-space-4);
		font-weight: 500;
		font-size: 14px;
		cursor: pointer;
		transition: opacity 0.12s;
	}

	.generate-button:hover:not(:disabled) {
		opacity: 0.9;
	}

	.generate-button:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}

	.status {
		margin: 0;
		padding: var(--lq-space-3);
		border-radius: 4px;
		font-size: 13px;
	}

	.status-error {
		background: var(--lq-error-bg, #fef2f2);
		color: var(--lq-error-text, #991b1b);
		border: 1px solid var(--lq-error-border, #fecaca);
	}

	.status-success {
		background: var(--lq-success-bg, #f0fdf4);
		color: var(--lq-success-text, #166534);
		border: 1px solid var(--lq-success-border, #bbf7d0);
	}

	.next-steps {
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 8px;
		padding: var(--lq-space-5);
	}

	.next-steps h2 {
		margin: 0 0 var(--lq-space-3);
		font-size: 16px;
		font-weight: 600;
	}

	.next-steps ol {
		margin: 0 0 var(--lq-space-4);
		padding-left: var(--lq-space-5);
		line-height: 1.6;
	}

	.next-steps li {
		margin-bottom: var(--lq-space-2);
	}

	.release-note {
		margin: 0;
		padding: var(--lq-space-3);
		background: var(--lq-warning-bg, #fef3c7);
		color: var(--lq-warning-text, #92400e);
		border-radius: 4px;
		font-size: 13px;
		line-height: 1.5;
	}
</style>
