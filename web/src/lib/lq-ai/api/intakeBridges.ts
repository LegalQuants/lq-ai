/**
 * Admin intake-bridges API client — M3-D4.
 *
 * Surface:
 *
 *   - GET    /api/v1/admin/intake-bridges           — list live installs
 *   - DELETE /api/v1/admin/intake-bridges/slack/{id} — soft-delete
 *   - DELETE /api/v1/admin/intake-bridges/teams/{id} — soft-delete
 *
 * All endpoints are admin-gated server-side; non-admin users get a
 * 403 which `apiRequest` surfaces as a typed `ForbiddenError` the
 * admin page catches and renders inline.
 */
import { apiRequest } from './client';

export interface SlackWorkspaceSummary {
	id: string;
	team_id: string;
	team_name: string;
	installer_slack_user_id: string;
	installed_at: string;
}

export interface TeamsTenantSummary {
	id: string;
	tenant_id: string;
	tenant_name: string;
	installer_oid: string;
	installed_at: string;
}

export interface IntakeBridgesList {
	slack_workspaces: SlackWorkspaceSummary[];
	teams_tenants: TeamsTenantSummary[];
}

export async function listIntakeBridges(): Promise<IntakeBridgesList> {
	return apiRequest<IntakeBridgesList>('/admin/intake-bridges', { method: 'GET' });
}

export async function deleteSlackWorkspace(workspaceId: string): Promise<void> {
	await apiRequest<void>(`/admin/intake-bridges/slack/${workspaceId}`, {
		method: 'DELETE'
	});
}

export async function deleteTeamsTenant(tenantId: string): Promise<void> {
	await apiRequest<void>(`/admin/intake-bridges/teams/${tenantId}`, {
		method: 'DELETE'
	});
}
