# Property-based testing (Hypothesis) — DE-230

> **Status:** active. Runs on every PR (`ci.yml`, profile `ci`).
> **Scope:** parsers, normalizers, and round-trip encoders — the code whose
> correctness is an *algebraic contract*, not a workflow. Endpoint-level
> behavior stays with the example-based suites; DB-backed flows are out of
> scope by design.

Property tests generate hundreds of inputs per invariant instead of a
hand-picked few. They live in:

- `gateway/tests/property/` — anonymization round-trip, streaming
  rehydration, pseudonym mapper, tier-floor refusal, tier derivation.
- `api/tests/property/` — citation normalization and citation locators.

Hypothesis (MPL-2.0) is a **dev-only** dependency in both packages'
`[dev]` extras; it never ships in a product image, so the file-level
copyleft has no distribution consequence.

---

## The invariants, in plain language

### Gateway — anonymization (the security boundary)

| Property | Invariant |
|---|---|
| Round-trip identity (stub analyzer) | Pseudonymizing a text and rehydrating the result returns the original **byte-for-byte**, whatever set of entity spans the analyzer reports. A lawyer's work product must come back exactly as written; "close" is corruption. |
| Round-trip identity (real Presidio engine, `slow`) | Same invariant under the production AnalyzerEngine (spaCy NER + pattern + custom legal recognizers), so real — messy, overlapping — detections exercise the span math. Detection-agnostic, so stable across Presidio/spaCy upgrades. |
| Multi-message mapper reuse | One mapper threaded through several messages (the middleware pattern) still round-trips every message, with stable pseudonyms across messages. |
| Overlap collapse | Duplicate and nested recognizer hits on the same region collapse to a single substitution and still round-trip. |
| **No recognized entity survives** | No character of any analyzer-recognized entity remains in the provider-bound text (proved exactly via a disjoint-alphabet construction; plus a real-engine variant: no generated email address survives). This is the fail-closed half of the anonymization promise and **partially delivers DE-240** — the *recall* half (does the analyzer recognize the PII at all?) remains DE-240 corpus work. |
| Streaming split-invariance | Splitting the response stream at **arbitrary** positions — including mid-pseudonym and character-at-a-time — yields exactly the one-shot rehydration result. Chunking is a transport detail; it must never change what the user reads. |
| Mapper algebra | Pseudonym assignment is stable per `(type, original)`, injective (two originals never share a pseudonym — the worst failure would swap one party's name for another's), format-locked, with independent per-type counters and an exact reverse table. |

Known exclusion: source text already containing a literal
pseudonym-shaped string (`PERSON_0001`-like) is the **DE-274** known
issue; the strategies filter that shape so the suite pins the supported
contract instead of rediscovering it. The shape itself is covered by an
explicit example test in `gateway/tests/anonymization/test_round_trip.py`.

### Gateway — tier enforcement (PRD §1.5.2 / §4.4)

| Property | Invariant |
|---|---|
| Effective floor | The resolved floor is the *minimum* declared value across request / project / skill floors (lower tier number = stronger security; strictest wins), or no floor when nothing declares one. |
| Refusal iff too weak | A request is refused **exactly when** the routed tier is weaker (higher-numbered) than the strictest declared floor — never served below a declared floor, never refused when every floor allows it. |
| Monotonicity | If tier *t* is allowed, every stronger tier is allowed; if refused, every weaker tier is refused. |
| Provenance | The 403's `details.source` deterministically names a source that declared the binding value (request > project > skill in attachment order). |
| Tier derivation | `derive_routed_inference_tier` honors the documented lookup order (pair override → provider override → type default → provider `tier:`) and always yields a tier in 1–5. |

### API — citation verification substrate

| Property | Invariant |
|---|---|
| Canonical form | `normalize()` output never contains smart quotes, `\r`, whitespace runs, or non-space whitespace, and is stripped — for both OCR modes. |
| Idempotence (always-on layer) | `normalize(normalize(t)) == normalize(t)` with `was_ocrd=False`, per the module's documented contract. |
| Comparison insensitivity | Whitespace layout (doubled spaces, newlines-for-spaces) and quote style (typographic vs straight) never change the canonical form — precisely the differences Stage 2 exists to forgive. |
| Locator fidelity | `locate_passage` / `locate_in_chunk` (exact path): a quote genuinely present in the source locates to offsets whose slice **is** the quote — never an off-by-N span — and whitespace padding around the quote never moves the span. `locate_passage` never fabricates a span for absent text. Fuzzy-path results are always in-bounds. |

