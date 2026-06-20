import { describe, it, expect } from 'vitest';
import { toolUsageNote } from '../skills/toolUsageNote';

describe('toolUsageNote', () => {
	it('no declaration → no uses, no warning', () => {
		expect(toolUsageNote(null, null)).toEqual({ uses: [], warning: null });
	});
	it('declared + all available → uses listed, no warning', () => {
		expect(toolUsageNote(['courtlistener'], [])).toEqual({ uses: ['courtlistener'], warning: null });
	});
	it('declared + missing → warning names the gap', () => {
		const r = toolUsageNote(['courtlistener'], ['courtlistener']);
		expect(r.uses).toEqual(['courtlistener']);
		expect(r.warning).toContain('courtlistener');
		expect(r.warning).toContain('not configured');
	});
	it('undeterminable (null unavailable) → uses listed, no warning', () => {
		expect(toolUsageNote(['courtlistener'], null)).toEqual({ uses: ['courtlistener'], warning: null });
	});
});
