"""Hypothesis profiles for the gateway property suite — DE-230.

Three profiles, selected via the ``HYPOTHESIS_PROFILE`` environment
variable (default ``dev``). Registration lives in this per-directory
conftest so the rest of the gateway suite never imports Hypothesis.

* ``dev`` — the default for local iteration. Small example budget so
  the fast feedback loop stays fast.
* ``ci`` — the per-PR gate (``ci.yml`` exports
  ``HYPOTHESIS_PROFILE=ci``). Bounded example count so CI time is
  predictable, and ``derandomize=True`` so the gate is deterministic:
  the same example sequence runs on every CI invocation — a
  fail-closed gate must not flake on an unlucky seed.
* ``thorough`` — the deep run (nightly / manual, see
  ``docs/security/property-tests.md``). Randomized so repeated runs
  explore new ground; ``print_blob=True`` prints the
  ``@reproduce_failure`` blob for any find so it can be pinned.

``deadline=None`` on every profile is deliberate and load-bearing:
Hypothesis's default 200 ms per-example deadline flakes on shared CI
runners (and the first real-Presidio example pays a multi-second spaCy
model load). Hypothesis itself disables the deadline when it detects
CI for exactly this reason; we make it explicit so local == CI.
"""

from __future__ import annotations

import os

from hypothesis import settings

settings.register_profile(
    "dev",
    max_examples=25,
    deadline=None,
    print_blob=True,
)
settings.register_profile(
    "ci",
    max_examples=50,
    deadline=None,
    derandomize=True,
    print_blob=True,
)
settings.register_profile(
    "thorough",
    max_examples=1000,
    deadline=None,
    print_blob=True,
)

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