Not covered here: the DE-375 external-ref key encoder round-trip — that
encoder is not on `main` at the time of writing; add the property when it
lands.

---

## Known bug found by this suite (deliberately not fixed here)

**OCR-layer normalization is not idempotent**, contradicting
`api/app/citation/normalization.py`'s documented contract ("The function
is idempotent … for every input"), which the Stage-2 verifier relies on
for re-run symmetry. The `l→1` and `O→0` rules each run in a single
pass, and a substitution can create a *new* digit adjacency that only a
second pass would rewrite:

```
normalize("Ol5", was_ocrd=True)  == "O15"   # l→1 fires; O had no digit neighbor yet
normalize("O15", was_ocrd=True)  == "015"   # now it does
```

(Also `ll5 → l15 → 115`, `5lO → 51O → 510`.) Pinned as a **strict
xfail** in
`api/tests/property/test_normalization_properties.py::test_ocr_layer_idempotence_violation_is_pinned`.
Fixing it (iterating the OCR rules to a fixed point, or reordering the
digit-adjacency rules) changes verifier-visible canonical forms for
OCR'd documents, so the fix needs a maintainer decision on the intended
semantics rather than a drive-by patch. Practical blast radius today:
only affects `was_ocrd=True` comparisons where letter/digit confusions
are chained (`Ol5`-like sequences); a single normalize pass is still
applied identically to both sides of every comparison, so verification
outcomes remain internally consistent per run.

---

## Profiles and budgets

Profiles are registered in `{api,gateway}/tests/property/conftest.py`
and selected with the `HYPOTHESIS_PROFILE` environment variable
(default `dev`). Every profile sets `deadline=None`: Hypothesis's
default 200 ms per-example deadline flakes on shared CI runners (and
the first real-Presidio example pays the spaCy model load), and a
fail-closed gate must not flake.

| Profile | max_examples | Randomization | Where | Measured runtime* |
|---|---|---|---|---|
| `dev` | 25 | random seed | local default | ~1 s + ~1 s per package |
| `ci` | 50 | **derandomized** (fixed example sequence) | every PR via `ci.yml` | gateway ~2 s, api ~0.5 s |
| `thorough` | 1000 | random seed, `print_blob=True` | nightly / manual | gateway ~16 s, api ~4 s |

\* Apple-silicon dev machine, spaCy model warm on disk; CI runners are
slower but the suite is a rounding error next to the rest of the run.

**Seed policy.** The PR gate is derandomized: the same example sequence
runs every time, so a red gate is reproducible by anyone and a green
gate can't be luck. Exploration of *new* inputs is the `thorough`
profile's job — it runs randomized, and `print_blob=True` emits an
`@reproduce_failure(...)` blob for any find, which gets pinned as an
explicit regression test (or a strict xfail, as with the OCR bug above)
rather than relying on the local `.hypothesis` example database.

**Running locally:**

```bash
# fast iteration (dev profile is the default)
cd gateway && pytest tests/property -q
cd api     && pytest tests/property -q

# exactly what CI runs
HYPOTHESIS_PROFILE=ci pytest tests/property -q

# the deep run
HYPOTHESIS_PROFILE=thorough pytest tests/property -q
```

**Nightly `thorough` run — current status: manual.** The nightly
scheduled workflow (mutation testing, DE-229) is landing on a separate
branch; duplicating scheduled-workflow scaffolding here would guarantee
a merge conflict for ~20 seconds of compute. Until the branches
converge, the `thorough` profile is a documented manual command (above);
**TODO(DE-230):** once the nightly workflow is on `main`, add one step
per package: `HYPOTHESIS_PROFILE=thorough pytest tests/property -q`.

---

## Authoring guidance

- Put properties in `tests/property/`; keep example-based tests where
  they are. A property file should test one module's contract.
- Budget centrally: never set `max_examples` per-test — the profile is
  the single knob CI relies on. Per-test `@settings` may only *add*
  health-check suppressions.
- If a property finds a real bug, do not fix it silently inside the
  test PR: pin the counterexample as a deterministic strict-xfail test
  naming the finding (see the OCR example), and surface the decision to
  the maintainer. A property suite that quietly absorbs bug-fixes hides
  exactly the information it exists to produce.
- Gateway anonymization strategies live in
  `gateway/tests/property/strategies.py` — extend those rather than
  re-inventing entity-document generation (the DE-274 exclusion is
  encoded there once).
