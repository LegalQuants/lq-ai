# #563 — Required anonymization for governed authority calls

Status: implemented locally under proposed ADR 0035 and ADR 0014 D5. No public
orchestration dispatch is enabled. ADR ratification and publication remain open.

## Scope and request contract

A governed authority call inherits `ExecutionScope.anonymize`. It can now execute
with that requirement when fresh gateway configuration advertises
`authority_anonymization_version: 1`, the named provider enables
`anonymize_outbound`, and gateway anonymization is enabled for its egress tier.
Missing capability or incompatible configuration refuses before effect admission.
The source binding records the requirement; the guard compares it with the stored
scope so a binding cannot downgrade it. Privileged classification does not waive
this explicit tool-query requirement: these arguments are distinct from the
privileged inference work product that existing middleware leaves unchanged.

The gateway client sends `require_anonymization` outside the tool's `args`, with
`X-LQ-AI-Config-Revision`. A true requirement without a revision receives HTTP 412.
The revision now hashes an envelope containing dispatch `contract_version: 2` and
the validated configuration. This prevents an older replica, which understands
configuration revisions but ignores the new body field, from accepting the call
and sending raw arguments. Callers treat the digest as opaque. Configuration-only
v1 digests no longer match; running fixture effects/checkpoints from the previous
unpublished contract must be recreated rather than assumed replay-compatible.

After revision, adapter, rate-limit and tier checks, the gateway transforms the
supported authority argument shapes with the existing local Presidio/spaCy engine.
It never falls back to raw dispatch when a required transform fails. It returns
`anonymization_applied` as a boolean; the guard requires an exact match and records
it in the effect receipt. The value means the protection pass ran, including when
it detected no entities. Missing or incorrect acknowledgements preserve an
uncertain reservation and do not permit automatic replay.

## Argument and evidence handling

Supported operations and bounds:

| Provider | Operation | Handling |
| --- | --- | --- |
| GovInfo | `search_authority` | Pseudonymize the query (at most 8,192 UTF-8 bytes); collection must be `USCODE` or `CFR`; optional page size must be an integer from 1 to 100. |
| EDGAR | `search_authority` | Pseudonymize the query with the same bound; optional form filter must match the supported comma-separated syntax and pass entity detection unchanged. |
| GovInfo | `get_authority` | Exactly one `package_id` or `granule_id`; bounded reference syntax and entity detection must pass unchanged. |
| EDGAR | `get_authority` | Bounded numeric CIK/accession plus document reference; entity detection must pass unchanged. |
| EUR-Lex | `get_authority` | Bounded supported CELEX syntax; entity detection must pass unchanged. |

Filters and reference strings are capped at 512 UTF-8 bytes. Unknown fields,
nested argument objects, unsupported operations, invalid types and malformed
references are refused before provider I/O. Detected entities in a reference or
filter cause refusal instead of substitution: pseudonymizing a document ID could
fetch a different document. Syntax and detection do not prove an ID is public.
This increment retains the existing source/resource authorization boundary.

Only free-text queries are rewritten. The mapper is local to the transform and
is discarded. Response evidence, titles and public identifiers stay verbatim;
there is no rehydration that could corrupt a source quote or replace a literal
pseudonym appearing in a public document. The provider receives neither the
requirement flag nor the revision header. The gateway audit records counts,
provider/tool/tier and the applied/refused flags, never arguments or mappings.
Validation/recognizer errors return a generic refusal without their input text.

## Limits and remaining work

This closes required anonymization for the registered governed authority profile.
It does not implement automatic anonymization for every legacy tool caller or
arbitrary MCP/CourtListener argument schemas; those callers retain their existing
behavior. A provider flag alone does not activate this checked path. Global
ADR 0014 default enforcement remains separate work. An anonymized scope cannot
use an unsupported operation or a provider that opted out.

The existing detector's legal-corpus precision/recall is unmeasured (PRD DE-282).
Pseudonymized search can lose entity-specific matches; an empty result still
means only that this query returned no candidates. The transform neither proves
zero disclosure nor guarantees research coverage. Identifiers detected as entities
may require a differently approved request rather than an automatic raw retry.
A real-engine fixture currently refuses an otherwise well-formed EDGAR filing
reference (`320193_000032019324000123_aapl-20240928.htm`); GovInfo and CELEX
reference fixtures pass unchanged. This conservative refusal limits anonymized
EDGAR retrieval. Broader identifier provenance/recognizer work remains necessary
to support those references without weakening the privacy requirement.

Shared current-policy distribution, worker scheduling/capacity, lease/wakeup and
phase reconciliation, pre-approval planning, joins and public API/UI remain in the
[feature PRD](../prds/issue-563-governed-orchestration.md). Accounting is the existing configured per-call
charge, not a provider invoice guarantee. Failed gateway calls retain conservative
uncertainty even when the gateway reports a pre-dispatch refusal.

## Validation

HTTP fixtures use the actual GovInfo adapter with stubbed HTTP and a deterministic
analyzer to check outbound pseudonyms, unchanged public results, request metadata
isolation, unsupported argument refusal, disabled/failing anonymization, and
old/missing revisions. A real local Presidio/spaCy case verifies query email
substitution. Additional shape fixtures cover EDGAR and EUR-Lex identifiers.
Postgres fixtures check capability/configuration refusal before admission,
scope/binding agreement, completed receipt reuse, and retained uncertain
reservations on missing or malformed acknowledgements. No live providers or
application databases are used.

Validation with locked dependencies:

- Full API: **2,940 passed, one skipped** in 214.25 seconds (`pytest -n 4 -q`).
- Full gateway: **835 passed, three skipped** in 11.47 seconds (`pytest -q`).
- Final gateway authority/route checks, including the subsequently added real
  reference and advertised-capability cases: **64 passed** in 2.47 seconds.
- Focused orchestration/client checks: **224 passed** in 10.61 seconds; the later
  binding-downgrade case is included in the full API run.
- Ruff check/format and mypy passed (**200 API / 58 gateway source files**).
  Gateway OpenAPI YAML parses, local references resolve, and diff checks pass.

The first focused run exposed the old guard's blanket anonymization refusal,
which was replaced with exact binding/scope agreement. Test fixtures were updated
for app configuration, the extended transport signature and receipt metadata.
All passing results above follow those corrections. The disposable database was
removed after testing; no provider credentials, live data or feature flags changed.
