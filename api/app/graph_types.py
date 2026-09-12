"""Callable contract shared by the three application graph executors.

LangGraph 1.x checks a node protocol with a named ``state`` parameter.
``Callable[[State], Awaitable[dict]]`` loses that keyword-call contract even
though every node closure accepts it. Preserve the actual async signature
without importing a private LangGraph protocol or changing runtime behavior.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol


class AsyncStateNode[StateT](Protocol):
    """An async phase node accepting state and returning a partial update."""

    def __call__(self, state: StateT) -> Awaitable[dict[str, Any]]: ...
