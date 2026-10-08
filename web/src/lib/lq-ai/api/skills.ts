/**
 * /api/v1/skills — list + detail.
 *
 * The detail call's response carries `content_yaml` (frontmatter); the input
 * form needs the parsed `inputs` block. We parse it client-side via a small
 * YAML-subset parser keyed only at the keys the skill-authoring guide
 * documents (`inputs:` followed by a list of mappings).
 *
 * If the upstream backend later surfaces parsed `inputs` directly on the
 * Skill payload, this client adopts that and skips the local parse.
 */
import { apiRequest } from './client';
import type {
	Skill,
	SkillAutocompleteResponse,
	SkillInputDef,
	SkillInputs,
	SkillSummary
} from '../types';

/** GET /api/v1/skills — summary list. */
export async function listSkills(scope?: 'builtin' | 'user' | 'team'): Promise<SkillSummary[]> {
	const qs = scope ? `?scope=${encodeURIComponent(scope)}` : '';
	return apiRequest<SkillSummary[]>(`/skills${qs}`);
}

/** GET /api/v1/skills/{name}/inputs — canonical input definitions resolved user > team > built-in. */
export async function getInputs(name: string): Promise<SkillInputs> {
	return apiRequest<SkillInputs>(`/skills/${encodeURIComponent(name)}/inputs`);
}

/**
 * GET /api/v1/skills/autocomplete?q=&limit= — Wave D.2 Task 2.5.
 *
 * Lightweight typeahead suggestions for the slash-invocation dropdown
 * and the Skill Creator's "fork from existing" picker. The backend ranks
 * results by slash-alias prefix > slug prefix > title-substring; this
 * client just forwards the query unchanged. ``limit`` defaults to 10
 * (the backend caps at 50).
 */
export async function autocompleteSkills(
	q: string,
	limit: number = 10
): Promise<SkillAutocompleteResponse> {
	const path = `/skills/autocomplete?q=${encodeURIComponent(q)}&limit=${limit}`;
	return apiRequest<SkillAutocompleteResponse>(path);
}

/**
 * GET /api/v1/skills/{name} — full skill payload, with `inputs` parsed
 * from `content_yaml` when the backend doesn't already surface it.
 */
export async function getSkill(name: string): Promise<Skill> {
	const skill = await apiRequest<Skill>(`/skills/${encodeURIComponent(name)}`);
	if (!skill.inputs && skill.content_yaml) {
		skill.inputs = parseInputsFromYaml(skill.content_yaml);
	}
	return skill;
}

/** GET /api/v1/skills/{name}/contents — human-readable source, including on-demand references. */
export async function getSkillContents(name: string): Promise<Skill> {
	const skill = await apiRequest<Skill>(`/skills/${encodeURIComponent(name)}/contents`);
	if (!skill.inputs && skill.content_yaml) {
		skill.inputs = parseInputsFromYaml(skill.content_yaml);
	}
	return skill;
}

// ---------------------------------------------------------------------------
// Frontmatter `inputs:` block parser.
//
// The skill-authoring guide documents the shape:
//
//   inputs:
//     - name: perspective
//       type: enum
//       enum: [recipient, discloser, both]
//       required: true
//       description: ...
//     - name: deal_type
//       type: string
//       default: ""
//       description: ...
//
// The full YAML grammar is overkill here — we only need to extract a list of
// `{name, type, enum, required, description, default}` entries from the
// `inputs:` key. This parser is intentionally minimal and tolerant; if a
// skill's frontmatter doesn't match the supported subset, we return [] and
// the form skips the input form (skill still runs without inputs).
// ---------------------------------------------------------------------------

const KNOWN_TYPES = new Set(['string', 'enum', 'boolean', 'integer']);

interface ParseState {
	lines: string[];
	idx: number;
}

function indentOf(line: string): number {
	let n = 0;
	while (n < line.length && line[n] === ' ') n += 1;
	return n;
}

function stripComment(line: string): string {
	// Conservative comment strip: only `#` outside of quoted strings.
	let inSingle = false;
	let inDouble = false;
	for (let i = 0; i < line.length; i += 1) {
		const ch = line[i];
		if (ch === "'" && !inDouble) inSingle = !inSingle;
		else if (ch === '"' && !inSingle) inDouble = !inDouble;
		else if (ch === '#' && !inSingle && !inDouble) return line.slice(0, i).trimEnd();
	}
	return line;
}

