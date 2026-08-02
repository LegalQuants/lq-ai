/**
 * Focused regression coverage for chat-local file grounding.
 *
 * ChatPanel keeps the metadata returned by upload, which may still say
 * `pending` even after asynchronous ingestion finishes. The send boundary
 * must therefore preserve every still-attached id instead of filtering on
 * that stale status; the backend performs the authoritative readiness check.
 */
import { describe, expect, it } from 'vitest';

import {
	buildChatMessageCreate,
	canAttachChatFile,
	canSendChatMessage,
	chatAttachmentStateAfterSelection,
	initializeChatFilesChatId,
	isCurrentChatFileUpload,
	reconcileChatSendFailure
} from '../chat/messageCreate';
import { messageBubbleInstanceKey } from '../components/MessageList.svelte';

describe('buildChatMessageCreate', () => {
	it('puts every attached chat file into the actual MessageCreate file_ids field', () => {
		const message = buildChatMessageCreate({
			content: 'Analyse the authorities in the attached records.',
			model: 'smart',
			attachedSkills: [{ slug: 'legal-research', source: 'picker' }],
			files: [
				{ id: 'ready-file', ingestion_status: 'ready' },
				{ id: 'stale-pending-file', ingestion_status: 'pending' },
				{ id: 'ready-file', ingestion_status: 'ready' }
			],
			skillInputs: { 'legal-research': { jurisdiction: 'England and Wales' } },
			setSticky: false
		});

		expect(message).toEqual({
			content: 'Analyse the authorities in the attached records.',
			model: 'smart',
			attached_skills: [{ slug: 'legal-research', source: 'picker' }],
			file_ids: ['ready-file', 'stale-pending-file'],
			skill_inputs: { 'legal-research': { jurisdiction: 'England and Wales' } },
			set_sticky: false,
			stream: true
		});
	});

	it('omits optional attachment fields when the composer has none', () => {
		const message = buildChatMessageCreate({
			content: 'Hello',
			attachedSkills: [],
			files: [],
			skillInputs: {}
		});

		expect(message.file_ids).toBeUndefined();
		expect(message.attached_skills).toBeUndefined();
		expect(message.skill_inputs).toBeUndefined();
	});
});

describe('chat attachment isolation', () => {
	it('remounts a resumed assistant bubble so final evidence is fetched again', () => {
		const settled = messageBubbleInstanceKey('assistant-1', false);
		const streaming = messageBubbleInstanceKey('assistant-1', true);

		expect(settled).toBe('assistant-1:settled');
		expect(streaming).toBe('assistant-1:streaming');
		expect(streaming).not.toBe(settled);
		expect(messageBubbleInstanceKey('assistant-1', false)).toBe(settled);
	});

	it('prevents sending while an attachment upload is still in flight', () => {
		expect(canSendChatMessage('Analyse this file', false)).toBe(true);
		expect(canSendChatMessage('Analyse this file', true)).toBe(false);
		expect(canSendChatMessage('   ', false)).toBe(false);
	});

	it('binds a remounted composer to an already-active chat', () => {
		expect(initializeChatFilesChatId(null, 'active-chat')).toBe('active-chat');
		expect(initializeChatFilesChatId('draft-owner', 'active-chat')).toBe('draft-owner');
		expect(initializeChatFilesChatId(null, null)).toBeNull();
	});

	it('allows four direct chat attachments and blocks selecting a fifth', () => {
		expect(canAttachChatFile(3)).toBe(true);
		expect(canAttachChatFile(4)).toBe(false);
		expect(canAttachChatFile(5)).toBe(false);
	});

	it('clears chat-local files and per-attachment source state when the chat changes', () => {
		expect(
			chatAttachmentStateAfterSelection(
				{
					chatId: 'chat-a',
					files: [{ id: 'file-from-a' }],
					attachmentSources: { 'legal-research': 'picker' }
				},
				'chat-b'
			)
		).toEqual({ chatId: 'chat-b', files: [], attachmentSources: {} });
	});

	it('retains files for the same chat while clearing draft source state', () => {
		expect(
			chatAttachmentStateAfterSelection(
				{
					chatId: 'chat-a',
					files: [{ id: 'file-from-a' }],
					attachmentSources: { 'legal-research': 'slash' }
				},
				'chat-a'
			)
		).toEqual({ chatId: 'chat-a', files: [{ id: 'file-from-a' }], attachmentSources: {} });
	});

	it('rejects an upload completion from another chat or an invalidated generation', () => {
		expect(isCurrentChatFileUpload('chat-a', 2, 'chat-b', 2)).toBe(false);
		expect(isCurrentChatFileUpload('chat-a', 1, 'chat-a', 2)).toBe(false);
		expect(isCurrentChatFileUpload('chat-a', 2, 'chat-a', 2)).toBe(true);
	});
});

