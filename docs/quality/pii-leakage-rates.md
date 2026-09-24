# PII Leakage Rates — Anonymization Layer (DE-240)

> **Status of these numbers:** measured, not aspirational. They are produced by a
> deterministic local harness running the real anonymization engine over a labeled
> synthetic corpus, and several of them are bad. Publishing the bad numbers is the
> point — a miss in this layer is a silent confidentiality incident, so operators
> deserve the measured rates, not a claim.

- **Measured:** 2026-07-25 (macOS arm64, gateway venv; Python 3.12)
- **Engine under test:** the exact production configuration constructed by
  [`gateway/app/anonymization/engine.py::get_analyzer_engine`](../../gateway/app/anonymization/engine.py)
- **Environment:** presidio-analyzer 2.2.364 · presidio-anonymizer 2.2.360 ·
  spacy 3.8.14 · en_core_web_lg 3.8.0
- **Corpus:** [`tests/pii/corpus/pii_corpus.json`](../../tests/pii/corpus/pii_corpus.json)
  — 71 entries, 80 expected entity occurrences, all values synthetic
- **Baseline (anti-regression pin):**
  [`tests/pii/baseline/pii_leakage_baseline.json`](../../tests/pii/baseline/pii_leakage_baseline.json)

## Methodology

The harness ([`gateway/tests/anonymization/pii_leakage.py`](../../gateway/tests/anonymization/pii_leakage.py))
runs every corpus entry through `Anonymizer.pseudonymize_into` against the real
Presidio `AnalyzerEngine` (spaCy `en_core_web_lg` backbone) and scores the
anonymized output:

- **Full leak** — the expected entity value survives verbatim (case-sensitive
  substring) in the anonymized text. The provider would receive the exact PII string.
- **Partial leak** — the full value is broken up, but a *significant token* of it
  survives (length ≥ 4, excluding generic structural/corporate words like "Avenue"
  or "Corporation"). The provider would receive an identifying fragment.

The unit of measurement is the expected entity occurrence, not the corpus entry.
This measures **leakage, not classification accuracy**: an entity substituted under
the "wrong" type (e.g. a passport number caught by the bank-number recognizer)
still counts as protected, because the original text never reaches the provider.

Corpus classes mirror the recognizer set the gateway actually registers — six kept
Presidio defaults (`PERSON`, `ORGANIZATION`, `EMAIL_ADDRESS`, `PHONE_NUMBER`,
`US_BANK_NUMBER`, `LOCATION`) plus two custom legal recognizers (`CASE_NUMBER`,
`MATTER_NUMBER`) — crossed with format variants (canonical, mid-sentence, list
context, spaced, punctuated, all-caps, non-Anglo/unicode names, international
phone formats). A **known-untargeted** section documents classes the configuration
deliberately does not cover (see below).

Reproduce (fully offline, deterministic for a fixed model/version set):

```bash
cd gateway
.venv/bin/python -m tests.anonymization.pii_leakage --markdown   # rate tables
.venv/bin/python -m tests.anonymization.pii_leakage              # full JSON report
```

## Measured rates — per class

Measured 2026-07-25 — presidio-analyzer 2.2.364, presidio-anonymizer 2.2.360, spacy 3.8.14, en_core_web_lg 3.8.0.

| Class | Targeted | Entities | Full-leak rate | Partial-leak rate |
|---|---|---:|---:|---:|
| PERSON | yes | 12 | 0.0% | 0.0% |
| ORGANIZATION | yes | 10 | **100.0%** | 0.0% |
| EMAIL_ADDRESS | yes | 9 | 0.0% | 11.1% |
| PHONE_NUMBER | yes | 11 | 0.0% | 0.0% |
| US_BANK_NUMBER | yes | 5 | 0.0% | 0.0% |
| LOCATION | yes | 10 | 0.0% | 20.0% |
| CASE_NUMBER | yes | 8 | 12.5% | 0.0% |
| MATTER_NUMBER | yes | 7 | 14.3% | 0.0% |
| CREDIT_CARD | no (out of scope, measured informationally) | 1 | 0.0% | 0.0% |
| DATE_OF_BIRTH | no | 1 | 0.0% | 0.0% |
| EIN | no | 1 | 100.0% | 0.0% |
| IBAN_CODE | no | 1 | 100.0% | 0.0% |
| IP_ADDRESS | no | 1 | 100.0% | 0.0% |
| US_DRIVER_LICENSE | no | 1 | 100.0% | 0.0% |
| US_PASSPORT | no | 1 | 0.0% | 0.0% |
| US_SSN | no | 1 | 100.0% | 0.0% |

