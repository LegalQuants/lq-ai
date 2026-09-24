---
fixture: dated-deadlines
skill: action-items-from-client-alert
description: >
  Single-jurisdiction client alert with an explicit alert date and
  three explicit deadlines (test-plan.md Scenario 1): deadlines must be
  preserved exactly and items bucketed by timeframe.
synthetic: >
  All parties, names, laws, and facts are fully synthetic test data
  authored for DE-231. The "State of New Cambria" and its statute are
  fictional. Not a real document, not legal advice, not attorney work
  product.
prompt: |
  Please extract action items from the attached client alert. Our
  organization: a Delaware-incorporated consumer-electronics retailer
  with about 900 employees, selling online to customers in all US
  states including New Cambria; we have an existing privacy program.
  Relevant business areas: e-commerce, marketing, customer support.
skill_inputs:
  document: Provided in full in the message below.
  organization_context: Delaware-incorporated consumer-electronics retailer, ~900 employees, online sales to all US states including New Cambria; existing privacy program.
  alert_date: June 5, 2026
---

# CLIENT ALERT — HARBORLIGHT LLP

**June 5, 2026**

## New Cambria Amends Its Consumer Data Protection Act: What Retailers
Need to Do Before October

On May 28, 2026, the fictional State of New Cambria enacted Senate Bill
214, amending the New Cambria Consumer Data Protection Act ("NC-CDPA").
The amendments principally affect retailers that process the personal
data of 50,000 or more New Cambria residents in a calendar year.

### Key changes

1. **Universal opt-out signals (Section 12).** Covered retailers must
   honor browser-based universal opt-out signals for targeted
   advertising. This requirement takes effect on **October 1, 2026**.

2. **Data-broker registration (Section 15).** Companies that sell
   personal data they did not collect directly from consumers must
   register with the New Cambria Department of Commerce and pay an
   annual fee. Existing businesses must register by **November 15,
   2026**; registration renews each January 31 thereafter.

3. **Recognition audits (Section 17).** Covered retailers must conduct
   an annual audit of their opt-out-signal recognition mechanisms and
   retain audit records for five years. The first audit must be
   completed within twelve months of the effective date of the
   amendments and annually thereafter — an ongoing obligation.

4. **Cure-period sunset (Section 21).** The Attorney General's
   mandatory 30-day cure period for alleged violations sunsets on
   **January 1, 2027**, after which the AG may bring enforcement
   actions without a cure opportunity. Civil penalties remain up to
   $7,500 per violation.

### Who is covered

The amendments apply to controllers doing business in New Cambria that
meet the 50,000-resident processing threshold, with the existing
NC-CDPA exemptions (HIPAA-regulated entities, financial institutions
subject to GLBA) unchanged. The data-broker registration duty in
Section 15 applies regardless of the 50,000-resident threshold.

### Recommended first steps

Retailers should confirm coverage against the processing threshold,
inventory current opt-out-signal handling against Section 12, assess
whether any data-sales practices trigger Section 15 registration, and
calendar the audit cycle required by Section 17.

*This alert is a summary for clients of Harborlight LLP and is not
legal advice. Contact your Harborlight relationship attorney with
questions about your specific circumstances.*
