<script lang="ts">
	import LqText from './shared/LqText.svelte';
	import LqTitle from './shared/LqTitle.svelte';
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
	<LqTitle order={3} size="16" weight="semibold" tone="primary" class="card-title"
		>Where your data lives</LqTitle
	>
	<ul class="service-list">
		{#each services as s}
			<li class="service-row">
				<div class="service-meta">
					<LqText as="span" size="14" weight="medium" tone="primary" class="service-label"
						>{s.label}</LqText
					>
					<LqText as="span" size="12" tone="secondary" class="service-desc">{s.desc}</LqText>
				</div>
				<code class="host-badge">{s.host}</code>
			</li>
		{/each}
	</ul>
	<LqText as="p" size="12" tone="tertiary" class="footer-note">
		All four services run in the operator's environment. Provider API keys never leave the gateway.
	</LqText>
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

	.lq-card :global(.card-title) {
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

	.lq-card :global(.footer-note) {
		margin: 0;
	}
</style>
