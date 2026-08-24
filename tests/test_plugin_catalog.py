from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"


class PluginCatalogTests(unittest.TestCase):
    def test_marketplace_entries_resolve_to_matching_plugins(self) -> None:
        catalog = json.loads(MARKETPLACE.read_text(encoding="utf-8"))

        for entry in catalog["plugins"]:
            plugin = ROOT / entry["source"]["path"].removeprefix("./")
            manifest_path = plugin / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["name"], entry["name"])
            self.assertEqual(entry["source"]["source"], "local")
            self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
            self.assertTrue((plugin / "skills").is_dir())

    def test_skills_have_complete_frontmatter_and_ui_prompts(self) -> None:
        plugin_names = {"host-operations", "workflow-intake", "workspace-coordination"}
        skills = (
            skill
            for plugin_name in plugin_names
            for skill in (ROOT / "plugins" / plugin_name / "skills").iterdir()
            if skill.is_dir()
        )

        for skill in skills:
            skill_text = (skill / "SKILL.md").read_text(encoding="utf-8")
            ui_text = (skill / "agents" / "openai.yaml").read_text(encoding="utf-8")

            self.assertTrue(skill_text.startswith("---\n"), skill)
            self.assertNotIn("[TODO:", skill_text, skill)
            self.assertIn(f"name: {skill.name}", skill_text, skill)
            self.assertIn(f"${skill.name}", ui_text, skill)

    def test_operational_skills_keep_adversarial_safety_gates(self) -> None:
        skills = ROOT / "plugins"
        gpu = (
            skills
            / "host-operations"
            / "skills"
            / "windows-gpu-lane-hygiene"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        credential = (
            skills
            / "host-operations"
            / "skills"
            / "credential-source-diagnostics"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        intake = (
            skills
            / "workflow-intake"
            / "skills"
            / "external-procedure-intake"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        workspace = (
            skills
            / "workspace-coordination"
            / "skills"
            / "multi-repository-workspace-coordination"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("explicit human gate", gpu)
        self.assertIn("Do not display `docker compose config`", credential)
        self.assertIn("never print, log, hash, partially reveal", credential)
        self.assertIn("exact commit/revision or content hash", intake)
        self.assertIn("Stop for a human gate", intake)
        self.assertIn("failure rather than treating cached remote state as current", workspace)
        self.assertIn("Do not reset, checkout,", workspace)


if __name__ == "__main__":
    unittest.main()
