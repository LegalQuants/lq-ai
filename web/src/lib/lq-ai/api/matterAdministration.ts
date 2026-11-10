import { apiRequest } from './client';

export type MatterRole = 'lead' | 'contributor' | 'reader' | 'blocked';
export type ShareScope = 'personal' | 'members' | 'org';
export interface ManagedMatter {
	id: string;
	name: string;
	owner_id: string;
	share_scope: ShareScope;
	archived_at: string | null;
}
export interface DirectoryPerson {
	id: string;
	email: string;
	display_name: string | null;
}
export interface MatterMember {
	user_id: string;
	email: string;
	display_name: string | null;
	role: MatterRole;
	is_owner: boolean;
}
const id = encodeURIComponent;
export const matterAdministration = {
	list: (offset = 0) => apiRequest<ManagedMatter[]>(`/admin/matters?limit=100&offset=${offset}`),
	directory: () => apiRequest<DirectoryPerson[]>('/users/directory'),
	members: (matter: string) => apiRequest<MatterMember[]>(`/admin/matters/${id(matter)}/members`),
	add: (matter: string, user_id: string, role: MatterRole, reason: string) =>
		apiRequest(`/projects/${id(matter)}/members`, {
			method: 'POST',
			body: { user_id, role, reason }
		}),
	change: (matter: string, user: string, role: MatterRole, reason: string) =>
		apiRequest(`/projects/${id(matter)}/members/${id(user)}`, {
			method: 'PATCH',
			body: { role, reason }
		}),
	remove: (matter: string, user: string, reason: string) =>
		apiRequest(`/projects/${id(matter)}/members/${id(user)}?reason=${id(reason)}`, {
			method: 'DELETE'
		}),
	policy: (matter: string, share_scope: ShareScope, reason: string) =>
		apiRequest<ManagedMatter>(`/admin/matters/${id(matter)}/policy`, {
			method: 'PATCH',
			body: { share_scope, reason }
		}),
	transfer: (matter: string, owner_id: string, former_owner_role: MatterRole, reason: string) =>
		apiRequest<ManagedMatter>(`/admin/matters/${id(matter)}/transfer`, {
			method: 'POST',
			body: { owner_id, former_owner_role, reason }
		})
};
