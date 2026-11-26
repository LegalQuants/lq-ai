# Expected - r1-already-clear (test-plan Refusal 1: text does not need rewriting)

**Input:** a short, already-plain passage (synthetic). Audience: non-legal layperson.

- The skill says the text doesn't need rewriting [src: test-plan.md:139 «Skill notes that the text doesn't need rewriting (or doesn't have legal content amenable to legal-jargon simplification).»]
- Or it light-edits WITH an explicit note to that effect [src: test-plan.md:140 «Skill optionally proceeds with light edits and a note.»]
- No fabricated complexity to justify a rewrite [doc-specific ← test-plan.md:157 «The rewrite does not add factual claims, exceptions, or qualifications not in the original.»]

## Pass criteria
- Structural: refusal-or-light-touch behavior is explicit, not silent [src: test-plan.md:139 «Skill notes that the text doesn't need rewriting (or doesn't have legal content amenable to legal-jargon simplification).»]
- Calibration: no low-quality forced rewrite [src: test-plan.md:142 «Skill avoids producing low-quality rewrites of text that doesn't need rewriting.»]
