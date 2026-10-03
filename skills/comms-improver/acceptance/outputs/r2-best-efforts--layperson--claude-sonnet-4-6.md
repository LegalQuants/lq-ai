<!--
run: comms-improver--r2-best-efforts--layperson--anthropic
provider: anthropic
requested_model: claude-sonnet-4-6
resolved_model: claude-sonnet-4-6
run_at: 2026-07-10T22:00:25-07:00
max_tokens: 4096
params: temperature/top_p/thinking OMITTED (faithful to gateway); tools NONE
system_prompt_sha256: b6b7d5c0f3c7f8ef957897d23c3f7f9ce1b148d629d958d01c47f53756d36288
user_trigger: 'Please apply the skill to the provided inputs and produce the output as specified.'
assertions: clean
-->

# Comms Improver: Inventory allocation during shortage clause

**Audience:** Non-legal layperson
**Purpose:** Explain what this clause means in plain language
**Length constraint:** Matched to original (short clause)
**Tone:** Neutral, conversational

---

## Rewritten text

> During a shortage, the supplier will do their best to make sure you still get inventory. But they're not required to go out and buy extra stock at inflated prices just for you, and they can't be forced to break prior commitments they've already made to other customers at the same level.

---

## What was changed

- **"Best efforts" → "will do their best"** — simplified to conversational language (see note below on why this term is flagged).
- **Active, direct structure** — reoriented from a supplier-obligation framing into plain cause-and-effect: shortage → what happens to you → what the supplier is not required to do.
- **"Procure inventory from third parties at a premium" → "buy extra stock at inflated prices"** — same meaning, everyday words.
- **"Existing commitments to other customers of similar tier" → "prior commitments they've already made to other customers at the same level"** — same meaning, no jargon.

---

## Terms simplified or preserved

| Original term | Treatment | Note |
|---|---|---|
| **"Best efforts"** | Simplified to "will do their best" | ⚠️ See concern below — this is a legal term of art with graduated standards |
| **"Shortage"** | Preserved verbatim | Straightforward; no simplification needed |
| **"Procure at a premium"** | Simplified to "buy at inflated prices" | Meaning preserved |
| **"Existing commitments"** | Simplified to "prior commitments they've already made" | Meaning preserved |
| **"Customers of similar tier"** | Simplified to "customers at the same level" | Meaning preserved; see concern below |

---

## Preservation-of-meaning concerns

**1. "Best efforts" is a legal term of art — and it matters here.**
In contract law, "best efforts," "reasonable efforts," and "commercially reasonable efforts" are distinct standards with different legal weight, and courts have interpreted them differently. "Best efforts" is generally the *highest* standard — it may require the supplier to take steps beyond what's merely reasonable. Simplifying it to "will do their best" captures the spirit but loses that legal specificity. For a non-legal layperson who just wants to understand the gist, this simplification is probably fine. But if the reader is making a business decision based on how hard the supplier is *actually required* to try, they should know the original says "best efforts" — a demanding standard.

**2. "Customers of similar tier" may have a specific meaning.**
This phrase implies there's a tiering system for the supplier's customers (e.g., platinum, gold, standard). The plain rewrite says "at the same level," which conveys this, but if the tiers are formally defined elsewhere in the contract, the precise tier definition controls. The layperson reader should know this isn't just "other customers generally" — it's customers ranked comparably to them.

**3. The clause is written entirely from the supplier's perspective.**
The original is a supplier obligation clause — it says what the supplier will *try* to do and what they are *not required* to do. The plain rewrite preserves this framing. A layperson reader might ask: "What are *my* rights if they don't allocate inventory to me?" This clause doesn't answer that — it only describes the supplier's obligations and carve-outs. That may be worth flagging to the reader.

---

## Suggested follow-ups

1. **If the reader asks "what happens if the supplier still doesn't send me anything?"** — this clause doesn't address remedies. That question points to a different part of the contract (breach, termination, or force majeure clauses). Worth flagging if the reader is in an active shortage situation.
2. **If the reader needs more precision on "best efforts"** — consider adding a parenthetical: "will make their strongest effort (the contract uses the high legal standard of 'best efforts')."
3. **If this is being shared as a summary of the customer's position** (not just an explanation) — you may want to add one sentence on what the customer *can* expect: "In practice, this means the supplier must prioritize allocating available stock to you — they just can't be held to guarantees they physically can't meet."