function parseScalar(raw: string): unknown {
	const v = raw.trim();
	if (v === '') return '';
	if (v === 'true') return true;
	if (v === 'false') return false;
	if (v === 'null' || v === '~') return null;
	if (/^-?\d+$/.test(v)) return parseInt(v, 10);
	if (/^-?\d+\.\d+$/.test(v)) return parseFloat(v);
	if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
		return v.slice(1, -1);
	}
	return v;
}

function parseFlowList(raw: string): unknown[] {
	const inner = raw.trim().replace(/^\[/, '').replace(/\]$/, '').trim();
	if (inner === '') return [];
	// Split on commas at depth 0 (no nested brackets in our input shape).
	const parts: string[] = [];
	let buf = '';
	let inSingle = false;
	let inDouble = false;
	for (const ch of inner) {
		if (ch === "'" && !inDouble) inSingle = !inSingle;
		if (ch === '"' && !inSingle) inDouble = !inDouble;
		if (ch === ',' && !inSingle && !inDouble) {
			parts.push(buf);
			buf = '';
		} else {
			buf += ch;
		}
	}
	if (buf.trim() !== '') parts.push(buf);
	return parts.map((p) => parseScalar(p));
}

function findInputsLine(state: ParseState): number {
	// Returns the line index of `inputs:` at indent 0 in the frontmatter, or -1.
	for (let i = 0; i < state.lines.length; i += 1) {
		const line = stripComment(state.lines[i]);
		if (line.match(/^inputs:\s*$/)) {
			return i;
		}
	}
	return -1;
}

/**
 * Parse the `inputs:` list from a frontmatter YAML body. Returns [] when
 * the block is absent or shaped in a way the minimal parser doesn't
 * recognise; the caller treats [] as "this skill has no required inputs."
 */
export function parseInputsFromYaml(yaml: string): SkillInputDef[] {
	const state: ParseState = { lines: yaml.split(/\r?\n/), idx: 0 };
	const start = findInputsLine(state);
	if (start === -1) return [];

	const inputs: SkillInputDef[] = [];
	let current: Partial<SkillInputDef> | null = null;
	const baseIndent = 2; // skills use 2-space indents per the corpus.

	for (let i = start + 1; i < state.lines.length; i += 1) {
		const rawLine = state.lines[i];
		const line = stripComment(rawLine);
		if (line.trim() === '') continue;
		const indent = indentOf(line);
		if (indent === 0) {
			// next top-level key — end of inputs block.
			break;
		}
		if (line.trim().startsWith('- ')) {
			if (current) inputs.push(currentToDef(current));
			current = {};
			const after = line.trim().slice(2).trim();
			if (after) {
				const kv = splitKv(after);
				if (kv) {
					applyKv(current, kv.key, kv.value);
				}
			}
			continue;
		}
		if (current && indent >= baseIndent + 2) {
			const kv = splitKv(line.trim());
			if (kv) {
				applyKv(current, kv.key, kv.value);
			}
		}
	}
	if (current) inputs.push(currentToDef(current));
	return inputs;
}

function splitKv(line: string): { key: string; value: string } | null {
	const colon = line.indexOf(':');
	if (colon === -1) return null;
	const key = line.slice(0, colon).trim();
	const value = line.slice(colon + 1).trim();
	return { key, value };
}

function applyKv(current: Partial<SkillInputDef>, key: string, value: string): void {
	switch (key) {
		case 'name':
			current.name = String(parseScalar(value) ?? '');
			break;
		case 'type': {
			const t = String(parseScalar(value));
			if (KNOWN_TYPES.has(t)) {
				current.type = t as SkillInputDef['type'];
			}
			break;
		}
		case 'required':
			current.required = parseScalar(value) === true;
			break;
		case 'description':
			current.description = String(parseScalar(value) ?? '');
			break;
		case 'enum':
			if (value.startsWith('[')) {
				current.enum = parseFlowList(value).map(String);
			}
			break;
		case 'default':
			current.default = parseScalar(value);
			break;
		default:
			// ignore unknown keys
			break;
	}
}

function currentToDef(p: Partial<SkillInputDef>): SkillInputDef {
	return {
		name: p.name ?? '',
		type: p.type,
		required: p.required ?? false,
		description: p.description,
		enum: p.enum,
		default: p.default
	};
}
