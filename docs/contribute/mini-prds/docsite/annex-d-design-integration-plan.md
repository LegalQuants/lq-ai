# Annex D — Documentation design integration plan

**Status:** Draft for maintainer review. The source/export foundation, diagrams, site-owned product captures, persistent navigation, Pagefind composer, adjacent/modal guide reader, and optional playback are implemented. The A/B/C demos were published at the maintainer's request. The broader task-guide and complete skill-based fictional walkthrough work below remain planned; pushing, merging, and publication remain maintainer actions.
**Date:** 2026-10-06
**Updated:** 2026-10-07
**Decision, 2026-10-18:** The committee adopted Version C, which is now the default build. On 2026-10-22 its visual design moved to the proposed LQ.AI interface redesign — the app's own look — in place of Graphite & copper and Source Sans 3. Where this plan says "Graphite & copper palette" or "pathway accents", read the redesign's ink palette with the orange mark on Security & privacy; [`site/README.md`](../../../../site/README.md) ("The theme") is current. The same day, search was made one control: the composer is on every page, the header search and Starlight's modal are gone from Version C, and other pages hand their question to Explore — completing the "rather than keeping two search implementations" row below (site/README.md, "Version C has one search"). The structure below is otherwise unchanged.

Build on Iris's B design by combining its four pathways with LiquidUI's guided introduction, visible search, and optional adjacent guide reader. Add the community's visual onboarding and progressive disclosure to the same documentation system. The result should help a lawyer understand LQ.AI, judge its fit and data implications, and find a first task without already understanding the project's architecture.

