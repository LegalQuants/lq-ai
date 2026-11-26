# Procurement Cover Letter — Template

> **Status:** AI-drafted, pending professional review.
>
> Per [`docs/procurement/README.md` §Contributing](README.md#contributing), procurement responses are counsel-review-gated: review this template for legal accuracy — in particular the questionnaire-licensing position, which is flagged for counsel confirmation — before sending a derivative of it to a procurement team.

This is a template the **operator** (the team deploying LQ.AI inside their organization) adapts and sends to their own procurement / vendor-security team. Bracketed `[OPERATOR: …]` fields are deployment-specific; everything else describes properties of the software that hold across deployments. It follows the pack's convention: every claim below cites a repository artifact a reviewer can open, or is marked as operator-supplied.

---

To: [OPERATOR: procurement / vendor-security team]
From: [OPERATOR: deploying team / deployment owner]
Re: Security review of LQ.AI, a self-hosted open-source AI platform for in-house legal work

## 1. What is being procured — and why this review is unusual

LQ.AI is **not a SaaS purchase**. It is open-source software (Apache-2.0 — `LICENSE`) that we deploy and operate **in our own environment**: [OPERATOR: name the environment — e.g., "our AWS VPC," "on-premises in our data center"]. There is no vendor operating a service, no vendor access to our data, and **no subprocessors**: the only third parties that can see content are the inference providers **we** contract with directly under our own API keys, routed through the deployment's Inference Gateway — the single component holding those keys and the single point of outbound egress (`docs/architecture.md`; `gateway/app/secrets.py`; `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md`). For the most sensitive matters, the deployment can require fully local inference so content never leaves our environment (`gateway/app/tier_floor.py`).

Most vendor-intake questions ("Where is our data stored?", "Who at the vendor can access it?") therefore resolve to properties of **our deployment**, not of a vendor. The pack below marks those items `[OPERATOR-CONFIGURABLE]`, and we have filled them in for our deployment where applicable.

## 2. On certifications: what attaches to whom

Certifications and authorizations — SOC 2 reports, ISO 27001/42001 certificates, FedRAMP ATOs, HIPAA obligations and BAAs — attach to **operating organizations**, not to software artifacts. LQ.AI is software we run, so the project holds no such certifications and honestly says so (`docs/compliance/README.md`; `docs/HONEST-STATE.md` §7). What the project provides instead is alignment material: control-by-control mappings, each citing the code path or document that implements it, so that **our** compliance program — the thing that actually gets audited — has substantive evidence rather than a blank questionnaire. Features in the software *support* our compliance program; they do not by themselves make anything "compliant."

## 3. What this pack contains

| Document | What it is |
|---|---|
| [`sig-lite.md`](sig-lite.md) | **Security Assessment Response Pack** — self-authored responses on data classification, privileged-matter handling, audit/logging, third-party integrations and credential custody, service authentication, and install integrity. |
| [`caiq.md`](caiq.md) | **Completed CAIQ-style self-assessment** across all seventeen CSA Cloud Controls Matrix domains plus an AI-specific (AI-CAIQ-oriented) supplement, each row carrying an ownership class and a repository-path evidence citation. |
| Supporting artifacts | STRIDE threat model (`docs/security/threat-model.md`); security-artifact set (`docs/security/`); pre-empted procurement objections ([PRD Appendix E](../PRD.md#appendix-e--pre-empted-procurement-objections)); the shipped-vs-deferred catalog (`docs/HONEST-STATE.md`). |

Two conventions to know when reading it:

- **Ownership classes** on every response: *structural-in-code* (the codebase enforces it), *operator-configured* (our deployment supplies it), *shared*, *residual* (a known, named gap — the pack cites the tracking ID rather than leaving a blank), and *out-of-scope*. Deferred items are answered honestly: for example, cryptographic tamper-evidence on the audit log, configurable retention schedules, and referenced-subject DSAR tooling are all **not yet shipped** and are stated as such with their tracking IDs (DE-100, DE-106, DE-107 in `docs/PRD.md` §9).
- **Every claim is verifiable in source.** The project publishes its honest-state catalog in the repository (`docs/HONEST-STATE.md`); if a claim and the codebase disagree, the codebase is canonical.

## 4. On proprietary questionnaires (SIG and similar)

If your process requires a specific questionnaire that is **proprietary** — the Shared Assessments SIG / SIG Lite being the common case — note that the project does not distribute pre-filled copies of licensed questionnaires, because their question sets cannot be reproduced without a license. This is a licensing position, not an evasion: the self-authored response pack covers the same security domains under the project's own taxonomy. **If your program holds a SIG (or other licensed questionnaire) license, we will complete your copy from the response pack on request** — the substantive answers already exist; only the transcription into your licensed format remains. [OPERATOR: name the contact who will do this.]

## 5. Verifying the software artifacts themselves

Release integrity is verifiable end-to-end, not asserted. The release pipeline (`.github/workflows/release.yml`) builds four container images (`api`, `gateway`, `web`, `proxy`) and, for each image:

1. **Signs the image** with sigstore keyless signing (`cosign sign`, recorded in the Rekor transparency log) — `sign` job.
2. **Generates an SPDX-JSON SBOM** (anchore/sbom-action), verifies it is non-empty, and **attaches it as a signed cosign attestation** of type `spdxjson` bound to the image digest — `sbom` + `sign` jobs.
3. **Attaches SLSA build provenance** via `actions/attest-build-provenance`, pushed to the registry — `build-and-push` job.

Your team can verify all three independently, before running anything, using the step-by-step commands in [`docs/security/releases/README.md`](../security/releases/README.md) (`cosign verify`, `cosign verify-attestation --type spdxjson`, provenance verification). Dependency posture and update process are documented in `docs/security/dependencies.md` and `.github/dependabot.yml`.

**Honest boundaries on this claim:** signing covers the container images. The Word add-in's sideloaded manifest is currently **unsigned** (a named gap, DE-295 — see [`sig-lite.md`](sig-lite.md) Q9), and the project's committed annual penetration test and adversarial red-team engagements have not yet had their first run (`docs/HONEST-STATE.md` §8).

## 6. What we are asking from you

[OPERATOR: state the ask — e.g., "review of the attached pack against our vendor-intake standard, with deployment-specific items answered in the attached addendum; we propose treating this as a self-hosted software review rather than a SaaS vendor review."]

For questions the pack does not answer, the project maintains a public issue tracker and a coordinated-disclosure channel for anything security-sensitive (`SECURITY.md`).

[OPERATOR: signature block]

---

*Template maintained as part of the Procurement-Readiness Pack ([DE-086](../PRD.md#de-086--procurement-readiness-pack)). Contributions from completed procurement cycles are welcomed per [`README.md` §Contributing](README.md#contributing).*
