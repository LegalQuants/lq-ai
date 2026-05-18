/**
 * Bootstrap-state probe — M3-0.1 / DE-283.
 *
 * Unauthenticated read of `/api/v1/admin/bootstrap-status`, consulted by the
 * login screen on the first failed login attempt. When the deployment is in
 * fresh-install state (an admin user still has `must_change_password=true`),
 * the login UI escalates a generic 401 into an actionable hint pointing the
 * operator at `docker compose logs api`.
 *
 * `skipAuth: true` is load-bearing here — the caller has no token yet, and
 * the endpoint must not be gated on one.
 */
import { apiRequest } from './client';

export interface BootstrapStatus {
	default_password_active: boolean;
	logs_hint: string;
}

export async function getBootstrapStatus(): Promise<BootstrapStatus> {
	return apiRequest<BootstrapStatus>('/admin/bootstrap-status', {
		skipAuth: true,
		skipRefresh: true
	});
}
