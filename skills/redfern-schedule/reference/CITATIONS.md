# Citation provenance ledger

Every legal citation in this skill, checked against the official source. The method is deterministic: download the official artifact, extract its text, and match each cited number and phrase against the literal text. This is not a model judgment. The same source gives the same result every time.

**Verification date:** 2026-06-20 (build pass), re-verified 2026-06-20 (adversarial-review pass), re-verified 2026-06-20 (citation-review pass).
**Method labels:** "byte-verified" means the official PDF was downloaded and its extracted text literally matched. "source-confirmed" means the official web page text was read where a clean PDF was not extractable (slightly lower assurance, re-confirm against the PDF before a load-bearing filing).

## Adversarial review pass (2026-06-20): further corrections

An independent adversarial review re-verified every citation against the live official sources (not this ledger) and corrected the following in the reference files.

1. **LCIA 22.1(v) wording in `regimes.md`.** The regimes file had paraphrased the power as documents the tribunal "decides are relevant." The official LCIA 2020 text is "which the Arbitral Tribunal decides **to be** relevant." Corrected in `regimes.md` to match (this ledger was already correct). The article number 22.1(v) is correct: (iv) is the inspection power, (vi) is the rules-of-evidence power.
2. **Prague sua-sponte power re-cited.** `regimes.md` had placed "the tribunal may also request documents on its own initiative" next to Article 4.6. The claim is correct but the power lives in **Article 3.2(a)** (the tribunal's proactive role: it may, after hearing the parties, at any stage and on its own initiative, request a party to submit documentary evidence), not Article 4. Re-cited to Art 3.2(a). Verified by hand against the official Prague PDF: Art 4.5 (three conditions) and Art 4.6 (tribunal may order production after hearing the party's view) are cited correctly, and Art 4.7 is the originals/photocopies provision.
3. **IBA 3.3(a)(ii) in `iba-3-3-checklist.md` (Gate A3).** The checklist had treated missing electronic search terms or custodians as a Gate A identification failure. Under 3.3(a)(ii) those are a means to make the search efficient, not a mandatory identification element. Reworded: absence of search terms is not a Gate A failure but an efficiency weakness that invites a 9.2(g) proportionality objection.
4. **9.2(f) auto-flag re-scoped (substance, not a miscite).** The state-party flag now surfaces (f) as a content-based candidate, recommended only where a document's content implicates a governmental or sovereign function, not on every request because a party is state-owned. Reflected in `iba-9-2-objections.md` and the examples.

## Citation-review pass (2026-06-20): ICSID Rule 37 wording corrected

