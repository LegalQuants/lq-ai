"""Stage 3 paraphrase-judge prompt construction — M2-C1.

Builds the ``list[ChatCompletionMessage]`` the Citation Engine
dispatches to the gateway as its Stage 3 judge call. The judge is an
LLM asked to evaluate whether a model-emitted claim is faithfully
supported by the cited source passage.

The prompt is deliberately conservative: it biases the judge toward
``no`` / ``partial`` on uncertainty, on the principle that
false-positive verifications (calling an unsupported claim verified)
do more harm in a legal-citation context than false-negative
verifications (calling a borderline-supported claim unverified). The
M2-F1 acceptance corpus will measure this trade-off empirically; the
prompt's calibration is the lever to tune.

Output contract: the judge returns a single JSON object with three
fields — ``verdict`` (``yes`` / ``partial`` / ``no``), ``confidence``
(``high`` / ``medium`` / ``low``), and ``justification`` (free text).
:func:`app.citation.verification.verify_paraphrase` parses this shape;
the parser falls through to MISS on malformed JSON so a misbehaving
judge can't crash the pipeline.
"""

from __future__ import annotations

from app.schemas.gateway import ChatCompletionMessage

__all__ = ["build_judge_prompt"]


_SYSTEM_PROMPT = """\
You are a Citation Verification Judge for a legal AI assistant.

Your job is to evaluate whether a claim — a passage another model
quoted from a source document — is FAITHFULLY SUPPORTED by the
SOURCE passages provided. You are NOT evaluating the legal merits
of the claim; only whether the source actually says what the claim
asserts.

Respond with STRICTLY VALID JSON in this exact shape:

  {"verdict": "yes" | "partial" | "no",
   "confidence": "high" | "medium" | "low",
   "justification": "<one or two sentences explaining your verdict>"}

Verdict meanings:

* "yes" — the source supports the ENTIRE substance of the claim.
  The wording does not need to match verbatim, but every assertion
  in the claim must follow from the source.
* "partial" — the source supports SOME of the claim's assertions
  but not all. A claim that adds qualifiers or details the source
  doesn't contain is "partial", not "yes".
* "no" — the source does not support the claim, or the source
  contradicts it.

Confidence meanings:

* "high" — the verdict is unambiguous; another careful reader would
  reach the same conclusion.
* "medium" — the verdict is sound but reasonable readers could
  weigh it differently.
* "low" — the verdict is best-guess; the source is ambiguous or
  the claim is vague enough to be hard to evaluate.

CALIBRATION — IMPORTANT.

When you are uncertain, prefer "no" or "partial" over "yes". A
false-positive verification (declaring an unsupported claim
verified) is worse than a false-negative (declaring a supported
claim unverified) in this context. If the source is ambiguous, or
the claim adds qualifiers the source doesn't contain, lean toward
"partial". If the source is genuinely off-topic relative to the
claim, lean toward "no".

Output ONLY the JSON object. No preamble, no markdown fencing, no
trailing commentary."""


def build_judge_prompt(
    *,
    claim_text: str,
    chunks: list[str],
) -> list[ChatCompletionMessage]:
    """Construct the two-message judge prompt.

    Args:
        claim_text: The text the citation-generating model quoted.
            This is the ``source_text`` field on the citation
            candidate — the model's literal claim, as it appears in
            the assistant's response.
        chunks: The source-document text chunks the citation points
            at. The caller decides what to include (typically the
            cited span plus a small window of surrounding context);
            this function just embeds each chunk into the user message
            verbatim with separators.

    Returns:
        A two-element list: ``[system_message, user_message]`` ready
        to set as :attr:`ChatCompletionRequest.messages`.
    """

    user_message = _build_user_message(claim_text=claim_text, chunks=chunks)
    return [
        ChatCompletionMessage(role="system", content=_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user_message),
    ]


def _build_user_message(*, claim_text: str, chunks: list[str]) -> str:
    """Format SOURCE chunks and CLAIM into a labeled user message body."""

    # Degenerate empty-chunks case is well-formed — the judge will
    # return "no" / "low" confidence (nothing to support a claim
    # against) but the prompt is still parseable.
    source_block = "\n---\n".join(chunks) if chunks else "(no source passages provided)"

    return (
        "SOURCE PASSAGES:\n"
        '"""\n'
        f"{source_block}\n"
        '"""\n\n'
        "CLAIM:\n"
        '"""\n'
        f"{claim_text}\n"
        '"""\n\n'
        "Does the SOURCE support the CLAIM? Respond with the JSON "
        "object only — no preamble, no markdown fencing."
    )
