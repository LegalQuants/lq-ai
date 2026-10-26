# Find the skill files

Built-in skills are stored under `skills/` in the repository. Each has a
directory containing `SKILL.md` and, where needed, a `reference/` folder
or a `test-plan.md`.

## Read before using

Look through the instructions and supporting files before you rely on a
skill. Reference content is included in the AI request, so it can affect
the answer and what information reaches a provider.

## Record the version you used

Keep the skill revision with your test results. An author name or
version label describes the file; it does not show that someone
independently reviewed it.

## Personal skills

A skill saved for your own use is a database record, not a change to
the repository. Your version can take the place of a built-in with the
same name in your own chats; other users keep their own version or the
built-in. This is a useful starting point for adapting a task without
publishing it.

### Details

Save it through the Skill Creator or the skill wizard inside the
running application; it lands as a row in the `user_skills` database
table, scoped to you
([ADR 0012](../adr/0012-db-backed-user-skills.md)). It **shadows** a
built-in of the same name in your own chats only — if you fork the
shipped NDA Review skill and tweak its severity calibration, your
version renders for you; everyone else, including the skill's original
author, keeps seeing the built-in. Nothing here touches this repository
or requires a PR.

## Team skills

The API also supports team-owned skills, with team-admin checks for
creating and changing them. These remain database records and belong in
the database backup. The older design record deferred this feature, but
the reviewed code includes it; do not rely on that old "deferred"
label.

### Details

The same wizard supports a team-scoped skill, visible to everyone on
that team rather than to you alone — a team-admin action, gated in
[`api/app/api/user_skills.py`](../../api/app/api/user_skills.py).
[ADR 0012](../adr/0012-db-backed-user-skills.md) deferred team scope to
a follow-on task (D8.1); the shipped code implements it — a `teams`
table
([`api/alembic/versions/0014_create_teams.py`](../../api/alembic/versions/0014_create_teams.py))
and `owner_team_id` on `user_skills` — and no later ADR records the
extension, so ADR 0012's "deferred" text is stale against the running
code as of the checked commit. Still a database row, still no
repository change — this is the right home for a skill your
organization standardized on internally but has no reason to publish.

## Publishing a skill

The curated built-ins live in this repository's `skills/` directory.
The contribution policy routes community work-product skills to
[`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills).
Claim a task before starting and check that repository's contribution
and license terms. Publishing a skill is separate from saving or
sharing it inside your installation.

For most skill contributions — a new jurisdiction's calibration for an
existing review skill, or a new domain skill entirely — that's this
route. Per
[README.md §"Starter skills"](../../README.md#starter-skills-ship-with-m1),
this repository's `skills/` holds the fifteen first-party built-in
skills — the ten M1 starter skills plus `case-law-research` and four
table-mode/internal skills (`contract-snapshot`, `msa-snapshot`,
`nda-snapshot`, `playbook-easy-extract`). The community repository is
where jurisdiction- and practice-area-specific contributions
accumulate, under review norms that mirror
[`skills/CONTRIBUTING.md`](../../skills/CONTRIBUTING.md)'s bar
(practicing-attorney attestation, peer review), but live in that
repository, not this one.

### Details

[ADR 0024](../adr/0024-jurisdiction-and-practice-area-expansion.md)
settled the routing after several contributions stalled on exactly this
question. An incoming jurisdiction or practice-area contribution is
classified into one of four shapes:

1. **Skills (S2) go to `legalquants/lq-skills`.** Community work-product
   skills route to the community skills repo; this repository's `skills/`
   directory holds the curated first-party set.
2. **Authority sources (S1) go to this repository** as sources under
   ADR 0021, with the security review gateway-egress changes already
   carry.
3. **Corpora / statutory graphs (S3) go to org-level repos** per the
   PRD §9 DE-264 pattern; anything S3 that reaches operators is gated in
   this repository as an S1-class change.
4. **Practice areas excluded by PRD §1.6 (S4) require a mini-PRD and a
   committee-decided PRD amendment first**; the proposal's S1/S2/S3 parts
   route normally once the amendment lands. Litigation is chief among
   the practice areas PRD §1.6 excludes today.

ADR 0024 also commits to a standing ledger at
`docs/contribute/coverage-map.md`, checked before a contribution is
routed and updated in the same sweep. **That file is not present in the
repository as of the checked commit.** Until it exists, claim your
contribution on a tracking issue first
([`skills/CONTRIBUTING.md`](../../skills/CONTRIBUTING.md)), same as any
skill contribution, so two contributors don't duplicate the same
jurisdiction or practice area.

## If the contribution adds more than instructions

A new outside research source changes the application's network access
and needs the security review gateway-egress changes already carry
([ADR 0021](../adr/0021-content-source-registry-and-free-source-expansion.md);
CODEOWNERS routes `gateway/**` changes to security review), with the
adversarial read in
[docs/security/external-contribution-vetting.md](../security/external-contribution-vetting.md)
for authors outside the known-contributor circle. A dataset may need a
separate repository. A proposal outside the stated product scope needs
a scope decision before implementation. ADR 0024 describes these routes
(in detail above); ask a maintainer to classify a mixed proposal.
