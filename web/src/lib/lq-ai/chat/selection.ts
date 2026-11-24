import { get } from 'svelte/store';
import { chatsApi, filesApi, messagesApi, projectsApi } from '../api';
import { chatsStore, messagesStore, projectsStore } from '../stores';
import type { Chat, FileMeta } from '../types';

export async function createListedChat(projectId: string | null): Promise<Chat> {
	const chat = await chatsApi.createChat({ project_id: projectId });
	chatsStore.update((chats) => [chat, ...chats.filter((item) => item.id !== chat.id)]);
	return chat;
}

/** Each panel owns its pending lookups and reads, including callbacks after unmount. */
export function createChatSelection(
	activate: (chat: Chat) => void,
	setProjectFiles: (files: FileMeta[]) => void
) {
	// A lookup supersedes earlier navigation. The displayed chat can keep loading
	// until the next chat actually opens (the lookup may fail or be cancelled).
	let revision = 0;
	let activeRevision = 0;
	function begin() {
		const ticket = ++revision;
		return () => ticket === revision;
	}

	async function select(target: Chat | string, current = begin()) {
		if (!current()) return;
		let chat: Chat;
		try {
			chat =
				typeof target === 'string'
					? (get(chatsStore).find((item) => item.id === target) ?? (await chatsApi.getChat(target)))
					: target;
		} catch (error) {
			if (current()) throw error;
			return;
		}
		if (!current()) return;
		const read = ++activeRevision;
		activate(chat);
		messagesStore.set([]);
		setProjectFiles([]);
		try {
			const page = await messagesApi.listMessages(chat.id, { limit: 100 });
			if (read !== activeRevision) return;
			messagesStore.set(page.items);
		} catch (error) {
			if (read !== activeRevision) return;
			console.error('lq-ai: failed to load messages', error);
		}
		if (!chat.project_id) return;
		try {
			const project = await projectsApi.getProject(chat.project_id);
			if (read !== activeRevision) return;
			projectsStore.update((projects) => projects.map((p) => (p.id === project.id ? project : p)));
			const files = await Promise.all(
				(project.attached_file_ids ?? []).map((id) => filesApi.getFile(id).catch(() => null))
			);
			if (read === activeRevision)
				setProjectFiles(files.filter((file): file is FileMeta => file !== null));
		} catch (error) {
			if (read === activeRevision) console.error('lq-ai: failed to load project context', error);
		}
	}

	function dispose() {
		revision++;
		activeRevision++;
	}

	return { begin, select, dispose };
}
