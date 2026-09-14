# Optional skill storage and helpers

The local implementation adds two independent capabilities: persistent workspaces
and installed Python helpers. Skills choose whether to use either. Both are
disabled by default; see the [implementation overview](issue-563-workflow.md) for
release status.

## Persistent workspaces

A skill can explicitly list, read and write saved text across invocations. Storage
is isolated by owner, matter or personal namespace, exact skill identity and
declared format version. It is separate from curated memory and is never
automatically added to prompts.

Files survive chat/run deletion and skill removal. Owners can inspect, export and
reset them even when execution is disabled. Hard account/matter deletion removes
the data. Revision checks prevent conflicting writes; quotas bound storage.

## Bundled helpers

A call selects a declared, installed Python helper and passes bounded JSON data.
The implementation pins the script bundle and runtime image and refuses missing
or mismatched configuration. A private broker creates fresh containers with no
network, credentials, application mounts or engine access, plus limits on
resources, duration and output. Generated code and arbitrary commands are excluded.

Helpers receive explicitly selected input. They cannot directly access saved
workspaces; reading input and saving output remain separate skill tools. A sample
skill demonstrates saved notes and a bundled text counter.

Tools are connected to chat, query-driven background planning and guarded
root/child execution. Single-inference playbooks, tabular execution and query-less
watch paths do not gain a tool loop.

## Validation and release limits

Local Postgres, Docker and application-flow checks covered cross-invocation reuse,
namespace isolation, concurrent writes, inspection/reset/export, real helper
output, bundle refusal, timeout, bounded output, cleanup and direct container
isolation. Regression, browser and stack checks passed with controlled providers.

Executable security-review routing and approval evidence, hostile-output tests
through later calls and persisted reuse, and production executor/log-handling
review remain pending under
[ADR D8c/D8d](../adr/0035-governed-orchestration-run-tree.md#d8d--confidentiality-must-survive-compromised-helper-output).
Passing direct isolation checks does not establish the complete confidentiality
requirement. [Draft operator guidance](../deploy/skill-capabilities.md) describes
configuration, retention and execution limits.
