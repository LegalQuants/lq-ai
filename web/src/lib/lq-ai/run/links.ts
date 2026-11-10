/** Where the run components link to. Pure; ids are interpolated as path or query values only. */

/** Open a chat in the chat page. `/lq-ai/chats` reads `?id=` to select that chat on load. */
export function chatHref(chatId: string): string {
	if (typeof chatId !== 'string' || chatId === '') return '/lq-ai/chats';
	return `/lq-ai/chats?id=${encodeURIComponent(chatId)}`;
}

/** The receipt view of a run: the same run components, without a chat around them. */
export function receiptHref(rootId: string): string {
	if (typeof rootId !== 'string' || rootId === '') return '/lq-ai/autonomous';
	return `/lq-ai/autonomous/orchestration/chat/${encodeURIComponent(rootId)}`;
}

/**
 * The receipt view for an autonomous session, when the session is the root of a
 * governed run. Root sessions carry their registry profile in
 * `params.orchestration_profile`; a task's session carries `research` and the
 * earlier demonstration carries `demonstration`, and neither has a run receipt.
 */
export function receiptHrefForSession(session: {
	id: string;
	params?: Record<string, unknown> | null;
}): string | null {
	const profile = session.params?.orchestration_profile;
	if (typeof profile !== 'string' || profile === '') return null;
	if (profile === 'research' || profile === 'demonstration') return null;
	if (typeof session.id !== 'string' || session.id === '') return null;
	return receiptHref(session.id);
}