## Measured rates — per variant

| Class | Variant | n | Full leaks | Partial leaks |
|---|---|---:|---:|---:|
| PERSON | all_caps | 1 | 0 | 0 |
| PERSON | canonical | 2 | 0 | 0 |
| PERSON | list_context | 3 | 0 | 0 |
| PERSON | mid_sentence | 1 | 0 | 0 |
| PERSON | non_anglo | 3 | 0 | 0 |
| PERSON | punctuated | 1 | 0 | 0 |
| PERSON | surname_first | 1 | 0 | 0 |
| ORGANIZATION | all_caps | 1 | 1 | 0 |
| ORGANIZATION | canonical | 2 | 2 | 0 |
| ORGANIZATION | law_firm | 1 | 1 | 0 |
| ORGANIZATION | list_context | 3 | 3 | 0 |
| ORGANIZATION | mid_sentence | 1 | 1 | 0 |
| ORGANIZATION | no_suffix | 1 | 1 | 0 |
| ORGANIZATION | unicode | 1 | 1 | 0 |
| EMAIL_ADDRESS | all_caps | 1 | 0 | 0 |
| EMAIL_ADDRESS | canonical | 1 | 0 | 0 |
| EMAIL_ADDRESS | list_context | 2 | 0 | 0 |
| EMAIL_ADDRESS | mid_sentence | 1 | 0 | 0 |
| EMAIL_ADDRESS | plus_address | 1 | 0 | 0 |
| EMAIL_ADDRESS | punctuated | 1 | 0 | 0 |
| EMAIL_ADDRESS | spaced | 1 | 0 | 1 |
| EMAIL_ADDRESS | subdomain | 1 | 0 | 0 |
| PHONE_NUMBER | canonical | 1 | 0 | 0 |
| PHONE_NUMBER | extension | 1 | 0 | 0 |
| PHONE_NUMBER | international | 3 | 0 | 0 |
| PHONE_NUMBER | list_context | 2 | 0 | 0 |
| PHONE_NUMBER | mid_sentence | 1 | 0 | 0 |
| PHONE_NUMBER | punctuated | 2 | 0 | 0 |
| PHONE_NUMBER | spaced | 1 | 0 | 0 |
| US_BANK_NUMBER | canonical | 1 | 0 | 0 |
| US_BANK_NUMBER | labeled | 1 | 0 | 0 |
| US_BANK_NUMBER | mid_sentence | 1 | 0 | 0 |
| US_BANK_NUMBER | punctuated | 1 | 0 | 0 |
| US_BANK_NUMBER | spaced | 1 | 0 | 0 |
| LOCATION | canonical | 2 | 0 | 0 |
| LOCATION | list_context | 3 | 0 | 0 |
| LOCATION | mid_sentence | 2 | 0 | 0 |
| LOCATION | street_address | 2 | 0 | 2 |
| LOCATION | unicode | 1 | 0 | 0 |
| CASE_NUMBER | canonical | 2 | 0 | 0 |
| CASE_NUMBER | docket | 2 | 0 | 0 |
| CASE_NUMBER | lowercase | 1 | 0 | 0 |
| CASE_NUMBER | mid_sentence | 1 | 0 | 0 |
| CASE_NUMBER | spaced | 1 | 1 | 0 |
| CASE_NUMBER | state_reporter | 1 | 0 | 0 |
| MATTER_NUMBER | canonical | 1 | 0 | 0 |
| MATTER_NUMBER | dotted | 1 | 1 | 0 |
| MATTER_NUMBER | list_context | 2 | 0 | 0 |
| MATTER_NUMBER | lowercase | 1 | 0 | 0 |
| MATTER_NUMBER | mid_sentence | 1 | 0 | 0 |
| MATTER_NUMBER | punctuated | 1 | 0 | 0 |
| CREDIT_CARD | canonical | 1 | 0 | 0 |
| DATE_OF_BIRTH | canonical | 1 | 0 | 0 |
| EIN | canonical | 1 | 1 | 0 |
| IBAN_CODE | canonical | 1 | 1 | 0 |
| IP_ADDRESS | canonical | 1 | 1 | 0 |
| US_DRIVER_LICENSE | canonical | 1 | 1 | 0 |
| US_PASSPORT | canonical | 1 | 0 | 0 |
| US_SSN | canonical | 1 | 1 | 0 |

