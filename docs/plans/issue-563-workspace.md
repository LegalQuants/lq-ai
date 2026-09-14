# Run working files

The local implementation gives each orchestration session durable files for notes
and findings. Files survive worker interruption and later execution of the same
session. See the [implementation overview](issue-563-workflow.md) for release status.

## Available behavior

Children read and write private named text files. Explicit sharing freezes a
revision for the parent root to read; siblings cannot access it. The root can use
shared findings for synthesis. Owners can inspect all run files through the
receipt, including after halt or opt-out.

Writes require the expected revision and commit together with their effect
receipt. Retrying completed work does not create another write. Each session is
limited to eight files, 64 KiB per file and 256 KiB total, with up to 32 content
revisions per file.

Files are application-owned data with logical names, not host paths or executable
code. Deleting the owning session, root or user removes them.
[Persistent skill workspaces](issue-563-skill-capabilities.md) separately support
reuse across new runs.

## Validation

A separate worker was interrupted after saving notes and before checkpointing.
Its replacement reused the committed write, read the notes and completed findings
that the parent consumed. Local checks also covered isolation, revision conflicts,
atomic rollback, deletion and owner inspection after halt.
