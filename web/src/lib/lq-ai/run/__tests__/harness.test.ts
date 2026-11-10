/**
 * New harness as an entry in the model picker (ADR 0038 D1): which profile the
 * server offers, when the entry can be chosen, and where Send goes for a chat whose
 * model it is. The recorded availability reads are the input.
 */
import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';

import ModelPicker from '../../components/ModelPicker.svelte';
import RunModePanel from '../../components/run/RunModePanel.svelte';
import type { RunProfilesRead } from '../../api/orchestration';
import {
	HARNESS_CHECKING,
	NEW_HARNESS_ID,
	NEW_HARNESS_LABEL,
	composerMode,
	harnessOption,
	proposeBlocker,
	unavailableReason
} from '../composer';
import { profiles } from './fixtures';

function markup(component: unknown, props: Record<string, unknown>): string {
	return render(component as never, { props: props as never }).body;
}

/** The same read with every profile unavailable for one reason. */
function unavailable(read: RunProfilesRead, reason: string, text: string | null): RunProfilesRead {
	return {
		...read,
		profiles: read.profiles.map((profile) => ({
			...profile,
			available: false,
			reason,
			reason_text: text
		}))
	};
}

describe('which profile is New harness', () => {
	it('is the one the server names, never one picked here', () => {
		const read = profiles('documents');
		const option = harnessOption(read);
		expect(option?.profile.profile).toBe(read.composer_profile);
		expect(option?.resolves).toBe(option?.profile.model);
		expect(option?.disabledReason).toBeNull();
	});

	it('offers nothing when the server names none, though profiles are listed', () => {
		const read = profiles('documents');
		expect(harnessOption({ ...read, composer_profile: null })).toBeNull();
		expect(harnessOption({ ...read, composer_profile: undefined })).toBeNull();
		expect(harnessOption({ ...read, composer_profile: 'not_in_the_list' })).toBeNull();
		expect(harnessOption({ ...read, profiles: [] })).toBeNull();
		expect(harnessOption(null)).toBeNull();
	});

	it('does not offer the fictional fixture profile, available or not', () => {
		for (const name of ['available', 'documents', 'active-run', 'no-project', 'uncertain-run']) {
			expect(harnessOption(profiles(name))?.profile.profile, name).not.toBe('model_demo_v1');
		}
	});

	it('shows no pinned model for a blank one', () => {
		const read = profiles('documents');
		const blank = {
			...read,
			profiles: read.profiles.map((profile) => ({ ...profile, model: '   ' }))
		};
		expect(harnessOption(blank)?.resolves).toBeNull();
	});
});

describe('when the entry can be chosen', () => {
	it('is disabled, with the reason, where the operator has not enabled it', () => {
		const option = harnessOption(profiles('available'));
		expect(option?.profile.available).toBe(false);
		expect(option?.disabledReason).toBe(unavailableReason(option!.profile));
		expect(option?.disabledReason).toBeTruthy();
	});

	it('gives a reason for a code this client does not know and the server did not word', () => {
		const option = harnessOption(unavailable(profiles('documents'), 'a_new_reason', null));
		expect(option?.disabledReason).toBe('This profile is unavailable right now.');
	});

	it('stays choosable while another run is active: that blocks Send, not the entry', () => {
		const waiting = unavailable(
			profiles('documents'),
			'active_run',
			'Another run of yours is still active.'
		);
		const option = harnessOption(waiting);
		expect(option?.disabledReason).toBeNull();
		const mode = composerMode({
			storedModelId: NEW_HARNESS_ID,
			read: waiting,
			checked: true,
			error: null
		});
		expect(mode).toMatchObject({ kind: 'harness', state: 'ready' });
		expect(proposeBlocker({ profile: option!.profile, goal: 'A request', selectedCount: 1 })).toBe(
			'Another run of yours is still active.'
		);
	});
});

