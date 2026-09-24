---
name: repo-graph
description: Build a local interactive code graph and a bounded architecture diagram for a repository. Use when the user asks to visualize or map a repo, including large ones.
---

# Repo Graph

Run `python3 ../../scripts/build_repo_graph.py [repo-path]` from this skill's directory. Resolve `../../scripts/` relative to this `SKILL.md`, not the repository being mapped. The path defaults to the current directory; `--output DIR` places results elsewhere. The script uses the installed `graphify` command, or `uvx` to obtain `graphifyy` on first use.

It writes to a stable directory under the user's cache by default, leaving the source repository untouched. Report the script's measured node, edge, and model-token counts and link its `graph.html`, `architecture.html`, `architecture.md`, and `graph.json`. Do not load the whole graph or source tree into the model context. Read only a targeted subgraph or source file when the user asks a follow-up question.

The default scan is code only and invokes no model. Graphify extracts relationships from supported source languages; `architecture.mmd` groups the extracted links into at most 24 components and 40 connections. Large interactive graphs show community or component overviews; the JSON retains full detail. When no code nodes are found, the graph is a repository file inventory with containment edges, not an inferred architecture. Tell the user which scope was produced. Both HTML views load viewer JavaScript from public CDNs when opened; the JSON and Mermaid files stay local.
