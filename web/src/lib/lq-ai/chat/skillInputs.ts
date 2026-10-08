/** Pure helpers for the composer's skill-input form. No Svelte, no network. */

import type { SkillInputDef, SkillInputs } from '../types';

/**
 * Flatten `GET /skills/{name}/inputs` into the list the form renders:
 * required inputs first, then optional, each carrying its `required` flag.
 * A name declared twice keeps its first entry — the form keys fields and
 * values by name, so a second one could never hold a value of its own.
 */
export function flattenSkillInputs(inputs: SkillInputs): SkillInputDef[] {
	const seen = new Set<string>();
	return [
		...inputs.required.map((def) => ({ ...def, required: true })),
		...inputs.optional.map((def) => ({ ...def, required: false }))
	].filter((def) => {
		if (seen.has(def.name)) return false;
		seen.add(def.name);
		return true;
	});
}

/** A document-typed input: satisfied by an attached file as well as by pasted text. */
export function isDocumentInput(def: SkillInputDef): boolean {
	return def.type === 'document' || def.type === 'file';
}

/**
 * Options for an enum input. The api schema names the list `enum`; the
 * authoring guide writes `values`, which the api passes through untouched.
 */
export function enumOptions(def: SkillInputDef): string[] {
	if (def.type !== 'enum') return [];
	return (def.enum ?? def.values ?? []).map(String);
}

/**
 * Whether the form offers this input. `structured` inputs are filled by the
 * app (enhance-prompt's `attached_skills`, `chat_history`), not typed by a
 * person, so optional ones are left out; a required one still renders so the
 * user is never stuck with an input they cannot supply.
 */
export function isFormInput(def: SkillInputDef): boolean {
	return def.type !== 'structured' || def.required === true;
}

/** DOM id for one skill's field; scoped by skill because attached skills share input names. */
export function skillInputFieldId(skillName: string, inputName: string): string {
	return `lq-ai-skill-input-${skillName}-${inputName}`;
}

/**
 * The value bound to a document input the user left empty while files are
 * attached. The file text itself travels on the separate `file_ids` channel
 * (the api injects it under a `### {filename}` heading); this names the same
 * files so the model can tie the input to that block.
 */
export function attachedDocumentsValue(fileNames: string[]): string {
	return `Attached file(s): ${fileNames.join(', ')}`;
}

/**
 * Placeholder for a document input's paste box. Only a required document
 * input is met by attached files, so an optional one must not suggest
 * attaching a file.
 */
export function documentInputPlaceholder(def: SkillInputDef, readyFileNames: string[]): string {
	if (def.required !== true) {
		return 'Paste the text here. Attached files are not matched to this input.';
	}
	return readyFileNames.length > 0
		? 'Paste text here to use it instead of the attached file(s).'
		: 'Attach the file with + Files, or paste its text here.';
}

function isBlank(value: unknown): boolean {
	if (value === undefined || value === null) return true;
	if (typeof value === 'string') return value.trim() === '';
	// A cleared number field parses to NaN.
	return typeof value === 'number' && Number.isNaN(value);
}

export interface MissingSkillInputs {
	skill: string;
	inputs: SkillInputDef[];
}

export interface ResolvedSkillInputs {
	/** The `skill_inputs` payload; undefined when there is nothing to send. */
	skillInputs: Record<string, Record<string, unknown>> | undefined;
	/** Required inputs with no value, per skill, in attach order. */
	missing: MissingSkillInputs[];
}

/**
 * Build the `skill_inputs` payload for a send and report what is still missing.
 *
 * Per input, in order: the value the user entered; else, if they never
 * touched the field, its declared default; else, for a required document
 * input, the names of the attached files that are ready; else, for a required
 * checkbox, `false` (what an unticked box shows). Blank values are dropped
 * rather than sent — the gateway treats `""` as missing
 * (`gateway/app/skills/assembler.py`).
 */
export function resolveSkillInputsForSend(
	skillNames: string[],
	inputDefs: Record<string, SkillInputDef[] | undefined>,
	values: Record<string, Record<string, unknown>>,
	readyFileNames: string[]
): ResolvedSkillInputs {
	const skillInputs: Record<string, Record<string, unknown>> = {};
	const missing: MissingSkillInputs[] = [];

	for (const skill of skillNames) {
		const entered = values[skill] ?? {};
		const bound: Record<string, unknown> = {};
		for (const [key, value] of Object.entries(entered)) {
			if (!isBlank(value)) bound[key] = value;
		}

		const stillMissing: SkillInputDef[] = [];
		for (const def of inputDefs[skill] ?? []) {
			if (def.name in bound) continue;
			// A field the user emptied stays empty: the form shows it blank,
			// so the default must not come back behind their back.
			const untouched = !(def.name in entered);
			if (untouched && !isBlank(def.default)) {
				bound[def.name] = def.default;
			} else if (def.required && isDocumentInput(def) && readyFileNames.length > 0) {
				bound[def.name] = attachedDocumentsValue(readyFileNames);
			} else if (def.required && def.type === 'boolean') {
				bound[def.name] = false;
			} else if (def.required) {
				stillMissing.push(def);
			}
		}

		if (Object.keys(bound).length > 0) skillInputs[skill] = bound;
		if (stillMissing.length > 0) missing.push({ skill, inputs: stillMissing });
	}

	return {
		skillInputs: Object.keys(skillInputs).length > 0 ? skillInputs : undefined,
		missing
	};
}

/**
 * The composer's send-blocked message for one skill with missing inputs.
 * `processingFileNames` are attached files still being ingested: they cannot
 * stand in for a document yet, and saying so beats "attach a file".
 */
export function missingInputsMessage(
	missing: MissingSkillInputs,
	skillTitle?: string,
	processingFileNames: string[] = []
): string {
	const names = missing.inputs.map((def) => def.name).join(', ');
	let hint = '';
	if (missing.inputs.some(isDocumentInput)) {
		hint =
			processingFileNames.length > 0
				? ` ${processingFileNames.join(', ')} is still processing — wait for it to finish, or paste the document text.`
				: ' Attach a file or paste the document text.';
	}
	return `Skill "${skillTitle ?? missing.skill}" is missing required inputs: ${names}.${hint}`;
}

export interface UnloadedSkillInputs {
	skill: string;
	/** True when the schema fetch failed; false while it is still in flight. */
	loadFailed: boolean;
}

/**
 * The first attached skill whose input schema is not on hand, or null when
 * every schema has loaded. The send is held on it: without the schema the
 * composer cannot tell which inputs are required, and the gateway would
 * refuse the turn. A skill that declares no inputs loads as an empty list
 * and is not held.
 */
export function firstUnloadedSkillInputs(
	skillNames: string[],
	inputDefs: Record<string, SkillInputDef[] | undefined>,
	failedSkillNames: string[]
): UnloadedSkillInputs | null {
	const skill = skillNames.find((name) => !inputDefs[name]);
	if (skill === undefined) return null;
	return { skill, loadFailed: failedSkillNames.includes(skill) };
}

/** The composer's send-blocked message for a skill whose input schema is not on hand. */
export function skillInputsUnavailableMessage(skillTitle: string, loadFailed: boolean): string {
	return loadFailed
		? `Could not load the inputs for skill "${skillTitle}". Retry it in the Skills panel, or detach it.`
		: `Skill "${skillTitle}" is still loading. Try again in a moment.`;
}