describe('where Send goes for a chat', () => {
	const usable = profiles('documents');
	const disabled = profiles('available');

	it('is an ordinary model unless New harness is the chat’s model', () => {
		for (const storedModelId of ['smart', 'anthropic/some-model', null]) {
			for (const read of [usable, disabled, null]) {
				expect(
					composerMode({ storedModelId, read, checked: read !== null, error: null }),
					String(storedModelId)
				).toEqual({ kind: 'model' });
			}
		}
	});

	it('is a run when New harness is the chat’s model and it can be used here', () => {
		const mode = composerMode({
			storedModelId: NEW_HARNESS_ID,
			read: usable,
			checked: true,
			error: null
		});
		expect(mode.kind).toBe('harness');
		expect(mode).toMatchObject({ state: 'ready' });
		if (mode.kind === 'harness' && mode.state === 'ready') {
			expect(mode.option.profile.profile).toBe(usable.composer_profile);
		}
	});

	// The cases below are the ones that must never fall through to another model:
	// the person chose New harness, so nothing else may answer in its place.
	it('waits, and says it is checking, until the availability read has returned', () => {
		const mode = composerMode({
			storedModelId: NEW_HARNESS_ID,
			read: null,
			checked: false,
			error: null
		});
		expect(mode).toEqual({
			kind: 'harness',
			state: 'checking',
			option: null,
			reason: HARNESS_CHECKING
		});
	});

	it('waits, with the reason, when the read failed', () => {
		const mode = composerMode({
			storedModelId: NEW_HARNESS_ID,
			read: null,
			checked: true,
			error: 'The network is down'
		});
		expect(mode).toMatchObject({ kind: 'harness', state: 'unavailable', option: null });
		expect(mode.kind === 'harness' && mode.state === 'unavailable' && mode.reason).toContain(
			'New harness could not be checked: The network is down. Choose another model'
		);
		expect(mode.kind === 'harness' && mode.state === 'unavailable' && mode.reason).toContain(
			'Choose another model'
		);
	});

	it('waits when the server has no such read, or names no profile', () => {
		for (const read of [null, { ...usable, composer_profile: null }]) {
			const mode = composerMode({
				storedModelId: NEW_HARNESS_ID,
				read,
				checked: true,
				error: null
			});
			expect(mode).toMatchObject({ kind: 'harness', state: 'unavailable', option: null });
		}
	});

	it('waits, with the server’s reason, where New harness cannot be used', () => {
		const mode = composerMode({
			storedModelId: NEW_HARNESS_ID,
			read: disabled,
			checked: true,
			error: null
		});
		expect(mode).toMatchObject({ kind: 'harness', state: 'unavailable' });
		if (mode.kind === 'harness' && mode.state === 'unavailable') {
			expect(mode.option?.disabledReason).toBeTruthy();
			expect(mode.reason).toContain(mode.option!.disabledReason!);
			expect(mode.reason).toContain('Choose another model');
		}
	});

	it('still waits after a route failure that arrives mid-conversation', () => {
		const down = unavailable(usable, 'route_unavailable', 'The model route is unavailable.');
		const mode = composerMode({
			storedModelId: NEW_HARNESS_ID,
			read: down,
			checked: true,
			error: null
		});
		expect(mode).toMatchObject({ kind: 'harness', state: 'unavailable' });
	});

	it('uses an id no gateway model or alias can have', () => {
		expect(NEW_HARNESS_ID).toBe('lq-ai:new-harness');
		expect(NEW_HARNESS_LABEL).toBe('New harness');
	});
});

describe('the picker’s button', () => {
	const harness = {
		id: NEW_HARNESS_ID,
		label: NEW_HARNESS_LABEL,
		resolves: 'ollama-local/some-model',
		disabledReason: null
	};

	it('names New harness, marks it experimental and shows its pinned model when chosen', () => {
		const html = markup(ModelPicker, { selectedId: NEW_HARNESS_ID, harness });
		expect(html).toContain('New harness');
		expect(html).toContain('experimental');
		expect(html).toContain('ollama-local/some-model');
	});

	it('shows the ordinary model when one is chosen, with nothing about New harness', () => {
		const html = markup(ModelPicker, {
			selectedId: 'smart',
			harness,
			models: {
				object: 'list',
				data: [{ id: 'smart', object: 'model', owned_by: 'lq-ai', lq_ai_kind: 'alias' }]
			}
		});
		expect(html).toContain('smart');
		expect(html).not.toContain('New harness');
		expect(html).not.toContain('experimental');
	});

	it('still names New harness while it is being checked, with no model to show yet', () => {
		const html = markup(ModelPicker, {
			selectedId: NEW_HARNESS_ID,
			harness: { ...harness, resolves: null, disabledReason: HARNESS_CHECKING }
		});
		expect(html).toContain('New harness');
		expect(html).not.toContain('→');
	});
});

