from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "session-improvement-loop"
    / "skills"
    / "review-session-improvements"
    / "scripts"
    / "scan_recent_sessions.py"
)


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class ScanRecentSessionsTests(unittest.TestCase):
    def run_script(self, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_inventory_ranks_failure_and_correction_without_message_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "completed.jsonl"
            write_rows(
                session,
                [
                    {"type": "event_msg", "payload": {"type": "task_started"}},
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Start the work"},
                    },
                    {
                        "type": "response_item",
                        "payload": {"type": "custom_tool_call", "call_id": "c1", "name": "shell"},
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "custom_tool_call_output",
                            "call_id": "c1",
                            "output": "Exit code: 2",
                        },
                    },
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "No, preserve the file instead"},
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 100,
                                    "cached_input_tokens": 50,
                                    "cache_write_input_tokens": 0,
                                    "output_tokens": 25,
                                    "reasoning_output_tokens": 10,
                                    "total_tokens": 185,
                                }
                            },
                        },
                    },
                    {"type": "event_msg", "payload": {"type": "task_complete"}},
                ],
            )

            result = self.run_script("inventory", "--root", str(root), "--since-hours", "1")

            self.assertEqual(result["session_count"], 1)
            item = result["sessions"][0]
            self.assertEqual(item["status"], "completed")
            self.assertEqual(item["tool_failure_count"], 1)
            self.assertEqual(item["human_turn_count"], 2)
            self.assertEqual(item["token_totals"]["output_tokens"], 25)
            self.assertNotIn("preserve the file", json.dumps(item))
            self.assertEqual(
                {signal["kind"] for signal in item["signals"]},
                {"tool_failure", "human_correction_candidate"},
            )

    def test_active_sessions_are_excluded_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_rows(root / "active.jsonl", [{"type": "event_msg", "payload": {"type": "task_started"}}])

            default = self.run_script("inventory", "--root", str(root), "--since-hours", "1")
            included = self.run_script(
                "inventory", "--root", str(root), "--since-hours", "1", "--include-active"
            )

            self.assertEqual(default["session_count"], 0)
            self.assertEqual(default["active_sessions_excluded"], 1)
            self.assertEqual(included["sessions"][0]["status"], "active")

    def test_slice_redacts_secrets_paths_and_urls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session.jsonl"
            write_rows(
                session,
                [
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": (
                                "Use token=secret-value from C:\\Users\\alice\\.env "
                                "at https://private.example.test/path"
                            ),
                        },
                    }
                ],
            )

            result = self.run_script("slice", "--session", str(session), "--line", "1", "--radius", "0")
            text = result["rows"][0]["text"]

            self.assertIn("token=[REDACTED]", text)
            self.assertIn("%USERPROFILE%", text)
            self.assertIn("<url>", text)
            self.assertNotIn("secret-value", text)
            self.assertNotIn("alice", text)


if __name__ == "__main__":
    unittest.main()
