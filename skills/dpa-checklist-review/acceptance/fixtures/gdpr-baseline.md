---
fixture: gdpr-baseline
skill: dpa-checklist-review
description: >
  Complete controller-to-processor GDPR DPA covering the Article 28(3)
  elements; baseline calibration per test-plan.md Scenario 1 — most
  checklist rows should assess Present.
synthetic: >
  All parties, names, addresses, and facts are fully synthetic test data
  authored for DE-231. Not a real document, not legal advice, not
  attorney work product.
prompt: |
  We are the controller. Please run your checklist review of the
  attached data processing agreement. Regulatory regime: GDPR. Party
  role: controller (data exporter).
skill_inputs:
  document: Provided in full in the message below.
  regulatory_regime: gdpr
  party_role: controller
---

# DATA PROCESSING AGREEMENT

This Data Processing Agreement ("DPA") is entered into as of May 5,
2026 between **Harborlight Analytics Ltd.**, with offices in Dublin,
Ireland ("Controller"), and **Pinwheel Robotics Inc.**, a Delaware
corporation ("Processor"), and supplements the Master Subscription
Agreement between the parties dated May 5, 2026.

**1. Subject Matter; Roles.** Processor processes EU/EEA personal data
on behalf of Controller to provide the workforce-scheduling service.
The subject matter, duration, nature and purpose of processing, and the
categories of personal data and data subjects are set out in Annex 1.

**2. Documented Instructions.** Processor shall process personal data
only on Controller's documented instructions, including with regard to
international transfers, unless required by Union or Member State law;
in that case Processor informs Controller before processing unless the
law prohibits it (Art. 28(3)(a) GDPR).

**3. Confidentiality.** Processor ensures that persons authorised to
process the personal data have committed themselves to confidentiality
or are under an appropriate statutory obligation (Art. 28(3)(b)).

**4. Security.** Processor implements the technical and organisational
measures described in Annex 2, including encryption of personal data in
transit and at rest, access controls, logging, and annual penetration
testing, taking into account the requirements of Art. 32 GDPR.

**5. Sub-processors.** Controller grants general written authorisation
to the sub-processors listed in Annex 3. Processor gives Controller at
least thirty (30) days' prior notice of any intended addition or
replacement, during which Controller may object on reasonable grounds.
Processor imposes the same data-protection obligations on each
sub-processor by written contract and remains fully liable for
sub-processor performance (Art. 28(2), 28(4)).

**6. Data Subject Rights.** Taking into account the nature of the
processing, Processor assists Controller by appropriate technical and
organisational measures in responding to requests to exercise data
subject rights under Chapter III GDPR (Art. 28(3)(e)).

**7. Assistance.** Processor assists Controller in ensuring compliance
with the obligations in Arts. 32 to 36 GDPR (security, breach
notification, impact assessments, prior consultation), taking into
account the nature of processing and the information available to
Processor (Art. 28(3)(f)).

**8. Personal Data Breach.** Processor notifies Controller without
undue delay, and in any event within forty-eight (48) hours, after
becoming aware of a personal data breach affecting Controller's
personal data, providing the information described in Art. 33(3) GDPR
as it becomes available.

**9. Deletion or Return.** At Controller's choice, Processor deletes or
returns all personal data at the end of the provision of services and
deletes existing copies within sixty (60) days, unless Union or Member
State law requires storage (Art. 28(3)(g)).

**10. Audits.** Processor makes available to Controller all information
necessary to demonstrate compliance with Art. 28 and allows for and
contributes to audits, including inspections, conducted by Controller
or an auditor mandated by Controller, on thirty (30) days' notice, no
more than once per year absent a breach (Art. 28(3)(h)). Processor
informs Controller if, in its opinion, an instruction infringes the
GDPR.

**11. International Transfers.** Personal data is hosted in the EEA.
Any transfer to a third country occurs only under the European
Commission's Standard Contractual Clauses (Module 2), which the parties
execute as Annex 4, or another valid transfer mechanism.

**12. Term.** This DPA applies for as long as Processor processes
personal data on behalf of Controller.

**Annex 1 — Processing Details.** Data subjects: Controller's employees
and contractors. Categories: name, work contact details, shift and
scheduling data. No special categories. Duration: term of the MSA.
**Annex 2 — Security Measures.** Encryption (TLS 1.2+, AES-256 at
rest); role-based access; MFA; logging and monitoring; vendor
personnel training; incident-response plan; annual third-party
penetration test.
**Annex 3 — Authorised Sub-processors.** Fictional Cloud Hosting GmbH
(Frankfurt, hosting); Imaginary Mail Ltd. (Dublin, transactional
email).
**Annex 4 — Standard Contractual Clauses (Module 2).** [Executed by the
parties.]

**HARBORLIGHT ANALYTICS LTD.**       **PINWHEEL ROBOTICS INC.**
By: /s/ Avery Fictitious             By: /s/ Quinn Specimen
Title: DPO                           Title: CEO
