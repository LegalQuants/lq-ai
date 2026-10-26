---
fixture: disclaimer-for-customers
skill: comms-improver
description: >
  Legalese product disclaimer rewritten for non-technical consumers
  (test-plan.md Scenario 1: meaningfully simpler, legal effect
  unchanged, defined terms handled without changing scope).
synthetic: >
  All parties, names, and facts are fully synthetic test data authored
  for DE-231. Not a real document, not legal advice, not attorney work
  product.
prompt: |
  Please rewrite the following disclaimer in plain language for our
  product page. Audience: customer-facing disclaimer for non-technical
  consumers buying a home-battery monitoring app subscription. Keep it
  short enough for a product page. The source text is below.
skill_inputs:
  text: The disclaimer language quoted in full in the message below.
  audience: Non-technical consumers reading a product page for a home-battery monitoring app.
  length_constraint: Short enough for a product page; a few short paragraphs at most.
  preserve_specific_terms: Preserve the phrase "not a safety device" — regulatory counsel requires that exact phrase.
---

Excerpt from the Juniper Grid Systems consumer terms, Section 11
(Disclaimer):

"THE APPLICATION AND ANY DATA, ALERTS, ESTIMATES, OR NOTIFICATIONS
GENERATED THEREBY ARE PROVIDED FOR INFORMATIONAL PURPOSES ONLY, ARE NOT
A SAFETY DEVICE, AND ARE NOT INTENDED TO, AND SHALL NOT BE CONSTRUED
TO, CONSTITUTE ADVICE, WARNING, OR MONITORING UPON WHICH USER MAY RELY
IN CIRCUMSTANCES INVOLVING RISK OF PERSONAL INJURY, PROPERTY DAMAGE, OR
DEATH. WITHOUT LIMITING THE GENERALITY OF THE FOREGOING, COMPANY DOES
NOT WARRANT THAT BATTERY-STATE ESTIMATES, THERMAL ALERTS, OR OUTAGE
NOTIFICATIONS WILL BE ACCURATE, TIMELY, OR DELIVERED AT ALL, AND USER
ACKNOWLEDGES THAT THE APPLICATION'S FUNCTIONING IS DEPENDENT UPON
THIRD-PARTY NETWORKS, HARDWARE, AND SERVICES OUTSIDE COMPANY'S CONTROL.
USER SHALL MAINTAIN AND RELY UPON INDEPENDENT SAFETY MEASURES,
INCLUDING SMOKE AND CARBON-MONOXIDE DETECTION EQUIPMENT CONFORMING TO
APPLICABLE CODES, AND SHALL COMPLY WITH ALL MANUFACTURER INSTRUCTIONS
PERTAINING TO BATTERY INSTALLATION, VENTILATION, AND MAINTENANCE. TO
THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, COMPANY DISCLAIMS ALL
LIABILITY ARISING FROM USER'S RELIANCE ON THE APPLICATION IN LIEU OF
SUCH INDEPENDENT MEASURES."
