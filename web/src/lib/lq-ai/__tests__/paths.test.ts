import { describe, expect, it } from 'vitest';
import { isLQAIPath } from '../paths';

describe('isLQAIPath', () => {
	it.each(['/lq-ai', '/lq-ai/', '/lq-ai/login', '/lq-ai/chats', '/lq-ai/admin/audit-log'])(
		'recognizes shell route %s',
		(path) => {
			expect(isLQAIPath(path)).toBe(true);
		}
	);

	it.each(['/', '/auth', '/lq-ai-other', '/lq-aix', '/learn/lq-ai'])(
		'does not capture unrelated route %s',
		(path) => {
			expect(isLQAIPath(path)).toBe(false);
		}
	);
});
