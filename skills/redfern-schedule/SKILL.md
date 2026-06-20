---
name: redfern-schedule
description: Use when preparing, responding to, or ruling on a Redfern Schedule for document production in international arbitration. Builds and maintains the request-to-produce table for the requesting party, the producing party, or the tribunal. Applies the IBA Rules (2020) Article 3.3 admissibility checklist and the Article 9.2 grounds for objection, raises the political and institutional sensitivity prompt by document content when a party is a State or state-owned entity, and produces an internal memo flagging the user's own weak requests or objections. Enforces form and the admissibility checklist. It does not decide whether a document is material or whether an objection will succeed.
lq_ai:
  title: Redfern Schedule
  version: 1.0.0
  author: LegalQuants
  tags: [arbitration, document-production, redfern, procedure, regulatory]
  jurisdiction: regime-aware
  trigger_examples:
    - "build a Redfern Schedule for our document requests"
    - "draft our requests to produce for the arbitration"
    - "we received the other side's Redfern Schedule, help me with our objections"
    - "reply to the objections in this Redfern Schedule"
    - "prepare the Redfern Schedule for the tribunal to rule on"
    - "run the IBA Article 3.3 check on these document requests"
  inputs:
    required: []
    optional:
      - name: role
        type: enum
        values: [requesting, producing, tribunal]
        description: Which side the user is acting for. Drives the whole pipeline. Elicited in the intake interview if not supplied.
      - name: regime
        type: enum
        values: [iba-2020, prague-2018, icc, lcia, icsid]
        description: The governing evidence regime. Defaults to iba-2020. Prague changes the request unit and the posture. ICC, LCIA, and ICSID borrow the IBA tests and add their own procedural framing. See reference/regimes.md.
      - name: round
        type: enum
        values: [first-draft, objections, reply, decision, merge, simultaneous]
        description: Where in the iteration this run sits. Use simultaneous for a joint exchange where both sides serve requests at once (party-prefixed IDs). Elicited if not supplied.
      - name: requests
        type: text
        description: The raw request list for the requesting role (plain text, a pasted list, or an attached .docx or grid). Either this or prior_schedule is needed.
      - name: prior_schedule
        type: text
        description: A returned schedule from the other side, for the producing, reply, tribunal, or merge rounds. Its existing columns are reproduced verbatim and never altered.
      - name: issues
        type: text
        description: An optional pleaded-issues list (for relevance-tying). When absent, the skill marks relevance ties as unverified.
      - name: parties
        type: text
        description: Optional party metadata. Marking any party as a State or state-owned entity arms the content-based Article 9.2(f) sensitivity prompt in the producing pipeline (raised by what a document is, not merely by who owns the party).
  output_format: report
  use_organization_profile: true
  self_improvement: false
---

> **YOU ARE ABOUT TO DO HIGHLY PRIVILEGED WORK. PLEASE CHECK THE RULES OF YOUR JURISDICTION, AS YOU MAY NEED TO SWITCH TO A LOCAL MODEL. BEFORE YOU PROCEED, CONFIRM THAT YOU ARE FINE WITH PROCEEDING.**
>
> A Redfern Schedule carries the live substance of a dispute and is usually privileged and confidential. Assume local or on-premises execution. Do not send live schedule content to a cloud endpoint without the seat's rules, the parties' agreement, and the client's consent, and a check against the CIArb Guideline on the Use of AI in Arbitration (2025) and the applicable bar and ethics rules. This warning is enforced as the first step of the workflow below.

# Redfern Schedule

Build and maintain the Redfern Schedule that organises requests to produce documents in international arbitration. The skill serves three roles from one artefact: the requesting party (who drafts the requests and the relevance-and-materiality case), the producing party (who states objections), and the tribunal (who rules). It applies the IBA Rules on the Taking of Evidence (2020) admissibility form and grounds for objection, holds version discipline across rounds, and tells the user where their own requests are weak. It enforces form. The legal calls stay with counsel.

## When this skill applies

Apply when the user is working on document production in an arbitration and wants to:

- Draft requests to produce and run them against the IBA Article 3.3 admissibility checklist.
- Respond to the other side's requests by mapping objections to the Article 9.2 grounds.
- Reply to objections already entered against the user's requests.
- Prepare a clean, decision-ready schedule for the tribunal.
- Merge a returned schedule from the other side into the working file without losing column discipline.

## When this skill does not apply

Do not apply when:

- The user wants advice on whether a specific objection will win or whether a document is truly material. The skill enforces form and flags weakness. It does not predict outcomes. Say so and stop.
- The matter is litigation under court disclosure rules (for example English CPR or US discovery) rather than arbitration. The admissibility tests here are the IBA arbitration tests. Note the mismatch and stop.
- The user wants a full document review or extraction over a corpus of files. That is a different skill.
- The request is to draft the underlying documents or the pleadings themselves.

