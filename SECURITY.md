# Security Policy

## Reporting a vulnerability

**Do not file security vulnerabilities as public GitHub issues.** Public reports give attackers a head start; coordinated disclosure protects users while we develop a fix.

To report a vulnerability:

- **Email:** admin@legalquants.com
- **GitHub Security Advisory:** Alternatively, you can report privately through GitHub's [Security Advisories](https://github.com/legalquants/lq-ai/security/advisories/new) feature.

Please include:

- A description of the vulnerability and its potential impact.
- Reproduction steps or proof-of-concept code.
- The version(s) and configurations affected.
- Any suggested fix or mitigation, if you have one.
- Your contact information for follow-up (or note if you prefer anonymity).

## Response commitments

We commit to:

- **Acknowledge receipt within 72 hours** of the initial report.
- Provide an **initial assessment within 7 business days** including our preliminary view on severity and timeline.
- Address **critical vulnerabilities within 30 days** of confirmation, **high-severity within 60 days**, **medium-severity within 90 days** of confirmation.
- Coordinate public disclosure timing with the reporter.
- Credit the reporter in the published advisory unless anonymity is preferred.

For vulnerabilities being actively exploited in the wild, we accelerate; please flag this in your initial report.

## Coordinated disclosure

LQ.AI follows coordinated disclosure: we ask reporters to give us reasonable time to develop and ship a fix before public disclosure. We will work with you to set a disclosure date that balances user safety with researcher interests.

After a fix ships, we publish:

- A **GitHub Security Advisory** describing the vulnerability, affected versions, and remediation.
- A **CVE** (where applicable) coordinated through MITRE.
- **Reporter credit** in the advisory acknowledgments section.

## Scope

**In scope** for security disclosures:

- The LQ.AI codebase: `api/`, `gateway/`, `web/`, `scripts/`.
- Official deployment artifacts: `docker-compose.yml`, Helm charts, container images we publish.
- Cryptographic implementations and key handling.
- Authentication, authorization, session management, and audit logging.
- The Inference Gateway's Tier Derivation, Anonymization Layer, and provider-routing logic.
- Documentation that could mislead operators about security posture.

**Out of scope** (please report elsewhere):

- Vulnerabilities in third-party LLM providers (Anthropic, OpenAI, Vertex, etc.) — report directly to the provider.
- Vulnerabilities in dependencies — report upstream; we'll respond to advisories that affect us.
- Operator-specific deployment configurations or operator-modified forks.
- Social engineering attacks on LegalQuants employees or community members.
- Theoretical attacks without a demonstrable exploit path against the project's threat model.

## Judging whether a finding needs the private path

This policy does not itself state a rule for the harder question a reporter with real findings has
to answer alone: is *this specific* finding safe to work on in the open, or does it need the private
path above? The project's only full security audit to date (#288, 22 findings) is the only precedent:
its findings were remediated in public PRs, and [the v0.7.0 release notes](docs/releases/v0.7.0.md)
record that "none is exploitable by a raw external attacker in the shipped default (every service
binds to `127.0.0.1`)." Reading that precedent generally: **if a finding requires access an attacker
cannot get in the deployment's shipped default configuration — an unexposed local port, a credential
the operator already holds, a network position the shipped topology doesn't grant — public review is
usually safer and faster than a private report sitting in a queue.** If a finding is exploitable by
an attacker who has only what the shipped default exposes, use the private, coordinated path above.
When you are not sure which side of the line a finding falls on, the private path is the conservative
default.

## What we will not do

- We will not pursue legal action against good-faith security researchers who follow this policy.
- We will not retaliate against reporters or ban them from the community.
- We will not require non-disclosure agreements or other restrictive agreements as a condition of accepting reports.

## Safe harbor

If you make a good-faith effort to comply with this policy during your security research, we will consider your activities authorized and we will not pursue civil or criminal action against you. We will work with you to understand and resolve issues quickly.

This safe-harbor commitment does not authorize:

- Activities that compromise the privacy or safety of users beyond what is necessary to demonstrate the vulnerability.
- Activities that disrupt or degrade the availability of services or other users' deployments.
- Accessing data beyond what is needed to demonstrate the vulnerability.
- Public disclosure before the coordinated disclosure timeline agreed upon with the maintainers.
- Targeting LegalQuants infrastructure or employee accounts (this policy covers the open-source project; LegalQuants commercial services have separate disclosure terms).

## Past advisories

Past security advisories and reporter acknowledgments are listed at:
[GitHub Security Advisories page — URL becomes active when first advisory is published].

## Questions about this policy

For questions about this policy (rather than vulnerability reports), GitHub Discussions in the `Help` category is appropriate. For sensitive policy questions, email security@legalquants.com.

---

*This policy is adapted in part from the [disclose.io](https://disclose.io) Core Terms project. Updates to this policy follow the project's standard documentation cadence; substantive changes will be announced in advance through GitHub Discussions.*
