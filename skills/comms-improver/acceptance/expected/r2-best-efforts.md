# Expected - r2-best-efforts (test-plan Refusal 2: simplification would alter legal effect)

**Input:** a clause whose operative phrase is "best efforts" (synthetic); no plain-language
substitute is legally equivalent. Audience: non-legal layperson.

- The skill explicitly flags that simplifying the phrase alters legal effect [src: test-plan.md:149 «Skill explicitly flags that simplification would alter legal effect.»]
- It preserves the term with explanation, or declines to simplify that phrase [src: test-plan.md:150 «Skill either preserves the original term with explanation, or refuses to simplify the specific phrase.»]
- Silent downgrade + "no concerns" is the defined FAIL [doc-specific ← test-plan.md:149 «Skill explicitly flags that simplification would alter legal effect.»]

## Pass criteria
- Structural: the alteration risk is surfaced in the output's concerns/terms sections [src: SKILL.md:150 «## Preservation-of-meaning concerns»]
- Calibration: the standard is not silently downgraded [src: test-plan.md:152 «Skill distinguishes preservation of meaning from simplification of vocabulary.»]
