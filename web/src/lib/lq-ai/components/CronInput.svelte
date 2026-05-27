<script lang="ts">
	/**
	 * CronInput — frequency picker with live client-side next-run preview.
	 *
	 * Usage:
	 *   <CronInput bind:value={cronExpr} />
	 *   <CronInput bind:value={cronExpr} disabled={submitting} />
	 *
	 * Emits a compiled 5-field cron string via the `value` bindable prop.
	 * The preview is advisory; the backend 422s invalid/unsatisfiable exprs.
	 *
	 * Presets compile to `presetToCron(...)`; Custom exposes a raw text field
	 * that passes through unchanged. All cron fields use local time (the server
	 * scheduler likewise runs in its own local time — this is noted in the UI).
	 */
	import { presetToCron, nextRun } from '$lib/lq-ai/autonomous/cron';
	import type { CronPreset } from '$lib/lq-ai/autonomous/cron';

	// ---------------------------------------------------------------------------
	// Public props
	// ---------------------------------------------------------------------------

	/** The current compiled cron expression. Bind to this. */
	export let value: string = '';

	/** Disable all controls (e.g. while parent form is submitting). */
	export let disabled: boolean = false;

	/** Optional error message to show below the field (e.g. from a server 422). */
	export let error: string | null = null;

	// ---------------------------------------------------------------------------
	// Internal state
	// ---------------------------------------------------------------------------

	let preset: CronPreset = 'daily';
	let hour: number = 9;
	let minute: number = 0;
	/** Day-of-week for weekly preset (0=Sun … 6=Sat). */
	let dow: number = 1;
	/** Day-of-month for monthly preset (1–28). */
	let dom: number = 1;
	/** Raw expression for the Custom preset. */
	let rawCron: string = '';

	// ---------------------------------------------------------------------------
	// Derived: compile value reactively whenever any input changes
	// ---------------------------------------------------------------------------

	$: if (preset !== 'custom') {
		value = presetToCron(preset, { hour, minute, dow, dom });
	} else {
		value = rawCron;
	}

	// ---------------------------------------------------------------------------
	// Next-run preview
	// ---------------------------------------------------------------------------

	$: previewDate = value ? nextRun(value) : null;

	function formatPreview(d: Date | null): string {
		if (d === null) return 'Invalid or unsupported expression';
		// Format in local time: "Mon 2026-06-01 at 09:00"
		const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const dow_ = days[d.getDay()];
		const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
		const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
		return `${dow_} ${date} at ${time} (local time)`;
	}

	// ---------------------------------------------------------------------------
	// Select options
	// ---------------------------------------------------------------------------

	const DOW_OPTIONS = [
		{ value: 0, label: 'Sunday' },
		{ value: 1, label: 'Monday' },
		{ value: 2, label: 'Tuesday' },
		{ value: 3, label: 'Wednesday' },
		{ value: 4, label: 'Thursday' },
		{ value: 5, label: 'Friday' },
		{ value: 6, label: 'Saturday' }
	];

	// Limit dom to 1–28 to guarantee the day exists in all months.
	const DOM_OPTIONS = Array.from({ length: 28 }, (_, i) => ({ value: i + 1, label: String(i + 1) }));

	const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => ({
		value: i,
		label: String(i).padStart(2, '0')
	}));

	const MINUTE_OPTIONS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55].map((m) => ({
		value: m,
		label: String(m).padStart(2, '0')
	}));
</script>