describe('the picker’s list', () => {
	const models = {
		object: 'list',
		data: [
			{ id: 'smart', object: 'model', owned_by: 'lq-ai', lq_ai_kind: 'alias' },
			{ id: 'ollama-local/some-model', object: 'model', owned_by: 'ollama-local' }
		]
	};
	const harness = {
		id: NEW_HARNESS_ID,
		label: NEW_HARNESS_LABEL,
		resolves: 'ollama-local/some-model',
		disabledReason: null
	};
	const ROW = 'data-testid="lq-ai-model-picker-harness"';
	const OPTION = 'data-testid="lq-ai-model-picker-option"';

	it('puts New harness first, above every model, under an Experimental heading', () => {
		const html = markup(ModelPicker, { open: true, selectedId: 'smart', harness, models });
		expect(html).toContain(ROW);
		expect(html).toContain(OPTION);
		expect(html.indexOf(ROW)).toBeLessThan(html.indexOf(OPTION));
		expect(html.indexOf('Experimental')).toBeLessThan(html.indexOf('Aliases'));
		expect(html.indexOf('Experimental')).toBeLessThan(html.indexOf(ROW));
	});

	it('lists only models where the server offers no New harness', () => {
		const html = markup(ModelPicker, { open: true, selectedId: 'smart', harness: null, models });
		expect(html).not.toContain(ROW);
		expect(html).not.toContain('Experimental');
		expect(html).toContain(OPTION);
	});

	it('says why the row cannot be chosen, and keeps it reachable to read the reason', () => {
		const reason = 'Turn on Autonomous in your settings to start a run.';
		const html = markup(ModelPicker, {
			open: true,
			selectedId: 'smart',
			harness: { ...harness, disabledReason: reason },
			models
		});
		const row = html.slice(html.indexOf(ROW) - 400, html.indexOf(ROW) + 200);
		expect(html).toContain(reason);
		expect(row).toContain('aria-disabled="true"');
		// The reason is text inside the row's own button, so it is part of what the button is
		// called. Describing the button by that same text would have it read twice.
		expect(html).not.toContain('aria-describedby');
		const button = html.slice(html.indexOf(ROW), html.indexOf('</button>', html.indexOf(ROW)));
		expect(button).toContain(reason);
		// The `disabled` attribute would take the row out of the tab order, and a
		// keyboard or screen-reader user could then never read the reason.
		expect(row).not.toMatch(/\sdisabled(=|\s|>)/);
	});

	it('says no models are available even when the New harness row is shown', () => {
		const empty = { object: 'list', data: [] };
		const withRow = markup(ModelPicker, { open: true, harness, models: empty });
		expect(withRow).toContain(ROW);
		expect(withRow).toContain('No models available');
		const without = markup(ModelPicker, { open: true, harness: null, models: empty });
		expect(without).not.toContain(ROW);
		expect(without).toContain('No models available');
	});
});

describe('the strip above the composer', () => {
	const profile = harnessOption(profiles('documents'))!.profile;
	const html = markup(RunModePanel, { profile });

	it('says what a request reads, the cap, and what Send does', () => {
		expect(html).toContain(profile.reads);
		expect(html).toMatch(/total cap \$/);
		expect(html).toContain(profile.planning_notice.slice(0, 40));
		expect(html).toContain('Limits and tools');
	});

	it('has no control for leaving: that is the model picker’s', () => {
		expect(html).not.toMatch(/<button/);
		expect(html).not.toContain('Leave run mode');
	});
});
