# Feature Retro

A portable, skill-only plugin for the end of a feature build. It prepares a
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

One skill, optional prompts and a local-link check. Brag-inspired story structure, no Brag runtime
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
