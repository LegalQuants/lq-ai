# Example: producing party, objections round

The producing party reproduces the requesting columns verbatim and fills the Objections column. Because a party is the State and another is state-owned, the Article 9.2(f) sensitivity prompt is surfaced as a content-based candidate, pressed only where a document's content implicates a governmental function. Fact pattern and known-good answer in `gold-fact-pattern.md`.

## Input

- Role: producing (the Republic of Marateca and Marateca National Grid).
- Regime: IBA 2020.
- Round: objections.
- State party: yes, both Respondents are State or state-owned. The content-based 9.2(f) prompt is armed.
- Prior schedule: the requesting party's draft with the requesting columns filled (R1 to R5).

The privilege gate fired first and the user confirmed.

## Output

**Producing party objections, round 1. Regime: IBA 2020. State-party sensitivity flag armed.**

The requesting party's columns are reproduced verbatim, exactly as drafted in `example_requesting.md`. Only the Objections column is new.

| No. | Document(s) or Category Requested | Relevance and Materiality | Objections | Reply | Tribunal's Decision |
|---|---|---|---|---|---|
| R1 | All board minutes of Marateca National Grid recording or discussing the decision to terminate the Power Purchase Agreement, 1 January 2022 to 30 June 2022. Not in the Claimant's possession, authored and held by MNG. | Relevant to Statement of Claim paragraphs 41 to 46. Material to whether the termination was politically directed or made on commercial grounds, which the Tribunal must decide. Tied to Issue 1. | Ground (b) privilege: the minutes in part record legal advice from counsel. The Respondent offers production with the privileged passages redacted and a basis stated, under Article 9.5, against a privilege log. The 9.2(f) sensitivity candidate is not pressed: ordinary commercial board minutes do not implicate a governmental function, so asserting it would be non-colourable. |  |  |
| R2 | Correspondence between the Ministry of Energy and Marateca National Grid concerning the 2021 feed-in tariff revision, 1 March 2021 to 31 December 2021. Not in the Claimant's possession, held by the Ministry and MNG. | Relevant to Statement of Claim paragraphs 60 to 64. Material to whether the 2021 tariff revision was a disguised expropriatory measure. Tied to Issue 2. | Ground (f) special political or institutional sensitivity: correspondence between the Ministry, a State organ, and MNG, a state-owned utility, bearing on a governmental tariff decision. Ground (e) commercial confidentiality of third-party pricing within the correspondence. The Respondent offers, under Article 9.5, to produce the correspondence to opposing counsel with third-party prices redacted, and separately invites the Tribunal to order in-camera review only of the discrete passages bearing on the governmental tariff decision that are too sensitive for opposing counsel to see. |  |  |
| R3 | All documents, communications, and correspondence concerning the Project. | Relevant to the Claimant's case on the Respondent's conduct. | Ground (a) lack of relevance and materiality: the request names a topic, not documents material to a pleaded issue. Ground (c) unreasonable burden: an undefined, undated sweep of the entire Project record. Article 3.3(a) deficiency: not a narrow and specific category. |  |  |
| R4 | The internal briefing note prepared for the Minister of Energy recommending the 2021 tariff revision. Reasonably believed to exist, held by the Ministry. | Relevant to Statement of Claim paragraphs 60 to 64. Material to whether the tariff revision was an expropriatory measure rather than a routine regulatory adjustment. Tied to Issue 2. | Ground (f) special political or institutional sensitivity: a briefing note prepared for a Minister is governmental deliberative content. Ground (b) deliberative or governmental-process privilege, asserted only so far as a specific domestic official-information rule is identified, recognition being jurisdiction-dependent. The Respondent offers restricted-access production of the note to opposing counsel under Article 9.5 with the deliberative recommendation redacted, and separately invites the Tribunal to order in-camera review only of that redacted recommendation, which is too sensitive for opposing counsel to see. The Respondent acknowledges it must identify and justify the document and cannot rely on a blanket classification. |  |  |
| R5 | Emails of the four named Marateca National Grid board members and the MNG Chief Executive referring to the termination of the Power Purchase Agreement or to Helios, 1 October 2021 to 30 June 2022, located using the search terms "Helios", "PPA", "termination", and "milestone". Not in the Claimant's possession, held by MNG. | Relevant to Statement of Claim paragraphs 41 to 46. Material to whether the termination was politically directed or made on commercial grounds. Tied to Issue 1. | Ground (b) privilege where any of the emails route legal advice, with an Article 9.5 redaction offer against a privilege log. The 9.2(f) candidate is not pressed: these are ordinary commercial emails, so their content does not implicate a governmental function even though MNG is state-owned. |  |  |

**State-party note.** The 9.2(f) sensitivity prompt is a candidate on every request because a Respondent is the State or state-owned, but it is pressed only where the document's content implicates a governmental function. So it is asserted on R2 and R4 (Ministry and Minister material) and not pressed on R1 and R5 (the ordinary commercial documents of the state-owned utility). It is not raised on R3, which is disposed of on relevance and burden. The Tribunal decides whether any sensitivity is compelling. A State cannot self-certify a blanket exemption and must still search and justify each document.

### Internal flags memo (privileged work product, do not send)

- **R1.** Do not assert ground (f) on the utility's ordinary commercial board minutes. The content does not implicate a governmental function, so the objection would be non-colourable. Press the (b) privilege point on the genuinely privileged passages instead.
- The objections on R2, R3, R4, and R5 are colourable as drafted. No further weakness flagged.

**Calibration note.** Run for the producing role under IBA 2020 with the state-party flag armed. The requesting party's columns are reproduced verbatim. Only the Objections column was written. Whether any objection succeeds is for the Tribunal, not validated here.

## What this example demonstrates

- The producing role writing only the Objections column and reproducing every other column verbatim.
- The content-based 9.2(f) prompt: pressed on the Ministry and Minister material (R2, R4) and correctly not pressed on the state-owned utility's ordinary commercial documents (R1, R5).
- Grounds (b), (e), and (f) paired with an Article 9.5 producing-party measure (redaction, restricted access), with in-camera review framed as something the Tribunal is invited to order, not a party measure.
- Deliberative privilege under (b) flagged as jurisdiction-dependent, with the sensitivity routed primarily through (f).
- R3 met on relevance, burden, and a 3.3(a) deficiency.
- The producing party's own internal flags memo naming its one non-colourable objection (f on R1).
- The honest limit stated: the State must justify each document and the Tribunal decides compelling sensitivity.
