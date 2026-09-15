# ADR 0027 — Community skill catalog served from the local submodule

**Status:** Proposed (2026-07-25) — authored in-PR with roadmap item 3.8 (DE-263, community skill installer admin UI); reviewable at PR time. New admin endpoints carry **security review** per the auth-touching-surface rule in CLAUDE.md / CODEOWNERS.

**Relates to:** [ADR 0004](0004-skill-loader-locus.md) (the skill loader lives in the backend; filesystem-canonical skills), [ADR 0012](0012-db-backed-user-skills.md) (DB-backed user skills, `forked_from` documentary lineage, audit-log lineage records), [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) / [ADR 0016](0016-transparency-and-governance-invariants.md) (the gateway is the only egress path; the backend makes no outbound HTTP calls beyond its single gateway client — enforced by `tests/test_transparency_invariants.py`). Realizes **DE-263**.

---

## Context

The `skills/community` git submodule (the `lq-skills` repo) is the distribution channel
for community-contributed skills. The existing loader (`api/app/skills/loader.py`,
wired via `api/app/skills/bootstrap.py`) already scans `skills/community/skills/`
at startup and merges parseable community skills into the in-memory registry with
`source="community"` (built-ins win on slug collision).

DE-263 adds an **admin installer UI**: an operator browses the community catalog,
reads the full SKILL.md (transparency principle — the work product is the artifact),
and installs a skill as an editable DB-backed copy. The open question this ADR pins:
**where does the catalog come from at request time?**

## Decision

**Serve the catalog from the local submodule checkout, by re-scanning
`skills/community/skills/` (or the operator's `LQ_AI_COMMUNITY_SKILLS_DIR`
override) from disk on each admin catalog request. The api never fetches the
catalog over the network.**

Consequences pinned with this decision:

1. **Refresh path is `git submodule update --remote skills/community` (operator-run),
   followed by SIGHUP (or restart) if the merged registry should also pick up the
   new corpus.** The catalog endpoints re-scan the directory per request, so the
   admin UI sees a refreshed submodule immediately; the chat-facing registry
   refreshes on the existing SIGHUP/restart path.
2. **Catalog provenance is recorded as `forked_from = "lq-skills:<slug>@<sha>"`** on
   the installed `user_skills` row, where `<sha>` is the submodule's HEAD commit.
   The sha is resolved by **pure file reads** of git plumbing (`skills/community/.git`
   gitdir pointer → `HEAD` → loose ref or `packed-refs`); the api does **not** shell
   out to git at request time. When the plumbing is absent (uninitialized submodule,
   Docker image built without `.git`), the sha degrades honestly to `"unknown"`.
3. **An absent or empty submodule is a first-class state, not an error.** The catalog
   endpoint returns 200 with an empty list plus an operator hint naming the
   `git submodule update --init skills/community` remedy. Fresh clones without
   `--recurse-submodules` must not break the admin UI.
4. **Install reuses the ADR 0012 user-skill validation path** (`UserSkillCreate`
   bounds), so a malformed community SKILL.md is rejected with the same 422 shape a
   hand-authored malformed skill would get, and the install writes the standard
   `community_skill.installed` audit-log row in the same transaction as the row
   insert.
5. **Attestation is displayed, never asserted.** Community skills are attested at
   their source repo (lq-skills PR process). The catalog surfaces whatever
   attestation metadata the SKILL.md frontmatter carries and states "none declared"
   otherwise; the installer never synthesizes attestation state.

## Alternatives considered

- **GitHub API fetch from the api (rejected).** Fetching the lq-skills repo listing
  from the backend would add a second outbound HTTP surface beyond the single
  gateway client, violating the egress invariant that
  `tests/test_transparency_invariants.py` enforces (ADR 0014/0016), and would break
  air-gapped deployments — a core self-hosted posture. It would also make the
  catalog non-reproducible: what the operator reviewed and what got installed could
  differ between requests.
- **Web-side fetch (browser calls GitHub directly) (rejected).** Moves the
  supply chain into the browser: CSP loosening for `github.com`/`raw.githubusercontent.com`,
  un-audited content rendered and installed from a URL the deployment does not pin,
  and no server-side record of what was actually reviewed at install time. The
  install provenance would be whatever the browser happened to see — unauditable.
- **Dedicated registry service (rejected).** A separate catalog service (or DB-synced
  mirror of the submodule) is overkill for a corpus of dozens of skills that already
  ships inside the repo as a submodule; it would add an SBOM/deploy surface and a
  second source of truth that can drift from the filesystem-canonical one (ADR 0004).

## Consequences

- Air-gap compatible; zero new egress; zero new dependencies.
- The catalog is exactly as fresh as the operator's submodule checkout — the UI
  states the pinned sha (or `unknown`) so staleness is visible, not hidden.
- Installed copies do not auto-update; they are forks (ADR 0012 semantics) whose
  lineage lives in `forked_from` + the audit log. A future "update available"
  surface can diff installed `forked_from` shas against the current submodule sha
  (deferred; would be a new DE).
