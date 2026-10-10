# Community skill catalog and team distribution

The admin community-skills page reads a local catalog. By default that is
`skills/community/skills/`, supplied by the LegalQuants/lq-skills Git submodule.
The existing `LQ_AI_COMMUNITY_SKILLS_DIR` operator setting can point to another
local compatible catalog. The API does not fetch repositories at request time.
Multiple-source settings and plugin lifecycle management are deferred to DE-404.

## Install a reviewed version

Open **Community skills** in administration, select a receiving team, review a
skill's full instructions and source declarations, then choose **Install for team**.
The confirmation names the team and fixed version. All team members can find the
shared copy in their skill picker; team admins can edit/archive it. Members may
fork personal copies. Deployment administration alone does not confer team-admin
membership. **Install for myself** creates a personal copy instead.

If the catalog changes after review, installation returns a conflict and asks for
review again. A live skill with the same slug in the receiving scope is not
overwritten. Archive it deliberately before reinstalling. Personal and team copies
are distinct; a personal copy takes precedence for that user's skill resolution.
Installed copies never follow catalog updates automatically.

## Source metadata in a checkout or container

The source repository is read from this checkout's Git origin and stripped of
credentials/query parameters before display or audit. Identity and revision come
from the same checkout; a broken HEAD stays unknown rather than inheriting a
parent repository revision. A Git HEAD is recorded as a
source revision, never asserted to verify the installed files. Local modifications
are identified by the installed-content hash.

For a deployment artifact that excludes Git metadata, package an operator/build
manifest named `lq-catalog-provenance.json` in the catalog directory or its parent:

```json
{
  "format_version": 1,
  "repository": "https://github.com/LegalQuants/lq-skills.git",
  "revision": "<full source commit SHA>"
}
```

Populate this from the actual source used to build the artifact, and copy it with
the catalog. For a private/local override, declare that source, not LegalQuants.
If repository or revision cannot be established, omit it or use null; source fields
stay unknown. The manifest is an operator declaration, not a signature. Git metadata
takes precedence when available. Source declarations do not replace the content hash.

Every installation preserves its original installed fields and content hash,
repository/revision/path, declared authorship/attestation, installing admin, time,
receiving scope/team and skill ID. Later edits do not rewrite this original record.
Displayed attestation is a statement from SKILL.md, not independent verification;
the admin's approval to distribute is recorded separately.

## Refresh and verification

An operator refreshes the local checkout with
`git submodule update --remote skills/community`. Rebuild images carrying the catalog
to distribute new files; the filesystem registry follows its existing reload/restart
path. Browsing the refreshed catalog does not change previously installed copies.
An absent or empty catalog returns an empty list and setup guidance.

Apply migration 0071 through the deployment's normal migration mechanism. For a
running development stack, rebuild api, arq-worker and ingest-worker together;
never run a host migration against the live development database. Integration
checks use a disposable database and cover team permissions, member discovery/use,
personal precedence, stale-review conflicts and immutable provenance. Security
review remains required before merge.

## Catalog input limits

The installer rejects SKILL.md files larger than 1 MiB before parsing. Files must
use UTF-8; frontmatter must be nonrecursive, no deeper than 64 levels, and contain
at most 10,000 nodes and 1 MiB of text after expanding YAML aliases. Binary and
set-valued YAML metadata are rejected; installed metadata must serialize as JSON.
Small nonrecursive aliases are
supported. Malformed entries appear in catalog errors while valid entries remain
available. Parser diagnostics report location without copying source text into
logs. Portable provenance manifests must be regular files of at most 8 KiB.
