"""Test fixtures for the LQ.AI Slack Bridge.

``app/main.py`` constructs the FastAPI ``app`` object at module import time
(``app = create_app()``), which calls ``Settings()`` and fails if the
operator hasn't set the required Slack/LQ.AI env vars. Tests don't want
to depend on a real Slack App's secrets, so this conftest seeds the
process environment with safe fixture values BEFORE pytest collects any
test that imports from ``app.main`` (which then imports
``app.oauth``).

Individual tests construct their own app via ``create_app(settings=…)``
to inject test-specific Settings; the env-var seeding here just makes
the module-level ``app = create_app()`` line not crash on import.
"""

from __future__ import annotations

import os

_TEST_DEFAULTS = {
    "SLACK_CLIENT_ID": "test-client-id",
    "SLACK_CLIENT_SECRET": "test-client-secret",
    "SLACK_SIGNING_SECRET": "test-signing-secret",
    "LQ_AI_BACKEND_URL": "http://api.test",
    "LQ_AI_BRIDGE_TOKEN": "test-bridge-token",
    "LQ_AI_BRIDGE_PUBLIC_URL": "https://bridge.test",
}

for key, value in _TEST_DEFAULTS.items():
    os.environ.setdefault(key, value)
