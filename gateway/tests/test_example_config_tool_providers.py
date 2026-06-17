"""Regression test: gateway.yaml.example ships with tool_providers commented out.

The example file documents the tool_providers block (ADR 0014) but keeps it
commented so the default stack is unchanged (empty list). This test guards that:

1. The example loads cleanly with load_config (YAML is valid, no schema errors).
2. tool_providers defaults to [] when the block is commented out.

If a future contributor accidentally uncommenting the block without supplying
real secrets, this test surfaces the failure at CI rather than at operator
deploy time.
"""

from __future__ import annotations

import pytest

from app.config_loader import load_config
from tests.conftest import EXAMPLE_CONFIG


@pytest.mark.unit
def test_example_config_has_commented_tool_providers(example_env: None) -> None:
    """The example loads cleanly; the tool_providers block ships commented so
    the default stack is unchanged (empty list)."""
    cfg = load_config(EXAMPLE_CONFIG)
    assert cfg.tool_providers == []
