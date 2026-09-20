# Feature Retro

A portable skill and JavaScript toolkit for the end of a feature build. It prepares a
dated retrospective design review and evidence-backed article inputs. It does
not write or publish an article, run a provider evaluation, or install build hooks.

## Use

After installing this catalog entry, ask Codex: “Use `$feature-retro` to review
[feature/source] and prepare notes in [authoring repo].” For source-only use,
give the agent `plugins/feature-retro/skills/feature-retro/SKILL.md` explicitly.
Follow the repository marketplace instructions for installation; a new task
is needed for installed skill discovery.

For a local Claude Code plugin session, from this repository:

```bash
claude --plugin-dir ./plugins/feature-retro
```

Then invoke `/feature-retro:feature-retro` with the source feature and destination.
This source package includes Codex and Claude manifests. The Codex marketplace
catalog includes this plugin. Manifest validation does not prove host installation
or discovery. No global plugin installation is required to review the source.

## Design

One skill, reusable artifact components and a local-link check. Brag-inspired story structure, no Brag runtime
dependency. It complements an authoring repository's existing writing skills:
feature build → review and claim register → explicit article request → existing
editorial workflow. No automatic publication bridge.

Keep project-specific review artifacts and source claims in their selected
authoring repository, not this public plugin catalog. No private writing
repository, project identity, machine layout or API credential is required.

From this repository, validate a review package's local artifact links:

```bash
node plugins/feature-retro/scripts/check-package.mjs <review-directory>
```

The helper only checks local file targets. It does not certify source claims,
external URLs, fragment anchors or deployment safety.

## Build repeatable elements

Node 22 or newer, no npm install for HTML and SVG. From this repository:

```bash
node plugins/feature-retro/scripts/build-review.mjs plugins/feature-retro/examples/review.json review-output
```

Copy the synthetic example into the selected authoring repository and replace
its content with sourced claims. Run the same command with that JSON path and a
**new** output directory. Existing directories (including symlinks) are refused.
The output parent must exist. A failed build may leave a partial directory;
`build.json` is written only after generation completes. It is not review approval.

The builder produces a self-contained `review-board.html` and an editable SVG
for each flow. Identical input produces byte-identical HTML, SVG and generation
receipts. HTML uses native disclosure controls, light/dark CSS and keyboard
scrollable diagrams/tables. No browser JavaScript, remote assets or network
requests are needed. This is build-time JavaScript, not an interactive editor.

### Content contract (version 1)

The runnable [example](examples/review.json) is the starting point. All copy is
plain text, escaped by the renderer. Newlines create line breaks. There is no
raw HTML, link URL, image fetch, template evaluation or arbitrary-code field.

- Top level: `version: 1`, `title`, `date`, `headline`, `summary`, `notice`,
  `sections`, `footer`, and optional `slides`.
- Each section: unique `id`, navigation `label`, `title`, `blocks`.
- Blocks: `paragraph`/`callout` with `text`; `details` with `summary`/`text`;
  `list` with labeled items; `table` with caption, headers and equal-width rows;
  `flow` with unique ID, title, description, caption and independent paths.
- Each flow path: title, 2–4 nodes, optional response node and optional `proof`
  accent. Nodes have `label`/`detail`, each at most two explicitly broken lines
  of 30 characters. A response connects the last node back to an advice node;
  separate paths never acquire cross-links. Use a different diagram for a
  relationship this grammar cannot honestly express.
- Slides: title, required source/limitation `notes`, and `elements`. Reusable
  primitives are `text`, labeled `row`, `box`, and `arrow`, on a 1280×720 canvas.
  The example supplies their fields. Geometry is bounded, not auto-arranged.
  Rendered inspection is still required to catch text overlap or clipping.

Library consumers can import `renderBoard`, `renderFlow`, `createDeck` and
`validateReview` from `scripts/render-review.mjs`. The deck adapter accepts the
presentation runtime and font explicitly. No feature-specific content belongs
in these components. The board and slides share a data file, but their narrative
copy is deliberately separate; review them together when a claim changes.

### Optional editable PowerPoint

Use the installed presentation skill and its bundled `@oai/artifact-tool`
runtime. Follow that skill's authoring/validation guidance. Ask the agent to
resolve its runtime once into a **local, untracked** `runtime.json` with absolute
`nodeModules`, `presentationSkill` and `python` paths. This trusted operator
config selects local executable code; never accept it from review/source data.
Do not copy runtime paths or credentials into a public repository.

```bash
node plugins/feature-retro/scripts/build-review.mjs review.json review-output --runtime runtime.json
```

This adds `review.pptx`, validates the package and renders every delivered slide
in a private temporary directory printed by the command. Inspect those renders
before delivery. Runtime validation receipts stay there, outside the output.
Export metadata may vary, so PPTX byte identity is not promised. No PDF/video
pipeline, provider evaluation, global installation or publication is performed.
Portable HTML/SVG builds never require this optional dependency.

### Checks

```bash
node --test plugins/feature-retro/scripts/render-review.test.mjs
node plugins/feature-retro/scripts/check-package.mjs --self-test
```

The synthetic check covers determinism, escaped hostile copy, rejected malformed
data/geometry, all slide primitives, and refusal to overwrite files/directories
or follow an output symlink. It is not a provider or browser qualification test.
