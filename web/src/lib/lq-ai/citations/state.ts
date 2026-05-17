/**
 * Citation render-state helpers — shared by `M2Citations.svelte` (sidecar
 * chip list) and `decorate-inline.ts` (inline prose decorator).
 *
 * Per M2-C2 the chat surface renders five citation states; M2-C2 itself
 * ships four of them (per Decision H, 'system-error' is deferred to M2-D
 * when the pipeline has a signal to emit). The fifth slot is reserved in
 * the type union for forward compatibility — adding it later is purely
 * additive on the renderer side.
 */
import type { Citation } from '../types';

export type CitationRenderState =
	| 'verified-exact'
	| 'verified-tolerant'
	| 'verified-paraphrase'
	| 'unverified';

/**
 * Matches `"<quote>" (Source: [N])` pairs the model emits, both straight
 * and curly quote variants. Mirrors the api/'s `_CITATION_RE` in
 * `app/citation/extraction.py` so the frontend and backend extract from
 * the exact same surface. The `s` (dotAll) flag lets the body span line
 * breaks; `g` is required for iterative matching via `matchAll`.
 *
 * Capture groups:
 *   1: straight-quote body, 2: straight-quote source index
 *   3: curly-quote body,    4: curly-quote source index
 * Exactly one of (1,2) or (3,4) is populated per match.
 */
export const CITATION_REGEX =
	/"([^"]+?)"\s*\(Source:\s*\[(\d+)\]\)|“([^”]+?)”\s*\(Source:\s*\[(\d+)\]\)/gs;

/** Convenience: parsed citation marker from a model response. */
export interface ParsedCitationMarker {
	quote: string;
	sourceIndex: number;
	/** Byte offsets of the full marker (including the `"..."` + ` (Source: [N])`). */
	start: number;
	end: number;
	/** Byte offsets of just the quoted span (excluding the trailing source marker). */
	quoteStart: number;
	quoteEnd: number;
}

/**
 * Map a citation row (or `null` for "no row found for this marker") to a
 * render state. Per Decision G, `verification_method='paraphrase_judge'`
 * always maps to verified-paraphrase (yellow), regardless of the
 * `partial` flag — `partial` modulates the tooltip wording, not the
 * color choice.
 *
 * Per M2-D1 Decision F, ensemble methods (`ensemble_strict` and
 * `ensemble_majority`) also render as yellow, reusing the
 * verified-paraphrase chip. The tooltip varies by method + partial
 * flag (e.g., "Models disagreed: K of N verified" for majority with
 * dissent). Reusing the chip rather than adding a 5th visual state
 * keeps the M2-C2 design surface small.
 */
export function citationRenderState(citation: Citation | null): CitationRenderState {
	if (citation === null || !citation.verified) {
		return 'unverified';
	}
	switch (citation.verification_method) {
		case 'exact_match':
			return 'verified-exact';
		case 'tolerant_match':
			return 'verified-tolerant';
		case 'paraphrase_judge':
		case 'llm_judge':
		case 'ensemble_strict':
		case 'ensemble_majority':
			return 'verified-paraphrase';
		case 'failed':
			return 'unverified';
		case null:
		case undefined:
			// Legacy rows without a method — be conservative and treat
			// a verified=true row as the byte-level (green) treatment.
			return 'verified-tolerant';
		default:
			// Unknown future stage — degrade to the closest safe state.
			return 'verified-tolerant';
	}
}

/**
 * Iterate through `"<quote>" (Source: [N])` markers in `text`.
 * Yields a parsed marker per match, with absolute string offsets so the
 * caller can replace, wrap, or annotate the matched ranges in place.
 */
export function* iterCitationMarkers(text: string): IterableIterator<ParsedCitationMarker> {
	// `matchAll` requires the `g` flag, which CITATION_REGEX has. Each
	// match carries `index` (absolute start of the whole match).
	for (const match of text.matchAll(CITATION_REGEX)) {
		const start = match.index ?? 0;
		const end = start + match[0].length;

		// Exactly one of the two alternations populates per match.
		const quote = match[1] ?? match[3];
		const indexStr = match[2] ?? match[4];
		if (quote === undefined || indexStr === undefined) {
			continue;
		}

		// The quoted span begins one char in (skip the opening `"` / `“`)
		// and spans `quote.length`. Compute absolute offsets for callers.
		const quoteStart = start + 1;
		const quoteEnd = quoteStart + quote.length;

		yield {
			quote,
			sourceIndex: parseInt(indexStr, 10),
			start,
			end,
			quoteStart,
			quoteEnd
		};
	}
}

/**
 * Resolve a marker's render state against a citations array. Matches a
 * citation row whose `source_text` equals the marker's quote — that is
 * the field the api persists for the verified hit, so an exact match is
 * the right signal. Returns `'unverified'` when no row matches; per
 * `_persist_message_citations` in the api, absence of a row is the
 * unverified signal.
 */
export function matchMarkerState(
	marker: ParsedCitationMarker,
	citations: Citation[]
): { state: CitationRenderState; citation: Citation | null } {
	const hit = citations.find((c) => c.source_text === marker.quote);
	return { state: citationRenderState(hit ?? null), citation: hit ?? null };
}

/**
 * Tooltip text per render state. Mirrors the M2-C2 plan's spec verbatim
 * for the four states the data pipeline currently emits. The
 * paraphrase-judge tooltip is parameterised because it carries the
 * judge's confidence + partial framing.
 */
export function citationTooltip(
	state: CitationRenderState,
	citation: Citation | null
): string {
	switch (state) {
		case 'verified-exact':
			return 'Verified verbatim against source.';
		case 'verified-tolerant':
			return 'Verified against source (minor formatting differences).';
		case 'verified-paraphrase': {
			const conf = citation?.verification_confidence;
			const confLabel =
				conf === null || conf === undefined
					? 'judge'
					: conf >= 0.85
						? 'high confidence'
						: conf >= 0.6
							? 'medium confidence'
							: 'low confidence';
			const method = citation?.verification_method;
			// M2-D1: ensemble methods get distinct tooltip wording.
			// `ensemble_strict` always means every judge agreed
			// (otherwise the row wouldn't have persisted); `partial=true`
			// in that case flags that at least one judge said partial.
			// `ensemble_majority` with `partial=true` flags dissent
			// (at least one judge missed) — the spec's "Models
			// disagreed" case.
			if (method === 'ensemble_strict') {
				if (citation?.partial) {
					return `Verified by ensemble (${confLabel}): all judges agreed, but the source partially supports this claim.`;
				}
				return `Verified by ensemble (${confLabel}): all judges agreed.`;
			}
			if (method === 'ensemble_majority') {
				if (citation?.partial) {
					return `Verified by ensemble (${confLabel}): majority of judges verified, but some disagreed.`;
				}
				return `Verified by ensemble (${confLabel}): majority of judges verified.`;
			}
			if (citation?.partial) {
				return `Verified by judge (${confLabel}): the source partially supports this claim.`;
			}
			return `Verified by judge (${confLabel}): the source supports this claim.`;
		}
		case 'unverified':
			return "Could not verify this citation against the source. The model may have produced a claim that doesn't follow from the cited content.";
	}
}
