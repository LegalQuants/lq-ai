"""Explicit AWS compatible-API routing; no model-name or URL guessing."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

BedrockProtocol = Literal["messages", "chat_completions", "responses"]
BedrockEndpoint = Literal["runtime", "mantle"]


def validate_bedrock_base_url(
    base_url: str, protocol: BedrockProtocol, endpoint: BedrockEndpoint
) -> str:
    """Require an AWS HTTPS origin and a documented protocol base path."""
    parsed = urlsplit(base_url)
    host_pattern = (
        r"bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?"
        if endpoint == "runtime"
        else r"bedrock-mantle\.[a-z0-9-]+\.api\.aws"
    )
    if (
        parsed.scheme != "https"
        or not re.fullmatch(host_pattern, parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Bedrock requires the selected AWS endpoint's HTTPS origin")
    paths = {"/anthropic"} if protocol == "messages" else {"/openai/v1"}
    if endpoint == "mantle" and protocol != "messages":
        paths.add("/v1")
    if parsed.path.rstrip("/") not in paths:
        raise ValueError("Bedrock base_url must include the selected protocol's base path")
    return base_url.rstrip("/")
