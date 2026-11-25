import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getCurrentUser } from '../api/auth';
import { clearSession, getCurrentUser as cachedUser, setSession } from '../auth/store';
import type { User } from '../types';

const user: User = {
	id: 'reviewer',
	email: 'reviewer@example.invalid',
	is_admin: false,
	mfa_enabled: false,
	must_change_password: false,
	created_at: '2026-01-01T00:00:00Z'
};
const updated = { ...user, display_name: 'Updated profile' };

function pendingProfile() {
	let finish!: (response: Response) => void;
	const response = new Promise<Response>((resolve) => {
		finish = resolve;
	});
	vi.stubGlobal(
		'fetch',
		vi.fn(() => response)
	);
	const request = getCurrentUser();
	return async () => {
		finish(Response.json(updated));
		expect(await request).toEqual(updated);
	};
}

describe('profile cache ownership', () => {
	beforeEach(() => setSession({ access_token: 'initial', expires_in: 900, user }));
	afterEach(() => {
		clearSession();
		vi.unstubAllGlobals();
	});

	it('retains the profile update across a token refresh', async () => {
		const finish = pendingProfile();
		setSession({ access_token: 'rotated', expires_in: 900 });
		await finish();
		expect(cachedUser()).toEqual(updated);
	});

	it('keeps a signed-out cache empty', async () => {
		const finish = pendingProfile();
		clearSession();
		await finish();
		expect(cachedUser()).toBeNull();
	});

	it.each(['reviewer', 'another-reviewer'])('keeps a later sign-in for %s intact', async (id) => {
		const finish = pendingProfile();
		const next = { ...user, id, display_name: 'New session profile' };
		setSession({ access_token: 'new-session', expires_in: 900, user: next });
		await finish();
		expect(cachedUser()).toEqual(next);
	});
});
