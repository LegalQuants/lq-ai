import { get } from 'svelte/store';
import { beforeEach, expect, it, vi } from 'vitest';
import { chatsApi, filesApi, messagesApi, projectsApi } from '../api';
import { createChatSelection } from '../chat/selection';
import { chatsStore, messagesStore, projectsStore } from '../stores';
import type { Chat, FileMeta, PaginatedMessages, Project } from '../types';

vi.mock('../api', () => ({
	chatsApi: { getChat: vi.fn() },
	messagesApi: { listMessages: vi.fn() },
	projectsApi: { getProject: vi.fn() },
	filesApi: { getFile: vi.fn() }
}));

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason: Error) => void;
	const promise = new Promise<T>((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}

const chat = (id: string): Chat => ({
	id,
	title: id,
	owner_id: 'owner',
	project_id: id,
	created_at: '',
	updated_at: ''
});
const page = (id: string): PaginatedMessages => ({
	items: [{ id, chat_id: id, content: id, role: 'user', created_at: '' }],
	next_cursor: null
});
const project = (id: string): Project => ({
	id,
	name: id,
	slug: id,
	owner_id: 'owner',
	privileged: false,
	created_at: '',
	updated_at: '',
	attached_file_ids: [id]
});
const file = (id: string): FileMeta => ({
	id,
	filename: id,
	mime_type: 'text/plain',
	size_bytes: 1,
	owner_id: 'owner',
	created_at: ''
});

function panel() {
	const activate = vi.fn();
	const setFiles = vi.fn();
	return { activate, setFiles, ...createChatSelection(activate, setFiles) };
}

beforeEach(() => {
	vi.resetAllMocks();
	chatsStore.set([chat('b')]);
	messagesStore.set([]);
	projectsStore.set([project('a'), project('b')]);
	vi.mocked(messagesApi.listMessages).mockImplementation(async (id) => page(id));
	vi.mocked(projectsApi.getProject).mockImplementation(async (id) => project(id));
	vi.mocked(filesApi.getFile).mockImplementation(async (id) => file(id));
});

it.each(['resolve', 'reject'] as const)(
	'ignores a late chat lookup (%s) after a cached sidebar selection',
	async (outcome) => {
		const old = deferred<Chat>();
		vi.mocked(chatsApi.getChat).mockReturnValueOnce(old.promise);
		const view = panel();
		const opening = view.select('a');
		await view.select('b');
		if (outcome === 'resolve') old.resolve(chat('a'));
		else old.reject(new Error('gone'));
		await opening;
		expect(view.activate.mock.calls).toEqual([[chat('b')]]);
		expect(get(messagesStore)).toEqual(page('b').items);
	}
);

it.each(['resolve', 'reject'] as const)(
	'ignores a late message page (%s) and keeps the new project files',
	async (outcome) => {
		const old = deferred<PaginatedMessages>();
		vi.mocked(messagesApi.listMessages).mockReturnValueOnce(old.promise);
		const view = panel();
		const opening = view.select(chat('a'));
		await view.select('b');
		if (outcome === 'resolve') old.resolve(page('a'));
		else old.reject(new Error('gone'));
		await opening;
		expect(get(messagesStore)).toEqual(page('b').items);
		expect(projectsApi.getProject).toHaveBeenCalledTimes(1);
		expect(view.setFiles).toHaveBeenLastCalledWith([file('b')]);
	}
);

it('clears the previous thread and files on selection and drops a late attachment read', async () => {
	const oldFile = deferred<FileMeta>();
	vi.mocked(filesApi.getFile).mockReturnValueOnce(oldFile.promise);
	const view = panel();
	const opening = view.select(chat('a'));
	await vi.waitFor(() => expect(filesApi.getFile).toHaveBeenCalledWith('a'));
	const newer = view.select(chat('b'));
	expect(get(messagesStore)).toEqual([]);
	expect(view.setFiles).toHaveBeenLastCalledWith([]);
	await newer;
	oldFile.resolve(file('a'));
	await opening;
	expect(view.setFiles).toHaveBeenLastCalledWith([file('b')]);
});

it('discards a project response after unmount', async () => {
	const oldProject = deferred<Project>();
	vi.mocked(projectsApi.getProject).mockReturnValueOnce(oldProject.promise);
	const view = panel();
	const opening = view.select(chat('a'));
	await vi.waitFor(() => expect(projectsApi.getProject).toHaveBeenCalledWith('a'));
	view.dispose();
	oldProject.resolve({ ...project('a'), name: 'late' });
	await opening;
	expect(get(projectsStore)[0].name).toBe('a');
	expect(filesApi.getFile).not.toHaveBeenCalled();
});

it('preserves the displayed thread load when a pending navigation is abandoned', async () => {
	const old = deferred<PaginatedMessages>();
	vi.mocked(messagesApi.listMessages).mockReturnValueOnce(old.promise);
	const view = panel();
	const opening = view.select(chat('b'));
	const pending = view.begin();
	view.begin();
	await view.select(chat('a'), pending);
	old.resolve(page('b'));
	await opening;
	expect(view.activate.mock.calls).toEqual([[chat('b')]]);
	expect(get(messagesStore)).toEqual(page('b').items);
});
