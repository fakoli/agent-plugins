#!/usr/bin/env python3
"""Build an offline, bounded repository map from local paths and imports."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


PAGE_SIZE = 24
READ_LIMIT = 64 * 1024
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "build", "vendor", "target"}
CODE_EXTENSIONS = {".go", ".py", ".js", ".jsx", ".ts", ".tsx"}
ROLES = ("application", "library", "infrastructure", "tests", "documentation", "examples", "tooling", "other")


def repo_files(root: Path) -> list[str]:
    command = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    result = subprocess.run(command, cwd=root, capture_output=True, check=False) if shutil.which("git") else None
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


def tree_index(files: list[str]) -> dict[str, dict]:
    tree = {"": {"count": 0, "children": set(), "direct": [], "sample": []}}
    for file in files:
        parent = ""
        for part in PurePosixPath(file).parts[:-1]:
            child = f"{parent}/{part}" if parent else part
            tree.setdefault(child, {"count": 0, "children": set(), "direct": [], "sample": []})
            tree[parent]["children"].add(child)
            tree[parent]["count"] += 1
            if len(tree[parent]["sample"]) < 8:
                tree[parent]["sample"].append(file)
            parent = child
        tree[parent]["count"] += 1
        tree[parent]["direct"].append(file)
        if len(tree[parent]["sample"]) < 8:
            tree[parent]["sample"].append(file)
    for node in tree.values():
        node["children"] = sorted(node["children"])
    return tree


def imports_from(path: str, source: str) -> list[str]:
    ext = PurePosixPath(path).suffix
    if ext == ".go":
        imports, in_block = [], False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ("):
                in_block = True
                continue
            if in_block and stripped == ")":
                in_block = False
                continue
            if in_block or stripped.startswith("import "):
                match = re.search(r'"([^"\n]+)"', stripped.split("//", 1)[0])
                if match:
                    imports.append(match.group(1))
        return imports
    if ext == ".py":
        imports = []
        for line in source.splitlines():
            match = re.match(r"\s*(?:from\s+([.\w]+)\s+import|import\s+([\w.]+))", line)
            if match:
                imports.append(match.group(1) or match.group(2))
        return imports
    if ext in {".js", ".jsx", ".ts", ".tsx"}:
        return re.findall(r"""(?:\bfrom\s*|\bimport\s*\(|\brequire\s*\()\s*['"]([^'"]+)['"]""", source)
    return []


def local_target(path: str, imported: str, module: str, tree: dict[str, dict]) -> str | None:
    parent = posixpath.dirname(path)
    ext = PurePosixPath(path).suffix
    if ext == ".go" and module and imported.startswith(module + "/"):
        target = imported[len(module) + 1:]
    elif ext == ".py":
        if imported.startswith("."):
            dots = len(imported) - len(imported.lstrip("."))
            base = parent
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            target = posixpath.join(base, imported[dots:].replace(".", "/"))
        else:
            target = imported.replace(".", "/")
    elif ext in {".js", ".jsx", ".ts", ".tsx"} and imported.startswith("."):
        target = posixpath.normpath(posixpath.join(parent, imported))
    else:
        return None
    target = target.strip("/")
    if target in tree:
        return target
    stem = posixpath.splitext(target)[0]
    return posixpath.dirname(stem) if posixpath.dirname(stem) in tree else None


def extract_dependencies(root: Path, files: list[str], tree: dict[str, dict], cache_path: Path) -> tuple[list[dict], dict]:
    module = ""
    if (root / "go.mod").is_file():
        match = re.search(r"(?m)^module\s+(\S+)", (root / "go.mod").read_text(encoding="utf-8", errors="replace")[:4096])
        module = match.group(1) if match else ""
    try:
        old = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    current, edges = {}, Counter()
    scanned = reused = truncated = 0
    # ponytail: one metadata pass and 512-file batches; use SQLite only if a multi-million-file repo needs it.
    for start in range(0, len(files), 512):
        for file in files[start:start + 512]:
            if PurePosixPath(file).suffix not in CODE_EXTENSIONS:
                continue
            try:
                stat = (root / file).stat()
                stamp = [stat.st_mtime_ns, stat.st_size]
                cached = old.get(file)
                if cached and cached[:2] == stamp:
                    imports = cached[2]
                    reused += 1
                else:
                    with (root / file).open("rb") as stream:
                        source = stream.read(READ_LIMIT).decode("utf-8", errors="replace")
                    imports = imports_from(file, source)
                    scanned += 1
                truncated += stat.st_size > READ_LIMIT
            except OSError:
                continue
            current[file] = [*stamp, imports]
            source_dir = posixpath.dirname(file)
            for imported in imports:
                target_dir = local_target(file, imported, module, tree)
                if target_dir is not None and target_dir != source_dir:
                    edges[source_dir, target_dir] += 1
    cache_path.write_text(json.dumps(current, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return ([{"source": a, "target": b, "count": n, "relation": "imports"}
             for (a, b), n in sorted(edges.items())],
            {"scanned": scanned, "reused": reused, "truncated": truncated, "code_files": len(current)})


def scope_edges(dependencies: list[dict]) -> dict[str, list[dict]]:
    scopes: dict[str, Counter] = {}
    for edge in dependencies:
        a = edge["source"].split("/") if edge["source"] else []
        b = edge["target"].split("/") if edge["target"] else []
        common = 0
        while common < min(len(a), len(b)) and a[common] == b[common]:
            common += 1
        scope = "/".join(a[:common])
        source = "/".join(a[:common + 1]) if len(a) > common else f"scope:{scope}"
        target = "/".join(b[:common + 1]) if len(b) > common else f"scope:{scope}"
        if source != target:
            scopes.setdefault(scope, Counter())[source, target] += edge["count"]
    return {scope: [{"source": a, "target": b, "count": n, "relation": "imports"}
                    for (a, b), n in sorted(links.items(), key=lambda item: (-item[1], item[0]))]
            for scope, links in scopes.items()}


def mermaid(tree: dict[str, dict], edges: dict[str, list[dict]]) -> str:
    children = (tree[""]["children"] + tree[""]["direct"])[:PAGE_SIZE - 1]
    ids = {path: f"n{index + 1}" for index, path in enumerate(children)}
    lines = ["flowchart LR", f'    n0["Repository ({tree[""]["count"]} files)"]']
    for path in children:
        label = re.sub(r"[^\w ./()-]", " ", path)[:60].replace('"', " ")
        count = tree[path]["count"] if path in tree else 1
        lines.append(f'    {ids[path]}["{label} ({count} files)"]')
        lines.append(f'    n0 -.-> {ids[path]}')
    for edge in edges.get("", [])[:40 - len(children)]:
        source = "n0" if edge["source"] == "scope:" else ids.get(edge["source"])
        target = "n0" if edge["target"] == "scope:" else ids.get(edge["target"])
        if source and target:
            lines.append(f'    {source} -->|{edge["count"]} imports| {target}')
    return "\n".join(lines) + "\n"


def jev_roles(names: list[str], key: str) -> dict[str, str]:
    if not names:
        return {}
    questions = {f"c{i}": {"type": "choice",
                         "instructions": f"Classify state.directories[{i}] by its likely software role from its name only.",
                         "criteria": {role: role for role in ROLES}}
                 for i in range(len(names))}
    body = json.dumps({"model": "jev-latest", "state": {"directories": names}, "questions": questions}).encode()
    request = Request("https://api.typesafe.ai/v1/systemone", data=body,
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urlopen(request, timeout=3) as response:
        payload = json.load(response)
    answers = payload.get("answers", {}) if isinstance(payload, dict) else {}
    roles = {}
    for i, name in enumerate(names):
        answer = answers.get(f"c{i}", {})
        choice = answer.get("choice") if isinstance(answer, dict) else None
        confidence = answer.get("confidence", 0) if isinstance(answer, dict) else 0
        if choice in ROLES and isinstance(confidence, (float, int)) and confidence >= .6:
            roles[name] = choice
    return roles


def typesafe_key() -> str:
    if key := os.environ.get("TYPESAFE_API_KEY"):
        return key
    try:
        with (Path.home() / ".env").open(encoding="utf-8") as stream:
            for line in stream:
                for prefix in ("TYPESAFE_API_KEY=", "export TYPESAFE_API_KEY="):
                    if line.startswith(prefix):
                        value = line[len(prefix):].strip()
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                            value = value[1:-1]
                        return value
    except OSError:
        pass
    return ""


def write_page(path: Path, data: dict) -> None:
    template = Path(__file__).resolve().parents[1] / "assets" / "diagram.html"
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    path.write_text(template.read_text(encoding="utf-8").replace("__REPO_GRAPH_DATA__", payload), encoding="utf-8")


def source_root(value: str, cache: Path, refresh: bool = False) -> Path:
    if not value.startswith("https://"):
        return Path(value).expanduser().resolve()
    url = urlsplit(value)
    if url.username or url.password or not url.hostname or url.query or url.fragment:
        raise ValueError("Use a public HTTPS repository URL without credentials or query parameters.")
    name = Path(url.path.rstrip("/")).name.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError("Invalid repository URL.")
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    dest = cache / "sources" / f"{name}-{digest}"
    if dest.exists() and not (dest / ".git").is_dir():
        raise RuntimeError("Cached clone is incomplete; remove that cache entry and retry.")
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--single-branch", value, str(dest)],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            shutil.rmtree(dest, ignore_errors=True)
            raise RuntimeError("Repository clone failed. Check the URL and git access.")
    elif refresh:
        result = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError("Could not refresh cached clone; its checkout may have changed.")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", help="local path or public HTTPS git URL")
    parser.add_argument("--output", type=Path, help="output directory (default: user cache)")
    parser.add_argument("--refresh", action="store_true", help="update a cached HTTPS clone before scanning")
    parser.add_argument("--jev", action="store_true", help="optionally classify top-level directories using TypeSafe System One")
    args = parser.parse_args()
    cache = Path.home() / ".cache" / "repo-graph"
    root = source_root(args.repo, cache, args.refresh)
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    digest = hashlib.sha256(os.fsencode(root)).hexdigest()[:12]
    output = (args.output or cache / f"{root.name}-{digest}").expanduser().resolve()
    if output == root or root in output.parents:
        parser.error("output directory must be outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    files = repo_files(root)
    if not files:
        raise RuntimeError("No readable repository files found.")
    tree = tree_index(files)
    top_names = tree[""]["children"][:16]
    role_cache = output / "jev-roles.json"
    role_key = hashlib.sha256(json.dumps(top_names).encode()).hexdigest()
    roles, jev_status, result = {}, "off", {}
    started, worker = time.monotonic(), None
    if args.jev:
        key = typesafe_key()
        if not key:
            jev_status = "unavailable: TYPESAFE_API_KEY was not found"
        else:
            try:
                cached = json.loads(role_cache.read_text(encoding="utf-8"))
                if cached.get("key") == role_key:
                    roles, jev_status = cached["roles"], "cached"
            except (OSError, ValueError, KeyError):
                pass
            if jev_status != "cached":
                jev_status = "pending"
                def classify() -> None:
                    try:
                        result["roles"] = jev_roles(top_names, key)
                    except (OSError, ValueError, KeyError) as error:
                        result["error"] = type(error).__name__
                        result["roles"] = {}
                worker = threading.Thread(target=classify, daemon=True)
                worker.start()
    dependencies, scan = extract_dependencies(root, files, tree, output / "scan-cache.json")
    if worker:
        worker.join(timeout=max(0, 3.2 - (time.monotonic() - started)))
        if not worker.is_alive():
            roles = result.get("roles", {})
            jev_status = f"unavailable: {result['error']}" if "error" in result else "used" if roles else "no confident roles"
            if "error" not in result:
                role_cache.write_text(json.dumps({"key": role_key, "roles": roles}), encoding="utf-8")
        else:
            jev_status = "timed out"
    edges = scope_edges(dependencies)
    graph = {"schema": 1, "name": root.name, "file_count": len(files), "files": files,
             "tree": tree, "dependencies": dependencies, "scope_edges": edges,
             "scan": scan, "jev": jev_status, "roles": roles}
    graph_path = output / "graph.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    view = {key: graph[key] for key in ("name", "file_count", "tree", "scope_edges", "scan", "jev", "roles")}
    for name in ("architecture.html", "graph.html"):
        write_page(output / name, view)
    diagram = mermaid(tree, edges)
    (output / "architecture.mmd").write_text(diagram, encoding="utf-8")
    (output / "architecture.md").write_text("# Repository architecture\n\n```mermaid\n" + diagram + "```\n", encoding="utf-8")
    print(f"{len(files)} files, {len(tree) - 1} directories, {len(dependencies)} local import links; "
          f"{scan['scanned']} scanned, {scan['reused']} cached, {scan['truncated']} truncated; Jev: {jev_status}")
    for label, name in (("Diagram", "architecture.html"), ("Graph", "graph.html"),
                        ("Mermaid", "architecture.mmd"), ("JSON", "graph.json")):
        print(f"{label}: {output / name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"repo-graph: {error}", file=sys.stderr)
        raise SystemExit(1) from error