## Findings (honest, root-caused)

### 1. ORGANIZATION leaks 100% — the documented "enabled" recognizer never fires

Every organization name in the corpus — `Meridian Fabrication LLC`, `Delacroix &
Marsh LLP`, all ten — reached the anonymized output verbatim. Root cause,
verified during measurement: raw spaCy `en_core_web_lg` detects these spans as
`ORG` correctly, but Presidio's **default** `AnalyzerEngine` NLP configuration
ships `ORGANIZATION` in `labels_to_ignore` (Presidio suppresses it by default
because of its false-positive rate on general text). The gateway constructs
`AnalyzerEngine(registry=...)` without overriding the NLP-engine configuration,
so the suppression applies. The `ENABLED_DEFAULT_RECOGNIZERS` tuple in
`engine.py` that lists `ORGANIZATION` is documentation only — nothing in the
code path enforces it.

**Consequence for operators today:** company names — counterparties, clients,
targets in M&A matters — are NOT pseudonymized. Treat any matter where the
organization's identity is itself confidential accordingly (Tier 1 local routing
per `docs/security/anonymization.md`).

**Not fixed in this change deliberately:** un-ignoring `ORGANIZATION` is a
behavior change inside the security boundary with a known precision cost (the
reason Presidio suppresses it), which is exactly the recall/precision trade-off
DE-282's legal-corpus validation exists to calibrate. Needs a maintainer
decision; the drift pin will make the improvement visible when it lands.

### 2. Custom-recognizer format edges

- **`MATTER_NUMBER` dotted form at sentence end** (14.3% class rate): the
  pattern `2025.0138.` — a dotted matter number followed by the sentence's
  period — is missed because the recognizer's trailing guard `(?![\d.])` treats
  the sentence-final period as part of a longer decimal. Verified: the analyzer
  returns zero results for that sentence.
- **`CASE_NUMBER` spaced docket** (12.5% class rate): `Case No. 1:24 - cv - 00317`
  (spaces around hyphens, as OCR or sloppy transcription produces) defeats the
  docket regex.

### 3. Partial leaks: street addresses and spaced emails

- **Street addresses**: spaCy catches the city/state (`Springfield, Illinois`)
  but the house number and street name (`1247 Marlowe`…) and the ZIP (`59801`)
  survive — 2 of 2 street-address entries partially leak. The surviving fragment
  is enough to identify a premises.
- **Spaced email** (`elena . marchetti @ quarrybend-example . com`): the email
  recognizer misses the spaced form; identifying tokens (`quarrybend`) survive.

### 4. What the configuration deliberately does not cover (known-untargeted)

`engine.py` disables `UsSsnRecognizer`, `UsPassportRecognizer`,
`UsLicenseRecognizer`, `CryptoRecognizer`, `IbanRecognizer`, `IpRecognizer`, and
`MedicalLicenseRecognizer` (false-positive rationale documented inline there),
and no recognizer targets EINs. As measured: **SSNs, EINs, driver's licenses,
IPs, and IBANs pass through to the provider verbatim (100% leak)**. Operators
whose corpus contains these re-enable per-recognizer in their deployment per
`docs/security/anonymization.md`.

Two untargeted classes were caught *incidentally* — attribute honestly, don't
count on them:

- The passport number was substituted by `UsBankRecognizer` at confidence 0.05
  (a nine-digit number resembles an account number). Fragile, not a guarantee.
- The date of birth was caught by `DATE_TIME` and the credit card by
  `CREDIT_CARD` — recognizers that are **registered but not documented** in
  `ENABLED_DEFAULT_RECOGNIZERS`. The measured registry also includes
  `DateRecognizer`, `CreditCardRecognizer`, `MacAddressRecognizer`,
  `NhsRecognizer`, `UrlRecognizer`, and `UsItinRecognizer`: the enable-list in
  `engine.py` is descriptive, the disable-list is what's enforced. The full
  measured recognizer inventory is embedded in every harness report
  (`metadata.recognizers`).

