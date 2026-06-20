# Example: tribunal pass

The tribunal receives the schedule with every party column complete and keeps the Tribunal's Decision column clean. The skill does not propose a decision. It offers a private worksheet that lists the grounds in play with no recommendation. Fact pattern and known-good answer in `gold-fact-pattern.md`.

## Input

- Role: tribunal.
- Regime: IBA 2020.
- Round: decision pass.
- Prior schedule: every party column complete (the requests, the relevance and materiality, the objections, and the requesting party's reply).

The privilege gate fired first and the user confirmed.

## Output

**Tribunal decision pass. Regime: IBA 2020. The Tribunal's Decision column is blank for the Tribunal's ruling.**

Every party column is reproduced verbatim, byte for byte, from the producing and reply rounds. Nothing is abridged or paraphrased. Only the Tribunal's Decision column is left blank.

| No. | Document(s) or Category Requested | Relevance and Materiality | Objections | Reply | Tribunal's Decision |
|---|---|---|---|---|---|
| R1 | All board minutes of Marateca National Grid recording or discussing the decision to terminate the Power Purchase Agreement, 1 January 2022 to 30 June 2022. Not in the Claimant's possession, authored and held by MNG. | Relevant to Statement of Claim paragraphs 41 to 46. Material to whether the termination was politically directed or made on commercial grounds, which the Tribunal must decide. Tied to Issue 1. | Ground (b) privilege: the minutes in part record legal advice from counsel. The Respondent offers production with the privileged passages redacted and a basis stated, under Article 9.5, against a privilege log. The 9.2(f) sensitivity candidate is not pressed: ordinary commercial board minutes do not implicate a governmental function, so asserting it would be non-colourable. | The Claimant accepts redaction of genuinely privileged passages against a privilege log, and presses for the remainder. |  |
| R2 | Correspondence between the Ministry of Energy and Marateca National Grid concerning the 2021 feed-in tariff revision, 1 March 2021 to 31 December 2021. Not in the Claimant's possession, held by the Ministry and MNG. | Relevant to Statement of Claim paragraphs 60 to 64. Material to whether the 2021 tariff revision was a disguised expropriatory measure. Tied to Issue 2. | Ground (f) special political or institutional sensitivity: correspondence between the Ministry, a State organ, and MNG, a state-owned utility, bearing on a governmental tariff decision. Ground (e) commercial confidentiality of third-party pricing within the correspondence. The Respondent offers, under Article 9.5, to produce the correspondence to opposing counsel with third-party prices redacted, and separately invites the Tribunal to order in-camera review only of the discrete passages bearing on the governmental tariff decision that are too sensitive for opposing counsel to see. | The Claimant accepts redaction of third-party prices and in-camera review, and presses for the substance of the tariff correspondence. |  |
| R3 | All documents, communications, and correspondence concerning the Project. | Relevant to the Claimant's case on the Respondent's conduct. | Ground (a) lack of relevance and materiality: the request names a topic, not documents material to a pleaded issue. Ground (c) unreasonable burden: an undefined, undated sweep of the entire Project record. Article 3.3(a) deficiency: not a narrow and specific category. | The Claimant does not press R3 as drafted and reserves the right to file a narrowed request. |  |
| R4 | The internal briefing note prepared for the Minister of Energy recommending the 2021 tariff revision. Reasonably believed to exist, held by the Ministry. | Relevant to Statement of Claim paragraphs 60 to 64. Material to whether the tariff revision was an expropriatory measure rather than a routine regulatory adjustment. Tied to Issue 2. | Ground (f) special political or institutional sensitivity: a briefing note prepared for a Minister is governmental deliberative content. Ground (b) deliberative or governmental-process privilege, asserted only so far as a specific domestic official-information rule is identified, recognition being jurisdiction-dependent. The Respondent offers restricted-access production of the note to opposing counsel under Article 9.5 with the deliberative recommendation redacted, and separately invites the Tribunal to order in-camera review only of that redacted recommendation, which is too sensitive for opposing counsel to see. The Respondent acknowledges it must identify and justify the document and cannot rely on a blanket classification. | The Claimant presses for in-camera review and notes the Respondent must justify the document and cannot rely on a blanket classification. |  |
| R5 | Emails of the four named Marateca National Grid board members and the MNG Chief Executive referring to the termination of the Power Purchase Agreement or to Helios, 1 October 2021 to 30 June 2022, located using the search terms "Helios", "PPA", "termination", and "milestone". Not in the Claimant's possession, held by MNG. | Relevant to Statement of Claim paragraphs 41 to 46. Material to whether the termination was politically directed or made on commercial grounds. Tied to Issue 1. | Ground (b) privilege where any of the emails route legal advice, with an Article 9.5 redaction offer against a privilege log. The 9.2(f) candidate is not pressed: these are ordinary commercial emails, so their content does not implicate a governmental function even though MNG is state-owned. | The Claimant accepts redaction of any genuinely privileged emails against a privilege log, and presses for the remainder. |  |

### Optional private worksheet for the Tribunal (not part of the schedule)

- **R1.** In play: relevance and materiality (not contested), privilege (b) on part, protective measure (9.5 redaction against a privilege log). The (f) candidate was not pressed because the content is commercial. Decision points: scope of privilege, whether a privilege log is ordered.
- **R2.** In play: sensitivity (f) on governmental content, confidentiality (e), protective measure (9.5 redaction), and an invitation to order in-camera review. Decision points: whether the sensitivity is compelling, and whether redaction plus in-camera review resolves it.
- **R3.** In play: relevance (a), burden (c), 3.3(a) sufficiency. Decision point: deny as drafted, or invite a narrowed request.
- **R4.** In play: special political or institutional sensitivity (f) on governmental deliberative content, deliberative privilege (b) only so far as a domestic rule is named, protective measure (9.5 restricted access), and an invitation to order in-camera review. Decision points: whether the document is justified item by item, and whether in-camera review is ordered.
- **R5.** In play: relevance and materiality (not contested), privilege (b) on any legal-advice emails, protective measure (9.5 redaction). The (f) candidate was not pressed because the content is commercial. Decision points: scope of privilege, whether a privilege log is ordered.

No recommendation is given. Each decision is the Tribunal's.

**Calibration note.** Run for the tribunal role under IBA 2020. Every party column reproduced verbatim. The Tribunal's Decision column left blank. The worksheet lists grounds in play without proposing an outcome.

## What this example demonstrates

- The Tribunal's Decision column kept clean, with no party text and no proposed decision.
- Every party column reproduced verbatim, byte for byte, from the prior rounds, with no abridging or paraphrasing. This is the integrity guarantee of the artefact: a reader can diff the tribunal schedule against the input and find columns one to five identical.
- A private worksheet that frames the live grounds per request and the decision points, with no recommendation, honouring the judgment boundary.
