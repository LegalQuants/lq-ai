---
fixture: scenario-late-payment
skill: contract-qa
description: >
  Type D scenario question: what happens if payment is ten days late?
  Expects the controlling provisions as a bulleted chain with quotes
  and a consequence trace (SKILL.md Type D format).
synthetic: >
  All parties, names, addresses, and facts are fully synthetic test data
  authored for DE-231. Not a real document, not legal advice, not
  attorney work product.
prompt: |
  Under the attached subscription agreement, if we pay an invoice ten
  days after its due date, what can the provider do, and in what
  sequence?
skill_inputs:
  document: Provided in full in the message below.
  question: If we pay an invoice ten days after its due date, what can the provider do, and in what sequence?
  perspective: our_side
---

# PLATFORM SUBSCRIPTION AGREEMENT

This Platform Subscription Agreement (this "Agreement") is entered into
as of April 22, 2026 between **Atlas Biotech Inc.**, a Delaware
corporation ("Customer"), and **Juniper Grid Systems Inc.**, a Nevada
corporation ("Provider").

**1. Access.** Provider grants Customer access to its laboratory
inventory platform for the term of this Agreement.

**2. Fees; Late Payment.**
(a) Fees are $6,000 per month, invoiced monthly in advance, due net
thirty (30) days from invoice date.
(b) Amounts unpaid when due accrue interest at the lesser of 1.0% per
month or the maximum lawful rate, from the due date until paid.
(c) If any undisputed amount remains unpaid ten (10) days after
Provider gives written notice of non-payment, Provider may suspend
Customer's access to the platform until payment in full, upon at least
five (5) business days' additional written notice.

**3. Good-Faith Disputes.** Customer may withhold amounts disputed in
good faith, provided it notifies Provider of the dispute before the due
date and pays all undisputed amounts. Suspension rights under Section
2(c) do not apply to amounts disputed under this Section 3.

**4. Termination.**
(a) Either party may terminate for material breach uncured within
thirty (30) days of written notice. Failure to pay undisputed fees is a
material breach.
(b) Termination does not relieve Customer of amounts accrued before the
effective date of termination.

**5. Effect of Suspension.** During any suspension for non-payment,
fees continue to accrue, and Provider is not liable for any
unavailability of Customer's data, which remains exportable via the
platform's self-service tools for sixty (60) days after any
termination.

**6. Limitation of Liability.** Neither party is liable for indirect or
consequential damages. Each party's aggregate liability is capped at
fees paid in the twelve (12) months preceding the claim.

**7. General.** Governed by Delaware law; venue Wilmington, Delaware.
Entire agreement; written amendments only.

**ATLAS BIOTECH INC.**               **JUNIPER GRID SYSTEMS INC.**
By: /s/ Riley Placeholder            By: /s/ Casey Notreal
Title: VP Operations                 Title: VP Sales
