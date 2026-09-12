# Saved work: issue 563 and LangGraph evaluation

Inventory checked on 12 September 2026. **The work below is preserved together on branch `codex/issue-563-langgraph-evaluation`.** The initial inventory found these artifacts untracked; Houfu subsequently authorized committing and pushing this research snapshot. No application feature, GitHub issue, PR or review comment is created by this snapshot.

| Artifact | What it preserves |
|---|---|
| [Implementation plan](issue-563-plan.md) | User decisions, proposed architecture, milestones, subissues, acceptance gates and remaining approvals |
| [Prior-art assessment](issue-563-prior-art.md) | Comparable harnesses, source citations, LangGraph/queue tradeoffs and dependency-maintenance recommendations |
| [PR prerequisite review](issue-563-pr-prerequisite-review.md) | PRs 410, 411 and 536; issue 332; the latest reviewed CI/merge evidence and remaining findings |
| [Prototype report](issue-563-spike/README.md) | Experiment design, 23-test results, limitations and the LangGraph 1.2.11 → 1.0.10 comparison |
| [Prototype sources and manifest](issue-563-spike/pyproject.toml) | Application-owned contracts/receipts, LangGraph and native adapters, stub CLI, tests and the current frozen dependency lock |
| [Original 1.2.11 baseline](issue-563-spike/baselines/langgraph-1.2.11/README.md) | Original manifest/lock and source hashes, copied out of temporary storage during this inventory check |

The prototype currently pins LangGraph 1.0.10. It passed unchanged on both tested runtime versions. Two additional one-off checks resumed a paused run and a crashed run from 1.2.11 under 1.0.10 without duplicate provider calls. These results are documented; raw terminal logs and temporary cross-version databases are not part of this saved source bundle.

The application source and dependency files were not changed by this work. The production backend choice and full implementation plan remain unapproved. The prototype proves a replaceable boundary for a fixed batch, not production Postgres, gateway or multi-worker integration.

The preservation commit contains only these issue-563 artifacts. Other work under `outputs/` and `.codex/` is excluded. The branch starts from local main at `de73fa4061a0b76c55d9ec61052f5c7816a18606`; later remote commits inspected during research are cited in the reports without being imported into this checkout. Remote publication is a separate operation; the Git remote and branch tracking state establish whether the push succeeded.
