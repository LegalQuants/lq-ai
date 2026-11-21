"""Unwrap one JSON answer without interpreting surrounding model prose."""

from __future__ import annotations

import re


def unwrap_json_answer(content: str) -> str:
    """Accept bare JSON or one complete fenced block, with optional prose.

    Multiple blocks are ambiguous and remain invalid. JSON parsing and
    shape validation belong to the caller; no answer text is repaired.
    """
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        return stripped
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL)
    if len(blocks) == 1 and stripped.count("```") == 2:
        return blocks[0].strip()
    return stripped
