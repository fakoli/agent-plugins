from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "plugins/repo-graph/scripts/build_repo_graph.py"
SPEC = importlib.util.spec_from_file_location("build_repo_graph", SCRIPT)
assert SPEC and SPEC.loader
repo_graph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repo_graph)


class RepoGraphTests(unittest.TestCase):
    def test_large_diagram_is_bounded_and_escapes_labels(self) -> None:
        nodes = [{"id": f"n{i}", "source_file": f"packages/part{i}/file.py",
                  "file_type": "code"} for i in range(60)]
        nodes[0]["source_file"] = 'packages/evil\"]; click n0 "https://bad.example"/file.py'
        edges = [{"source": f"n{i}", "target": f"n{i+1}", "relation": "calls"}
                 for i in range(59)]
        source = repo_graph.mermaid({"nodes": nodes, "links": edges})

        self.assertLessEqual(source.count('["'), repo_graph.MAX_GROUPS)
        self.assertLessEqual(source.count(" -->"), repo_graph.MAX_EDGES)
        self.assertNotIn("click n0", source)
        self.assertIn("Other directories", source)
        overview = repo_graph.overview_graph(source)
        self.assertLessEqual(len(overview["nodes"]), repo_graph.MAX_GROUPS)
        self.assertLessEqual(len(overview["edges"]), repo_graph.MAX_EDGES)

    def test_inventory_uses_names_and_containment_without_hidden_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("private content", encoding="utf-8")
            (root / "docs" / "second.md").write_text("more content", encoding="utf-8")
            (root / ".env").write_text("secret", encoding="utf-8")
            graph = repo_graph.inventory_graph(root, root / "graph.json")

        self.assertEqual({node["source_file"] for node in graph["nodes"]},
                         {"docs", "docs/guide.md", "docs/second.md"})
        self.assertEqual(graph["edges"][0]["relation"], "contains")
        self.assertNotIn("private content", str(graph))


if __name__ == "__main__":
    unittest.main()
