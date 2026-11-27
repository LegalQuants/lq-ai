"""Unwrap one JSON answer without interpreting surrounding model prose."""

from __future__ import annotations

import json
import re


def unwrap_json_answer(content: str) -> str:
    """Accept one JSON answer, allowing the local model's response wrappers.

    Identical repeated fences contain one answer. Different blocks, multiple
    bare answers, malformed JSON, and trailing prose after bare JSON stay
    invalid. No answer text or source language is repaired here.
    """
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        return stripped
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL)
    if (
        blocks
        and stripped.count("```") == 2 * len(blocks)
        and len({b.strip() for b in blocks}) == 1
    ):
        return blocks[0].strip()
    if "```" not in stripped:
        start = re.search(r"(?m)^[ \t]*[\{\[]", stripped)
        if start:
            candidate = stripped[start.start() :].lstrip()
            try:
                _, end = json.JSONDecoder().raw_decode(candidate)
            except json.JSONDecodeError:
                return stripped
            if not candidate[end:].strip():
                return candidate[:end]
    return stripped
