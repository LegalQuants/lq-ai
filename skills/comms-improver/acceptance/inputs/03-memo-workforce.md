# Input 03 - workforce analytics evaluation memo (own practice, de-identified; test-plan Scenario 2 + Scenario 6 audience-comparison pair)

> Source: own-practice legal analysis memo, de-identified at source by the reviewing
> attorney before it reached this workspace - no party names, client identifiers, matter
> numbers, or product names present. One voice-transcription artifact corrected
> ("Meta" -> "metadata"). Matter-blind. Verified: Rampart on-device scan + attorney read
> before staging.
> Test notes: legal memo / analysis sample. This is the Scenario 6 pair - run at two
> audiences and compare. A faithful rewrite must preserve the conditional approval and every
> guardrail (see the expected/ file): the automated-decision limit, the exclusions, the
> US-only scope, need-to-know access, and the privacy-notice-refresh trigger.

---

# Evaluation of Workforce Analytics Program

## Issue
Can we use a workforce analytics program using Calendar, HR, and other software data sources across employees around the world to assess workforce engagement, integration, and general happiness of the employee base?

## Rules
* **Automated Decision-Making Technology Rules:** Engagement signals may inform us to look closely, but they cannot independently themselves alone be a basis for a significant decision like termination, demotion, or denial of benefits. Using them as opportunities to further investigate, coach, or intervene as the manager are appropriate.
* **Disclosure & Privacy Notices:** While these uses may be covered under existing terms, the more we collect—and depending on how insights are used—the stronger the need for disclosure becomes.
* **Data Retention & Legal Holds:** Granular employee-level data is deleted when they are terminated, though aggregate data can be retained so long as it remains high-level per team or acquired company. Additionally, we may need to protect legal requirements in the case of anticipated employment claims, recordkeeping requirements, or other legal obligations that could attach.
* **Jurisdictional Constraints:** Workforce analytics elsewhere (outside the US) implicate potential council/employee representative consultation and are generally more privacy-heavy.

## Analysis
* **Scope Discipline & Data Collection:** Scope discipline is the primary control. Extracting every possible field from these tools for every employee to create aggregated write-ups tends toward over-inclusivity and over-collection. Instead, we should preserve a short list of high-level indicators for things like average meetings per week, all-hands attendance, manager attrition, and one-on-one cadence with managers, drawn from metadata already collected through ordinary workforce management.
* **Excluded Content:** Granular content measurement—such as message-to-message response time, camera-on rates, emoji reaction delivery time, number of emoji reactions, as well as participation in potentially protected group activity—should be excluded.
* **Privacy Notice Evaluation:** We need to look into refreshing our employee privacy notice. Likely these are already covered in our existing notice, and these are simply additional ways of using what is already collected. 
* **Access Control:** Access to the data should be need-to-know only, particularly at the individual level (for example: direct management, senior management, HR team, and potentially in an aggregate fashion for the analytics team).
* **Geographic Refinement:** After further discussion, the team decided to scope this correctly to the US workforce only. Analytics elsewhere require separate review. Ironically, this also means that data will be US-only rather than pulled from across our workforce, potentially biasing the conclusions. 

## Conclusion
The workforce analytics program is approved to proceed, provided it is strictly scoped to the US workforce for now (global expansion requires a separate review). The program must adhere to strict scope discipline (relying on high-level indicators and explicitly excluding granular/protected data), limit data access to a need-to-know basis, utilize findings strictly for managerial coaching rather than standalone automated decisions, and trigger a refresh of the employee privacy notice if deeper insights increase disclosure necessity.
