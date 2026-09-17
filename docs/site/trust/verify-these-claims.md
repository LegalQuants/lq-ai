---
title: Verify these claims yourself
description: The commands, files, and tests behind every page in the trust centre — so nothing here has to be taken on faith.
audience: [evaluator, operator, contributor]
status: draft
sources:
  - README.md
  - docs/HONEST-STATE.md
  - docs/db-schema.md
  - .github/workflows/release.yml
  - docker-compose.yml
  - docs/security/releases/README.md
  - docs/adr/0022-committee-governance-and-meeting-records.md
sidebar:
  order: 13
---

Every other page in this section makes a claim and names the file it traces to. This page collects
the actual commands: what to run, what to read, and what a passing result looks like, organized by
the trust-centre page each one backs. None of this requires access to a running deployment except
where noted — most of it works against a plain clone of the repository.

## Clone and read

```bash
git clone https://github.com/LegalQuants/lq-ai.git
cd lq-ai
```

Every path cited on every `/trust/` page is inside this clone. The honest catalog at
[`docs/HONEST-STATE.md`](../../HONEST-STATE.md) names, for every capability it lists, a **file
path** or a **test command** in its Verification column — that is the same discipline this site
applies. If a claim on this site and the codebase ever disagree, the codebase is canonical; please
[open an issue](https://github.com/LegalQuants/lq-ai/issues).

## Per-page verification

| Claim | Verify with |
|---|---|
| [Threat model](threat-model.md) — the STRIDE mitigations | Read the cited file (e.g. `api/app/security/jwt.py`, `gateway/app/api/dependencies.py`) directly against the "Mitigation" cell that names it. |
| [Anonymization](anonymization.md) — the round-trip guarantee | `cd gateway && pytest tests/anonymization/ tests/test_inference_anonymization.py` |
| [Anonymization](anonymization.md) — what is *not* validated | `gateway/app/anonymization/engine.py` — read `DISABLED_DEFAULT_RECOGNIZERS` and the enabled recognizer list directly; no test suite claims recall/precision numbers, because none exist. |
| [Audit & evidence](audit-and-evidence.md) — the audit-write invariant | `api/app/audit.py` — one function, `audit_action()`, is the only writer; read it to confirm the transaction boundary claim. |
| [Audit & evidence](audit-and-evidence.md) — the matter-scoped queries | Run the two `SELECT` statements on this page's source against a migrated database — the schema they reference is `docs/db-schema.md`'s `citation_ledger_entry` and `inference_routing_log` tables. |
| [Supply chain](supply-chain.md) — image signing | `cosign verify --certificate-identity-regexp "https://github.com/legalquants/lq-ai" --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/legalquants/lq-ai-api:vX.Y.Z` |
| [Supply chain](supply-chain.md) — the missing SLSA step | `grep -n "attest-build-provenance" .github/workflows/release.yml` — no match, as of the checked commit. |
| [Published gaps](published-gaps.md) — the test-file counts | `find api/tests -name 'test_*.py' | wc -l` and the equivalent for `gateway/tests/` and `web/src` — compare against the counts named in HONEST-STATE §8. |
| [Governance](governance.md) — the adoption drift | Compare `GOVERNANCE.md`'s header line against [ADR 0022](../../adr/0022-committee-governance-and-meeting-records.md)'s `Status: Accepted` line. |
| [Continuity](continuity.md) — where data lives | `grep -A5 "^volumes:" docker-compose.yml` — lists `pgdata`, `redisdata`, `miniodata` and `ollamadata` as named, operator-controlled volumes. |

## What "verify" means for a claim about *absence*

Several claims on this site — the missing SLSA-provenance step, the un-shipped NIST/OWASP
mappings, the desktop signing bottleneck — are claims that something does *not* exist. Those are
verified the same way: `grep` for the thing that would exist if the claim were false, and confirm
it isn't there. A negative result from a specific, named search is evidence; an absence you have to
take on trust is not, and this site tries not to ask for the second kind.

## Next

- [Published gaps](published-gaps.md) — the fullest single verification table in the project.
- [Trust centre](index.md) — back to the index this page supports.