When declining, route the user plainly to what they actually need.

## Inputs

The skill runs conversationally through the intake interview below. It needs, at minimum, either a request list (requesting role) or a returned schedule (producing, reply, tribunal, or merge round). The optional inputs in the frontmatter change the substance of the run, not just its presentation:

- **role** decides the pipeline and which column the skill is allowed to write.
- **regime** changes the request unit and the posture. Prague 2018 discourages production and uses a single-document unit with a public-domain filter. ICC, LCIA, and ICSID borrow the IBA tests. See `reference/regimes.md`.
- **issues** lets the skill tie each request to a pleaded issue. Without it, relevance ties are marked unverified and the user is told that the relevance case is weaker as a result.
- **parties** marked as State or state-owned arm the content-based Article 9.2(f) sensitivity prompt: it is raised where a document's content implicates a governmental or sovereign function, not on every request because of who owns a party.

If an optional input is absent, proceed on the default and state the default in the output so the user knows the run was not calibrated to that input.

## Workflow

### Step 0. Privilege gate, then intake interview

This step runs first, every time, before any ingestion or drafting.

**0a. Privilege gate (hard stop).** Reproduce the capitalised warning at the top of this file. Then name the concrete checks the user should make now: the seat of the arbitration, the institutional rules, the parties' national laws, the applicable bar and ethics rules, and the CIArb 2025 Guideline (sections 2.2 on confidentiality, 6.7 on which rules govern, and 7 on disclosure). Do not read any schedule content, ingest any attachment, or draft anything until the user gives an explicit affirmative that they are fine to proceed. If the user does not confirm, stop.

**0b. Intake interview.** After confirmation, ask only for what you do not already have, one question at a time, in this order. Skip any item the user already supplied. See `reference/intake.md`.
1. Role: requesting, producing, or tribunal.
2. Regime: IBA 2020 (default), Prague 2018, ICC, LCIA, or ICSID.
3. Round: first draft, objections, reply, decision, merge, or simultaneous (joint) exchange.
4. Is any party a State or a state-owned entity. If yes, record which, to arm the content-based 9.2(f) sensitivity prompt.
5. Is there a pleaded-issues list to tie relevance to.
6. Where the requests or the returned schedule are.
7. Optional: are there production deadlines (Procedural Order No. 1 or a procedural order) to record and check.

### Step 1. Load the right references for the regime and role

Read `reference/schedule-format.md` for the column model, the ID rules, the status vocabulary, the deadlines block, and the merge and column-ownership rules. Read `reference/regimes.md` and apply the selected regime (IBA 2020, Prague 2018, ICC, LCIA, or ICSID). For the requesting role read `reference/iba-3-3-checklist.md`. For the producing role read `reference/iba-9-2-objections.md`. If an issues list was provided, read `reference/issue-matching.md`.

### Step 2. Run the role pipeline

Refer to columns by name throughout, never by number. The requesting party owns *No.*, *Document(s) or Category Requested*, *Relevance and Materiality*, and *Reply*. The producing party owns *Objections*. The tribunal owns *Tribunal's Decision*. Every column a role does not own is reproduced verbatim. See `reference/schedule-format.md`.

**Requesting.** Ingest the requests. Assign each a stable ID. Run the Article 3.3 pre-flight per `reference/iba-3-3-checklist.md` and record a pass or fail with a reason for each gate. Tie each request to a pleaded issue using `reference/issue-matching.md` where the issues list is present, otherwise mark the tie unverified. Write the *No.*, *Document(s) or Category Requested*, and *Relevance and Materiality* columns. Produce the schedule and the internal flags memo.

**Producing.** Reproduce the requesting party's columns verbatim. Map each request against the Article 9.2 grounds per `reference/iba-9-2-objections.md`. Where a request is met by confidentiality, privilege, or sensitivity, pair the objection with the Article 9.5 protective-measure option (redaction or a confidentiality ring) rather than a flat refusal, and where only the tribunal need see a document, invite the tribunal to order in-camera review rather than offering it as a party measure. If any party is marked State or state-owned, surface the 9.2(f) sensitivity prompt as a candidate only where the document's content implicates a governmental or sovereign function, not on every request, and not on a request already disposed of on relevance or burden. Write the *Objections* column. Also produce the producing party's internal flags memo naming its own weak or non-colourable objections.

**Reply (requesting, later round).** Reproduce the prior columns verbatim. Answer each objection in the *Reply* column, point by point. Narrow a request where that saves it, and say so. Write the *Reply* column.

**Tribunal.** Reproduce every party column verbatim, byte for byte, with no abridging or paraphrasing. Keep the *Tribunal's Decision* column empty. Do not propose a decision. If the user wants a private aid, offer a separate worksheet that lists, per request, the objection grounds in play and the protective-measure options, with no recommendation.

**Merge.** Match the returned schedule to the working file by request ID. Reproduce the other side's column verbatim. Report any ID that does not line up rather than dropping or reordering a row.

