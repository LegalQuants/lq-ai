<script lang="ts">
	import { onMount } from 'svelte';
	import { preferences, setPreference, initPreferences } from '$lib/lq-ai/stores/preferences';
	import SettingsToggleGroup from '$lib/lq-ai/components/SettingsToggleGroup.svelte';
	import type { FeaturedTools, WorkspaceLayout, TrustPills, ProvenancePills } from '$lib/lq-ai/types';
	import {
		AUTO_ENHANCE_STORAGE_KEY,
		readAutoEnhance,
		writeAutoEnhance
	} from '$lib/lq-ai/preferences/autoEnhance';
	import {
		CAPTURE_AFFORDANCE_STORAGE_KEY,
		captureAffordanceInline,
		readCaptureAffordanceInline
	} from '$lib/lq-ai/preferences/capture-affordance';
	import LqText from '$lib/lq-ai/components/shared/LqText.svelte';
	import LqTitle from '$lib/lq-ai/components/shared/LqTitle.svelte';

	let autoEnhance = false;
	let captureInline = true;

	onMount(() => {
		initPreferences();
		autoEnhance = readAutoEnhance();
		captureInline = readCaptureAffordanceInline();
	});

	function toggleAutoEnhance(): void {
		autoEnhance = !autoEnhance;
		writeAutoEnhance(autoEnhance);
	}

	function toggleCaptureInline(): void {
		captureInline = !captureInline;
		// Use the writable wrapper's setValue so subscribers in MessageBubble
		// (via $captureAffordanceInline auto-subscribe) see the change live —
		// the plain write* function only touches localStorage and doesn't
		// broadcast to the in-memory store. (Wave D.2 final-review fix.)
		captureAffordanceInline.setValue(captureInline);
	}
</script>

<LqTitle order={2} size="16" weight="semibold" tone="primary" style="margin-bottom: var(--lq-space-4);">Appearance</LqTitle>
<LqText as="p" size="14" tone="secondary" style="margin-bottom: var(--lq-space-6);">
	Tune how LQ.AI presents itself. Brave choices are on by default; you can dial them back if you
	want less ceremony.
</LqText>

<SettingsToggleGroup
	label="Featured tools"
	description="Where Enhance Prompt, Skill Creator, and the launcher live."
	value={$preferences.featured_tools}
	options={[
		{
			value: 'prominent',
			label: 'Prominent cards on dashboard',
			description: 'Featured cards with descriptions, plus ⌘K launcher.'
		},
		{
			value: 'inline',
			label: 'Inline toolbar only',
			description: 'Small button row on every composer; less ceremony.'
		}
	]}
	onChange={(v) => setPreference('featured_tools', v as FeaturedTools)}
/>

<SettingsToggleGroup
	label="Workspace layout"
	description="How matter views compose (Wave C)."
	value={$preferences.workspace_layout}
	options={[
		{
			value: 'three_pane',
			label: 'Three panes',
			description: 'Matter rail · chat · outputs panel (default).'
		},
		{
			value: 'two_pane',
			label: 'Two panes',
			description: 'Chat · outputs panel; matter rail collapsed.'
		},
		{
			value: 'one_pane',
			label: 'Single pane',
			description: 'Chat only; docs open in a modal.'
		}
	]}
	onChange={(v) => setPreference('workspace_layout', v as WorkspaceLayout)}
/>

<SettingsToggleGroup
	label="Trust pills"
	description="The ambient indicators in the top bar."
	value={$preferences.trust_pills}
	options={[
		{
			value: 'labels',
			label: 'Labels',
			description: '"self-hosted" — full label on the pill.'
		},
		{
			value: 'dots',
			label: 'Dots',
			description: 'Just the dot; label appears on hover.'
		}
	]}
	onChange={(v) => setPreference('trust_pills', v as TrustPills)}
/>

<SettingsToggleGroup
	label="Provenance pills"
	description="The per-message skill/tier/provider/audit row (Wave D)."
	value={$preferences.provenance_pills}
	options={[
		{
			value: 'always',
			label: 'Always shown',
			description: 'Pills under every AI reply.'
		},
		{
			value: 'collapsed',
			label: 'Collapsed; expand on hover',
			description: 'Single "details" affordance per reply.'
		}
	]}
	onChange={(v) => setPreference('provenance_pills', v as ProvenancePills)}
/>

<!--
	§7.1 — Auto-enhance on send. Frontend-only preference (localStorage,
	key=AUTO_ENHANCE_STORAGE_KEY) so it doesn't drift the backend Preferences
	contract. The send-side wiring (call enhance() before sendMessage when
	enabled) lands in v1.1+ once UX is settled for the implicit-confirm path.
-->
<div class="lq-auto-enhance" style="margin-top: var(--lq-space-6);">
	<LqText as="label" size="14" tone="primary" style="display: flex; gap: var(--lq-space-2); align-items: flex-start;">
		<input
			type="checkbox"
			checked={autoEnhance}
			on:change={toggleAutoEnhance}
			data-testid="lq-ai-auto-enhance-toggle"
		/>
		<span>
			<strong>Auto-enhance prompts on send</strong>
			<span style="display: block; color: var(--lq-text-secondary); font-size: 12px;">
				Run Enhance Prompt automatically before each send (preview-and-confirm UX
				ships in v1.1+; setting is stored locally).
			</span>
		</span>
	</LqText>
</div>

<!--
	Wave D.2 — Capture-as-skill affordance placement. Frontend-only preference
	(localStorage, key=CAPTURE_AFFORDANCE_STORAGE_KEY) for the same reasons as
	auto-enhance: the server Preferences schema is a strict 5-field contract
	and adding a column would require an OpenAPI update + migration churn for
	a per-device UX preference with no audit/policy implications. See Task 5.1
	(commits 8ce9897 + 64ab0d9) for the storage layer + MessageBubble wiring.
-->
<div class="lq-capture-affordance" style="margin-top: var(--lq-space-6);">
	<LqText as="label" size="14" tone="primary" style="display: flex; gap: var(--lq-space-2); align-items: flex-start;">
		<input
			type="checkbox"
			checked={captureInline}
			on:change={toggleCaptureInline}
			data-testid="lq-ai-capture-affordance-toggle"
		/>
		<span>
			<strong>Skill capture button</strong>
			<span style="display: block; color: var(--lq-text-secondary); font-size: 12px;">
				Show Capture-as-skill inline on every AI message. When off, the action
				stays in the message's overflow (More actions) menu.
			</span>
		</span>
	</LqText>
</div>
