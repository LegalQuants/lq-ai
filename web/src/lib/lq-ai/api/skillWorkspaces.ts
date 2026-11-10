import { apiRequest } from './client';

export interface SavedSkillFile {
	name: string;
	revision: string;
	size_bytes: number;
	updated_at: string;
}

export interface SavedSkillWorkspace {
	id: string;
	skill_name: string;
	project_id: string | null;
	project_name: string | null;
	format_version: number;
	files: SavedSkillFile[];
}

export const skillWorkspacesApi = {
	list: (offset = 0) => apiRequest<SavedSkillWorkspace[]>(`/skill-workspaces?offset=${offset}`),
	read: (id: string, name: string) =>
		apiRequest<SavedSkillFile & { content: string }>(
			`/skill-workspaces/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`
		),
	reset: (id: string) =>
		apiRequest<void>(`/skill-workspaces/${encodeURIComponent(id)}`, { method: 'DELETE' })
};
