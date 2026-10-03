# Expected - 06-authority (test-plan Scenario 4: authority preservation)

Common checklist (`00-common-structural.md`) plus. Run condition: this cell supplies the
passage's citations through the skill's `preserve_specific_terms` input (the skill declares no
`preserve_authority` input - divergence flagged to maintainers); run parameters are recorded
in `results.md` and each output's metadata header.

- All citations preserved exactly (Section 5(a) of the FTC Act; In the Matter of Rite Aid Corporation, C-4308, 150 F.T.C. 694 (Nov. 12, 2010); 28 U.S.C. §§ 1331, 1337(a), and 1345; 28 U.S.C. §§ 1391(b)(1), (b)(2), (c)(2), and (d); 15 U.S.C. § 53(b)) [src: test-plan.md:88 «Citations are preserved exactly.»]
- No authority invented or altered [src: test-plan.md:89 «The rewrite does not invent or alter authorities.»]
- All of the multiple authorities survive [src: test-plan.md:93 «If the original has multiple authorities, all are preserved.»]
- The reasoning chain survives: prior order → alleged violations of it → this action's jurisdiction/venue [src: test-plan.md:90 «The reasoning chain that connects the authority to the conclusion is preserved.»]
- Allegations stay allegations - the source is a complaint; "alleged violations" must not become established findings [doc-specific ← test-plan.md:157 «The rewrite does not add factual claims, exceptions, or qualifications not in the original.»]
- The three venue grounds survive compression (principal place of business; transacts business; substantial part of events) [doc-specific ← test-plan.md:158 «The rewrite does not silently drop substantive provisions in the name of simplification.»]

## Pass criteria
- Structural: common checklist green; the Terms section accounts for the preserved citations [src: SKILL.md:146 «## Terms simplified or preserved»]
- Calibration: reviewing attorney confirms citations unaltered [src: test-plan.md:88 «Citations are preserved exactly.»]
