<!--
run: comms-improver--01-clause-lol--layperson--anthropic
provider: anthropic
requested_model: claude-sonnet-4-6
resolved_model: claude-sonnet-4-6
run_at: 2026-07-10T21:56:51-07:00
max_tokens: 4096
params: temperature/top_p/thinking OMITTED (faithful to gateway); tools NONE
system_prompt_sha256: 8f549d86b29e6dd53a23baa3d32bdc7d4f67467028732c20427671070cf015b1
user_trigger: 'Please apply the skill to the provided inputs and produce the output as specified.'
assertions: clean
-->

# Comms Improver: Limitation of Liability Clause

**Audience:** Non-legal layperson — customer reading their own services agreement, no legal background
**Purpose:** Help the customer understand what they can and cannot claim if something goes wrong
**Length constraint:** Matched to substance; shorter than original
**Tone:** Direct, plain, second person

---

## Rewritten text

> **What happens if something goes wrong — our responsibility to you**
>
> If you have a problem related to this agreement or the equipment, there are two important limits on what you can claim from us:
>
> **1. We are not responsible for certain types of losses.**
> Even if we knew a problem was possible, we are not liable for losses like:
> - lost profits or revenue
> - lost data
> - disruption to your business
> - other knock-on financial losses
>
> This applies regardless of how the problem arose — whether through our fault, a product defect, or otherwise.
>
> **2. The total amount you can claim from us is capped.**
> The most we will ever owe you under this agreement is the amount you actually paid us for the specific equipment that caused the problem. We cannot owe you more than that, no matter what.
>
> **These limits do not apply if you are injured, or if the equipment damages your property.**
> If the equipment hurts someone or damages your property because it is defective, these caps do not apply. You can still make a full claim for personal injury or property damage caused by a defect in the equipment.

---

## What was changed

- **Led with a plain-language heading** that tells the reader what the section is about before any substance. The original's all-caps heading ("LIMITATION OF LIABILITY") is a legal label, not a reader-oriented explanation.
- **Broke into three numbered/labelled parts** — the exclusion of damage types, the aggregate cap, and the carve-out for personal injury and property damage. The original runs these together in two dense paragraphs with no internal signposting.
- **Converted the list of excluded damage types** from a wall of legal terms ("indirect, extraordinary, exemplary, punitive, special, incidental, consequential") to four everyday examples of what those categories actually mean to a customer (lost profits, lost data, business disruption, knock-on financial losses).
- **Moved the personal injury / property damage carve-out to a prominent position at the end**, framed as what the customer *can* still claim. The original buries this carve-out as the last sentence of the second paragraph, which means most readers never get there.
- **Removed all legal theory enumeration** ("contract, tort, negligence, strict liability, products liability or under any other theory of liability") — this is meaningful in a courtroom but tells a layperson nothing useful. The rewrite captures the practical effect: these limits apply however the problem arose.

---

## Terms simplified or preserved

| Original term | Rewrite treatment | Notes |
|---|---|---|
| Indirect, extraordinary, exemplary, punitive, special, incidental, consequential damages | Replaced with plain examples (lost profits, lost data, business disruption, knock-on financial losses) | These are legal damage categories; a layperson reader does not need the taxonomy, they need to know *what kinds of losses* are excluded. The plain examples cover the practical scope. Flag: the rewrite does not enumerate every sub-category; if a specific excluded type is legally important for the user's product (e.g., loss of use), verify the examples are adequate. |
| "Aggregate liability" | "Total amount you can claim from us" | Straightforward simplification; meaning preserved. |
| "Amounts actually paid by Distributor to Seller for the Equipment under the Approved Order for the Equipment giving rise to liability" | "The amount you actually paid us for the specific equipment that caused the problem" | Simplified; meaning preserved. "Approved Order" defined-term reference dropped — not meaningful to a layperson reading this clause in isolation. |
| "Personal injury or property damage caused by Equipment defects" | Preserved verbatim in substance; reworded slightly for second-person direct address | This is the carve-out that protects the reader most directly. The rewrite keeps the full scope (personal injury *and* property damage, caused by *defects* specifically). |
| "Contract, tort, negligence, strict liability, products liability, or under any other theory of liability" | Dropped | Legal theory enumeration. For a layperson audience this adds no meaning. Replaced with "however the problem arose." |
| "Even if Seller knows there is a possibility of such damage" | "Even if we knew a problem was possible" | Direct simplification; meaning preserved. |

---

## Preservation-of-meaning concerns

**1. The excluded damages list is illustrative, not exhaustive.**
The original lists specific legal categories that courts have defined. The plain-language rewrite gives examples of what those categories mean in practice. A sophisticated reader could argue the examples are narrower than the legal categories — for instance, "loss of use" (a recognised damage type) is not explicitly called out. For a layperson customer audience this is appropriate; the examples communicate the practical effect. However, if this rewrite is used in a revised customer-facing agreement rather than as an explanatory companion document, the drafting team should confirm the examples are either exhaustive or introduce language like "and other similar losses" to preserve breadth.

**2. "Distributor" in the original — the party being addressed.**
The original clause addresses the "Distributor," not an end customer. The rewrite converts this to second-person ("you"), which is appropriate for the stated audience. However, if this clause governs a distributor relationship (business-to-business) rather than a direct customer relationship, the audience may be mischaracterised and the simplification could obscure the fact that the clause governs a commercial distribution agreement, not a consumer services agreement. Verify that the stated audience (end customer, no legal background) is actually the reader of this agreement.

**3. "Approved Order" is a defined term that has been dropped.**
The cap calculation ties to amounts paid "under the Approved Order for the Equipment giving rise to liability" — meaning the cap is calculated order-by-order, not across the whole relationship. The rewrite captures this ("the specific equipment that caused the problem") but loses the precision of the defined term. If the customer has multiple orders, this matters — the cap for a problem with Order 1 is what they paid on Order 1, not the total they've ever paid the seller. The rewrite is approximately correct for a single-order reader; a multi-order customer may be misled.

---

## Suggested follow-ups

1. **If the customer asks "does this mean you're not responsible for anything?"** — A short follow-up explanation is useful: the clause limits *financial* liability for economic losses, but the personal injury / property damage carve-out means defective equipment that causes physical harm or damage to property is still fully claimable. That's the protection most customers actually care about.
2. **If this rewrite is being embedded in the agreement itself (not just a companion explanation):** have legal review the examples in the excluded-damages section to confirm they are broad enough to capture the intended scope. Plain-language rewrites in operative contract text carry more risk than companion explanations.
3. **If the audience is actually a B2B distributor** (as the original "Distributor" language suggests): the tone and framing of this rewrite is calibrated for a consumer. Run the skill again with audience set to "deal-team / commercial counterparty" for a version that preserves more legal structure.
