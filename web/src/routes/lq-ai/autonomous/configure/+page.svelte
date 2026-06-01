<script lang="ts">
	/**
	 * /lq-ai/autonomous/configure — Configure / education sub-tab (§4.2).
	 *
	 * Static educational content. Explains the autonomous layer's Off/On state,
	 * the difference between schedules and watches, Run-now, where results land,
	 * and the safety bounds (R4 cost cap, R5 halt + idle watchdog, R6 per-phase
	 * tool limits). The toggle itself lives in Settings → Autonomous; this page
	 * only orients and links there.
	 *
	 * Honesty: describes ONLY what exists. Run-now is the only one-off "test"
	 * mechanism — there is no custom-task authoring or separate test harness.
	 */
</script>

<div class="configure-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Configure autonomous</h1>
		<p class="page-intro">
			The autonomous layer lets LQVern run skills and playbooks on its own — on a schedule, when a
			document arrives, or once on demand. It is opt-in and off by default. This page explains how
			the pieces fit together and where the results land.
		</p>
	</header>

	<section class="config-section">
		<h2 class="section-title">On / Off</h2>
		<p class="section-body">
			Autonomous mode is off until you turn it on. Enable it in
			<a class="inline-link" href="/lq-ai/settings/autonomous">Settings → Autonomous</a>. Turning
			it off stops new runs from starting, but you keep every receipt and can still halt runs that
			are already in flight from the Sessions tab.
		</p>
	</section>

	<section class="config-section">
		<h2 class="section-title">Schedules</h2>
		<p class="section-body">
			A schedule is a cron-driven run of a skill or playbook you choose, optionally scoped to a
			knowledge base and/or a matter, with a per-run cost cap. It fires on its cadence until you
			disable or delete it.
		</p>
	</section>

	<section class="config-section">
		<h2 class="section-title">Watches</h2>
		<p class="section-body">
			A watch is a run triggered when a document is attached to a knowledge base you choose. The
			knowledge base is the trigger; the assigned skill or playbook runs against the new arrival.
		</p>
	</section>

	<section class="config-section">
		<h2 class="section-title">Run now</h2>
		<p class="section-body">
			Run now executes a skill or playbook once, on demand, from the
			<a class="inline-link" href="/lq-ai/autonomous">Sessions</a> tab. Use it to see the result
			before arming a schedule or a watch.
		</p>
	</section>

	<section class="config-section">
		<h2 class="section-title">Where results land</h2>
		<p class="section-body">
			Every run shows up in <a class="inline-link" href="/lq-ai/autonomous">Sessions</a> with its
			inspectable receipt. Depending on what the run produces, output also lands in
			<a class="inline-link" href="/lq-ai/autonomous/memory">Memory</a>,
			<a class="inline-link" href="/lq-ai/autonomous/precedents">Precedents</a>,
			<a class="inline-link" href="/lq-ai/autonomous/proposals">Proposals</a>, and
			<a class="inline-link" href="/lq-ai/autonomous/notifications">Notifications</a>.
		</p>
	</section>

	<section class="config-section">
		<h2 class="section-title">Safety</h2>
		<p class="section-body">
			Every run is bounded. A cost cap stops it before it can overspend (R4). An external halt and
			an idle watchdog can end a run that goes wrong or stalls (R5). Per-phase tool limits cap how
			much any single phase can do (R6). And every run produces a receipt you can inspect.
		</p>
	</section>

	<p class="page-footer">
		Ready to start? Turn the layer on in
		<a class="inline-link" href="/lq-ai/settings/autonomous">Settings → Autonomous</a>, then use
		<strong>Run now</strong> on the Sessions tab.
	</p>
</div>

<style>
	.configure-page {
		padding: var(--lq-space-5);
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-5);
		max-width: 60rem;
	}

	.page-header {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.page-intro {
		color: var(--lq-text-secondary);
		font-size: 14px;
		line-height: 1.5;
	}

	.config-section {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
	}

	.section-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--lq-text-primary);
		margin: 0;
	}

	.section-body {
		color: var(--lq-text-secondary);
		font-size: 14px;
		line-height: 1.5;
		margin: 0;
	}

	.inline-link {
		color: var(--lq-accent);
		text-decoration: none;
	}

	.inline-link:hover {
		text-decoration: underline;
	}

	.page-footer {
		color: var(--lq-text-secondary);
		font-size: 14px;
		line-height: 1.5;
		margin: 0;
		padding-top: var(--lq-space-3);
		border-top: 1px solid var(--lq-border);
	}
</style>