<div class="cron-input" class:cron-input--error={!!error}>
	<!-- Preset selector -->
	<div class="cron-row">
		<label class="cron-label" for="cron-preset">Frequency</label>
		<select
			id="cron-preset"
			class="cron-select"
			bind:value={preset}
			{disabled}
			aria-label="Frequency"
		>
			<option value="daily">Daily</option>
			<option value="weekly">Weekly</option>
			<option value="monthly">Monthly</option>
			<option value="custom">Custom (cron expression)</option>
		</select>
	</div>

	<!-- Time (hour + minute) — shown for all non-custom presets -->
	{#if preset !== 'custom'}
		<div class="cron-row">
			<label class="cron-label" for="cron-hour">Time</label>
			<div class="cron-time-group">
				<select
					id="cron-hour"
					class="cron-select cron-select--narrow"
					bind:value={hour}
					{disabled}
					aria-label="Hour"
				>
					{#each HOUR_OPTIONS as opt (opt.value)}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>
				<span class="cron-colon">:</span>
				<select
					id="cron-minute"
					class="cron-select cron-select--narrow"
					bind:value={minute}
					{disabled}
					aria-label="Minute"
				>
					{#each MINUTE_OPTIONS as opt (opt.value)}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>
			</div>
		</div>
	{/if}

	<!-- Day-of-week — Weekly only -->
	{#if preset === 'weekly'}
		<div class="cron-row">
			<label class="cron-label" for="cron-dow">Day of week</label>
			<select
				id="cron-dow"
				class="cron-select"
				bind:value={dow}
				{disabled}
				aria-label="Day of week"
			>
				{#each DOW_OPTIONS as opt (opt.value)}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</select>
		</div>
	{/if}

	<!-- Day-of-month — Monthly only -->
	{#if preset === 'monthly'}
		<div class="cron-row">
			<label class="cron-label" for="cron-dom">Day of month</label>
			<select
				id="cron-dom"
				class="cron-select cron-select--narrow"
				bind:value={dom}
				{disabled}
				aria-label="Day of month"
			>
				{#each DOM_OPTIONS as opt (opt.value)}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</select>
			<span class="cron-dom-note">(limited to 1–28 to work across all months)</span>
		</div>
	{/if}

	<!-- Custom cron expression input -->
	{#if preset === 'custom'}
		<div class="cron-row">
			<label class="cron-label" for="cron-raw">Cron expression</label>
			<input
				id="cron-raw"
				type="text"
				class="cron-input-text"
				class:cron-input-text--error={!!error}
				bind:value={rawCron}
				{disabled}
				placeholder="e.g. 0 9 * * 1"
				aria-label="Cron expression (5 fields: minute hour dom month dow)"
				aria-describedby={error ? 'cron-error' : 'cron-hint'}
			/>
			<p id="cron-hint" class="cron-hint">5 fields: minute hour day-of-month month day-of-week</p>
		</div>
	{/if}

	<!-- Compiled expression display (non-custom) -->
	{#if preset !== 'custom' && value}
		<div class="cron-expr-display">
			<span class="cron-expr-label">Expression:</span>
			<code class="cron-expr-code">{value}</code>
		</div>
	{/if}

	<!-- Server-side error message (e.g. 422) -->
	{#if error}
		<p id="cron-error" class="cron-error" role="alert">{error}</p>
	{/if}

	<!-- Next-run preview -->
	<div class="cron-preview" aria-live="polite">
		{#if value}
			<span class="cron-preview-label">Next run:</span>
			<span
				class="cron-preview-value"
				class:cron-preview-value--invalid={previewDate === null}
			>
				{formatPreview(previewDate)}
			</span>
		{:else}
			<span class="cron-preview-value cron-preview-value--invalid">No expression entered</span>
		{/if}
	</div>
</div>

<style>
	.cron-input {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-3);
	}

	.cron-row {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}

	.cron-label {
		font-size: 13px;
		font-weight: 500;
		color: var(--lq-text-primary);
	}

	.cron-select {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		color: var(--lq-text-primary);
		width: 100%;
		box-sizing: border-box;
		transition: border-color 0.15s ease;
	}

	.cron-select:focus {
		outline: none;
		border-color: var(--lq-accent);
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}

	.cron-select:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.cron-select--narrow {
		width: auto;
		min-width: 4rem;
	}

	.cron-time-group {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
	}

	.cron-colon {
		font-weight: 600;
		color: var(--lq-text-secondary);
	}

	.cron-dom-note {
		font-size: 11px;
		color: var(--lq-text-tertiary);
		margin: 0;
		margin-top: 2px;
	}

	.cron-input-text {
		background: var(--lq-inset);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 14px;
		font-family: var(--font-mono, monospace);
		color: var(--lq-text-primary);
		width: 100%;
		box-sizing: border-box;
		transition: border-color 0.15s ease;
	}

	.cron-input-text:focus {
		outline: none;
		border-color: var(--lq-accent);
		box-shadow: 0 0 0 2px var(--lq-accent-soft);
	}

	.cron-input-text:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.cron-input-text--error {
		border-color: var(--lq-error);
	}

	.cron-input-text--error:focus {
		box-shadow: 0 0 0 2px var(--lq-error-soft);
	}

	.cron-hint {
		font-size: 11px;
		color: var(--lq-text-tertiary);
		margin: 0;
	}

	.cron-expr-display {
		display: flex;
		align-items: center;
		gap: var(--lq-space-2);
		font-size: 13px;
	}

	.cron-expr-label {
		color: var(--lq-text-secondary);
	}

	.cron-expr-code {
		font-family: var(--font-mono, monospace);
		font-size: 13px;
		background: var(--lq-inset);
		padding: 1px 6px;
		border-radius: 4px;
		border: 1px solid var(--lq-border);
		color: var(--lq-text-primary);
	}

	.cron-error {
		font-size: 12px;
		color: var(--lq-error);
		background: var(--lq-error-soft, rgba(176, 0, 0, 0.06));
		border: 1px solid var(--lq-error-border, var(--lq-error));
		border-radius: var(--lq-radius);
		padding: var(--lq-space-2) var(--lq-space-3);
		margin: 0;
	}

	.cron-preview {
		display: flex;
		align-items: baseline;
		gap: var(--lq-space-2);
		font-size: 13px;
		padding: var(--lq-space-2) var(--lq-space-3);
		background: var(--lq-surface, rgba(0, 0, 0, 0.02));
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
	}

	.cron-preview-label {
		color: var(--lq-text-secondary);
		white-space: nowrap;
		font-weight: 500;
	}

	.cron-preview-value {
		color: var(--lq-text-primary);
	}

	.cron-preview-value--invalid {
		color: var(--lq-text-tertiary);
		font-style: italic;
	}
</style>
