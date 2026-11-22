import { afterEach, describe, expect, it, vi } from 'vitest';
import { captureSlackLink, clearSlackLink, slackLinkDestination } from '../auth/slack-link';

const token = 'a'.repeat(43);
function browser(url: string, disabled = false) {
	const values = new Map<string, string>();
	const location = { href: url };
	vi.stubGlobal('window', {
		location,
		history: {
			state: {},
			replaceState: vi.fn((_state, _unused, path) => {
				location.href = new URL(path, url).href;
			})
		}
	});
	vi.stubGlobal('sessionStorage', {
		getItem: (key: string) => {
			if (disabled) throw new Error('disabled');
			return values.get(key) ?? null;
		},
		setItem: (key: string, value: string) => {
			if (disabled) throw new Error('disabled');
			values.set(key, value);
		},
		removeItem: (key: string) => {
			if (disabled) throw new Error('disabled');
			values.delete(key);
		}
	});
	return { values, location };
}
afterEach(() => vi.unstubAllGlobals());
describe('Slack association capability navigation', () => {
	it('removes the fragment and resumes only the fixed confirmation route', () => {
		const { location } = browser(
			`https://lq.test/lq-ai/slack/link#token=${token}&next=https://evil.test`
		);
		expect(captureSlackLink()).to.equal(token);
		expect(location.href).to.equal('https://lq.test/lq-ai/slack/link');
		location.href = 'https://lq.test/lq-ai/login';
		expect(slackLinkDestination()).to.equal('/lq-ai/slack/link');
		clearSlackLink();
		expect(slackLinkDestination()).to.equal('/lq-ai');
	});
	it('does not capture a token from other routes', () => {
		browser(`https://lq.test/lq-ai/login#token=${token}`);
		expect(captureSlackLink()).to.equal(null);
	});
	it('clears an older pending token when an invalid fragment is opened', () => {
		const { values } = browser('https://lq.test/lq-ai/slack/link#token=invalid');
		values.set('lq_ai_pending_slack_link', token);
		expect(captureSlackLink()).to.equal(null);
	});
	it('fails closed and still removes the fragment when storage is disabled', () => {
		const { location } = browser(`https://lq.test/lq-ai/slack/link#token=${token}`, true);
		expect(captureSlackLink()).to.equal(null);
		expect(location.href).not.to.contain(token);
		expect(slackLinkDestination()).to.equal('/lq-ai');
		expect(() => clearSlackLink()).not.to.throw();
	});
});
