"""Minimal HTML->plaintext for CourtListener opinion bodies (WS3b).

Court opinion HTML is simple (paragraphs, blockquotes, citation spans), so a
stdlib ``html.parser`` tag-stripper suffices — no DOM/parsing dependency. We
drop tags, decode entities, insert paragraph breaks for block elements, skip
script/style content, and collapse runs of whitespace."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "li", "blockquote", "h1", "h2", "h3", "h4", "tr"}
_SKIP_CONTENT = {"script", "style"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """Return readable plaintext from an HTML (or already-plain) string."""
    parser = _TextExtractor()
    parser.feed(html)
    raw = parser.text()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    out: list[str] = []
    for line in lines:
        if line:
            out.append(line)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()
