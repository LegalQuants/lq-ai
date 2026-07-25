# Security Documentation

> **Status:** Stub at v1 launch. Substantive security artifacts (SBOM, threat model, signed releases, supply-chain transparency documentation) ship at M1 per [PRD §7.5 Code & Supply-Chain Transparency](../PRD.md#75-code--supply-chain-transparency-from-launch).

This folder is the home for LQ.AI's security artifacts. The PRD documents the project's security posture in detail; this folder contains the operational artifacts that substantiate that posture.

## What lands here

| Artifact | Status | Description |
|---|---|---|
| **SBOM** (`sbom.spdx.json`) | Landed (Phase E) | Software Bill of Materials in SPDX format, generated at build time and shipped with each release. |
| **Signed release attestations** (`releases/`) | Landed (Phase E) | Sigstore/cosign signatures for container images and release artifacts. |
| **SLSA Provenance** (`slsa/`) | Landed (Phase E) | SLSA Level 3 build provenance attestations. |
| **Threat model** (`threat-model.md`) | Landed | The project's documented threat model — assets, attackers, attack vectors, mitigations. |
| **Dependency security** (`dependencies.md`) | Landed | Approach to dependency review, vulnerability monitoring, and update cadence. |
| **Cryptographic implementations** (`cryptography.md`) | Landed | Documentation of cryptographic primitives used, key lifecycle, and known limitations. |
| **Network access controls** (`network-access-controls.md`) | M2 (or earlier with [DE-103 IP allowlisting](../PRD.md#de-103--ip-allowlisting-and-geo-restriction)) | IP allowlisting, geo-restriction, outbound proxy configuration. |
| **Audit logging** (`audit-logging.md`) | Landed | What is logged, retention, integrity protection. |
| **Encrypted-at-rest provider keys** ([`encrypted-keys.md`](encrypted-keys.md)) | Landed (ADR 0011) | Operator workflow for the master-key + Fernet-wrapped `api_key_encrypted` path in `gateway.yaml`. Bootstrap, rotation, recovery. |
| **OpenSSF Scorecard + Best Practices criteria** (`best-practices-criteria.md`) | Drafted (AI-drafted, pending review; DE-222/DE-223) | Check-by-check Scorecard expected state and the bestpractices.dev Passing-tier walk-through, split into in-repo evidence vs maintainer actions. |
| **Past advisories** (`advisories/`) | As advisories are published | Historical security advisories with reporter credit. |

## Reporting a vulnerability

See [`SECURITY.md`](../../SECURITY.md) at the repo root for the vulnerability disclosure policy. The short version:

- **Do not file** security vulnerabilities as public GitHub issues.
- **Use** GitHub Security Advisories or email security@legalquants.com.
- **Our commitments:** acknowledge within 72 hours; assess within 7 business days; fix critical issues within 30 days; coordinate disclosure with you; credit you in the published advisory.

## Verifying releases

When a release ships, verify with cosign:

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/legalquants/lq-ai" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/legalquants/lq-ai-api:vX.Y.Z
```

Detailed verification instructions land in `releases/README.md` at M1.

## Why supply-chain transparency matters

Closed-source legal AI products typically provide nothing approaching this level of supply-chain documentation — the customer trusts the vendor, with no way to verify what's in the binary or how it was built. Open-source projects can do better: SBOM, signed releases, build provenance, threat model, and audit-log specification are all artifacts the customer can inspect.

The Compliance Alignment Pack ([`docs/compliance/`](../compliance/)) maps these artifacts to specific control responses in SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, and FedRAMP. Pre-empted procurement responses ([PRD Appendix E](../PRD.md#appendix-e--pre-empted-procurement-objections)) reference both this folder and the Compliance Pack.

## Contributing

Security-relevant contributions follow the same process as other contributions ([CONTRIBUTING.md](../../CONTRIBUTING.md)) with two additions:

1. **Changes affecting the threat model, audit logging, or cryptographic implementations** require security review per [CODEOWNERS](../../.github/CODEOWNERS).
2. **Vulnerabilities** are not contributed via PR — they're disclosed per `SECURITY.md`, and the project produces a fix and advisory.

---

*Documentation maintained alongside the PRD. Updates land in the same release cadence; security-impacting changes warrant a PRD version bump.*
