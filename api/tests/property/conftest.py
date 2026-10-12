"""Hypothesis profiles for the api property suite — DE-230.

Three profiles, selected via the ``HYPOTHESIS_PROFILE`` environment
variable (default ``dev``). Registration lives in this per-directory
conftest so the rest of the api suite never imports Hypothesis. The
profile definitions intentionally mirror
``gateway/tests/property/conftest.py`` — the two services share no
in-process code (adapters cross the boundary explicitly), so the
few-line duplication is the honest cost of that rule.

* ``dev`` — the default for local iteration; small example budget.
* ``ci`` — the per-PR gate (``ci.yml`` exports
  ``HYPOTHESIS_PROFILE=ci``). Bounded example count for predictable
  CI time; ``derandomize=True`` so the gate is deterministic — a
  fail-closed gate must not flake on an unlucky seed.
* ``thorough`` — the deep run (nightly / manual, see
  ``docs/security/property-tests.md``). Randomized so repeated runs
  explore new ground; ``print_blob=True`` prints the
  ``@reproduce_failure`` blob for any find so it can be pinned.

``deadline=None`` on every profile is deliberate and load-bearing:
Hypothesis's default 200 ms per-example deadline flakes on shared CI
runners. Hypothesis itself disables the deadline when it detects CI
for exactly this reason; we make it explicit so local == CI.
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
