Naming a file format in a skill's frontmatter doesn't make the app accept
that format — the upload pipeline decides what it will actually ingest, and
the two can disagree.

**File formats still depend on the app, not the skill.** The upload parser
accepts a PDF with extractable text, or plain text and Markdown saved as
valid UTF-8; an encrypted or image-only PDF, or a text file that isn't valid
UTF-8, fails ingestion (`api/app/pipeline/ingest.py`,
`api/app/pipeline/parsers.py`). DOCX is not ingested today — a skill's
instructions or a declared input can mention a `.docx` file, but that
mention does not add Word-document upload support. DOCX ingest via Pandoc
is an accepted design
([ADR 0017](../../adr/0017-docx-ingest-via-pandoc.md)), not a shipped one;
its implementation is tracked separately from the decision to build it.
