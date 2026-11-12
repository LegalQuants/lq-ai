<!--
run: comms-improver--03-memo-workforce--executive--anthropic
provider: anthropic
requested_model: claude-sonnet-4-6
resolved_model: claude-sonnet-4-6
run_at: 2026-07-10T21:57:26-07:00
max_tokens: 4096
params: temperature/top_p/thinking OMITTED (faithful to gateway); tools NONE
system_prompt_sha256: 86e30139d7a153c99de64897aa7ec1d9a3c974ee938a21d1b221665145766598
user_trigger: 'Please apply the skill to the provided inputs and produce the output as specified.'
assertions: clean
-->

# Comms Improver: Workforce Analytics Program — Legal Memo to Executive Briefing

**Audience:** CEO and CFO — executive decision briefing
**Purpose:** Decision input — approve or decline the workforce analytics program
**Length constraint:** Matched to audience (brief; bottom line first)
**Tone:** Crisp, businesslike, decision-oriented

---

## Rewritten text

> **Workforce Analytics Program — Legal Sign-Off Summary**
>
> **Bottom line: Legal has approved the program to move forward, with conditions.**
>
> The program can use Calendar, HR, and similar tool data to track high-level engagement signals — things like average meetings per week, all-hands attendance, and manager one-on-one cadence. For now, it covers US employees only; expanding globally requires a separate legal review.
>
> **Four conditions apply:**
>
> 1. **Use only high-level indicators.** Don't collect granular behavioral data — message response times, camera-on rates, emoji activity, or data that could touch protected group participation are out.
> 2. **Data access is need-to-know.** Individual-level data is restricted to direct managers, senior management, and HR. Broader analytics teams see aggregate data only.
> 3. **No automated decisions.** Engagement signals can prompt a manager to investigate, coach, or intervene — they cannot by themselves be the basis for termination, demotion, or denial of benefits.
> 4. **Privacy notice may need updating.** Existing employee notices likely cover these uses, but we'll confirm. If the program expands or produces deeper insights, a notice refresh will be required before that expansion.
>
> **One flag for awareness:** Scoping to the US only means the data won't reflect the full global workforce, which could bias conclusions. The analytics team should account for this when presenting findings.
>
> **Recommended action:** Approve the program on these terms. Legal will monitor for triggers requiring global expansion review or privacy notice updates.

---

## What was changed

- **Led with the decision, not the analysis.** The original memo structures as Issue → Rules → Analysis → Conclusion. For an executive audience that needs to decide, the conclusion comes first: "Legal has approved, with conditions."
- **Condensed four analytical sections into four numbered conditions.** The original's structure was written for a legal reader working through the reasoning. The executive version presents the outcome of that reasoning as action items.
- **Eliminated legal framing and jargon habits.** "Implicate potential council/employee representative consultation," "over-inclusivity and over-collection," "scope discipline is the primary control" — these are replaced with direct statements about what the program can and can't do.
- **Preserved the bias flag.** The original raised the US-only scope as a potential analytical limitation. This is a substantive business point for executive awareness and was retained rather than buried.

---

## Terms simplified or preserved

| Original term | Treatment | Notes |
|---|---|---|
| "Automated Decision-Making Technology Rules" | Simplified → "No automated decisions" | The operative constraint for the audience is the action rule, not the regulatory label. |
| "Significant decision" (termination, demotion, denial of benefits) | Preserved with examples | The examples were already in the original and carry the meaning; retained verbatim. |
| "Need-to-know" | Preserved | Common enough in business contexts that it needs no translation; removing it would lose precision. |
| "Legal holds" / "recordkeeping requirements" | Omitted | Relevant to operational implementation, not to the executive approval decision. The conditions that matter for approval are the four listed. |
| "Protected group activity" | Preserved | Potentially legally significant term; simplified alternatives ("sensitive activity") could lose the legal weight. |
| "Aggregate" vs. individual-level data | Preserved as a distinction | The distinction between individual-level and aggregate access is operationally meaningful and was retained. |
| "Scope discipline" | Replaced → "Use only high-level indicators" | "Scope discipline" is legal-internal shorthand. The plain version communicates the same constraint in terms the executive can act on. |

---

## Preservation-of-meaning concerns

**The bias flag requires a judgment call.** The original notes that US-only scoping "potentially biases the conclusions" but frames it as a side observation. The rewrite elevates it to a named flag. Depending on how significant the team believes this limitation is, the language could be softened ("the data will reflect US employees only, which the analytics team should keep in mind") or strengthened ("conclusions about global workforce health cannot be drawn from this program"). The current rewrite is mid-register — flag this with whoever is presenting findings to confirm the right framing.

**"Likely covered" on the privacy notice.** The original says existing notices "likely" cover these uses. The rewrite softens this slightly ("existing employee notices likely cover these uses, but we'll confirm"). If Legal has already confirmed coverage, this hedge can be removed. If there's genuine uncertainty, the hedge should stay and the executives should know that a notice review is in progress, not just anticipated.

**Global expansion is deferred, not declined.** The rewrite says "requires a separate legal review" — which accurately reflects the original. If the executives might interpret this as a soft no on global expansion, it may be worth adding that legal is available to begin that review when the business is ready to scope it.

---

## Suggested follow-ups

1. **If they ask "what happens if we want to expand globally?"** — prepare a one-paragraph summary of what that review would involve (works council consultation obligations, GDPR requirements, likely timeline). The current briefing defers the question; the follow-up answers it.
2. **If they ask "what does a privacy notice refresh actually mean for employees?"** — have a one-sentence answer ready: employees would receive an updated notice describing the analytics uses before the program expands, likely via email or the employee handbook.
3. **If they want to share this with the business owner or analytics team lead** — the current version is calibrated for executives. A version for the operational team (what they can build, what's excluded, how access is structured) would need more detail on the four conditions. Run the skill again with audience set to the analytics program lead.