**Simultaneous (joint exchange).** Where both sides serve requests at once, run the requesting pipeline for each side's request set, prefix the IDs by party (C-R1, R-R1) so the two tracks never collide, and consolidate both into one schedule without renumbering either. See the ID rules in `reference/schedule-format.md`.

### Step 3. Produce the output

Produce the schedule as a Markdown table with the columns in `reference/schedule-format.md`. Then produce the internal flags memo: for the requesting and reply roles it names the user's own weak requests under Article 3.3, and for the producing role it names the user's own weak or non-colourable objections. Close with the calibration note (which regime, which role, whether the issues list was present, any timetable recorded) and the standing reminder that drafting quality and the merits of any objection are for counsel.

## Output

Two artefacts, both Markdown.

1. **The schedule**, a Markdown table with these columns: `No.`, `Document(s) or Category Requested`, `Relevance and Materiality`, `Objections`, `Reply`, `Tribunal's Decision`. Only the columns owned by the current role carry new text. Every other column is reproduced verbatim or left blank. The tribunal's column is blank until the tribunal rules.

2. **The internal flags memo** (requesting, reply, and producing roles), the user's own weak points named honestly. For the requesting and reply roles it lists requests that are weak under Article 3.3, each with the gate it fails and a one-line reason. For the producing role it lists the user's own weak or non-colourable objections (for example ground (f) on a plainly commercial document, a bare burden assertion, or a blanket privilege claim without 9.4 grounding). This memo is for the user's side only. It is never part of the schedule sent to the other side or the tribunal. Mark it clearly as internal and privileged work product.

Lead the output with a one-line statement of what was produced and for which role. Do not pad.

## Edge cases and refusals

- **No confirmation at the gate.** Stop. Produce nothing.
- **Regime is Prague.** The request unit is a single specific document, not a category. Apply the three Prague gates and show the production-discouraged note. See `reference/regimes.md`.
- **No issues list.** Proceed, but mark every relevance tie unverified and tell the user the relevance case is weaker without the pleaded issues.
- **A request is plainly the user already holding the document.** Flag it under Gate C. Do not silently fix it.
- **The other side's text contains an apparent error.** Reproduce it verbatim in their column. Note the apparent error in your own column or the memo. Do not edit their column.
- **Non-English schedule.** Confirm with the user whether to work in the document's language. The admissibility tests are language-neutral, but the drafting register is not validated for non-English output.
- **A party asserts blanket state secrecy.** Record it as a 9.2(f) objection and note that the tribunal decides whether the sensitivity is compelling and that a State must still search and justify each document. Do not treat it as a veto.
- **The documents are in a non-party's possession.** The ordinary producing-party objection menu does not fit, because the other party cannot produce what it does not hold. Flag the request for the Article 3.9 route (the requesting party asks the tribunal to take steps to obtain the documents from the non-party). See `reference/iba-3-3-checklist.md`, Gate C.
- **A timetable is supplied.** Record the production deadlines in the calibration note and flag any out-of-time step (a request after the request date, an objection past the objection date). Under Prague the marker is the case-management conference rather than a request deadline.
- **Simultaneous (joint) exchange.** Both sides serve requests at once. Run the requesting pipeline per side, prefix IDs by party (C-R1, R-R1), and consolidate without renumbering. Do not blend the two request sets into one numbering.

## What this skill does not do

- It does not decide whether a document is material or whether an objection will succeed. Those are the tribunal's calls and counsel's judgment.
- It does not give enforceability or privilege opinions. It records the asserted basis and frames the ground.
- It does not generate a Word `.docx` or an Excel `.xlsx` file. On the LQ.AI platform the output is the Markdown table shown in chat. File generation needs an agent runtime or a later platform release.
- It does not invent facts, issues, or citations that are not in the user's inputs or the reference files.
- It does not substitute for review by qualified arbitration counsel.

## Reference materials

- `reference/iba-3-3-checklist.md`: the Article 3.3 pre-flight, gate by gate, with pass and fail signals.
- `reference/iba-9-2-objections.md`: the Article 9.2 grounds, the content-based state-party (f) sensitivity prompt, and the 9.5 protective measures.
- `reference/regimes.md`: IBA 2020 default and the Prague, ICC, and LCIA variants.
- `reference/schedule-format.md`: the column model, ID rules, status vocabulary, and the merge and column-ownership rules.
- `reference/intake.md`: the privilege-gate banner and the ordered intake questions.
- `reference/issue-matching.md`: the separable relevance matcher (also reused by a later cross-examination skill).
- `reference/CITATIONS.md`: the provenance ledger. Every legal citation in this skill checked against its official source, with URLs, verdicts, and the verification date.
- `examples/example_requesting.md`, `examples/example_producing.md`, `examples/example_tribunal.md`: worked examples on one shared fact pattern.