A second, citation-focused adversarial review re-verified every citation against live official sources. Every rule number held, including the ICSID Rule 36/37 numbering (with a Rule 34 control check confirming Rule 34 is Deliberations, not evidence). One defect was found and is now fixed: **ICSID Rule 37** carried a spurious "the" in its title and paraphrased the operative verb. Verified against the binding ICSID Chapter V: Evidence rules index (https://icsid.worldbank.org/rules-regulations/convention/arbitration-rules/chapter-v-evidence) and the official PDF, the heading is "Disputes Arising from Requests for Production of Documents" and the verb is "the Tribunal shall consider all relevant circumstances". Corrected here and in `regimes.md`. The four factors (a) to (d) were already verbatim-correct.

## Errors the build pass caught and fixed

1. **IBA Article 3.5.** The checklist had claimed "in the 2020 revision any party may object." The literal text says the party to whom the Request to Produce is addressed (the producing party) objects, on the grounds in Articles 9.2 or 9.3 or a failure to meet Article 3.3. Fixed in `iba-3-3-checklist.md`.
2. **ICC 2026 renumbering.** `regimes.md` had cited "Article 28" for Establishing the Facts in the 2026 Rules. The official 2026 Rules list it as **Article 26** (Article 25 is New Claims, Article 28 is Closing of the Proceedings). Fixed in `regimes.md`.

## IBA Rules on the Taking of Evidence (2020): byte-verified

Source PDF: https://www.ibanet.org/MediaHandler?id=def0807b-9fec-43ef-b624-f2cb2af7cf7b

- **Currency.** The 2020 revision is the latest, adopted 17 December 2020, superseding 1999 and 2010. No later revision exists (confirmed on ibanet.org).
- **Art 3.2** a Request to Produce is submitted within the time the tribunal orders. PASS.
- **Art 3.3(a)** (i) a single document sufficient to identify it, or (ii) a narrow and specific category reasonably believed to exist. The electronic-documents search-terms provision sits inside 3.3(a)(ii). PASS.
- **Art 3.3(b)** "relevant to the case and material to its outcome" (conjunctive). PASS.
- **Art 3.3(c)** (i) not in the requesting party's possession or why burdensome, (ii) why the documents are assumed to be in another party's possession. PASS.
- **Art 3.5** the addressed party objects in writing, on the grounds in Articles 9.2 or 9.3 or a failure to meet Article 3.3. PASS (after fix).
- **Art 3.6** the tribunal may invite the relevant parties to consult to resolve the objection. PASS.
- **Art 3.7** the tribunal orders production only if the documents are relevant and material, none of the reasons in Articles 9.2 or 9.3 applies, and the Article 3.3 requirements are met. PASS.
- **Art 9.1** the tribunal determines admissibility, relevance, materiality, and weight. PASS.
- **Art 9.2(a) to (g)** the seven exclusion grounds. PASS.
- **Art 9.3** exclude evidence obtained illegally (added in 2020). PASS.
- **Art 9.4** the privilege-determination factors. Article 9.2(b) itself cross-references "see Article 9.4 below." PASS.
- **Art 9.5** confidentiality and protective arrangements. PASS.
- **Art 9.6 and 9.7** adverse inferences for non-production (documents, and other evidence). PASS.

## Prague Rules (2018), Article 4: byte-verified

Source PDF: https://praguerules.com/upload/medialibrary/9dc/9dc31ba7799e26473d92961d926948c9.pdf

- **Art 4.2** the tribunal and parties are encouraged to avoid any form of document production, including e-discovery. PASS.
- **Art 4.3** a party that needs documents should raise it at the case management conference. PASS.
- **Art 4.4** a later request is granted only in exceptional circumstances. PASS.
- **Art 4.5** a party may request a specific document that (a) is relevant and material to the outcome, (b) is not in the public domain, and (c) is in the other party's possession, power, or control. PASS.
- **Art 4.6** the tribunal, after hearing views, may order production. PASS.

## CIArb Guideline on the Use of AI in Arbitration (2025): byte-verified

Source PDF: https://www.ciarb.org/media/bpndtcgu/guideline-on-the-use-of-ai-in-arbitration_updated-sept-2025.pdf

- **§2.2 Confidentiality.** Third-party AI entails substantial confidentiality risk. PASS.
- **§3.4** using AI does not diminish a participant's responsibility and accountability, absent express written agreement. PASS.
- **§6.7** in ruling on AI use the arbitrators must consider and be guided by (i) the law of the seat, (ii) the law and rules governing the proceedings, and related rules. PASS.
- **§7 Disclosure.** Disclosure of AI use may be required, and the duty is continuous (7.4). PASS.
- **§8.2** arbitrators should not relinquish their decision-making powers to AI and must ensure independent judgement. PASS.
- **§8.4** an arbitrator shall assume responsibility for all aspects of an award regardless of AI assistance. PASS.

## ICC: 2021 byte-verified, 2026 source-confirmed

- **2021 Rules, Article 25 (Establishing the Facts of the Case)** "by all appropriate means." Byte-verified from the official 2021 PDF (https://iccwbo.org/wp-content/uploads/sites/3/2020/12/icc-2021-arbitration-rules-2014-mediation-rules-english-version.pdf). PASS.
- **2026 Rules, Article 26 (Establishing the Facts of the Case).** Source-confirmed from the official 2026 Rules page (https://iccwbo.org/dispute-resolution/dispute-resolution-services/arbitration/rules-procedure/2026-arbitration-rules/). Re-confirm against the 2026 PDF before relying on it as load-bearing. In the 2026 Rules, Article 25 is New Claims and Article 28 is Closing of the Proceedings.
- **Appendix IV (Case Management Techniques), item (d)** on controlling document production, including (d)(v) "using a schedule of document production to facilitate the resolution of issues" (the Redfern Schedule). Byte-verified from the official 2021 PDF. PASS.

## LCIA Arbitration Rules (2020): source-confirmed

Source page: https://www.lcia.org/Dispute_Resolution_Services/lcia-arbitration-rules-2020.aspx

- **Article 22 (Additional Powers), Article 22.1(v)** the tribunal may order a party to produce documents in its possession, custody, or power that the tribunal decides to be relevant. Confirmed as (v), not (iv) (which is the inspection power) and not (vi) (rules of evidence). PASS.

## ICSID Arbitration Rules (2022): source-confirmed

Source page: https://icsid.worldbank.org/procedures/arbitration/convention/production-of-documents/2022 (official ICSID). Re-confirm against the official ICSID Convention Arbitration Rules 2022 PDF (https://icsid.worldbank.org/sites/default/files/Arbitration_Rules.pdf) before a load-bearing filing.

- **Rule 36 (Evidence: General Principles).** The tribunal determines the admissibility and probative value of evidence, and each party bears the burden of proving the facts it relies on. Under **Rule 36(3)** the tribunal may, at any stage, call upon a party to produce documents or other evidence it deems necessary. PASS (source-confirmed).
- **Rule 37 (Disputes Arising from Requests for Production of Documents).** Where the parties disagree about producing a document or category, the tribunal shall consider all relevant circumstances, including the scope and timeliness of the request, the relevance and materiality of the documents requested, the burden of production, and the basis of the objection. PASS. This is the ICSID production-dispute rule, and its factors mirror the IBA 3.3 and 9.2 tests, which is why ICSID tribunals organise the dispute on a Redfern Schedule and borrow the IBA standard. Title and operative verb corrected on 2026-06-20 against the binding text: the heading is "Requests for Production of Documents" (no "the") and the verb is "shall consider", not the earlier paraphrase "decides, taking into account".

## How to re-run this check

Deterministic, no model in the verification step:
1. Download the official artifact by its stable URL with `curl`.
2. Extract text with `pdftotext -layout` (poppler).
3. Match each cited number and phrase against the extracted text with a regex assertion that prints PASS or FAIL and the literal snippet.

The downloadable PDFs (IBA, Prague, CIArb, ICC 2021) can be fully byte-verified this way. The ICC 2026 page and the LCIA page render as web pages, so they are read as official web text rather than PDF, and carry the "source-confirmed" label until a PDF is extracted.
