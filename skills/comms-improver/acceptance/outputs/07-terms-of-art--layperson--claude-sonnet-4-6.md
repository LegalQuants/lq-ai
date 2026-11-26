<!--
run: comms-improver--07-terms-of-art--layperson--anthropic
provider: anthropic
requested_model: claude-sonnet-4-6
resolved_model: claude-sonnet-4-6
run_at: 2026-07-10T21:59:10-07:00
max_tokens: 4096
params: temperature/top_p/thinking OMITTED (faithful to gateway); tools NONE
system_prompt_sha256: a8cd63ec32afd06b5b04304db0f9aa6fc0d0f5d2735e886f753087c37367aa64
user_trigger: 'Please apply the skill to the provided inputs and produce the output as specified.'
assertions: clean
-->

# Comms Improver: Vicarious liability and the Fair Housing Act

**Audience:** Non-legal layperson with no legal background
**Purpose:** Explaining a legal concept and court ruling in plain language
**Length constraint:** Matched to original
**Tone:** Neutral, accessible, conversational

---

## Rewritten text

> When a company's employee does something wrong on the job, the company itself is usually the one legally responsible — not the individual owner or executive who runs the company. This is a long-standing legal rule: if someone acts on a company's behalf and within the scope of their job, the company is on the hook for what they do, even if the owner or a senior executive didn't know about it or approve it.
>
> This rule only applies to the company, though — not automatically to the people at the top. For a company owner or officer to be personally responsible for an employee's wrongdoing, something more has to be true beyond simply being in charge.
>
> A lower federal court (the Ninth Circuit Court of Appeals) ruled that the Fair Housing Act — a law that prohibits housing discrimination — changed this standard. That court said that under the Act, a company owner or officer could be held personally responsible for a discriminatory act by one of their employees, just because the owner or officer had control (or the right to control) that employee's work.
>
> The Supreme Court disagreed. It ruled that the Fair Housing Act did *not* expand the standard rule in that way. Owners and officers are not automatically personally liable just because they had control over the employee who did something wrong. The traditional rule — that the *company* bears responsibility, not the individual at the top — still applies.

---

## What was changed

- **Jargon removed throughout.** Legal terms like *respondeat superior*, *vicarious liability*, *principal/agent relationship*, *torts*, and *in the absence of special circumstances* were replaced with plain equivalents or explained in everyday language ("the company is on the hook," "personally responsible," "does something wrong on the job").
- **Citations removed.** All case names, statute citations, Restatement references, and law review citations were removed. They establish legal authority for a legal audience but add no meaning for a layperson.
- **Bottom line moved to the front.** The original builds through authority citations before stating the rule; the rewrite leads with the rule itself.
- **Court structure explained briefly.** "The Ninth Circuit" was replaced with "a lower federal court (the Ninth Circuit Court of Appeals)" and the Supreme Court was named explicitly, giving the reader enough context to understand that one court was overruled by a higher one.

---

## Terms simplified or preserved

| Original term | Plain version | Notes |
|---|---|---|
| Vicarious liability | "legally responsible" / "on the hook" | Simplified. The concept is fully conveyed for a lay audience; the technical label is not needed. |
| Respondeat superior | Removed | Latin doctrine name; no meaning for a layperson; the underlying concept is explained instead. |
| Principal / agent | "company" / "employee acting on the company's behalf" | Simplified. The legal distinction between principal/agent and employer/employee was collapsed, which is appropriate for this audience since the original text treats them equivalently for this purpose. |
| Torts | "wrongdoing" / "something wrong" | Simplified. "Torts" means civil wrongs; "wrongdoing" captures the sense adequately for this context. |
| The Ninth Circuit | "a lower federal court (the Ninth Circuit Court of Appeals)" | Partially preserved with explanation. |
| The Fair Housing Act | Preserved verbatim | Proper name of a law; preserved with a brief description ("a law that prohibits housing discrimination"). |
| "In the absence of special circumstances" | "something more has to be true beyond simply being in charge" | Paraphrased. The original is a legal hedge meaning the general rule holds unless specific additional facts apply; the plain version conveys this without the hedging formula. |

---

## Preservation-of-meaning concerns

**The "consent" element of agency was omitted.** The original text quotes the Restatement's definition of a principal/agent relationship, which requires not only *control* but also mutual *consent* — both parties agreeing that one acts on behalf of the other. This element is what distinguishes an employee (who acts on the company's behalf by consent) from, say, an independent contractor or a stranger. The plain rewrite simplifies this to "an employee acts on a company's behalf" without explaining the consent element. For a layperson audience, this omission is unlikely to cause misunderstanding, but if the purpose of the communication is to explain *why* the control-only standard is legally insufficient (the core of the Supreme Court's disagreement with the Ninth Circuit), this distinction matters. **If the rewrite will be used to explain the Court's reasoning rather than just the outcome, consider adding:** *"Under the traditional rule, control alone isn't enough — both the company and the employee also have to have agreed, at least implicitly, that the employee acts on the company's behalf. An employee typically meets that standard; a corporate owner acting in their personal capacity may not."*

**"Special circumstances" was simplified.** The phrase "in the absence of special circumstances" signals that the general rule has exceptions without specifying them. The rewrite says "something more has to be true beyond simply being in charge," which conveys the structure but omits that the exceptions are legally defined, not open-ended. For a lay audience this is appropriate, but the user should be aware that the simplification does not tell the reader what would constitute a "special circumstance."

---

## Suggested follow-ups

1. **If the reader asks "so owners can never be responsible?"** — A follow-up clarification might be useful: the ruling means owners aren't *automatically* responsible just because they're in charge; they can still be liable if they were personally involved in the discriminatory act or if other legal standards are met.
2. **If a longer version is needed** (e.g., for an educational explainer or a community briefing), the consent element of agency and the specific Fair Housing Act context could be restored with examples — for instance, explaining what the original Ninth Circuit ruling would have meant in practice for housing discrimination cases.
3. **If a shorter version is needed** (e.g., a single paragraph summary), the rewrite can be condensed to: *"Under long-standing legal rules, when a company's employee does something unlawful on the job, the company — not its owner or officers personally — is the one held responsible. A lower federal court ruled that the Fair Housing Act changed this, making owners personally liable just for being in control of the employee who acted wrongly. The Supreme Court disagreed, ruling that the Act did not change the traditional rule: control alone is not enough to make an owner personally responsible for an employee's discriminatory acts."*
