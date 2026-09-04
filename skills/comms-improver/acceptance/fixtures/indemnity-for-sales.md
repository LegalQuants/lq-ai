---
fixture: indemnity-for-sales
skill: comms-improver
description: >
  Jargon-heavy indemnification/limitation clause rewritten for a sales
  team (test-plan.md Scenario 3: operationally usable; what they can
  say, cannot say, and when to escalate).
synthetic: >
  All parties, names, and facts are fully synthetic test data authored
  for DE-231. Not a real document, not legal advice, not attorney work
  product.
prompt: |
  Please rewrite the following contract language in plain language for
  our sales team. Audience: sales team — they need to understand what
  they can and can't promise to prospects about who pays when things go
  wrong, and when to loop in legal. The source text is below.
skill_inputs:
  text: The indemnification and limitation-of-liability language quoted in full in the message below.
  audience: Sales team; need to understand what they can and can't say to prospects about liability and indemnity, and when to escalate to legal.
  purpose: Action prompt — sales must know the boundaries before customer calls.
---

Excerpt from the Pinwheel Robotics standard Master Subscription
Agreement, Sections 8 and 9:

"8. Indemnification. Provider shall defend, indemnify, and hold
harmless Customer from and against any and all third-party claims,
demands, suits, or proceedings alleging that the Service, as provided
by Provider and used in accordance with this Agreement, infringes any
United States patent issued as of the Effective Date or any copyright,
and shall pay all damages finally awarded against Customer by a court
of competent jurisdiction, or agreed in settlement by Provider, that
are attributable to any such claim; provided, however, that Customer
(a) promptly notifies Provider in writing of any such claim, (b) grants
Provider sole control of the defense and settlement thereof, and (c)
provides reasonable cooperation at Provider's expense. The foregoing
notwithstanding, Provider shall have no obligation hereunder to the
extent any such claim arises from (i) modifications to the Service not
made by Provider, (ii) combination of the Service with products,
processes, or materials not supplied by Provider, where the Service
alone would not infringe, or (iii) Customer's continued use of the
Service after Provider has provided a substantially equivalent
non-infringing alternative.

9. Limitation of Liability. IN NO EVENT SHALL EITHER PARTY BE LIABLE
FOR ANY INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES, INCLUDING LOST PROFITS, LOSS OF USE, OR LOSS OF DATA, HOWEVER
CAUSED AND UNDER ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.
EXCEPT FOR PROVIDER'S INDEMNIFICATION OBLIGATIONS UNDER SECTION 8 AND
CUSTOMER'S PAYMENT OBLIGATIONS, EACH PARTY'S AGGREGATE LIABILITY
ARISING OUT OF OR RELATED TO THIS AGREEMENT SHALL NOT EXCEED THE TOTAL
AMOUNTS PAID OR PAYABLE BY CUSTOMER HEREUNDER IN THE TWELVE (12) MONTHS
IMMEDIATELY PRECEDING THE FIRST EVENT GIVING RISE TO LIABILITY."
