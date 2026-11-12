<!--
run: comms-improver--03-memo-workforce--layperson--anthropic
provider: anthropic
requested_model: claude-sonnet-4-6
resolved_model: claude-sonnet-4-6
run_at: 2026-07-10T21:59:48-07:00
max_tokens: 4096
params: temperature/top_p/thinking OMITTED (faithful to gateway); tools NONE
system_prompt_sha256: 72dd318aa7aeddda123b05d22619db944e49766c69e9b61eb18edd6971bfcac8
user_trigger: 'Please apply the skill to the provided inputs and produce the output as specified.'
assertions: clean
-->

# Comms Improver: Workforce Analytics Program Legal Memo

**Audience:** Non-legal layperson with no legal or technical background
**Purpose:** Explain what was approved, what the rules are, and what's off-limits — in plain language
**Length constraint:** Matched to original structure, compressed for accessibility
**Tone:** Neutral, conversational, direct

---

## Rewritten text

> **What We're Doing — and How We're Doing It Responsibly**
>
> We're launching a workforce analytics program to get a better sense of how engaged and connected our employees are. Think of it as a way to spot trends — like whether teams are getting enough one-on-one time with their managers, or whether all-hands attendance is dropping — so we can step in and help before small issues become bigger ones.
>
> **What data we'll use**
>
> We'll only look at high-level signals already collected through normal work tools — things like:
> - Average number of meetings per week
> - All-hands attendance rates
> - How often managers hold one-on-ones with their direct reports
> - Manager turnover
>
> We're keeping it simple and high-level on purpose.
>
> **What we won't track**
>
> Some things are off the table entirely. We won't measure:
> - How quickly someone responds to a message
> - Whether someone has their camera on during a video call
> - Emoji use or reaction times
> - Participation in any group activity that could relate to protected characteristics (like union activity or religious groups)
>
> **Who can see the data**
>
> Access is limited to people who genuinely need it:
> - Direct managers (for their own team)
> - Senior leadership and HR (for broader trends)
> - The analytics team (summary/aggregate views only — no individual-level detail)
>
> **How findings can — and can't — be used**
>
> The data is a starting point for conversations, not a verdict. A low engagement signal might prompt a manager to check in with someone, offer coaching, or think about how to better support their team. It cannot, on its own, be the reason someone is fired, demoted, or denied a benefit. Any serious decision still requires a real human review.
>
> **Where this applies**
>
> For now, this program only covers our US employees. Expanding to other countries requires a separate review — privacy rules for employees are significantly stricter in many parts of the world, and we need to work through those requirements before proceeding globally. We're aware this means our data will reflect the US workforce only, which may limit what we can conclude about the company as a whole.
>
> **What's coming next**
>
> We'll be reviewing our employee privacy notice to make sure it clearly covers this program. It likely already does, but we want to confirm — and update it if needed.

---

## What was changed

- **Led with purpose, not process.** The original opens with a legal framing ("Issue: Can we use a workforce analytics program…"). The rewrite opens with a plain statement of what the program is and why it exists.
- **Converted legal categories into plain headings.** "Automated Decision-Making Technology Rules," "Data Retention & Legal Holds," and "Jurisdictional Constraints" became human-readable sections: "How findings can and can't be used," "Where this applies," etc.
- **Replaced legal conditionals with direct statements.** Phrases like "engagement signals may inform us to look closely, but they cannot independently themselves alone be a basis for a significant decision" became: "A low engagement signal might prompt a manager to check in… It cannot, on its own, be the reason someone is fired."
- **Bullet lists for exclusions and access rules.** The original's prose descriptions of excluded data types and access tiers read more clearly as scannable lists for a lay reader.

---

## Terms simplified or preserved

| Original term | How it was handled |
|---|---|
| "Automated Decision-Making Technology" | Replaced with plain description: the data can't be the standalone reason for a serious decision |
| "Granular content measurement" | Replaced with concrete examples (camera-on rates, response times, emoji tracking) |
| "Need-to-know basis" | Preserved as a phrase (widely understood) and explained by listing who qualifies |
| "Aggregate data" | Replaced with "summary views" and "no individual-level detail" |
| "Legal holds" / "anticipated employment claims" | Simplified and omitted from the main rewrite (see Preservation-of-meaning concerns below) |
| "Council/employee representative consultation" | Replaced with "privacy rules for employees are significantly stricter in many parts of the world" |
| "Protected group activity" | Kept with a brief parenthetical example (union activity, religious groups) |

---

## Preservation-of-meaning concerns

**1. Legal holds and data retention were condensed significantly.**
The original memo contains a nuanced point: granular individual data is deleted when an employee leaves, *except* when a legal hold applies (e.g., if there's an anticipated employment lawsuit or regulatory obligation). This is an important operational point — if the HR or legal team needs to preserve data related to a specific employee dispute, that process still applies. The rewrite omits this detail to avoid overwhelming a lay reader, but depending on the audience's role (e.g., an HR manager or people ops lead), you may want to add a line: *"If there's an active or anticipated legal matter involving an employee, normal legal hold rules apply — check with Legal before deleting anything."*

**2. "Cannot on its own" is a simplification of the automated decision-making rule.**
The original is clear that engagement signals cannot *independently* drive a significant decision. The rewrite captures this as "cannot, on its own, be the reason." This is accurate, but the original also implies an affirmative duty to further investigate or involve a human manager before acting. If this rewrite will be seen by managers who make employment decisions, you may want to reinforce that the expectation isn't just "don't rely on the data alone" but "use it as a prompt to engage directly."

**3. The US-only scope limitation and its bias caveat.**
The memo notes — a bit unusually — that limiting to US data may bias conclusions about the global workforce. The rewrite preserves this honestly. Depending on the audience, you may prefer to soften or omit the bias caveat if it will generate more confusion than clarity.

---

## Suggested follow-ups

1. **If the audience includes people managers or HR:** Consider adding a one-paragraph companion piece specifically for managers, covering the "what you can do with this information" question with concrete examples (e.g., "if your team's one-on-one cadence drops, that's a prompt to reconnect — not a basis for a performance review").
2. **If this will be shared company-wide (e.g., as an employee communication):** The tone and framing would need adjustment — employees reading about their own monitoring will have different questions than managers reading about a tool they'll use. Run the skill again with audience set to "employees who will be subject to the program."
3. **If the privacy notice refresh surfaces material changes:** A separate plain-language summary of what changed in the notice — and why — would be worth preparing at that stage.
