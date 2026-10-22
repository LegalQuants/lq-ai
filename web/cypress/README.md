# Cypress tracks

`spec-tracks.ts` owns the inventory. Config loading rejects nonexistent,
duplicate and unclassified specs, including when Cypress is invoked directly.
With Node 22 (the workflow version):

```sh
npm run cy:inventory
npm run cy:inventory:test
npm run cy:run
```

The default track contains **13 specs**: controlled-response UI tests and
provider-free live login/CRUD. Enhance Prompt responses and outcome writes are
explicit fixtures; no inference key is required. `de263-community-skills.cy.ts`
belongs here: catalog, review and installation HTTP responses are mocked; it
does not fetch a remote skill, execute one or need the community submodule.

Three specs remain in the opt-in `CYPRESS_LLM=1` track because they perform live
inference (chat, skill capture/try-it, or ingestion/embedding). Two checked-in
specs have explicit exclusions: `wave-a-chrome` asserts retired ComingSoonModal
behavior; `lq-ai-a11y` belongs to its separate accessibility runner and matrix.
The inventory prints each exclusion's reason.

The former `lq-ai-orchestration-demo.cy.ts` entry pointed to no checked-in file
and has been removed. This does **not** claim browser coverage for governed runs:
that gap remains documented in `docs/test-strategy.md`. Adding a real spec must
also assign its track; a missing pathname cannot stand in for coverage.

Fake-token specs that use `rejectUnexpectedApiRequests` register that guard
before their contract-specific fixtures. Any unmocked API call fails the test
without contacting the backend. Do not replace the guard with blanket successful
responses, disable real auth handling or force-click an unmounted control.

For visibility checks in scrollable pages, scroll the scoped target and then
re-query it before asserting visibility/actionability. Easy Playbook exercises
the real five-second polling interval with request-specific timeouts. Enhance
Prompt holds its response until loading is observed, then checks each terminal
state and outcome action separately. No test retry is needed to hide a failure.

Per-PR workflow rollout (#706), image caching (#298), inherited skip-link and
phone-status layout repairs are separate work.
