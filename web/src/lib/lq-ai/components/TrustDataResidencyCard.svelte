<script lang="ts">
	/**
	 * TrustDataResidencyCard — shows where data lives in a self-hosted deployment.
	 *
	 * // V2-FALLBACK: hardcodes docker-compose service hostnames.
	 * Replace with GET /api/v1/trust/data-residency (spec §9.1) when that
	 * backend route ships; it will derive these from env or service-discovery.
	 */
	const services = [
		{
			label: 'Postgres',
			host: 'postgres:5432',
			desc: 'Chats, messages, file metadata, user accounts'
		},
		{
			label: 'RustFS / S3-compatible',
			host: 'object-store:9000',
			desc: 'Uploaded files, chat exports, BYOK key blobs'
		},
		{
			label: 'Gateway',
			host: 'gateway:9000',
			desc: 'Token routing — never persists prompts or responses'
		},
		{
			label: 'Redis',
			host: 'redis:6379',
			desc: 'Cache + job queue — ephemeral; survives restarts only as configured'
		}
	] as const;
</script>

<div class="lq-card">
	<h3 class="lq-text-panel-h card-title">Where your data lives</h3>
	<ul class="service-list">
		{#each services as s}
			<li class="service-row">
				<div class="service-meta">
					<span class="lq-text-body service-label">{s.label}</span>
					<span class="lq-text-caption service-desc">{s.desc}</span>
				</div>
				<code class="host-badge">{s.host}</code>
			</li>
		{/each}
	</ul>
	<p class="lq-text-caption footer-note">
		All four services run in the operator's environment. Provider API keys never leave the gateway.
	</p>
</div>

<style>
	.lq-card {
		background: var(--lq-canvas);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.card-title {
		margin: 0;
	}

	.service-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.service-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--lq-space-3);
		padding: var(--lq-space-2) 0;
		border-bottom: 1px dashed var(--lq-border);
	}

	.service-row:last-child {
		border-bottom: none;
	}

	.service-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.service-label {
		color: var(--lq-text);
		font-weight: 500;
	}

	.service-desc {
		color: var(--lq-text-secondary);
	}

	.host-badge {
		font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
		font-size: 11px;
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		padding: 2px 7px;
		color: var(--lq-text-secondary);
		white-space: nowrap;
		flex-shrink: 0;
	}

	.footer-note {
		color: var(--lq-text-tertiary);
		margin: 0;
	}
</style>
