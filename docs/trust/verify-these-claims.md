# Check the claims yourself

Every page in this section makes a claim and links it to source code, a local test, or outside
evidence that is still needed. Use the kind of check that answers the particular question. Most of
this doesn't require a running deployment — it works against a plain clone of the repository, except
where noted.

## Repeat the setup checks

Clone the repository and note the commit you're checking against:

```bash
git clone https://github.com/LegalQuants/lq-ai.git
cd lq-ai
```

Every path cited on every trust-centre page is inside this clone. Use a separate installation with
made-up data — never real client documents — and check startup, sign-in, upload and the expected
error messages before you connect an AI model.

## Read the result with its evidence

A declared setting can be checked by reading code. Whether a complete task actually succeeds needs a
test run. Keep those two kinds of check apart, and don't accept a design document alone as evidence
for either.

The honest catalog at [`docs/HONEST-STATE.md`](../HONEST-STATE.md) applies the same discipline: for
every capability it lists, its Verification column names a **file path** or a **test command**. If a
claim on this site and the codebase ever disagree, the codebase is canonical; please
[open an issue](https://github.com/LegalQuants/lq-ai/issues).

## Match the check to the proposition

For a default, read the declared value and the Compose overrides. For an access rule, follow the
route and authorization check and test both the permitted and the refused case. For a stored record,
inspect the schema and the code that writes it. For an installation promise, run that exact
installation in a disposable environment. A design document alone can't establish any of these.

### Details: per-page verification

The table below is the concrete version of that, one row per claim, organized by the trust-centre
page each one backs:

| Claim | Verify with |
|---|---|
| [Threat model](../security/threat-model.md) — the STRIDE mitigations | Read the cited file (e.g. `api/app/security/jwt.py`, `gateway/app/api/dependencies.py`) directly against the "Mitigation" cell that names it. |
| [Anonymization](../security/anonymization.md) — the round-trip guarantee | `cd gateway && pytest tests/anonymization/ tests/test_inference_anonymization.py` |
| [Anonymization](../security/anonymization.md) — what is *not* validated | `gateway/app/anonymization/engine.py` — read `DISABLED_DEFAULT_RECOGNIZERS` and the enabled recognizer list directly; no test suite claims recall/precision numbers, because none exist as of the checked commit (a community measurement is open in PR #439 / DE-240, not yet merged). |
| [Audit & evidence](../security/audit-logging.md) — the audit-write invariant | `api/app/audit.py` — one function, `audit_action()`, is the only writer; read it to confirm the transaction boundary claim. |
| [Audit & evidence](../security/audit-logging.md) — the matter-scoped queries | Run the two `SELECT` statements on that page's source against a migrated database — the schema they reference is [`docs/db-schema.md`](../db-schema.md)'s `citation_ledger_entry` and `inference_routing_log` tables. |
| [Supply chain](../security/releases/README.md) — image signing | `cosign verify --certificate-identity-regexp "https://github.com/legalquants/lq-ai" --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/legalquants/lq-ai-api:vX.Y.Z` |
| [Supply chain](../security/releases/README.md) — SLSA build provenance | `gh attestation verify oci://ghcr.io/legalquants/lq-ai-api:vX.Y.Z --owner legalquants --signer-workflow LegalQuants/lq-ai/.github/workflows/build-image.yml` — Build Level 3, for releases after v0.7.1. For v0.7.1 and earlier, drop `--signer-workflow`: those carry Build Level 2 provenance signed by `release.yml`. |
| [Published gaps](../HONEST-STATE.md) — the test-file counts | `find api/tests -name 'test_*.py' | wc -l` and the equivalent for `gateway/tests/` and `web/src` — compare against the counts named in HONEST-STATE §8. |
| [Governance](../../GOVERNANCE.md) | Compare `GOVERNANCE.md`'s header line against [ADR 0022](../adr/0022-committee-governance-and-meeting-records.md)'s `Status: Accepted` line. |
| [Continuity](continuity.md) — where data lives | `grep -A5 "^volumes:" docker-compose.yml` — lists `pgdata`, `redisdata`, `miniodata` and `ollamadata` as named, operator-controlled volumes. |

## Be careful with claims that something is absent

Search the relevant implementation, registration points, configuration and tests — not just a single
filename. Say where you looked and which version you checked. "Not found in the reviewed login path"
is narrower and more defensible than "does not exist anywhere." Real deployments, provider terms and
historical artifacts may need evidence outside the repository.

Several claims on this site — the un-shipped NIST/OWASP mappings, the desktop signing bottleneck — are
claims that something does *not* exist. Verify those the same way: `grep` for the thing that would
exist if the claim were false, and confirm it isn't there. A negative result from a specific, named
search is evidence; an absence you have to take on trust is not, and this site tries not to ask for
the second kind.

## Next

- [Published gaps](../HONEST-STATE.md) — the fullest single verification table in the project.