describe('pre-start send failure cleanup', () => {
	it('removes both optimistic bubbles after an attachments_not_ready 409 before start', () => {
		const attachmentsNotReady = Object.assign(new Error('Attached files are still processing.'), {
			status: 409,
			code: 'attachments_not_ready'
		});
		const messages = [
			{ id: 'persisted-earlier', content: 'Earlier message' },
			{ id: 'optimistic-user', content: 'Analyse the attachments' },
			{ id: 'draft-assistant', content: '' }
		];

		const failure = reconcileChatSendFailure(
			messages,
			{
				optimisticUserId: 'optimistic-user',
				draftAssistantId: 'draft-assistant',
				streamStarted: false
			},
			attachmentsNotReady
		);

		expect(attachmentsNotReady).toMatchObject({ status: 409, code: 'attachments_not_ready' });
		expect(failure.messages).toEqual([{ id: 'persisted-earlier', content: 'Earlier message' }]);
		expect(failure.errorMessage).toBe('Attached files are still processing.');
	});

	it('preserves the user and removes only the assistant draft after a gateway timeout before start', () => {
		const gatewayTimeout = Object.assign(new Error('Inference gateway timed out.'), {
			status: 504,
			code: 'gateway_timeout'
		});
		const messages = [
			{ id: 'persisted-earlier', content: 'Earlier message' },
			{ id: 'optimistic-user', content: 'Analyse the attachments' },
			{ id: 'draft-assistant', content: '' }
		];

		const failure = reconcileChatSendFailure(
			messages,
			{
				optimisticUserId: 'optimistic-user',
				draftAssistantId: 'draft-assistant',
				streamStarted: false
			},
			gatewayTimeout
		);

		expect(failure.messages).toEqual([
			{ id: 'persisted-earlier', content: 'Earlier message' },
			{ id: 'optimistic-user', content: 'Analyse the attachments' }
		]);
		expect(failure.errorMessage).toBe('Inference gateway timed out.');
	});

	it.each([
		{ status: 404, code: 'not_found', message: 'Attached file not found.' },
		{ status: 422, code: 'validation_error', message: 'Too many attached files.' },
		{ status: 422, code: 'http_422', message: 'Invalid attached file id.' }
	])('removes both optimistic bubbles after $code before persistence', (errorShape) => {
		const error = Object.assign(new Error(errorShape.message), errorShape);
		const messages = [
			{ id: 'persisted-earlier', content: 'Earlier message' },
			{ id: 'optimistic-user', content: 'Analyse the attachments' },
			{ id: 'draft-assistant', content: '' }
		];

		const failure = reconcileChatSendFailure(
			messages,
			{
				optimisticUserId: 'optimistic-user',
				draftAssistantId: 'draft-assistant',
				streamStarted: false
			},
			error
		);

		expect(failure.messages).toEqual([{ id: 'persisted-earlier', content: 'Earlier message' }]);
		expect(failure.errorMessage).toBe(errorShape.message);
	});

	it('preserves persisted and partial bubbles after an SSE start frame', () => {
		const messages = [
			{ id: 'optimistic-user', content: 'Analyse the attachments' },
			{ id: 'persisted-assistant', content: 'Partial response' }
		];

		expect(
			reconcileChatSendFailure(
				messages,
				{
					optimisticUserId: 'optimistic-user',
					draftAssistantId: 'draft-assistant',
					streamStarted: true
				},
				new Error('Connection interrupted')
			).messages
		).toEqual(messages);
	});
});
