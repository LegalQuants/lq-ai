# Where skills live

A skill you write has three possible homes, and which one is right
depends on who else should see it.

## Personal

Built through the Skill Creator or the skill wizard inside the running
application, a skill you save without sharing it lands as a row in the
`user_skills` database table, scoped to you
([ADR 0012](../adr/0012-db-backed-user-skills.md)). It **shadows** a
built-in of the same name in your own chats only — if you fork the
shipped NDA Review skill and tweak its severity calibration, your
version renders for you; everyone else, including the skill's original
author, keeps seeing the built-in. Nothing here touches this repository
or requires a PR.

## Team-shared

The same wizard supports a team-scoped skill, visible to everyone on
that team rather than to you alone (a team-admin action).
[ADR 0012](../adr/0012-db-backed-user-skills.md) deferred team scope to
a follow-on task (D8.1); the shipped code implements it — a `teams`
table
([`api/alembic/versions/0014_create_teams.py`](../../api/alembic/versions/0014_create_teams.py)),
`owner_team_id` on `user_skills`, and team-admin gating in
[`api/app/api/user_skills.py`](../../api/app/api/user_skills.py) — and no
later ADR records the extension, so ADR 0012's "deferred" text is stale
against the running code as of the checked commit. Still a database row,
still no repository change — this is the right home for a skill your
organization standardized on internally but has no reason to publish.

## Upstream

Publishing a skill for other operators to use is a repository
contribution, and *which* repository depends on what the contribution
actually is.
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
   route normally once the amendment lands.

For most skill contributions — a new jurisdiction's calibration for an
existing review skill, or a new domain skill entirely — that means
route 1: [`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills),
the community repository, not this repository's own `skills/` directory.
Per [README.md §"Starter skills"](../../README.md#starter-skills-ship-with-m1),
this repository's `skills/` holds the fifteen first-party built-in
skills — the ten M1 starter skills plus `case-law-research` and four
table-mode/internal skills (`contract-snapshot`, `msa-snapshot`,
`nda-snapshot`, `playbook-easy-extract`); the community repository is
where jurisdiction- and practice-area-specific contributions accumulate,
under review norms that mirror
[`skills/CONTRIBUTING.md`](../../skills/CONTRIBUTING.md)'s bar
(practicing-attorney attestation, peer review) but live in that
repository, not this one. Route 4 — a practice area PRD §1.6 currently
excludes, litigation chief among them — needs a mini-PRD and a
committee-decided PRD amendment before any skill work starts.

## On the coverage map

ADR 0024 commits to a standing ledger at
`docs/contribute/coverage-map.md`, checked before a contribution is
routed and updated in the same sweep. **That file is not present in the
repository as of the checked commit.** Until it exists, claim your
contribution on a tracking issue first
([`skills/CONTRIBUTING.md`](../../skills/CONTRIBUTING.md)), same as any
skill contribution, so two contributors don't duplicate the same
jurisdiction or practice area.
