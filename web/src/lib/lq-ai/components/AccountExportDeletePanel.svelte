<script lang="ts">
	import { onDestroy } from 'svelte';
	import { get } from 'svelte/store';
	import { auth } from '../auth/store';
	import { cancelDeletion, getExportJob, requestDeletion, startExport } from '../api/users';
	import type { DeleteScheduledResponse, ExportJob } from '../types';

	// ----- Export state -----

	type ExportState =
		| { kind: 'idle' }
		| { kind: 'starting' }
		| { kind: 'polling'; jobId: string }
		| { kind: 'done'; downloadUrl: string }
		| { kind: 'failed' };

	let exportState: ExportState = { kind: 'idle' };
	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let pollCount = 0;
	const MAX_POLLS = 60;

	function stopPolling() {
		if (pollInterval !== null) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
		pollCount = 0;
	}

	onDestroy(stopPolling);

	async function handleStartExport() {
		exportState = { kind: 'starting' };
		try {
			const job = await startExport();
			if (job.status === 'completed' && job.download_url) {
				exportState = { kind: 'done', downloadUrl: job.download_url };
				return;
			}
			if (job.status === 'failed') {
				exportState = { kind: 'failed' };
				return;
			}
			exportState = { kind: 'polling', jobId: job.job_id };
			startPolling(job.job_id);
		} catch {
			exportState = { kind: 'failed' };
		}
	}

	function startPolling(jobId: string) {
		stopPolling();
		pollInterval = setInterval(async () => {
			pollCount++;
			if (pollCount > MAX_POLLS) {
				stopPolling();
				exportState = { kind: 'failed' };
				return;
			}
			try {
				const job: ExportJob = await getExportJob(jobId);
				if (job.status === 'completed' && job.download_url) {
					stopPolling();
					exportState = { kind: 'done', downloadUrl: job.download_url };
				} else if (job.status === 'failed') {
					stopPolling();
					exportState = { kind: 'failed' };
				}
			} catch {
				stopPolling();
				exportState = { kind: 'failed' };
			}
		}, 5000);
	}

	// ----- Delete state -----

	type DeleteState =
		| { kind: 'idle' }
		| { kind: 'confirm' }
		| { kind: 'requesting' }
		| { kind: 'scheduled'; response: DeleteScheduledResponse }
		| { kind: 'cancelling' }
		| { kind: 'error'; message: string };

	let deleteState: DeleteState = { kind: 'idle' };
	let confirmEmail = '';

	$: userEmail = get(auth).user?.email ?? '';
	$: confirmReady = confirmEmail === userEmail;

	function openConfirm() {
		confirmEmail = '';
		deleteState = { kind: 'confirm' };
	}

	function closeConfirm() {
		deleteState = { kind: 'idle' };
		confirmEmail = '';
	}

	async function handleRequestDeletion() {
		deleteState = { kind: 'requesting' };
		try {
			const res = await requestDeletion();
			deleteState = { kind: 'scheduled', response: res };
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : 'Request failed. Please try again.';
			deleteState = { kind: 'error', message: msg };
		}
	}

	async function handleCancelDeletion() {
		deleteState = { kind: 'cancelling' };
		try {
			await cancelDeletion();
			deleteState = { kind: 'idle' };
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : 'Cancellation failed. Please try again.';
			deleteState = { kind: 'error', message: msg };
		}
	}

	function formatDate(iso: string): string {
		try {
			return new Date(iso).toLocaleDateString(undefined, {
				year: 'numeric',
				month: 'long',
				day: 'numeric'
			});
		} catch {
			return iso;
		}
	}

	$: scheduledState = deleteState.kind === 'scheduled' ? deleteState : null;
	$: deleteErrorState = deleteState.kind === 'error' ? deleteState : null;
</script>

