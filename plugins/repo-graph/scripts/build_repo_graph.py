#!/usr/bin/env python3
"""Build a local repository graph and bounded architecture diagram."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys


MAX_GROUPS = 24
MAX_EDGES = 40
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "build", "graphify-out"}


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = "\n".join((result.stderr + "\n" + result.stdout).splitlines()[-12:])
        raise RuntimeError(f"{' '.join(command[:3])} failed:\n{detail}")


def graphify_command() -> list[str]:
    if binary := shutil.which("graphify"):
        return [binary]
    if uvx := shutil.which("uvx"):
        return [uvx, "--from", "graphifyy", "graphify"]
    raise RuntimeError("Graphify is required. Install it with: uv tool install graphifyy")


def check_graphify(command: list[str]) -> None:
    result = subprocess.run(command + ["--help"], capture_output=True, text=True, check=False)
    help_text = result.stdout + result.stderr
    if result.returncode or "--code-only" not in help_text or "callflow-html" not in help_text:
        raise RuntimeError("Graphify needs code-only extraction and callflow export; update it with: uv tool install --upgrade graphifyy")


def repo_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, check=False,
    ) if shutil.which("git") else None
    if result is not None and result.returncode == 0:
        paths = [Path(os.fsdecode(part)) for part in result.stdout.split(b"\0") if part]
    else:
        paths = []
        for base, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
            paths.extend((Path(base) / name).relative_to(root) for name in files)
    return sorted({path.as_posix() for path in paths
                   if path.parts and not any(part.startswith(".") or part in SKIP_DIRS for part in path.parts)
                   and (root / path).is_file() and not (root / path).is_symlink()})


def inventory_graph(root: Path, destination: Path) -> dict:
    files = repo_files(root)
    if not files:
        raise RuntimeError("No readable repository files found.")
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[tuple[str, str]] = set()
    for file in files:
        path = PurePosixPath(file)
        parent = ""
        for directory in path.parts[:-1]:
            current = f"{parent}/{directory}" if parent else directory
            nodes.setdefault(f"dir:{current}", {"id": f"dir:{current}", "label": directory,
                                                 "file_type": "directory", "source_file": current,
                                                 "_origin": "inventory"})
            if parent and (f"dir:{parent}", f"dir:{current}") not in edge_keys:
                edges.append({"source": f"dir:{parent}", "target": f"dir:{current}",
                              "relation": "contains", "confidence": "EXTRACTED"})
                edge_keys.add((f"dir:{parent}", f"dir:{current}"))
            parent = current
        nodes[f"file:{file}"] = {"id": f"file:{file}", "label": path.name,
                                  "file_type": "file", "source_file": file,
                                  "_origin": "inventory"}
        if parent:
            edges.append({"source": f"dir:{parent}", "target": f"file:{file}",
                          "relation": "contains", "confidence": "EXTRACTED"})
    graph = {"nodes": list(nodes.values()), "edges": edges, "hyperedges": [],
             "input_tokens": 0, "output_tokens": 0}
    destination.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    return graph


def safe_label(value: str) -> str:
    return "".join(char if char.isalnum() or char in " /._()-" else " " for char in value)[:70]


def graph_edges(graph: dict) -> list[dict]:
    return graph.get("edges", graph.get("links", []))


def mermaid(graph: dict, inventory: bool = False) -> str:
    owners = {node["id"]: node.get("source_file", "") for node in graph["nodes"]}
    files = {path for node in graph["nodes"] if node.get("file_type") != "directory"
             if (path := node.get("source_file", ""))}
    if not files:
        return "flowchart LR\n    empty[\"No source files found\"]\n"

    def base(path: str) -> str:
        parts = PurePosixPath(path).parts
        return parts[0] if len(parts) > 1 else "(root)"

    roots = Counter(base(path) for path in files)
    split = {name for name, count in roots.items() if count * 5 > len(files) * 3
             and len({PurePosixPath(path).parts[1] for path in files
                      if base(path) == name and len(PurePosixPath(path).parts) > 2}) > 1}

    def group(path: str) -> str:
        parts = PurePosixPath(path).parts
        return "/".join(parts[:2]) if base(path) in split and len(parts) > 2 else base(path)

    if len({group(path) for path in files}) == 1 and len(files) > 1:
        group = lambda path: path  # A flat repository needs file-level nodes.

    groups = {node_id: group(path) for node_id, path in owners.items() if path}
    group_files: dict[str, set[str]] = defaultdict(set)
    for path in files:
        group_files[group(path)].add(path)
    raw_edges: Counter[tuple[str, str]] = Counter()
    for edge in graph_edges(graph):
        if edge.get("relation") == "contains" and not inventory:
            continue
        source, target = groups.get(edge.get("source")), groups.get(edge.get("target"))
        if source in group_files and target in group_files and source != target:
            raw_edges[source, target] += 1
    degree = Counter()
    for (source, target), count in raw_edges.items():
        degree[source] += count
        degree[target] += count
    ranked = sorted(group_files, key=lambda name: (-degree[name], -len(group_files[name]), name))
    selected = set(ranked[:MAX_GROUPS - 1]) if len(ranked) > MAX_GROUPS else set(ranked)
    collapsed = len(ranked) - len(selected)
    shown = sorted(selected)
    if collapsed:
        shown.append("Other directories")
    ids = {name: f"n{index}" for index, name in enumerate(shown)}

    def visible(name: str) -> str:
        return name if name in selected else "Other directories"

    lines = ["flowchart LR"]
    for name in shown:
        count = len(group_files[name]) if name in group_files else sum(len(group_files[other]) for other in ranked if other not in selected)
        label = f"{name} ({collapsed} groups, {count} files)" if name == "Other directories" else f"{name} ({count} {'file' if count == 1 else 'files'})"
        lines.append(f'    {ids[name]}["{safe_label(label)}"]')
    edges: Counter[tuple[str, str]] = Counter()
    for (source, target), count in raw_edges.items():
        a, b = visible(source), visible(target)
        if a != b:
            edges[a, b] += count
    for (source, target), count in sorted(edges.items(), key=lambda item: (-item[1], item[0]))[:MAX_EDGES]:
        lines.append(f"    {ids[source]} -->|{count}| {ids[target]}")
    if not edges:
        lines.append("    %% No cross-component relationships were extracted.")
    return "\n".join(lines) + "\n"


def overview_graph(diagram: str) -> dict:
    nodes, edges = [], []
    for line in diagram.splitlines():
        if node := re.fullmatch(r'\s*(n\d+)\["([^"]+)"\]', line):
            nodes.append({"id": node[1], "label": node[2], "file_type": "component",
                          "_origin": "aggregate"})
        elif edge := re.fullmatch(r"\s*(n\d+) -->\|(\d+)\| (n\d+)", line):
            edges.append({"source": edge[1], "target": edge[3],
                          "relation": "cross_component_links", "weight": int(edge[2]),
                          "confidence": "EXTRACTED", "_origin": "aggregate"})
    return {"nodes": nodes, "edges": edges, "hyperedges": [],
            "input_tokens": 0, "output_tokens": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", help="local repository path (default: current directory)")
    parser.add_argument("--output", type=Path, help="output directory (default: user cache)")
    args = parser.parse_args()
    root = Path(args.repo).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    digest = hashlib.sha256(os.fsencode(root)).hexdigest()[:12]
    output = (args.output or Path.home() / ".cache" / "repo-graph" / f"{root.name}-{digest}").expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    graph_dir = output / "graphify-out"
    graph_path = graph_dir / "graph.json"
    command = graphify_command()
    check_graphify(command)
    # ponytail: code-only omits semantic docs; add an opt-in model pass if file links are insufficient.
    run(command + ["extract", str(root), "--code-only", "--no-cluster", "--max-workers", "4", "--out", str(output)])
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    tokens = (graph.get("input_tokens", 0), graph.get("output_tokens", 0))
    inventory = not graph.get("nodes")
    if inventory:
        graph_path = graph_dir / "inventory-graph.json"
        graph = inventory_graph(root, graph_path)
    else:
        (graph_dir / "inventory-graph.json").unlink(missing_ok=True)
    if len(graph["nodes"]) > 500 and not inventory:
        run(command + ["cluster-only", str(output), "--graph", str(graph_path),
                       "--no-label", "--no-viz"])
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    diagram_source = mermaid(graph, inventory)
    (graph_dir / "graph.html").unlink(missing_ok=True)
    run(command + ["export", "html", "--graph", str(graph_path), "--node-limit", "500"])
    overview = False
    if not (graph_dir / "graph.html").is_file():
        overview = True
        overview_path = graph_dir / "overview-graph.json"
        overview_path.write_text(json.dumps(overview_graph(diagram_source), ensure_ascii=False), encoding="utf-8")
        run(command + ["export", "html", "--graph", str(overview_path), "--node-limit", "500"])
        if not (graph_dir / "graph.html").is_file():
            raise RuntimeError("Graphify could not render the component overview.")
    else:
        (graph_dir / "overview-graph.json").unlink(missing_ok=True)
    run(command + ["export", "callflow-html", "--graph", str(graph_path),
                   "--output", str(graph_dir / "architecture.html"), "--max-sections", "8",
                   "--max-diagram-nodes", "18", "--max-diagram-edges", "24"])
    diagram = graph_dir / "architecture.mmd"
    diagram.write_text(diagram_source, encoding="utf-8")
    (graph_dir / "architecture.md").write_text(
        "# Repository architecture\n\n```mermaid\n" + diagram_source + "```\n",
        encoding="utf-8",
    )
    scope = "repository file inventory" if inventory else "code relationships"
    print(f"{scope}: {len(graph['nodes'])} nodes, {len(graph_edges(graph))} edges; "
          f"{tokens[0]} input / {tokens[1]} output model tokens")
    if overview:
        print("Interactive graph: bounded component overview; JSON retains the full graph")
    for name, path in (("Graph", graph_dir / "graph.html"), ("Diagram", graph_dir / "architecture.html"),
                       ("Mermaid", diagram), ("JSON", graph_path)):
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"repo-graph: {error}", file=sys.stderr)
        raise SystemExit(1) from error