## Configurations: NER backends and inference tiers

- **NER backend:** the gateway supports exactly one backend today — Presidio's
  default spaCy engine with `en_core_web_lg`. There is no alternative-backend
  configuration surface, so the DE-240 "per NER backend" matrix collapses to
  this single measured column. If a transformer or alternative-model backend
  ever lands, it gets its own measured column here before it ships.
- **Inference tiers:** anonymization applies at the tiers listed in
  `anonymization.apply_at_tiers` (gateway config); the engine and therefore
  these rates are identical at every tier where it applies. At tiers where it
  does not apply (typically Tier 1 local, where the prompt never leaves the
  operator's environment), the leakage question is moot by construction.
  Privileged chats and per-request opt-outs skip anonymization entirely —
  those paths send original text by design (PRD §4.7 Decision A).

## Adversarial extraction (response path)

Fixtures at [`tests/pii/extraction/extraction_prompts.json`](../../tests/pii/extraction/extraction_prompts.json)
attack the response path: plant synthetic PII, then ask the model for a
*transformed* rendering (surname reversed, name letter-spelled, digits reversed,
base64, `[at]`-obfuscated email). The transformation is load-bearing — the
gateway rehydrates pseudonyms in responses, so the original value legitimately
reappears whenever the model echoes a pseudonym; only a transformed rendering
proves the provider saw raw PII. `tests/pii/test_fixture_integrity.py` enforces
deterministically (keyless, in CI-able form) that no leak indicator could
false-positive on a legitimate round-trip.

Two structural guarantees are pinned without any live model:

- the serialized provider-bound request contains pseudonyms only, and carries no
  reference to the mapper or its reverse table
  (`gateway/tests/anonymization/test_provider_payload_isolation.py`);
- the mapper never reaches logs or audit rows
  (`gateway/tests/anonymization/test_round_trip.py`, invariant 4).

The end-to-end check needs a live provider, so it is a **maintainer-run step**,
guarded off by default:

```bash
LQ_PII_LIVE=1 LQ_PII_GATEWAY_URL=http://127.0.0.1:8100 \
    pytest tests/pii/test_extraction_live.py -m live -rs
```

A failure (leak indicator in a response) is a confidentiality-incident signal.
A pass is evidence, not proof — model outputs are nondeterministic.

## CI integration and the anti-regression pin

`gateway/tests/anonymization/test_pii_leakage_rates.py` (marked `slow`, runs in
the normal gateway `pytest -q` suite) gates on two things only:

1. the harness runs and scores the complete corpus (the measurement capability
   must not rot), and
2. **no targeted class's full-leak rate worsens by more than 5 percentage
   points** versus the committed baseline.

The absolute rates are deliberately not gated — they are informational until
DE-282 calibrates recognizer accuracy on a real legal-document corpus. The pin
exists to catch *drift*: a Presidio/spaCy upgrade or config change that silently
starts leaking a class that used to be caught. Suite cost: ~2-4s added to the
gateway run (one spaCy model load, ~71 analyze calls).

After a deliberate corpus or engine change, regenerate the baseline and refresh
the tables in this document:

```bash
cd gateway
.venv/bin/python -m tests.anonymization.pii_leakage --write-baseline
.venv/bin/python -m tests.anonymization.pii_leakage --markdown
```

## Per-release process

Re-run the two commands above on the release branch, update the tables and the
"Measured" date here, and note any rate movement in the release notes. Rates are
attributed to the exact `presidio-analyzer` / `spacy` / `en_core_web_lg`
versions in the report metadata; a version bump without a rate re-measurement is
a release-checklist violation.

## Relationship to DE-282

This corpus is synthetic and format-focused: it measures how the engine handles
entity *format variants* under controlled conditions. It does **not** measure
recall/precision on real legal documents — annotated contracts, briefs, and
correspondence with natural context — which is DE-282's scope. When DE-282's
curated corpus lands, its recall numbers supersede these for "will my actual
documents leak" questions; the two harnesses share the same engine entry point
and can share fixture conventions.
