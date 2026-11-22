/** Keep the capability out of request URLs and login redirect parameters.
 * Session storage is confined to this browser tab and cleared on completion.
 * Only a fixed internal destination is resumed after normal sign-in.
 */
const key = 'lq_ai_pending_slack_link';
const path = '/lq-ai/slack/link';
const valid = (token: string | null): token is string =>
	!!token && /^[A-Za-z0-9_-]{43}$/.test(token);

export function captureSlackLink(): string | null {
	if (typeof window === 'undefined') return null;
	const url = new URL(window.location.href);
	if (url.pathname === path && url.hash) {
		const token = new URLSearchParams(url.hash.slice(1)).get('token');
		window.history.replaceState(window.history.state, '', url.pathname);
		try {
			if (valid(token)) sessionStorage.setItem(key, token);
			else sessionStorage.removeItem(key);
		} catch {
			return null;
		}
	}
	try {
		const stored = sessionStorage.getItem(key);
		return valid(stored) ? stored : null;
	} catch {
		return null;
	}
}

export function slackLinkDestination(): string {
	return captureSlackLink() ? path : '/lq-ai';
}

export function clearSlackLink(): void {
	try {
		sessionStorage.removeItem(key);
	} catch {
		/* Storage may be disabled. */
	}
}
