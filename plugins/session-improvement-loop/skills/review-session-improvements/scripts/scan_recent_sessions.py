#!/usr/bin/env python3
"""Inventory recent agent sessions without copying full transcripts."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
CORRECTION_PATTERNS = {
    "negation": re.compile(r"\b(?:no|not|don't|do not|never|stop)\b", re.IGNORECASE),
    "replacement": re.compile(r"\b(?:instead|rather than|replace|preserve)\b", re.IGNORECASE),
    "error": re.compile(r"\b(?:wrong|incorrect|mistake|failed|failure|broken)\b", re.IGNORECASE),
    "directive": re.compile(r"\b(?:you should|you need to|must|why did)\b", re.IGNORECASE),
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,\"'}]+"),
    re.compile(
        r"(?i)([\"']?(?:api[_-]?key|token|secret|password|cookie)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'}]+"
    ),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])[-_A-Za-z0-9]{12,}\b", re.IGNORECASE),
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
WINDOWS_HOME_PATTERN = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
UNIX_HOME_PATTERN = re.compile(r"/(?:Users|home)/[^/\s]+")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def default_roots() -> list[Path]:
    home = Path.home()
    return [home / ".codex" / "sessions", home / ".claude" / "projects"]


def write_json(data: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output:
        Path(output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def message_text(payload: dict[str, Any]) -> str:
    direct = payload.get("message")
    if isinstance(direct, str):
        return direct
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("input_text") or item.get("output_text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def correction_matches(text: str) -> list[str]:
    return [name for name, pattern in CORRECTION_PATTERNS.items() if pattern.search(text)]


def output_failed(output: Any) -> bool:
    if isinstance(output, dict):
        if output.get("isError") is True or output.get("is_error") is True:
            return True
        for key in ("exit_code", "exitCode", "status_code", "statusCode"):
            value = output.get(key)
            if isinstance(value, int) and value != 0:
                return True
    text = as_text(output)
    if re.search(r"(?im)^\s*Exit code:\s*[1-9]\d*\s*$", text):
        return True
    if re.search(r'(?i)"isError"\s*:\s*true|"is_error"\s*:\s*true', text):
        return True
    if "Traceback (most recent call last):" in text:
        return True
    return False


def token_totals(payload: dict[str, Any]) -> dict[str, int]:
    info = as_dict(payload.get("info"))
    totals = as_dict(info.get("total_token_usage"))
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    return {field: int(totals.get(field, 0) or 0) for field in fields}


def session_source(path: Path) -> str:
    lowered = {part.lower() for part in path.parts}
    if ".codex" in lowered:
        return "codex"
    if ".claude" in lowered:
        return "claude"
    return "unknown"


def scan_session(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path.resolve()),
        "source": session_source(path),
        "size_bytes": path.stat().st_size,
        "modified_at": iso_utc(dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)),
        "line_count": 0,
        "parse_error_count": 0,
        "session_id": None,
        "started_at": None,
        "cwd": None,
        "model": None,
        "reasoning_effort": None,
        "human_turn_count": 0,
        "assistant_message_count": 0,
        "tool_call_count": 0,
        "tool_output_count": 0,
        "tool_failure_count": 0,
        "task_started_count": 0,
        "task_complete_count": 0,
        "web_search_count": 0,
        "token_totals": {},
        "signals": [],
        "tool_counts": {},
    }
    call_names: dict[str, str] = {}
    tool_counts: collections.Counter[str] = collections.Counter()
    response_user_count = 0
    event_user_count = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            result["line_count"] = line_number
            try:
                row = json.loads(raw_line)
            except (json.JSONDecodeError, TypeError):
                result["parse_error_count"] += 1
                continue
            if not isinstance(row, dict):
                continue
            row_type = row.get("type")
            payload = as_dict(row.get("payload"))
            payload_type = payload.get("type")

            if row_type == "session_meta":
                result["session_id"] = payload.get("id") or payload.get("session_id")
                result["started_at"] = row.get("timestamp") or payload.get("timestamp")
                result["cwd"] = payload.get("cwd") or result["cwd"]
            elif row_type == "turn_context":
                result["cwd"] = payload.get("cwd") or result["cwd"]
                result["model"] = payload.get("model") or result["model"]
                result["reasoning_effort"] = payload.get("effort") or result["reasoning_effort"]

            if row_type == "event_msg":
                if payload_type == "task_started":
                    result["task_started_count"] += 1
                elif payload_type == "task_complete":
                    result["task_complete_count"] += 1
                elif payload_type == "user_message":
                    event_user_count += 1
                    result["human_turn_count"] = event_user_count
                    text = message_text(payload)
                    matches = correction_matches(text) if event_user_count > 1 else []
                    if matches:
                        result["signals"].append(
                            {
                                "kind": "human_correction_candidate",
                                "line": line_number,
                                "matched": matches,
                                "char_count": len(text),
                            }
                        )
                elif payload_type == "agent_message":
                    result["assistant_message_count"] += 1
                elif payload_type == "token_count" and payload.get("info"):
                    result["token_totals"] = token_totals(payload)
                elif payload_type == "web_search_end":
                    result["web_search_count"] += 1

            if row_type == "response_item":
                if payload_type == "message" and payload.get("role") == "user":
                    response_user_count += 1
                elif payload_type == "custom_tool_call":
                    name = str(payload.get("name") or "unknown")
                    call_id = str(payload.get("call_id") or payload.get("id") or line_number)
                    call_names[call_id] = name
                    tool_counts[name] += 1
                    result["tool_call_count"] += 1
                elif payload_type == "custom_tool_call_output":
                    result["tool_output_count"] += 1
                    output = payload.get("output")
                    if output_failed(output):
                        result["tool_failure_count"] += 1
                        call_id = str(payload.get("call_id") or "")
                        result["signals"].append(
                            {
                                "kind": "tool_failure",
                                "line": line_number,
                                "tool": call_names.get(call_id, "unknown"),
                            }
                        )

    if event_user_count == 0:
        result["human_turn_count"] = response_user_count
    result["tool_counts"] = dict(sorted(tool_counts.items(), key=lambda item: (-item[1], item[0])))
    result["status"] = (
        "active" if result["task_started_count"] > result["task_complete_count"] else "completed"
    )
    correction_count = sum(
        1 for signal in result["signals"] if signal["kind"] == "human_correction_candidate"
    )
    repeated_tool_calls = sum(max(0, count - 3) for count in tool_counts.values())
    output_tokens = int(as_dict(result["token_totals"]).get("output_tokens", 0) or 0)
    result["priority_score"] = (
        correction_count * 5
        + result["tool_failure_count"] * 4
        + repeated_tool_calls
        + min(10, output_tokens // 10_000)
    )
    return result


def session_files(roots: Iterable[Path], cutoff: dt.datetime) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            modified = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
            if modified >= cutoff:
                seen.add(resolved)
                yield path


def inventory_command(args: argparse.Namespace) -> int:
    generated_at = utc_now()
    cutoff = generated_at - dt.timedelta(hours=args.since_hours)
    roots = [Path(value).expanduser() for value in args.root] if args.root else default_roots()
    sessions = [scan_session(path) for path in session_files(roots, cutoff)]
    excluded_active = sum(1 for item in sessions if item["status"] == "active")
    if not args.include_active:
        sessions = [item for item in sessions if item["status"] != "active"]
    sessions.sort(key=lambda item: (item["priority_score"], item["modified_at"]), reverse=True)
    sessions = sessions[: args.max_sessions]
    write_json(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": iso_utc(generated_at),
            "cutoff": iso_utc(cutoff),
            "roots_checked": [str(root.resolve()) for root in roots if root.exists()],
            "active_sessions_excluded": excluded_active if not args.include_active else 0,
            "session_count": len(sessions),
            "sessions": sessions,
        },
        args.output,
    )
    return 0


def redact_text(text: str) -> str:
    redacted = WINDOWS_HOME_PATTERN.sub("%USERPROFILE%", text)
    redacted = UNIX_HOME_PATTERN.sub("$HOME", redacted)
    redacted = URL_PATTERN.sub("<url>", redacted)
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def slice_row(row: dict[str, Any], line_number: int, max_chars: int) -> dict[str, Any]:
    payload = as_dict(row.get("payload"))
    payload_type = payload.get("type")
    row_type = row.get("type")
    role = payload.get("role")
    tool = None
    text = ""
    if row_type == "event_msg" and payload_type in {"user_message", "agent_message", "agent_reasoning"}:
        text = message_text(payload) or as_text(payload.get("text"))
        role = {
            "user_message": "user",
            "agent_message": "assistant",
            "agent_reasoning": "assistant_reasoning",
        }[str(payload_type)]
    elif row_type == "response_item" and payload_type == "message":
        text = message_text(payload)
    elif row_type == "response_item" and payload_type == "custom_tool_call":
        tool = payload.get("name")
        text = as_text(payload.get("input"))
        role = "tool_call"
    elif row_type == "response_item" and payload_type == "custom_tool_call_output":
        text = as_text(payload.get("output"))
        role = "tool_output"
    cleaned = redact_text(text)
    truncated = len(cleaned) > max_chars
    if truncated:
        cleaned = cleaned[:max_chars] + "…"
    return {
        "line": line_number,
        "timestamp": row.get("timestamp"),
        "row_type": row_type,
        "payload_type": payload_type,
        "role": role,
        "tool": tool,
        "text": cleaned,
        "truncated": truncated,
    }


def slice_command(args: argparse.Namespace) -> int:
    path = Path(args.session).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"session file not found: {path}")
    selected: set[int] = set()
    for line_number in args.line:
        selected.update(range(max(1, line_number - args.radius), line_number + args.radius + 1))
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if line_number not in selected:
                continue
            try:
                row = json.loads(raw_line)
            except (json.JSONDecodeError, TypeError):
                rows.append({"line": line_number, "parse_error": True})
                continue
            if isinstance(row, dict):
                rows.append(slice_row(row, line_number, args.max_chars))
    write_json(
        {
            "schema_version": SCHEMA_VERSION,
            "session": str(path),
            "requested_lines": sorted(set(args.line)),
            "radius": args.radius,
            "rows": rows,
        },
        args.output,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="rank recent sessions using metadata and signal counts")
    inventory.add_argument("--root", action="append", help="session root; repeat for multiple roots")
    inventory.add_argument("--since-hours", type=float, default=24.0)
    inventory.add_argument("--include-active", action="store_true")
    inventory.add_argument("--max-sessions", type=int, default=50)
    inventory.add_argument("--output")
    inventory.set_defaults(func=inventory_command)

    slice_parser = subparsers.add_parser("slice", help="render small redacted windows around signal lines")
    slice_parser.add_argument("--session", required=True)
    slice_parser.add_argument("--line", action="append", required=True, type=int)
    slice_parser.add_argument("--radius", type=int, default=2)
    slice_parser.add_argument("--max-chars", type=int, default=2_000)
    slice_parser.add_argument("--output")
    slice_parser.set_defaults(func=slice_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "since_hours", 1) <= 0:
        raise SystemExit("--since-hours must be positive")
    if getattr(args, "max_sessions", 1) <= 0:
        raise SystemExit("--max-sessions must be positive")
    if getattr(args, "radius", 0) < 0:
        raise SystemExit("--radius cannot be negative")
    if getattr(args, "max_chars", 1) <= 0:
        raise SystemExit("--max-chars must be positive")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