The governing structure is **canonical repository docs → transformations in `site/` and Astro → public surfaces**. A rich interface must remain a view of the documentation. This follows [ADR 0028](../../../adr/0028-documentation-site-generator-and-hosting.md), the [authoring contract](../../../site/README.md), and [Annex B's reader journeys](annex-b-journeys.md).

This revision specifies page changes, source files, build contracts, and acceptance evidence. The implementation status above distinguishes completed local increments from remaining proposals; paths marked **new** describe the planned ownership and may now exist. Human and agent outputs are equal requirements for every change.

## Proposed experience

Use one visual system and two connected views:

- **Explore:** a brief answer to what LQ.AI is, Iris's three introductory questions, a simple architecture drawing, a concrete fictional example, prominent local documentation search, and a visible next step.
- **Guides:** Getting started, How to install, Security & privacy, and Contribute, plus All guides. Guides open at real page URLs; readers arriving from Explore may preview a guide beside their conversation on sufficiently wide screens.

The introduction answers **What is LQ.AI? → How does it answer my questions? → Is it secure?** Keep the questions and their source links recognizable from Iris's prototype. Add a clear invitation to inspect a worked example or choose an installation path. A new visitor can read all three answers immediately; optional playback supplies Iris's pacing, pause, resume, and replay controls.

Explore and Guides use the same typography, Graphite & copper palette, pathway accents, theme preference, and language. Keep navigation in one consistent place rather than displaying competing pathway tabs and a pathway sidebar together. Use visible labels for primary destinations; icon controls retain accessible names and keyboard tooltips.

The conversational composer is labelled **Search the docs**. Query submissions show matching passages, source links, and guide titles. The introduction is labelled as a guided introduction. Generated model answers are a separate future proposal because they change the data flow and operational requirements.

## How the ideas fit together

| Input | Incorporation | Adaptation |
| --- | --- | --- |
| Iris's original B design | Four pathways, readable font, restrained palette, light/dark themes, grouped navigation, All guides, history and reading-position behavior | Retain the established page routes and Astro rendering; use descriptive entry links where a question currently leads to another menu. |
| Iris's October 4 LiquidUI zip | Three-question introduction, architecture drawing, persistent search composer, source chips, adjacent reader, responsive reading overlay, preserved search state, code copying, playback controls | Generate content and guide data from repo sources; support normal page navigation and full-page reading alongside preview. |
| September 27 visual-onboarding feedback | Show the user's position, next steps, prerequisites, and expected outcome | Derive steps from the canonical guide. Publish time estimates only when supported by a documented measurement or explicit qualification. |
| September 28 interactive-UI suggestions | A small, clearly labelled example of using LQ.AI with fictional material | Version the example and screenshots against the product; distinguish demonstration behavior from available product capabilities. |
| Progressive-disclosure suggestions | Short answers first, optional explanation and technical detail, expandable pathway groups | Keep critical limitations, prerequisites, and security cautions visible before the decision they affect. |
| Praise for search | Make local search immediately discoverable and available while reading | Retain Pagefind as the search engine; adapt its presentation to Iris's composer rather than keeping two search implementations. |
| Request for a three-minute walkthrough | A brief walkthrough of the same fictional example, with captions and a transcript | First establish an accurate example; then record it. The written path remains usable when the video is unavailable. |
| Stripe and Josh Comeau references | Goal-based entry points, worked examples, and visual explanations | Adapt the communication approach to lawyers and the project's tone. A new framework or copied visual identity is unnecessary. |

## Page changes and source ownership

Stripe's progressive structure is applied as **choose the relevant approach → complete the required procedure → verify the result → expand optional capabilities**. The public presentation can emphasize an applicable path; the complete Markdown export preserves all paths with their conditions and labels. This structure applies to task guides as well as the introduction.

| Public page | Proposed visible change | Canonical document changes | Transformation and UI changes | Agent output |
| --- | --- | --- | --- | --- |
| `/` Explore and `/overview/` | Replace the current landing's brief paragraph and large menu cards with Iris's three-question introduction, a source-linked drawing, a fictional example, and compact pathway links. Keep search immediately visible. | **New** `docs/start/what-is-lq-ai.md` owns the product explanation and fit summary. Move the current component's prose here. Reuse named sections in architecture and data-handling docs for the other two answers. `docs/site/index.mdx` becomes navigation/curation over these sources. | Change `Landing.astro` and `[...lqnav].astro`; add `Explore.astro`, `GuidedIntro.astro`, and a source-chip component under `site/src/components/pathways/`. Select sections through `explore.yaml`, not answer strings in components. | `/overview.md` gives the full explanation. `/index.md` gives the introduction and goal links, including the same source qualifications. Both appear in the index. |
| `/pathways/about/` and `/start/` | Rename the displayed pathway to Getting started while retaining its URL. Put Understand the product, Decide if it fits, See an example, and Choose an installation first. Expand the first group; keep skills and releases available further down. | Revise the navigation in `docs/site/start/index.md` and `docs/site/start/choose-your-path.md`. Add the new overview and example links. Replace references that assume the visible site has eight namespace entry points with the current four pathways and goal index. | Move pathway metadata from `site/src/pathways.mjs` into one YAML source; retain its expansion and validation functions. Update `PathwayGroups.astro` and `AllDocs.astro` to use it. | A flat list of goals and direct document links. The agent need not walk nested pathway menus to discover a task. |
| `/start/is-it-for-you/` | Present a short fit checklist and visible disqualifiers. Make its existing deeper explanations expandable, preserving direct heading links. | Edit `docs/start/is-it-for-you.md`: retain its short leads and evidence; label details by their subject. Keep limitations such as required operations support and unavailable use cases outside optional detail. | A build transform recognizes explicit optional-detail regions. Scope the presentation to selected documents before applying it across the corpus. | Complete explanations and disqualifiers with their headings; no dependence on expansion state. |
| `/pathways/install/`, `/operate/`, and `/start/choose-your-path/` | Use a choice-led installation hub. Choose deployment method first; choose model/data arrangement separately. Show applicability and caveats beside each choice, then link to the existing guide. | Reorganize navigation in `docs/site/operate/index.md` and `docs/site/start/choose-your-path.md`. Keep authoritative requirements in `docs/INSTALL-MAC.md`, `docs/quickstart.md`, `docs/operate/install-helm.md`, and `docs/operate/air-gapped.md`. | Add a `JourneyChooser.astro` component driven by journey metadata and canonical applicability sections. Do not present reverse proxy or local inference as equivalent alternatives to macOS/Compose/Helm. They are separate configuration dimensions. | Explicit deployment options and conditions, including Helm's coverage limits. A selected option is a direct page URL, never browser-only state. |
| `/start/quickstart/` | Display the six existing steps as a visible progress outline. Required actions and success checks remain expanded. Offer explanatory details and optional follow-on tasks separately. At model setup, select cloud or local while keeping the data-handling qualification visible. | Edit `docs/quickstart.md`: add Before you start and Check that it worked sections; put expected results beside each numbered step; label cloud/local applicability explicitly; separate optional organization profile, skills, and advanced walkthrough material. Preserve commands and existing heading anchors where possible. | Add `JourneySteps.astro` and a small progress script; generate steps from numbered Markdown sections. Extend the disclosure transform for explicitly marked optional details. Selecting a model arrangement changes emphasis, not the authoritative stored text. | All six steps, their checks, both model arrangements, and their conditions. Upload reaching `ready` is distinguished from successful retrieval or AI output. |
| `/operate/install-macos/`, `/operate/install-docker-compose/`, and `/operate/install-helm/` | Reuse the task-guide pattern: applicability, prerequisites, ordered actions, verification, then maintenance or advanced configuration. Show each deployment's limitations early. | Make structural edits in `docs/INSTALL-MAC.md`, README's Quick Start section, and `docs/operate/install-helm.md`. Add meaningful verification headings where needed. The Compose route continues sourcing README's existing section; no copied installation wrapper is created. | Extend journey selectors for these existing routes. Reuse the same chooser, step-outline, and disclosure components. Route manifests continue mapping one canonical file to one guide route. | An agent can fetch the chosen installation guide directly, identify its prerequisites and limits, and determine what success should look like. |
| `/operate/architecture/` and `/start/what-it-touches/` | Put a simple request-flow diagram and explanation before the full architecture. Link each visible part to deeper detail. Show model calls and other enabled outbound connections as distinct concerns. | Add a short, plainly labelled simplified-flow section, Mermaid definition, and text equivalent to `docs/architecture.md`. Edit `docs/start/what-it-touches.md` to reference it, retaining its operational inventory. | Add build-time diagram rendering and an accessible `Diagram.astro` component. Explore selects the same simplified section; no second inline SVG or copied labels are authored in the landing. | The simplified explanation, Mermaid definition, and textual data flow remain in Markdown. The full diagram and limitations stay accessible. |
| `/pathways/security/`, `/trust/`, and `/trust/what-leaves-my-deployment/` | Begin with what can leave the deployment, what the operator controls, and what needs checking. Offer deeper evidence by topic. Keep material caveats visible before any model-selection choice. | Add a concise Data boundary summary section to `docs/trust/what-leaves-my-deployment.md`. Preserve its accounting of cloud prompts, embeddings, tools, notifications, monitoring, and relevant limitations. Update `docs/site/trust/index.md` to curate rather than repeat the summary. | Explore and installation views select the same summary. Source chips retain route, status, and revision. Cautions are not put inside collapsed optional explanations. `/trust/` URLs remain stable. | Complete evidence and limitations with source paths and revision. The short explanation cannot substitute for the full accounting. |
| **New** `/start/first-document/` | A small fictional NDA example shows the product interface, document upload, the difference between extraction and AI analysis, and inspecting an answer's cited source. Readers can step through it or read it normally. | **New** `docs/start/first-document.md` references existing `docs/quickstart/sample-nda.md` and authoritative quickstart sections. Keep the written example and transcript in the repository docs; put screenshots, capture instructions, revision metadata, and placement rules under `site/` as transformation assets. Keep commands in their owning guide. | Add a worked-example component that projects the written steps and images. A video can be added from the validated example; it gets captions, a transcript, and a refresh procedure. | Complete steps, image descriptions, fictional-input link, expected observations, and transcript. An agent can understand the example without viewing a video. |
| Maintenance, skill-authoring, and contribution pages | Apply the task-guide pattern after the first installation journey works. Reference and release pages retain complete lookup content and clear indexes. | Next candidates: `docs/operate/backup-and-restore.md`, `docs/skills/author-your-first-skill.md`, and contribution hub docs. Keep security cautions and legal-content review requirements visible. Generated reference facts stay sourced from code and manifests. | Reuse the same transformations; add task entries. Do not rewrite every guide or convert reference material into an onboarding sequence. | Relevant tasks link directly to complete guides. Generated references retain all keys, tables, definitions, and status distinctions. |

### The overview route needs an explicit migration

Today `sync-content.mjs` moves `docs/site/index.mdx` from `/` to `/overview/` in the pathways layout. Adding an explicit canonical overview route without changing that behavior would create a collision.

The proposed migration is:

1. Map `docs/start/what-is-lq-ai.md` onto `overview` in `docs/site/routes/start.yaml`.
2. Keep `docs/site/index.mdx` as the classic navigation hub, including a selected overview summary by reference.
3. In the pathways layout, do not emit that classic hub as another overview page. Emit the generated Explore navigation route at `/` instead.
4. Keep the explicit overview available in both layouts and assign it to the Getting started pathway. Add an explicit overview link to the classic sidebar in `astro.config.mjs`, since its namespace-autogenerated groups do not include the top-level overview route. Resolve links to the root hub to `/`; links to the canonical overview resolve to `/overview/`.
5. Update the route-collision, link, and layout fixtures together. Preserve the public `/overview/` URL.

## Proposed source formats

The examples below show the authoring contract to implement. They are proposed formats, not fields the current schema already accepts.

### Write guidance in ordinary Markdown

`docs/quickstart.md` retains ordinary headings, commands, and relative links. Add expected results to the relevant step, rather than keeping them only in a UI checklist:

```markdown
## Before you start

[Requirements, fictional-data condition, and limitations live here.]

## 3. Start the app

[Required action and the existing command remain here.]

### Check this step

The long-running services should be Up; services with health checks
should report healthy. The completed rustfs-init container may be exited.

<!-- docsite:optional -->
### Details

[The existing explanation of builds, storage, and initialization remains here.]
<!-- /docsite:optional -->

## Check that it worked

[A running app, a document ready for use, and successful AI analysis
are separate checks, with their applicable prerequisites.]
```

The markers are invisible comments on GitHub. Their headings and contents remain readable there. The proposed transform wraps only the marked section in a native `<details>` element for humans, using the section heading as its label. It rejects nested/unclosed markers and critical alert blocks inside optional regions. Markdown export retains the heading and body and removes only presentation markers.

Keep optional checks and explanations distinct from alternative procedures. Cloud and local model sections use explicit headings and applicability prose. Their content is not inferred from the user's tab selection. Preserve existing public anchors or provide anchor aliases where renaming is necessary.

### Select introductory answers by source section

Proposed `docs/site/_data/explore.yaml`:

```yaml
schemaVersion: 1
questions:
  - id: what-is-lq-ai
    content:
      route: overview
      heading: "## What is LQ.AI?"
    next: [start/is-it-for-you, start/first-document]
  - id: how-answers-work
    content:
      route: operate/architecture
      heading: "## How LQ.AI answers a question"
    next: [operate/architecture]
  - id: data-boundary
    label: "Is it secure?"
    content:
      route: trust/what-leaves-my-deployment
      heading: "## Data boundary summary"
    next: [trust/what-leaves-my-deployment, trust/published-gaps]
```

`label` is optional interface wording; factual answer text, diagram definitions, and caveats cannot be stored here. Resolve `route` through the existing route registry, then select the uniquely matching heading and its subtree outside code fences. A renamed or duplicate heading fails validation. Source headings supply labels when no interface label is requested.

Use complete answer sections, not a fixed character count that could truncate a qualification. Inherit source-file provenance and review status, and include presentation-metadata changes in the view's revision. The underlying guide's own source stamp remains distinguishable from the view's build revision.

### Describe journeys without copying instructions

Proposed `docs/site/_data/journeys.yaml`:

```yaml
schemaVersion: 1
journeys:
  - id: first-compose-install
    route: start/quickstart
    before: "## Before you start"
    steps:
      - "## 1. Get the files"
      - "## 2. Set four secrets"
      - "## 3. Start the app"
      - "## 4. Sign in"
      - "## 5. Upload a test document"
      - "## 6. Connect an AI model"
    choices:
      - id: cloud-model
        section: "### Details: a cloud provider key (Mode 1)"
      - id: local-model
        section: "### Details: local Ollama (Mode 2, offline once set up)"
    check: "## Check that it worked"
```

Labels and applicable conditions are read from the source sections. Each alternative must contain its own applicability statement. Shared model/data caveats stay in the parent step and appear for every alternative, including the existing caveat about document-search models. The source review must validate whether the current local/offline label still accurately describes the setup before retaining it.

Journey metadata selects sections; it does not duplicate commands, prerequisites, or success text. The same selections generate human progress outlines and agent task entries. Changing a step label in the UI requires changing its canonical heading, with anchor compatibility handled explicitly.

## Source code change map

| Existing or proposed file | Implementation responsibility |
| --- | --- |
| `docs/site/routes/start.yaml` | Add the explicit overview and first-document sources; keep existing route mappings and add onward links. Source facts remain in Markdown. |
| `docs/site/_data/pathways.yaml` **new** | Own the four pathways and group ordering currently authored in `site/src/pathways.mjs`. Add new guide routes once. |
| `site/src/pathways.mjs` | Load the single pathway definition; retain release expansion, lookup, ordering, and validation. Produce a generated browser projection where the reader needs one. |
| `docs/site/_data/explore.yaml` and `journeys.yaml` **new** | Select canonical sections and destinations using the contracts above. |
| `site/scripts/lib/views.mjs` **new** | Validate the view schemas; resolve routes and unique source sections; construct source-bearing introduction, choice, step, and task models. Reuse the fence-aware Markdown helpers. |
| `site/scripts/lib/markdown.mjs` | Add heading-subtree selection and optional-region handling. Replace lossy tab reduction with labelled Markdown sections. Keep code fences, conditions, and diagram descriptions intact. |
| `site/scripts/sync-content.mjs` | Resolve views after the route table is known; remove the implicit overview relocation; record navigation/explanation routes and view dependencies in `.sync-manifest.json`. Produce normalized Markdown and view data without scraping the public site. |
| `site/src/content.config.ts` and `site/scripts/lib/routes.mjs` | Add validated, optional references to resolved journey/view data if needed for collection rendering. Do not accept arbitrary answer HTML or duplicate factual strings in frontmatter. |
| `site/astro.config.mjs` and `site/scripts/lib/rehype-lq-guidance.mjs` **new** | Wire the guidance transformation through the existing Satteri processing path. Preserve normal code/table/alert rendering. Document and pin any necessary diagram dependency. |
| `site/src/components/pathways/Landing.astro` and `[...lqnav].astro` | Compose Explore from generated view data. Register real navigation routes and metadata. No product explanation remains hardcoded in the component. |
| `Explore.astro`, `GuidedIntro.astro`, `JourneyChooser.astro`, `JourneySteps.astro`, and `Diagram.astro` **new** | Render the introduction, applicable paths, steps, and diagrams. Controls change display only; the full explanation and links are present without JavaScript. |
| `site/src/components/pathways/Header.astro`, `PageTitle.astro`, `PathwayGroups.astro`, `AllDocs.astro`, and `site/src/routeData.mjs` | Unify navigation; add Markdown access and a visible agent-docs entry; show current path and source status; use one pathway registry in every view. |
| `site/src/scripts/docs-search.ts` **new** | Adapt Pagefind results into Iris's composer and source chips; keep input/results in the current session. No model call or second ranking engine. |
| `site/src/components/pathways/GuideReader.astro` and `site/src/scripts/guide-reader.ts` **new** | Add optional adjacent/modal reading, keyboard/focus behavior, state restoration, real permalink handling, and Open full guide. Lazy-load generated guide assets. |
| `site/src/components/Stamp.astro`, `StatusBadge.astro`, and `Footer.astro` | Reuse source/status presentation in full pages and previews. Source-section chips point to the owning guide and source revision. |
| `site/scripts/gen-reader-assets.mjs` **new** | Generate small guide assets from the same trusted compiled content used for full pages, retaining anchors, base-aware assets, callouts, and provenance. Build-scoped section IDs avoid collisions in the preview. |
| `site/scripts/postbuild-machine-surface.mjs` | Emit useful Markdown for Explore/pathway/index routes; preserve labels and alternative applicability; add source paths, kind, status, and structured goal discovery to existing output. |
| `site/scripts/gen-task-index.mjs` **new** | Project journey/view selections into `tasks.json` with route, Markdown URL, section anchors, prerequisites, applicable alternatives, and verification references. Render a goal index in `llms.txt` from the same data. |
| `site/scripts/check-single-source.mjs` and `check-orphans.mjs` | Validate the new source contracts and reachability across ordinary pages, navigation pages, task entries, and both layouts. |
| `docs/site/README.md` and `site/README.md` | Document canonical ownership, selection/disclosure syntax, build outputs, agent contracts, and the workflow for adding a visual guide without copied content. |

Names of new implementation modules may be consolidated during implementation where responsibilities overlap. Their required behavior and source ownership remain fixed by this plan.

## Agent output contract

The human interface may collapse optional detail or emphasize a chosen procedure. Agent exports must retain full labelled content and supply direct discovery. The target flow is **goal index → applicable guide → supporting reference**, using plain text URLs throughout.

Every task entry identifies the owning guide's `.md` URL and section anchors. An entry can point to prerequisite and verification sections rather than copying them. The export includes applicability and review/source metadata so an agent can distinguish an experimental or partial capability from a supported procedure. `llms-full.txt` remains available, while the goal index avoids requiring the whole corpus for every task.

For example, after choosing local inference in the human UI, the complete quickstart Markdown still contains:

```markdown
## 6. Connect an AI model

[Shared prerequisites and data-handling cautions.]

### Details: a cloud provider key (Mode 1)

Applicable when: [the canonical condition for this arrangement].
[Cloud instructions and checks.]

### Details: local Ollama (Mode 2, offline once set up)

Applicable when: [the canonical condition, including remaining outbound paths].
[Local instructions and checks.]
```

The current `reduceMdx` implementation removes `Tabs`/`TabItem` tags without preserving their label attributes. Before richer conditional UI is introduced, add a supported conversion that renders each tab label as a heading. Unsupported content-bearing components cause a located export error rather than silently dropping their meaning. Avoid adding MDX components to canonical guides; normal Markdown plus build metadata is the primary format.

For diagrams, output the Mermaid definition and adjacent prose description. For screenshots/video, output meaningful descriptions, the example revision, and the transcript. For the reader, an agent always has the full direct page/text link regardless of preview state.

Export tests must compare semantic content: labels, prerequisite boundaries, command text, cautions, and verification sections. Merely asserting that an `.md` file exists is insufficient.

## Example of one change reaching every surface

Take the expected-result text for quickstart's Start the app step:

1. A contributor edits the Check this step subsection in `docs/quickstart.md`. The commands and technical explanation stay in that file.
2. `docs/site/routes/start.yaml` already maps that file to `start/quickstart`. `journeys.yaml` selects the numbered step by its canonical heading.
3. `sync-content.mjs` and `lib/views.mjs` produce the step title, required text, verification text, optional explanations, anchor, and provenance from the Markdown. They do not generate a new factual answer with a model.
4. The normal guide renders the full source. `JourneySteps.astro` renders the step outline and selected step from that same resolved model. Pagefind indexes the guide's text, including the optional explanation.
5. The optional reader uses an asset compiled from the same guide renderer, preserving the heading/anchor and source metadata.
6. `postbuild-machine-surface.mjs` exports the complete step and explanations to `start/quickstart.md`; `tasks.json` links to its prerequisite and verification sections. The full-text bundle includes the revised text.

A build-level regression fixture changes the canonical verification text and checks all of these outputs, so the source-of-truth promise is tested as behavior.

The corresponding proposed Astro component accepts source-resolved data:

```astro
---
// Proposed GuidedIntro.astro fragment; source selection happens at build time.
import SourceChips from './SourceChips.astro';
const { questions } = Astro.props;
---

{questions.map((question) => (
  <section aria-labelledby={`intro-${question.id}`}>
    <h2 id={`intro-${question.id}`}>{question.label}</h2>
    <div set:html={question.compiledHtml} />
    <SourceChips sources={question.sources} status={question.status} />
  </section>
))}
```

`compiledHtml` is trusted build output from reviewed repo Markdown through the normal rendering pipeline. It never accepts search input, model output, an uploaded document, or captured third-party HTML. The component owns presentation; the answer's prose, caveats, diagrams, and links belong to the source sections.

## Source and transformation contract

### Canonical repository content

Keep factual prose, questions and answers, numbered instructions, diagrams, diagram descriptions, walkthrough transcripts, and illustrative assets in their canonical repository locations. Continue using ordinary GitHub-readable Markdown and relative links. Existing authoritative files remain authoritative; create a focused explanatory document only where the current docs do not provide a suitable introduction.

Move the product explanation currently written directly in `site/src/components/pathways/Landing.astro` into an appropriate canonical explanation page. Author the three introductory answers as named sections of canonical docs, including their qualifications and links to deeper material. A presentation manifest selects those sections rather than carrying copied answer strings.

The simple architecture drawing must have one editable source and a readable text equivalent. Use a canonical Mermaid definition where appropriate, rendered at build time into accessible SVG; validate the simplified drawing against `docs/architecture.md`. Diagram tooling needs a documented dependency justification. Rich diagram interaction is optional enhancement to that same definition.

Keep walkthrough prose and transcripts with their canonical example. Store screenshots and their descriptions, placement rules, revision metadata, and refresh procedure under `site/`; the transform projects them onto the human and agent surfaces. Record the product revision, fictional inputs, capture procedure, and re-capture triggers. Avoid embedding volatile UI screenshots as unexplained decoration.

### Presentation metadata

Extend the existing route manifests and `docs/site/_data/` narrowly. Proposed additions:

- An Explore manifest mapping the three questions to a route and named source section, plus links to a diagram and a worked example.
- Journey metadata referencing canonical guide steps, prerequisite sections, and onward routes.
- A single pathway definition used by full pages, reader navigation, All guides, and generated indexes. Titles come from the route/content manifest.

These files select and order content; they do not become another store for factual answers. Missing or ambiguous sections, unknown routes, duplicate placements, and unsupported metadata fail the build with a located error. Specify the schema before adding these fields.

### Astro and the build

Extend `site/scripts/sync-content.mjs` and its existing parsing helpers to resolve source sections and produce structured view data with route, section ID, source files, status, and checked-against metadata. Use Markdown structure rather than slicing rendered HTML or relying on a runtime crawler.

Astro owns the layouts, reusable components, styling, diagram rendering, responsive behavior, and generated outputs. Reuse Starlight's guide rendering, code blocks, callouts, table transformations, and Pagefind integration. The reader preview and ordinary guide page should share a rendering path so neither quietly loses content or formatting.

Use Astro components and small browser scripts for these interactions. A frontend framework integration requires a demonstrated need and the justification required by ADR 0028; the prototype can be integrated without assuming one.

### Public surfaces

Generate all of the following from the same source graph:

1. Full HTML guide pages with stable URLs, source links, status, and checked-against stamps.
2. Explore, pathway navigation, and All guides, with useful text equivalents.
3. Pagefind's local search index, with section links and excerpts.
4. Plain Markdown page twins, `llms.txt`, and the full-text bundle.
5. Small, generated reader/explanation assets where needed; lazy-load guide content instead of delivering the whole captured corpus at startup.

The baseline B build produced 87 HTML pages and 80 Markdown twins. Its navigation pages are rendered separately in `site/src/pages/[...lqnav].astro`. Include those routes in the output contract so the richer introduction and navigation remain available to readers and agents as text.

Generated content under `site/src/content/`, reader payloads, compiled diagrams, and search indexes remain uncommitted build outputs. Source changes invalidate every affected presentation, index, and stamp in the same build.

## Integration of Iris's archives

The September 25 archive contains the earlier pathway design, source scripts, screenshots, and its own QA reports. The October 4 archive contains a standalone static interface, captured guides in `docs.js`, a second pathway map, a local keyword search, a hardcoded SVG architecture drawing, and answer strings in `app.js`.

Preserve as much of the design and interaction behavior as useful: the warmer presentation, question sequence, drawing concept, source chips, reader continuity, theme behavior, mobile navigation, keyboard shortcuts, code-copy fallback, and playback controls.

Replace the archive-specific mechanisms:

- Captured `docs.js` becomes generated content from the canonical repo docs.
- Hardcoded introductory answers and diagram labels become source-backed Markdown and diagram data.
- The copied `pathways.js` becomes a build projection of one pathway definition.
- The hand-written search ranking becomes a Pagefind adapter.
- Hash-only guide routing gains real permalinks, section anchors, Back/Forward behavior, and normal new-tab links.
- Captured-HTML cleanup is replaced by the normal documentation rendering path; preview transport gets an explicit trust and rendering contract.
- Guide previews retain source/status metadata rather than presenting only an extracted article body.

Preserve Apache-2.0 and font notices and credit Iris's contributed design and code. Keep archive QA claims separate from acceptance evidence for the integrated Astro implementation.

## Delivery sequence

### 1. Establish the content and branch baseline

Reconcile the local B branch with the published #581/#604 stack before editing. The local review history and #604 use different commit IDs for substantially matching work, so compare content and preserve credit rather than blindly merging duplicate histories. Identify factual changes since the B snapshot and update canonical sources before presenting them as current.

Produce the source map for the three answers, architecture drawing, first example, and installation path. Keep the scope in this annex aligned with the existing mini-PRD. Static search and existing hosting follow ADR 0028; hosted inference, semantic search services, or a hosting change require a separate proposal.

**Done when:** every displayed factual block has a canonical source and every imported interaction has a reuse/adaptation decision.

### 2. Implement the source and export contracts

Implement and document the proposed view/journey schemas, section selection, optional-region conversion, and semantic Markdown export before introducing richer controls. Change the overview route ownership and include navigation routes in the generated output registry.

**Primary files:** `docs/site/README.md`, `site/README.md`, `site/scripts/lib/views.mjs`, `markdown.mjs`, `sync-content.mjs`, `postbuild-machine-surface.mjs`, the new task-index generator, and focused fixtures under `site/test/`.

**Done when:** missing/ambiguous sections fail the build; labels and complete alternative procedures survive export; overview/root routes do not collide; a text-only reader can discover a task and fetch its full guide without JavaScript.

### 3. Build one complete example

Implement **What is LQ.AI? → understand the data flow → inspect a fictional document workflow → choose the first setup step**. This combines the welcoming introduction with a practical outcome and covers the community's request to see the product.

Add section selection and provenance to the build; render the static introduction and diagram; connect source links to full guides. Check the example with a lawyer unfamiliar with the repo before applying the pattern across the docs.

**Primary files:** the new `docs/start/what-is-lq-ai.md` and `first-document.md`, `docs/architecture.md`, `docs/trust/what-leaves-my-deployment.md`, `docs/site/routes/start.yaml`, `explore.yaml`, `Landing.astro`, and the new introductory components. The example's repo Markdown and public text output ship with its visual presentation.

**Done when:** that reader can describe what LQ.AI does, identify what may leave the deployment, and choose an appropriate next action without a verbal explanation.

### 4. Add the first progressive task guide

Restructure quickstart and installation navigation as the table specifies. Add the step outline, prerequisite/check sections, explicitly labelled model alternatives, and optional explanations. Keep commands and data cautions in canonical Markdown. Verify the human chosen-path view and the complete agent export together.

**Primary files:** `docs/quickstart.md`, `docs/site/operate/index.md`, `docs/site/start/choose-your-path.md`, `journeys.yaml`, `JourneyChooser.astro`, `JourneySteps.astro`, and the guidance transform.

**Done when:** a human can select an appropriate setup and check each step; an agent given only the goal index and Markdown URLs can identify the same procedure, its applicable conditions, and its success checks.

### 5. Integrate Explore and guide reading

Port Iris's shell and composer presentation into Astro, retaining Pagefind. Add source-bearing results, optional adjacent guide previews, a full-page reading action, responsive overlays, state restoration, and theme controls. Browsing and the full introduction remain usable without JavaScript; enhanced search and reader state load progressively.

**Primary files:** `Header.astro`, `PageTitle.astro`, `PathwayGroups.astro`, `AllDocs.astro`, `routeData.mjs`, the new search/reader scripts and reader-assets generator, and the shared stamp/status components.

**Done when:** search → preview → full guide → section link → Back/Forward works with ordinary URLs, preserves context where appropriate, and exposes the same content and source metadata.

### 6. Extend the guidance and visual examples

Apply progressive disclosure and visual progress to the chosen installation journey, then the other high-priority reader journeys. Add diagrams where they answer a concrete question. Record the short walkthrough from the validated fictional example; keep its transcript and capture recipe canonical.

**Primary files:** `docs/INSTALL-MAC.md`, README's Quick Start section, `docs/operate/install-helm.md`, selected maintenance/skill-authoring guides, and `docs/start/examples/first-document/`. Reuse the components and source contracts established in earlier increments.

**Done when:** users can follow the first-task path, identify prerequisites and cautions, and recover their place after navigating away. Screenshots and video have a documented revision and refresh procedure.

### 7. Run acceptance and prepare the PR

Run existing site gates in the intended layout and at both `/` and `/lq-ai/`. Add focused tests for the new source-selection and navigation contracts. Re-run Annex B's relevant journeys and inspect keyboard, screen-reader, mobile, tablet, desktop, light/dark, and reduced-motion behavior.

Review the combined implementation with Iris and other contributors before generalizing the design further. Prepare a PR with source mapping, credit, screenshots, test evidence, and any remaining decisions. Review and publishing are subsequent actions; this plan does not publish the site.

## Acceptance checks

- Editing one canonical introductory answer changes Explore, its full guide, reader preview, Markdown twin, and relevant search output in one build.
- Removing or renaming a referenced source section causes a located build failure.
- A diagram and its text equivalent express the same data flow, including relevant local/cloud boundaries.
- Search uses the built docs locally and visibly identifies matching documentation; it cannot imply a generated answer when it returns guide matches.
- All guides remain reachable directly, with JavaScript disabled, and in plain Markdown. Public `/trust/` routes remain stable.
- Preview and full-guide rendering preserve headings, anchors, code copying, images, callouts, tables, source links, and status.
- Critical data-handling cautions remain visible before readers choose a deployment or example. Progressive disclosure does not conceal them.
- Playing, pausing, replaying, or changing motion preferences never deletes queries or results. Reading the introduction does not require waiting for simulated typing.
- Reader overlays manage focus and restore it on close. Menus, searches, and full guides remain usable at narrow and short viewport sizes.
- The initial page does not eagerly ship the prototype's entire captured corpus. Set a build-measured asset budget after the first integrated example and enforce it before expanding the experience.
- Existing single-source, link, orphan, table, contrast, accessibility, and docs-link checks pass. Add machine-surface coverage for the new navigation and introduction routes.
- A renamed source heading, duplicate heading, unclosed optional region, or caution inside an optional region fails with its owning document and location. Headings inside fenced examples never become journey steps.
- Machine exports preserve alternative labels, applicability statements, code-fence contents, critical qualifications, and verification headings. A text-only agent can choose the appropriate installation and explain what it must check without interacting with the visual selectors.
- Tests in `site/test/sync.test.mjs` cover the existing export/route contracts; new view and disclosure fixtures cover the new semantics, and `pathways.test.mjs` covers revised labels, new routes, and releases. Browser acceptance covers actual interaction and accessibility, rather than treating prototype QA reports as integration evidence.

## First implementation increment

The first local increment implements canonical overview ownership, the three
source-selected answers, quickstart step
navigation, native optional explanations, and complete text exports. Explore
and the pathway/index routes have Markdown twins. A generated `tasks.json`
provides prerequisite, step, alternative, and verification heading references.
Full-guide links in introductory sections preserve their owning route, and
cloud/local alternatives retain their labels and conditions in the agent text.

Validation includes source-to-export regression fixtures at `/` and `/lq-ai/`,
actual builds and link/reachability checks in both layouts, and the pathways
layout/table/contrast/accessibility gates. The new source/schema contracts are
documented in `docs/site/README.md` and `site/README.md`.

The diagram increment adds four canonical Mermaid definitions: the workspace
workflow, request routing, the data boundary, and first-run checks. A build-only
Mermaid renderer emits static SVGs in both themes and portrait flowchart layouts,
with descriptions and source controls. Machine Markdown retains the definitions.

The site-owned product capture increment adds real UI images and descriptions
through `site/product-captures/screenshots.json`, without adding presentation
paths to canonical guides. Human and agent outputs retain each example's
revision and limitations.

## Local LiquidUI implementation increment

Persistent pathways are rendered by `Sidebar.astro` from the existing pathway
map, with Starlight's native mobile menu. The Pagefind composer presents current
matching excerpts, section links, review status, complete guide links, and
Markdown links. It uses no model and retains queries/results in the page session.

`gen-reader-assets.mjs` builds lazy previews from the same compiled HTML as the
complete pages. `GuideReader.astro` and `guide-reader.ts` add adjacent reading on
wide screens and a native modal elsewhere. They preserve diagrams, images,
callouts, code, source/status metadata, normal permalinks, section anchors,
Back/Forward, disclosures and reading position. (The reader's All documentation title filter was removed on 2026-10-22: it read as a second search box, and the composer is the one search.)
Reloading a preview URL opens the ordinary complete guide.

Playback is optional and uses the existing source-selected answers. Playing,
pausing, resuming, and replaying highlight those answers without removing
content or search history. The introduction and guide navigation stay available
without JavaScript; enhanced search/preview failures fall back to normal pages.

The first complete local integration passed 132 tests, link/reachability checks,
layout checks at 1280px and 400px, contrast, all 88 accessibility URLs, and
canonical docs-link checks. Browser interaction verification is recorded
separately from the contributor's prototype QA claims. The complete skill-based
document walkthrough and broader progressive task selectors remain future work.

The maintainer owns all pushing, merging, and publication. The A/B/C demos were
published at the maintainer's request. They share the canonical guides and five
fresh product views: extraction readiness, the skill chooser, a completed
ordinary local-model answer, its declared route, and table-mode skill examples.
B retains its cards and top tabs; C uses the interactive explorer and reader.
The Contract QA skill's required-input error is recorded separately from the
successful ordinary-chat example. A regression now covers cancelling the first
guide lookup before the registry finishes loading.

## Evidence and limits

- [Iris's September 25 B-design message](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1790321804307949), including `lq-docs-v2.zip` (file `F0C48110NKV`).
- [Iris's October 4 LiquidUI update](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1791104031072889), including `lq-ai-liquidui-chat-standalone.zip` (file `F0C6HT7J2K0`). Both archives were unpacked and their source files inspected. LiquidUI's introduction, search, and desktop reader were also inspected in a browser.
- [October 4 search clarification](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1791106820638749): current behavior returns matching docs; AI answering was discussed as a possible extension. The delivered source implements local search.
- WhatsApp: `channels/LQ AI.txt`, source records `LQ AI#L1932–1940`, `L1943–1962`, and `L1963`. Authors remain pseudonymous. The retrieved archive ends October 2; the two September 27 design images were referenced in the export but were not available for visual inspection.
- [September 28 single-source and one-topic demonstration discussion](https://legalquants.slack.com/archives/C0BDS8RR7JM/p1790568930669199).
- Public references checked: [Stripe docs](https://docs.stripe.com/) and [Josh Comeau's tutorials](https://www.joshwcomeau.com/). Their ideas inform goal-oriented entry points and visual explanations; they do not determine the project's stack.
- Prototype QA files are contributor-supplied reports. Integrated mobile, accessibility, performance, and product-capability acceptance remains work in the delivery sequence.
