import { apiRequest as request } from './client';

const base = '/integrations/slack';
export interface SlackAccount {
	id: string;
	team_id: string;
	team_name: string;
	slack_user_id: string;
	created_at: string;
}
export interface SlackLinkPreview {
	team_id: string;
	team_name: string;
	slack_user_id: string;
	expires_at: string;
}
export const slackAccounts = {
	preview: (token: string) =>
		request<SlackLinkPreview>(`${base}/link-requests/preview`, { method: 'POST', body: { token } }),
	confirm: (token: string) =>
		request<SlackAccount>(`${base}/link-requests/confirm`, { method: 'POST', body: { token } }),
	list: () => request<SlackAccount[]>(`${base}/account-links`),
	unlink: (id: string) =>
		request<void>(`${base}/account-links/${encodeURIComponent(id)}`, { method: 'DELETE' })
};
