/**
 * How a governed run's delivered answer becomes HTML for the thread (ADR 0038 D1, D2).
 *
 * The answer is model output built from documents the run read, so text in it that
 * looks like markup is shown as text. Markdown structure is kept: headings, lists,
 * emphasis, code, tables and links. Three things differ from an ordinary assistant
 * message:
 *
 * - raw HTML in the answer is shown as the characters that were written;
 * - an image is never loaded: it is shown as its Markdown source, so an answer
 *   cannot make the browser fetch an address a document chose;
 * - a link is drawn only for an http, https or mailto address; any other is shown
 *   as its label and address in text;
 * - a task list's ticks are shown as `[x]` and `[ ]` in text, not as checkboxes.
 *
 * The result is then sanitised by DOMPurify, as every assistant message is, with
 * embedded and form content forbidden outright. `runAnswerMarkup` is the Markdown
 * step alone and needs no DOM, so it can be tested in node.
 */
import DOMPurify from 'dompurify';
import { Marked } from 'marked';

const ESCAPES: Record<string, string> = {
	'&': '&amp;',
	'<': '&lt;',
	'>': '&gt;',
	'"': '&quot;',
	"'": '&#39;'
};

/** The characters as written, safe to place in HTML text. */
export function escapeHtml(text: string): string {
	return text.replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

/**
 * Addresses a link may be drawn for, tested as written. Anything else is shown as
 * text, including an address with space before it: the link would be drawn from the
 * address as written, and that one would point under the page, not at the site.
 */
const LINK_SCHEMES = /^(?:https?:|mailto:)/i;

const strict = new Marked({
	renderer: {
		// Raw HTML, block or inline, is shown as it was written.
		html(html: string, block?: boolean): string {
			const text = escapeHtml(html);
			return block ? `<p>${text}</p>\n` : text;
		},
		// A task list keeps its ticks as text. A checkbox would be a form control,
		// which the sanitiser removes, and the list would then no longer say which
		// items were ticked.
		checkbox(checked: boolean): string {
			return checked ? '[x]' : '[ ]';
		},
		// Never an <img>: the Markdown source, as text.
		image(href: string, title: string | null, text: string): string {
			const suffix = title ? ` "${title}"` : '';
			return escapeHtml(`![${text}](${href}${suffix})`);
		},
		// `text` is the label, already rendered by this renderer.
		link(href: string, _title: string | null | undefined, text: string): string | false {
			if (LINK_SCHEMES.test(href)) return false;
			return `${text} (${escapeHtml(href)})`;
		}
	}
});

/** The Markdown step alone: HTML in which nothing the answer wrote is live markup. */
export function runAnswerMarkup(content: string): string {
	return strict.parse(content ?? '', { async: false }) as string;
}

/** Elements a run's answer never needs. Forbidden even if the Markdown step let one through. */
export const RUN_ANSWER_FORBIDDEN_TAGS = [
	'img',
	'picture',
	'source',
	'video',
	'audio',
	'track',
	'iframe',
	'object',
	'embed',
	'svg',
	'math',
	'style',
	'link',
	'form',
	'input',
	'button',
	'textarea',
	'select'
];

export const RUN_ANSWER_FORBIDDEN_ATTRS = ['style', 'srcset', 'background'];

/** The answer as sanitised HTML for the message bubble. Needs a DOM (DOMPurify). */
export function runAnswerHtml(content: string): string {
	return DOMPurify.sanitize(runAnswerMarkup(content), {
		FORBID_TAGS: RUN_ANSWER_FORBIDDEN_TAGS,
		FORBID_ATTR: RUN_ANSWER_FORBIDDEN_ATTRS
	});
}