<div class="aed-panel">
	<!-- ── Export section ─────────────────────────────── -->
	<section class="aed-section">
		<h3 class="section-title">Export my data</h3>
		<p class="lq-text-body" style="color: var(--lq-text-secondary); margin-bottom: var(--lq-space-3);">
			Download a copy of all your data — chats, files, skills, and account information. Exports expire after 24 hours.
		</p>

		{#if exportState.kind === 'idle'}
			<button type="button" class="lq-btn-secondary" on:click={handleStartExport}>
				Export my data
			</button>

		{:else if exportState.kind === 'starting' || exportState.kind === 'polling'}
			<p class="status-msg">Building export… (this can take a minute)</p>

		{:else if exportState.kind === 'done'}
			<div class="export-done">
				<p class="status-msg status-msg--ok">Your export is ready.</p>
				<a
					href={exportState.downloadUrl}
					class="lq-btn-primary download-link"
					download
					rel="noopener noreferrer"
				>
					Download (.zip)
				</a>
				<p class="lq-text-caption" style="margin-top: var(--lq-space-2); color: var(--lq-text-tertiary);">
					Link expires in 24 hours.
				</p>
			</div>

		{:else if exportState.kind === 'failed'}
			<p class="status-msg status-msg--err">Export failed.</p>
			<button
				type="button"
				class="lq-btn-ghost"
				style="margin-top: var(--lq-space-2);"
				on:click={() => { exportState = { kind: 'idle' }; }}
			>
				Try again
			</button>
		{/if}
	</section>

	<div class="section-divider" role="separator"></div>

	<!-- ── Delete section ────────────────────────────── -->
	<section class="aed-section">
		<h3 class="section-title">Delete my account</h3>
		<p class="lq-text-body" style="color: var(--lq-text-secondary); margin-bottom: var(--lq-space-3);">
			Schedule your account for permanent deletion. You have a grace period to cancel by signing back in.
		</p>

		{#if deleteState.kind === 'idle'}
			<button type="button" class="lq-btn-danger" on:click={openConfirm}>
				Delete my account
			</button>

		{:else if deleteState.kind === 'requesting' || deleteState.kind === 'cancelling'}
			<p class="status-msg">Please wait…</p>

		{:else if scheduledState}
			<div class="scheduled-block">
				<p class="status-msg status-msg--warn">
					Your account is scheduled for deletion on
					<strong>{formatDate(scheduledState.response.scheduled_deletion_at)}</strong>.
					You have {scheduledState.response.grace_period_days} days to cancel.
				</p>
				<button
					type="button"
					class="lq-btn-secondary"
					style="margin-top: var(--lq-space-3);"
					on:click={handleCancelDeletion}
				>
					Cancel deletion
				</button>
			</div>

		{:else if deleteErrorState}
			<p class="status-msg status-msg--err">{deleteErrorState.message}</p>
			<button
				type="button"
				class="lq-btn-ghost"
				style="margin-top: var(--lq-space-2);"
				on:click={() => { deleteState = { kind: 'idle' }; }}
			>
				Dismiss
			</button>
		{/if}
	</section>
</div>

<!-- ── Confirmation modal ───────────────────────────── -->
{#if deleteState.kind === 'confirm'}
	<div
		class="modal-backdrop"
		role="dialog"
		aria-modal="true"
		aria-labelledby="delete-confirm-title"
		tabindex="-1"
		on:keydown={(e) => e.key === 'Escape' && closeConfirm()}
	>
		<div class="modal" role="document">
			<h2 id="delete-confirm-title" class="lq-text-page-h" style="margin-bottom: var(--lq-space-4);">
				Delete account
			</h2>
			<p class="lq-text-body" style="margin-bottom: var(--lq-space-4);">
				This will schedule your account for permanent deletion. To confirm, type your email address below.
			</p>
			<label class="field-label" for="confirm-email">
				Type <strong>{userEmail}</strong> to confirm
			</label>
			<input
				id="confirm-email"
				type="email"
				class="lq-input"
				placeholder={userEmail}
				bind:value={confirmEmail}
				on:keydown={(e) => e.key === 'Enter' && confirmReady && handleRequestDeletion()}
				style="margin-bottom: var(--lq-space-6);"
				autocomplete="off"
			/>
			<div class="modal-actions">
				<button type="button" class="lq-btn-ghost" on:click={closeConfirm}>Cancel</button>
				<button
					type="button"
					class="lq-btn-danger"
					disabled={!confirmReady}
					on:click={handleRequestDeletion}
				>
					Confirm deletion
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.aed-panel {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.aed-section {
		padding: var(--lq-space-4) 0;
	}

	.section-divider {
		border-top: 1px solid var(--lq-border);
	}

	.section-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--lq-text);
		margin-bottom: var(--lq-space-1);
	}

	.status-msg {
		font-size: 14px;
		color: var(--lq-text-secondary);
	}
	.status-msg--ok { color: var(--lq-accent); font-weight: 500; }
	.status-msg--err { color: var(--lq-error); }
	.status-msg--warn { color: var(--lq-warn); }

	.export-done {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--lq-space-2);
	}

	.download-link {
		text-decoration: none;
		display: inline-block;
	}

	.scheduled-block {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
	}

	.field-label {
		display: block;
		font-size: 13px;
		color: var(--lq-text-secondary);
		margin-bottom: var(--lq-space-2);
	}

	.lq-input {
		display: block;
		width: 100%;
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border-strong);
		border-radius: var(--lq-radius);
		font-size: 14px;
		color: var(--lq-text);
		background: var(--lq-canvas);
		box-sizing: border-box;
	}
	.lq-input:focus { outline: 2px solid var(--lq-accent); outline-offset: 1px; }

	.modal-backdrop {
		position: fixed; inset: 0;
		background: rgba(0, 0, 0, 0.35);
		display: flex; align-items: center; justify-content: center;
		z-index: 100;
	}
	.modal {
		background: var(--lq-canvas);
		border-radius: var(--lq-radius-lg);
		padding: var(--lq-space-6);
		max-width: 480px;
		width: calc(100% - 32px);
		box-shadow: 0 24px 64px rgba(0, 0, 0, 0.18);
	}
	.modal-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--lq-space-2);
	}

	/* Danger variant — defined here per Wave A per-component pattern; downstream
	   forks can extract to practice.css when danger states appear elsewhere. */
	.lq-btn-danger {
		background: var(--lq-canvas);
		color: var(--lq-error);
		border: 1.5px solid var(--lq-error);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-danger:hover { background: var(--lq-error); color: white; }
	.lq-btn-danger:focus-visible { outline: 2px solid var(--lq-error); outline-offset: 2px; }
	.lq-btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }

	.lq-btn-primary {
		background: var(--lq-accent);
		color: white;
		border: 0;
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-primary:hover { opacity: 0.85; }
	.lq-btn-primary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }

	.lq-btn-secondary {
		background: var(--lq-canvas);
		color: var(--lq-accent);
		border: 1px solid var(--lq-accent-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		font-weight: 500;
		cursor: pointer;
	}
	.lq-btn-secondary:hover { background: var(--lq-accent-soft); }
	.lq-btn-secondary:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }

	.lq-btn-ghost {
		background: transparent;
		color: var(--lq-text-secondary);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-pill);
		padding: var(--lq-space-2) var(--lq-space-4);
		font-size: 14px;
		cursor: pointer;
	}
	.lq-btn-ghost:hover { background: var(--lq-inset); }
	.lq-btn-ghost:focus-visible { outline: 2px solid var(--lq-accent); outline-offset: 2px; }
</style>
