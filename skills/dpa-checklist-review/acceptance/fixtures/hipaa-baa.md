---
fixture: hipaa-baa
skill: dpa-checklist-review
description: >
  Business associate agreement reviewed under the hipaa_baa regime
  (test-plan.md Scenario 4): a mostly-complete BAA with a couple of
  soft spots (no minimum-necessary commitment; long breach-notice
  window) to exercise Partial statuses.
synthetic: >
  All parties, names, addresses, and facts are fully synthetic test data
  authored for DE-231. Not a real document, not legal advice, not
  attorney work product.
prompt: |
  We are the covered entity. Please run your checklist review of the
  attached business associate agreement. Regulatory regime: HIPAA BAA.
  Party role: covered entity.
skill_inputs:
  document: Provided in full in the message below.
  regulatory_regime: hipaa_baa
  party_role: controller
---

# BUSINESS ASSOCIATE AGREEMENT

This Business Associate Agreement ("BAA") is entered into as of
July 15, 2026 between **Stonebridge Medical Group LLC**, a Colorado
limited liability company ("Covered Entity"), and **Pinwheel Robotics
Inc.**, a Delaware corporation ("Business Associate"), in connection
with services under the Master Subscription Agreement dated June 1,
2026 that involve Protected Health Information ("PHI") as defined in 45
CFR §160.103.

**1. Permitted Uses and Disclosures.** Business Associate may use and
disclose PHI solely to perform the scheduling services described in the
underlying agreement, as permitted by this BAA, or as required by law
(45 CFR §164.504(e)(2)(i)).

**2. Safeguards.** Business Associate will use appropriate
administrative, physical, and technical safeguards, and comply with the
Security Rule (45 CFR Part 164, Subpart C) with respect to electronic
PHI, to prevent use or disclosure other than as provided by this BAA.

**3. Reporting.** Business Associate will report to Covered Entity any
use or disclosure not provided for by this BAA, any security incident,
and any breach of unsecured PHI, without unreasonable delay and in no
case later than thirty (30) days after discovery, including the
information required by 45 CFR §164.410.

**4. Subcontractors.** Business Associate will ensure that any
subcontractor that creates, receives, maintains, or transmits PHI on
its behalf agrees in writing to restrictions and conditions at least as
stringent as those in this BAA (45 CFR §164.502(e)(1)(ii)).

**5. Access and Amendment.** Business Associate will make PHI in a
designated record set available to Covered Entity as necessary to
satisfy Covered Entity's obligations under 45 CFR §164.524 and §164.526
within fifteen (15) business days of request.

**6. Accounting of Disclosures.** Business Associate will document
disclosures of PHI and make the information available to Covered Entity
as required for an accounting under 45 CFR §164.528.

**7. Books and Records.** Business Associate will make its internal
practices, books, and records relating to the use and disclosure of PHI
available to the Secretary of Health and Human Services for purposes of
determining compliance.

**8. Return or Destruction.** Upon termination of the underlying
agreement, Business Associate will return or destroy all PHI, if
feasible; where return or destruction is infeasible, protections of
this BAA extend to the retained PHI for as long as it is maintained.

**9. Termination for Cause.** Covered Entity may terminate the
underlying agreement if Business Associate materially breaches this BAA
and fails to cure within thirty (30) days of written notice.

**10. Miscellaneous.** This BAA is interpreted to permit compliance
with the HIPAA Rules. In the event of conflict with the underlying
agreement, this BAA controls as to PHI.

**STONEBRIDGE MEDICAL GROUP LLC**    **PINWHEEL ROBOTICS INC.**
By: /s/ Rowan Exemplar               By: /s/ Quinn Specimen
Title: Chief Administrative Officer  Title: CEO
