---
name: repo-graph
description: Build an offline interactive repository map and architecture diagram from local paths or a public HTTPS git URL, including large repositories.
---

# Repo Graph

Run `python3 ../../scripts/build_repo_graph.py [repo-path-or-https-url]` from this skill's directory. Resolve `../../scripts/` relative to this `SKILL.md`, not the repository being mapped. The path defaults to the current directory; `--output DIR` places results elsewhere. Public HTTPS URLs are cloned into the user's cache and reused; `--refresh` updates a cached clone.

It writes to a stable directory under the user's cache by default, leaving the source repository untouched. Report measured file, directory, local import, scan, and cache counts; link `architecture.html`, `graph.html`, `architecture.mmd`, and `graph.json`. The architecture view shows containment and imports; the dependency graph shows imports only. Do not load the whole graph or source tree into model context. Read only targeted paths when answering follow-up questions.

The default scan uses a dependency-free extractor and no model calls. It batches 512 files, reads at most 64 KiB per Go, Python, JavaScript, or TypeScript file, caches import lists by size and modification time, and resolves only local imports it can identify. Unrecognized languages still appear in the directory map. The HTML view is self-contained, with directory drilldown and pages of at most 23 entries plus a scope card; import links are capped to keep the canvas readable. `graph.json` retains the complete path inventory and aggregated local imports. The Mermaid file covers the first root page. Describe import links as heuristic, not call-flow proof.

`--jev` is optional. It reads only `TYPESAFE_API_KEY` from the process environment or the user's `~/.env`, then sends up to 16 top-level directory names to TypeSafe System One in one typed request while the local scan runs. It adds confident role labels, caches them, and never lets model output create links or alter the inventory. Directory names leave the machine only when the user opts in. Never display or log the key or other lines in `~/.env`.
