/**
 * `decorateCitationsInline` — Svelte action that wraps `"<quote>" (Source: [N])`
 * markers in rendered message prose with a subtle, color-coded underline span
 * keyed to the citation's render state (M2-C2 §F: hybrid inline + sidecar).
 *
 * The action keeps inline treatment intentionally minimal: a thin colored
 * underline + a native `title` tooltip. Click behavior and the long-form
 * tooltip live in the sidecar (`M2Citations.svelte`); inline is for the
 * procurement-reviewer scrolling test — a reviewer scanning the report
 * should be able to identify unverified citations by color alone.
 *
 * The action only decorates citation markers that fit inside a single text
 * node — i.e., the model's output didn't insert inline HTML (e.g., bold,
 * italic) mid-quote. Cross-element citations degrade gracefully to the
 * sidecar chip without an inline marker.
 */
import { iterCitationMarkers, matchMarkerState, citationTooltip } from './state';
import type { Citation } from '../types';

export interface DecorateCitationsParams {
	citations: Citation[];
	/**
	 * Streaming hint: when `false`, the action is a no-op. Callers pass
	 * `false` while the message is still streaming and switch to `true`
	 * once the assistant message completes — otherwise the regex would
	 * match partial markers mid-stream and re-decorate on every token.
	 */
	enabled?: boolean;
}

const WRAPPER_CLASS = 'lq-cite-inline';

/**
 * Strip any previously-applied inline-decoration spans from `root`,
 * collapsing their text content back into the parent so re-application
 * starts from a clean baseline. Safe to call when no decorations exist.
 */
function undecorate(root: HTMLElement): void {
	const wrappers = root.querySelectorAll(`span.${WRAPPER_CLASS}`);
	wrappers.forEach((span) => {
		const parent = span.parentNode;
		if (!parent) return;
		while (span.firstChild) {
			parent.insertBefore(span.firstChild, span);
		}
		parent.removeChild(span);
		// Adjacent text nodes left behind from the unwrap; let the browser
		// re-coalesce on the next normalize().
	});
	root.normalize();
}

/**
 * Walk text nodes inside `root` and wrap every quote that maps to a
 * citation marker with a state-styled span. The walk uses a NodeIterator
 * because we mutate the DOM as we go and want stable traversal of the
 * pre-mutation snapshot.
 */
function decorate(root: HTMLElement, citations: Citation[]): void {
	// Collect text nodes first, then mutate. Live-walking + mutating in
	// one pass corrupts the iterator's position.
	const textNodes: Text[] = [];
	const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
	let current = walker.nextNode();
	while (current) {
		textNodes.push(current as Text);
		current = walker.nextNode();
	}

	for (const node of textNodes) {
		const text = node.nodeValue ?? '';
		const markers = Array.from(iterCitationMarkers(text));
		if (markers.length === 0) continue;

		// Build a replacement DocumentFragment piece by piece, alternating
		// untouched text and state-styled spans. Walking markers in order
		// of their `start` offset keeps the offsets coherent.
		const fragment = document.createDocumentFragment();
		let cursor = 0;
		for (const marker of markers) {
			// Leading untouched text between cursor and the marker start.
			if (marker.quoteStart > cursor) {
				fragment.appendChild(
					document.createTextNode(text.slice(cursor, marker.quoteStart))
				);
			}

			const { state, citation } = matchMarkerState(marker, citations);
			const span = document.createElement('span');
			span.className = `${WRAPPER_CLASS} ${WRAPPER_CLASS}-${state}`;
			span.title = citationTooltip(state, citation);
			if (citation) {
				span.dataset.citeId = citation.id;
			}
			span.dataset.citeState = state;
			span.textContent = text.slice(marker.quoteStart, marker.quoteEnd);
			fragment.appendChild(span);

			cursor = marker.quoteEnd;
		}

		// Trailing untouched text after the last marker.
		if (cursor < text.length) {
			fragment.appendChild(document.createTextNode(text.slice(cursor)));
		}

		node.parentNode?.replaceChild(fragment, node);
	}
}

export function decorateCitationsInline(
	node: HTMLElement,
	params: DecorateCitationsParams
): {
	update(newParams: DecorateCitationsParams): void;
	destroy(): void;
} {
	let current = params;

	function apply(): void {
		undecorate(node);
		if (current.enabled === false) return;
		if (current.citations.length === 0 && !nodeContainsAnyMarker(node)) {
			// Nothing verified AND no markers in the text → skip the walk
			// to keep streaming-tail render cheap.
			return;
		}
		decorate(node, current.citations);
	}

	apply();

	return {
		update(newParams: DecorateCitationsParams) {
			current = newParams;
			apply();
		},
		destroy() {
			undecorate(node);
		}
	};
}

/** Cheap probe: does the rendered prose contain ANY citation marker? */
function nodeContainsAnyMarker(root: HTMLElement): boolean {
	const text = root.textContent ?? '';
	// Don't run the full regex iterator; a single test suffices.
	return /(?:"[^"]+?"|“[^”]+?”)\s*\(Source:\s*\[\d+\]\)/s.test(text);
}
