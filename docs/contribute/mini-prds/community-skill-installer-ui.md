# Mini-PRD: Community Skill Installer (admin UI)

> **Status:** Requirements revised by maintainer on 2026-10-10 for [PR #430](https://github.com/LegalQuants/lq-ai/pull/430); implementation and acceptance evidence pending
> **Effort:** M (frontend + small backend)
> **Contributor profile:** Mid-level engineer (Svelte + FastAPI); legal-domain understanding helpful for the install-warning copy but not required
> **Mentor:** Maintainer (Kevin Keller, via PR review)

## What this is

An admin-only **"Browse community skills"** page in LQ.AI that surfaces the local [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) catalog and lets an admin **install for a selected team**. Team members can find and use the shared skill; team admins manage it, and members can fork personal copies. **Install for myself** is a secondary action.

This complements the existing submodule at `skills/community/`. The installer reads the local `skills/community/skills/` catalog (or the existing operator-configured directory override), without fetching GitHub at request time. Admins can browse and distribute skills already present in that snapshot. Refreshing the upstream checkout remains an operator action; this PR does not remove that deployment step.

## Maintainer decisions — 2026-10-10

These requirements capture the #430 discussion and supersede the earlier personal-only installation scope; they do not claim that #430 already implements them.

- **Admin distribution:** "Let's aim for admins to distribute. There can be a special button for admins." Use the existing team ownership model: **Install for team** selects a receiving team and requires team-admin membership on the backend. Whole-deployment distribution is outside this slice.
- **Provenance:** Preserve the actual source repository, source revision when known, skill path, a hash of the installed content, and who distributed it to which team. A hard-coded `lq-skills` prefix must not misattribute an operator-overridden catalog; Git HEAD must not be presented as verification of locally modified files. Keep upstream authorship/declared attestation separate from the admin's approval to distribute.
- **Deferred package model:** "Let's leave this alone here. I note that it may be more canonical to use a plugin to install skills, mcp etc like Codex and Claude. This is DE." Multiple-source configuration belongs to [DE-404](../../PRD.md#de-404--plugin-installation-and-management-skills-mcp-and-supporting-resources), alongside plugin lifecycle management, rather than a new source-settings UI in #430.

## Why it matters

Three reasons:

1. **Catalog refresh remains deployment-managed.** New upstream content must first reach the local checkout or deployment artifact. This slice lets legal-team admins browse and distribute that available snapshot without shell access; configuring and refreshing additional sources is deferred to DE-404.

2. **Admins need to distribute a reviewed version.** A personal copy owned by the installing admin does not make the skill available to colleagues. Team installation makes the receiving audience explicit and records the exact installed content without silently tracking upstream changes.

3. **It surfaces the contribution path back to the catalog.** An operator who installs `dpa-checklist-review-eu`, customizes it, and finds gaps in the upstream version has an obvious place to file a PR back to lq-skills. The installer becomes a discovery surface for the community's work product.

## What we'd ship

```
web/src/routes/lq-ai/admin/community-skills/
  +page.svelte                # Browse + install page (admin only)
web/src/lib/lq-ai/components/
  CommunitySkillCard.svelte   # Card with name, description, author, install button
  CommunitySkillInstallModal.svelte  # Confirm-install dialog with provenance + license
api/app/api/
  community_skills.py          # GET /admin/community-skills (list), POST /admin/community-skills/{slug}/install
api/app/skills/
  community_installer.py       # Reads the local catalog; validates content and records source/content provenance
docs/
  community-skills-catalog.md  # Local catalog setup, operator refresh, team distribution and provenance
```

The installer **does not run arbitrary code**. It reads the local SKILL.md frontmatter + body and reuses `UserSkillCreate` validation and the existing user/team ownership and authorization rules. **Install for team** writes a team-owned row, available to members through the team skill picker; only team admins manage that shared row. **Install for myself** writes a user-owned row. The UI button is an affordance, not the authorization boundary: a deployment-admin login alone does not grant membership or management rights over every team.

The confirmation names the skill, receiving team (or personal scope), source and version, shows full skill contents, and states that the installed copy does not automatically update when the catalog changes. Slug conflicts must not silently overwrite existing skills.

### Source and installed-content provenance

Persist a durable installation record containing:

- Actual source repository identity, skill path/slug, and source revision when available. An operator override must not inherit the default repository's identity; unavailable source metadata is explicitly unknown.
- A content hash identifying the exact material installed, with a documented hashing/serialization contract. Record the installed snapshot, not just the checkout's HEAD; local modifications cannot be asserted to match that revision.
- Installing admin, installation time, receiving scope/team and resulting skill ID, linked to the transactional `community_skill.installed` audit event.
- Declared upstream author/attestation as source metadata, displayed separately from the admin's distribution approval. A declaration is not independent verification.

Missing `.git` data must not prevent identifying the installed content. Preserve source/revision metadata in the deployment artifact when available; otherwise retain the content hash and visibly unknown source fields. The storage schema and hashing contract remain implementation choices requiring review. Installed-copy edits must not rewrite the historical installation record as though they came from upstream.

## How we'd know it's done

- [ ] `GET /api/v1/admin/community-skills` lists the valid entries in a known local catalog fixture and reports an absent/empty catalog honestly
- [ ] Each entry includes: slug, title, description, author, version, license, URL to upstream SKILL.md
- [ ] `POST /api/v1/admin/community-skills/{slug}/install` is admin-only (403 for member/viewer roles)
- [ ] **Install for team** is the primary admin action; team selection and confirmation identify the receiving audience and pinned version. **Install for myself** remains secondary
- [ ] Team installation creates a team-owned skill using existing validation and team-admin authorization; a crafted request to install into an unauthorized team is rejected
- [ ] Browse page shows source, author, license and declared attestation; confirmation shows full SKILL.md contents and distinguishes source declarations from distribution approval
- [ ] End-to-end verification: admin installs a fixture skill for a team; a different team member finds it in their picker and uses it; a non-member cannot access the team-owned copy, and an ordinary member cannot edit/archive it
- [ ] Personal installation remains owner-scoped; a member can fork a team skill into a personal copy without changing the shared version
- [ ] Unit tests: installer validates the upstream SKILL.md against the existing schema; install fails cleanly if the SKILL.md is malformed
- [ ] Source/content provenance identifies the actual repository, known revision, skill path and exact installed content; an overridden catalog is not mislabeled `lq-skills`
- [ ] Tests cover absent Git metadata and locally modified source files: a content hash remains available, differing content is distinguishable, and a checkout revision is not falsely reported as content verification
- [ ] Audit `community_skill.installed` and installation persistence are transactional and record installing admin, receiving scope/team, skill ID and linked provenance without source credentials
- [ ] Existing live skills are not silently overwritten; upstream changes do not alter installed copies, and later edits preserve the original installation provenance
- [ ] Rendered acceptance checks cover team selection, content/provenance review, confirmation, success, conflict and empty-catalog states; security review covers team authorization and external-content persistence
- [ ] Operator documentation explains local catalog setup/override and refresh, missing-metadata behavior, team distribution and the deferred DE-404 source-management scope

## Where to start

1. Read `api/app/skills/loader.py` and `api/app/skills/registry.py` (just landed in commit `800f9d6`) to understand how community skills are discovered via the submodule today
2. Read `api/app/api/user_skills.py` for the existing user-skill create/validate endpoint — the installer reuses the same Pydantic validators
3. Read `docs/skill-authoring-guide.md` for the canonical SKILL.md schema
4. Read `web/src/routes/lq-ai/admin/audit-log/+page.svelte` for the admin-page styling pattern + role-gate pattern
5. Read `api/app/skills/bootstrap.py` and `api/app/config.py` for local catalog resolution and `LQ_AI_COMMUNITY_SKILLS_DIR`; preserve the existing gateway-only egress boundary

## Scope cuts (what's out of scope for this PR)

- Multi-source catalogs, admin repository/credential configuration, fetching and plugin installation: deferred to [DE-404](../../PRD.md#de-404--plugin-installation-and-management-skills-mcp-and-supporting-resources). Retain the existing local directory override without adding a new source-management UI.
- Automatic or new in-UI update mechanisms: installed copies remain pinned; explicit plugin update management belongs to DE-404.
- Curation / moderation flags: don't show "this skill has a known issue" warnings. Trust the upstream catalog's own quality signals.
- Whole-deployment distribution: this slice uses selected-team scope, not a new global sharing model.

## How this strengthens the project

The installer turns a deployment's available community catalog into reviewable, auditable team skills. An admin can inspect and distribute a specific version, while members retain the ability to make personal copies. Reliable source/content provenance preserves the connection to the upstream work even after deployment packaging removes Git metadata.

## References

- [PRD §3.2 Skill Library](../../PRD.md#32-skill-library) — the canonical skill format + scopes
- [DE-263](../../PRD.md#de-263--community-skill-installer-admin-ui) — governing installer requirements
- [DE-404](../../PRD.md#de-404--plugin-installation-and-management-skills-mcp-and-supporting-resources) — deferred plugin/source management
- [PRD §7.1 Project Philosophy](../../PRD.md#71-project-philosophy) — "skills are work product"
- [HONEST-STATE.md §1](../../HONEST-STATE.md#1-conversational-and-workspace-surface) — what's shipped today on the skill surface
- [skills/CONTRIBUTING.md](../../../skills/CONTRIBUTING.md) — the skill contribution workflow (the installer's metadata mirrors this)
- [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) — the upstream catalog
- Related mini-PRD: [Acceptance tests for built-in skills](skill-acceptance-tests.md) — installed community skills should pass the same acceptance bar

## Definition of "merged"

The PR is ready for a maintainer's merge decision when the revised acceptance checklist is satisfied, the browser-to-database team install and another member's use are demonstrated, rendered acceptance checks are complete, and security review of authorization and external-content persistence is complete. This specification records the requested revisions; it is not merge approval or a claim that the current PR has passed these checks.
