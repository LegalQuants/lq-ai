# Privilege gate and intake interview

This is the first step of the workflow. It runs before any ingestion or drafting.

## The privilege gate (hard stop)

Print this banner exactly:

> **YOU ARE ABOUT TO DO HIGHLY PRIVILEGED WORK. PLEASE CHECK THE RULES OF YOUR JURISDICTION, AS YOU MAY NEED TO SWITCH TO A LOCAL MODEL. BEFORE YOU PROCEED, CONFIRM THAT YOU ARE FINE WITH PROCEEDING.**

Then name the concrete checks, plainly:

- the seat of the arbitration and its rules,
- the institutional rules (ICC, LCIA, or other),
- the parties' national laws,
- the applicable bar and ethics rules,
- the CIArb Guideline on the Use of AI in Arbitration (2025): section 2.2 on confidentiality and third-party or cloud AI, section 6.7 on which rules govern, and section 7 on disclosure of AI use.

State the posture: assume local or on-premises execution, and do not send live schedule content to a cloud endpoint without the seat's rules, the parties' agreement, and the client's consent.

Do not ingest any attachment, read any schedule content, or draft anything until the user gives an explicit affirmative that they are fine to proceed. If the user does not confirm, stop and produce nothing.

## The intake interview

After confirmation, ask only for what the user has not already supplied, one question at a time, in this order. Skip any item already given in the trigger.

1. **Role.** Are you acting for the requesting party, the producing party, or the tribunal. This drives the pipeline and the column or columns you are allowed to write.
2. **Regime.** IBA Rules 2020 (default), Prague Rules 2018, ICC, LCIA, or ICSID. If unknown, default to IBA 2020 and say so.
3. **Round.** Is this a first draft, a set of objections, a reply to objections, a tribunal decision pass, a merge of a returned schedule, or a simultaneous (joint) exchange where both sides serve requests at once.
4. **State party.** Is any party a State or a state-owned entity. If yes, record which. This arms the Article 9.2(f) sensitivity prompt, which is then applied by document content, not by ownership alone.
5. **Issues list.** Is there a pleaded-issues list to tie relevance to. If not, relevance ties will be marked unverified.
6. **Sources.** Where are the requests, or the returned schedule. Plain text, an attachment, or a grid.
7. **Timetable (optional).** Are there production deadlines set by Procedural Order No. 1 or a procedural order (dates for requests, objections, replies, decision, production). If supplied, they are recorded and any out-of-time step is flagged. If not, the run is not calibrated to a timetable.

Ask one real question at a time. Do not invent inputs the user did not give. If the user supplied everything in the trigger, skip the interview and confirm the routing back to them in one line before proceeding.
