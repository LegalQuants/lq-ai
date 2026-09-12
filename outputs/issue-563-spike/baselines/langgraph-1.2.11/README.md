# Original LangGraph 1.2.11 comparison baseline

Preserved on 12 September 2026 from the temporary snapshot taken immediately before the requested switch to LangGraph 1.0.10.

- `pyproject.toml`: the original isolated dependency manifest.
- `uv.lock`: its original resolved dependency set, including LangGraph 1.2.11, SDK 0.4.4 and prebuilt 1.1.0.
- `source-hashes.json`: SHA-256 hashes of the four implementation modules and three test files, with paths relative to the prototype root.

All seven hashes were checked against the current prototype sources when this baseline was preserved and matched. No second source tree is needed: the Python code did not change for the version comparison.

This archive preserves the dependency comparison inputs. The 23-test results and two additional cross-version resume checks are recorded in the [prototype report](../../README.md). The cross-version check was a one-off experiment; its temporary SQLite fixtures and raw command output are not archived here. The saved tests cover restart and backend replacement within whichever environment runs them.

These files are local and untracked at the time of preservation; this archive is not a Git commit or remote backup.
