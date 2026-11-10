import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createUser, resetUserPassword } from '../api/admin';
import { clearSession, setSession } from '../auth/store';

const realFetch = global.fetch;
const response = (status: number, body: unknown) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json', 'cache-control': 'no-store' }
	});

describe('admin user provisioning API', () => {
	beforeEach(() => {
		clearSession();
		setSession({ access_token: 'admin-token', expires_in: 900 });
	});
	afterEach(() => {
		global.fetch = realFetch;
		clearSession();
	});

	it('creates a user with the supplied fields and returns the temporary password', async () => {
		const created = {
			user_id: 'user-id',
			email: 'new@example.com',
			display_name: 'New User',
			role: 'member',
			is_admin: false,
			must_change_password: true,
			initial_password: 'temporary-test-password'
		};
		const fetchSpy = vi.fn(async () => response(201, created));
		global.fetch = fetchSpy as unknown as typeof fetch;
		const body = {
			email: created.email,
			display_name: created.display_name,
			role: 'member' as const
		};
		expect(await createUser(body)).toEqual(created);
		const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toContain('/admin/users');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual(body);
		expect(init.headers).toMatchObject({ Authorization: 'Bearer admin-token' });
	});

	it('encodes the target user id when resetting a password', async () => {
		const reset = {
			user_id: 'user/id',
			email: 'user@example.com',
			initial_password: 'temp',
			sessions_revoked: 2
		};
		const fetchSpy = vi.fn(async () => response(200, reset));
		global.fetch = fetchSpy as unknown as typeof fetch;
		expect(await resetUserPassword('user/id')).toEqual(reset);
		const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toContain('/admin/users/user%2Fid/reset-password');
		expect(init.method).toBe('POST');
		expect(init.body).toBeUndefined();
	});

	it('preserves duplicate-email errors for the creation form', async () => {
		global.fetch = vi.fn(async () =>
			response(409, {
				detail: { code: 'conflict', message: 'A user with that email already exists.' }
			})
		) as unknown as typeof fetch;
		await expect(createUser({ email: 'existing@example.com' })).rejects.toMatchObject({
			status: 409,
			message: 'A user with that email already exists.'
		});
	});

	it('preserves authorization failures for reset confirmation', async () => {
		global.fetch = vi.fn(async () =>
			response(403, {
				detail: { code: 'forbidden', message: 'Admin privileges required.' }
			})
		) as unknown as typeof fetch;
		await expect(resetUserPassword('user-id')).rejects.toMatchObject({ status: 403 });
	});
});
