import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getSkill, getSkillContents } from '../api/skills';
import { loadResourceContents, modelReadLabel } from '../components/SkillResources.svelte';
import { loadSkillResourcePolicy } from '../components/DevSkillResourcePolicyCard.svelte';
import { clearSession, setSession } from '../auth/store';

const realFetch = global.fetch;
const source = {
	name: 'nda-review',
	scope: 'builtin',
	title: 'NDA review',
	version: '1.0.0',
	content_md: 'Review the NDA.',
	content_yaml: '',
	on_demand_files: [{ path: 'references/rules.md', size_bytes: 23 }],
	reference_read_enabled: false
};

function response(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

beforeEach(() => {
	clearSession();
	setSession({ access_token: 'tok', expires_in: 900 });
});
afterEach(() => {
	global.fetch = realFetch;
	vi.restoreAllMocks();
});

describe('human skill resource inspection', () => {
	it('metadata stays separate from the human contents endpoint', async () => {
		const fetch = vi.fn(async (url: RequestInfo | URL) =>
			response(
				String(url).endsWith('/contents')
					? {
							...source,
							on_demand_contents: [
								{ path: 'references/rules.md', content: 'Human-readable rules.' }
							]
						}
					: source
			)
		);
		global.fetch = fetch as typeof global.fetch;
		const metadata = await getSkill('nda-review');
		expect(metadata.on_demand_files).toEqual(source.on_demand_files);
		expect(metadata.on_demand_contents).toBeUndefined();
		expect(fetch).toHaveBeenCalledTimes(1);
		const contents = await getSkillContents('nda-review');
		expect(contents.on_demand_contents?.[0].content).toBe('Human-readable rules.');
		expect(fetch).toHaveBeenCalledTimes(2);
	});

	it('loads contents for human viewing even when model reading is disabled', async () => {
		global.fetch = vi.fn(async () =>
			response({
				...source,
				on_demand_contents: [
					{ path: 'references/rules.md', content: '<script>raw reference text</script>' }
				]
			})
		) as typeof fetch;
		const result = await loadResourceContents('nda-review');
		expect(result.error).toBeNull();
		expect(result.contents?.[0].content).toBe('<script>raw reference text</script>');
		expect(modelReadLabel(false)).toContain('disabled');
		expect(modelReadLabel(false)).toContain('still inspect');
		expect(modelReadLabel(true)).toContain('can read');
		expect(modelReadLabel(undefined)).toContain('could not be determined');
	});

	it('encodes the skill name for the contents request', async () => {
		const spy = vi.fn(async () => response(source));
		global.fetch = spy as typeof fetch;
		await getSkillContents('my skill/another');
		expect(String((spy.mock.calls[0] as unknown[])[0])).toContain(
			'/skills/my%20skill%2Fanother/contents'
		);
	});

	it('reports a failed contents request instead of treating it as an empty skill', async () => {
		global.fetch = vi.fn(async () =>
			response({ detail: { code: 'not_found', message: 'Skill disappeared' } }, 404)
		) as typeof fetch;
		const result = await loadResourceContents('nda-review');
		expect(result.contents).toBeNull();
		expect(result.error).toContain('Skill disappeared');
	});

	it('handles a DB-backed skill with no filesystem resources', async () => {
		global.fetch = vi.fn(async () =>
			response({ ...source, scope: 'user', on_demand_files: [] })
		) as typeof fetch;
		expect(await loadResourceContents('nda-review')).toEqual({ contents: [], error: null });
	});
});

describe('operator skill reference policy', () => {
	it.each([true, false])('reports the effective enabled=%s policy', async (enabled) => {
		const policy = {
			reference_read_enabled: enabled,
			max_files: 64,
			max_file_bytes: 65536,
			scope: 'installed skill references/'
		};
		global.fetch = vi.fn(async () =>
			response({ providers: [], model_aliases: {}, skill_resource_policy: policy })
		) as typeof fetch;
		expect(await loadSkillResourcePolicy()).toEqual({ policy, error: null });
	});

	it('does not claim enabled when the server omits the policy', async () => {
		global.fetch = vi.fn(async () =>
			response({ providers: [], model_aliases: {} })
		) as typeof fetch;
		const result = await loadSkillResourcePolicy();
		expect(result.policy).toBeNull();
		expect(result.error).toContain('did not report');
	});

	it('surfaces policy request errors for retry', async () => {
		global.fetch = vi.fn(async () => {
			throw new Error('Network unavailable');
		}) as typeof fetch;
		expect(await loadSkillResourcePolicy()).toEqual({ policy: null, error: 'Network unavailable' });
	});
});
