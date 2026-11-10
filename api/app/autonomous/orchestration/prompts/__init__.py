"""The engine's own system prompts: versioned files, not skills (ADR 0038 D3).

A run profile may pin a prompt file instead of an installed skill. The file's
whole text is the system message, exactly as written; nothing is added to it
and nothing is substituted in it. Standing instructions live in the file. The
facts of one run (the request, the thread, the documents, the date, the limits)
are assembled into the opening message by :mod:`..assembly`.

Rules for the files:

* A name is ``<family>/<role>.v<N>``, for example ``new_harness/orchestrator.v1``,
  and resolves to ``<family>/<role>.v<N>.md`` beside this module.
* A released file is never edited. A change is a new file with the next
  version, so every retained run can show the exact text it ran on, and a pin
  whose digest no longer matches its file is refused rather than run.
* A prompt is not in the skill library. It cannot be attached to a chat, and a
  prompt name is never resolved against installed skills.

These are engine prompts and are reviewed as code. They are not skills under
``skills/CONTRIBUTING.md``; whether any of them needs an attorney's attestation
is the maintainers' decision.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.autonomous.orchestration.contracts import SkillPin
from app.errors import Forbidden

_ROOT = Path(__file__).resolve().parent
_NAME = re.compile(
    r"^(?P<family>[a-z][a-z0-9_]{0,31})/(?P<role>[a-z][a-z0-9_]{0,31})\.v(?P<n>[1-9][0-9]{0,3})$"
)
MAX_PROMPT_BYTES = 32768


@dataclass(frozen=True)
class PinnedPrompt:
    """One prompt file as it is sent: its pin, its text and its version."""

    pin: SkillPin
    text: str
    family: str
    role: str
    version: int


def load_prompt(name: str) -> PinnedPrompt:
    """Read one versioned prompt and hash exactly the text that is sent.

    Refuses a name outside the naming rule, so a pin can never be made to read
    another file. Refuses a missing, empty or oversized file.
    """
    match = _NAME.fullmatch(name) if isinstance(name, str) else None
    if match is None:
        raise Forbidden(message="Pinned prompt name is invalid")
    path = _ROOT / match["family"] / f"{match['role']}.v{match['n']}.md"
    try:
        text = path.read_text("utf-8").strip()
    except (OSError, UnicodeError):
        raise Forbidden(message="Pinned prompt is unavailable") from None
    if not 1 <= len(text.encode("utf-8")) <= MAX_PROMPT_BYTES:
        raise Forbidden(message="Pinned prompt is empty or exceeds its bound")
    return PinnedPrompt(
        pin=SkillPin(
            name=name, digest=hashlib.sha256(text.encode("utf-8")).hexdigest(), kind="prompt"
        ),
        text=text,
        family=match["family"],
        role=match["role"],
        version=int(match["n"]),
    )
