# Product captures for the documentation site

This is a site asset workflow, not a second set of product instructions.
Repository guides own the explanation and procedures; the site transform adds
screenshots to those guides and their selected introduction sections.

## Refresh the captures

1. Use a running test deployment and its existing demo account. Record the
   release and source revision actually running, rather than the docsite branch.
2. Create an obviously fictional matter and use
   `docs/quickstart/sample-nda.md`. Keep client documents, personal information,
   credentials, provider-key settings, and unrelated chats out of the frame.
3. Capture the attached document's `ready` status, the Contract QA skill chooser,
   and, when inference succeeds, a completed response to a focused question about
   the sample. Use the app's ordinary document and chat controls. Confirm the
   displayed route before submitting. The October recovery captures use the
   configured local demo and include a completed ordinary-chat answer, its
   declared inference route, document readiness, and the skill chooser.
4. Review the visible answer against the actual sample and keep the UI's output
   and limitations intact. A screenshot of a pending or failed run must not be
   presented as a successful answer. Do not edit text into the screenshot.
5. Save the original browser JPEGs or PNGs under `site/public/product/`. Update each
   image's dimensions, description, caption, and provenance in
   `site/product-captures/screenshots.json`. Retain a credential-free capture
   receipt alongside this README.
6. Build and inspect the landing page, overview, and quickstart on desktop and
   mobile, including full-size links and keyboard-operated disclosures. Check
   that the `.md` twins contain all descriptions and image links.

Refresh when the relevant UI, document flow, skill selection, or answer display
changes. A product release moving forward does not silently make an old capture
current: retain its capture version until it is replaced.

Existing verified release or UAT captures may be reused without altering their
pixels. Record their original file, revision, evidence record, and actual input
separately from a fresh capture. Label experimental or disabled features and
different examples explicitly. The current gallery includes the v0.8.0 matter
intake image and the September 27 experimental Contract QA result; neither is
presented as the outcome of the October ordinary-chat attempt. The current
gallery uses the fresh recovery captures; the earlier release/UAT assets and
their provenance remain available for historical reference.

## October 6 recovery

Docker was available again, but the existing API container remained stopped.
Starting that container restored the demo without changing its v0.8.0 images.
The fictional NDA was uploaded and reached `ready`. The Contract QA chooser was
captured; running that skill failed with `skill_input_missing` even though its
UI said there were no required inputs. The successful answer therefore comes
from a fresh ordinary document chat, with no attached skill. Its follow-up
quotes "from the date of disclosure", which matches Section 4 of the sample.

`2026-10-06-live.json` records the fresh image hashes, input and running revision.
The earlier `2026-10-06.json` records the pre-recovery attempt and remains a
historical receipt. Captions distinguish extraction, an ordinary model answer,
a declared route, a skill chooser, and a library view. No completed skill run,
tabular review, or deployment-wide air gap is inferred from these images.

The pre-recovery chooser's original pixels are retained at
`archive/choose-skill-before-recovery.jpg`; its historical receipt records that
archived path and the original image hash. Refreshing the public chooser therefore
does not discard the evidence of the earlier attempt.

## Where each piece lives

| Piece | Owner |
|---|---|
| Explanations, commands, cautions, and verification instructions | Canonical repository documents |
| Browser JPEGs | `site/public/product/` |
| Image descriptions, captions, source/revision metadata, and exact placements | `site/product-captures/screenshots.json` |
| Matching, HTML figures/disclosures, and Markdown descriptions | `site/scripts/lib/product-screenshots.mjs` |
| Responsive presentation and focus styles | `site/src/styles/theme.css` |

The build validates committed captures; it never logs into a product deployment,
uploads a document, or invokes a model. Generated content stays gitignored.
