Every architecture decision record in `docs/adr/`, with the status each file
carries today. The table below is read from the directory at build time, not
hand-maintained, so it can't fall behind whatever files actually exist there.

**An accepted record describes an agreed direction — not necessarily what's
built yet.** Read a decision alongside the actual code and tests to see
which parts of it are available now; "Accepted" means the project has
committed to that direction, not that every part of it has shipped.

**A status can lag behind the code, and this index doesn't correct for
that.** The Status column is rendered exactly as the file states it,
including a record that still reads "Proposed" on a decision everyone
already treats as settled, or that mentions work as deferred after the
deferred part has since landed. When the status word and what you observe
in the running system disagree, the code is the more current answer; a
stale status is worth fixing in the ADR file itself, not worked around here.
