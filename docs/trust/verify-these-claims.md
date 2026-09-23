# Verify these claims yourself

Every page in the trust section makes a claim and names the file it traces to. This page collects
the actual commands: what to run, what to read, and what a passing result looks like, organized by
the trust-centre page each one backs. None of this requires access to a running deployment except
where noted — most of it works against a plain clone of the repository.

## Clone and read

```bash
git clone https://github.com/LegalQuants/lq-ai.git
cd lq-ai
```

Every path cited on every trust-centre page is inside this clone. The honest catalog at
[`docs/HONEST-STATE.md`](../HONEST-STATE.md) names, for every capability it lists, a **file path** or
a **test command** in its Verification column — that is the same discipline this section applies. If
a claim on this site and the codebase ever disagree, the codebase is canonical; please
[open an issue](https://github.com/LegalQuants/lq-ai/issues).

## Per-page verification

| Claim | Verify with |
|---|---|
| [Threat model](../security/threat-model.md) — the STRIDE mitigations | Read the cited file (e.g. `api/app/security/jwt.py`, `gateway/app/api/dependencies.py`) directly against the "Mitigation" cell that names it. |
| [Anonymization](../security/anonymization.md) — the round-trip guarantee | `cd gateway && pytest tests/anonymization/ tests/test_inference_anonymization.py` |
| [Anonymization](../security/anonymization.md) — what is *not* validated | `gateway/app/anonymization/engine.py` — read `DISABLED_DEFAULT_RECOGNIZERS` and the enabled recognizer list directly; no test suite claims recall/precision numbers, because none exist as of the checked commit (a community measurement is open in PR #439 / DE-240, not yet merged). |
| [Audit & evidence](../security/audit-logging.md) — the audit-write invariant | `api/app/audit.py` — one function, `audit_action()`, is the only writer; read it to confirm the transaction boundary claim. |
| [Audit & evidence](../security/audit-logging.md) — the matter-scoped queries | Run the two `SELECT` statements on that page's source against a migrated database — the schema they reference is [`docs/db-schema.md`](../db-schema.md)'s `citation_ledger_entry` and `inference_routing_log` tables. |
| [Supply chain](../security/releases/README.md) — image signing | `cosign verify --certificate-identity-regexp "https://github.com/legalquants/lq-ai" --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/legalquants/lq-ai-api:vX.Y.Z` |
| [Supply chain](../security/releases/README.md) — the missing SLSA step | `grep -n "attest-build-provenance" .github/workflows/release.yml` — no match, as of the checked commit. |
| [Published gaps](../HONEST-STATE.md) — the test-file counts | `find api/tests -name 'test_*.py' | wc -l` and the equivalent for `gateway/tests/` and `web/src` — compare against the counts named in HONEST-STATE §8. |
| [Governance](../../GOVERNANCE.md) | Compare `GOVERNANCE.md`'s header line against [ADR 0022](../adr/0022-committee-governance-and-meeting-records.md)'s `Status: Accepted` line. |
| [Continuity](continuity.md) — where data lives | `grep -A5 "^volumes:" docker-compose.yml` — lists `pgdata`, `redisdata`, `miniodata` and `ollamadata` as named, operator-controlled volumes. |

## What "verify" means for a claim about *absence*

Several claims on this site — the missing SLSA-provenance step, the un-shipped NIST/OWASP mappings,
the desktop signing bottleneck — are claims that something does *not* exist. Those are verified the
same way: `grep` for the thing that would exist if the claim were false, and confirm it isn't there.
A negative result from a specific, named search is evidence; an absence you have to take on trust is
not, and this site tries not to ask for the second kind.

## Next

- [Published gaps](../HONEST-STATE.md) — the fullest single verification table in the project.
