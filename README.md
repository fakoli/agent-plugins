# Fakoli Agent Plugins

Public, portable Codex plugins and skills derived from repeated agent-workflow evidence.

Every contribution must be useful without private environment context, use synthetic or sanitized examples, and pass the relevant skill and plugin validators. Raw sessions, personal paths, infrastructure topology, reachable endpoints, and credentials do not belong here.

## Marketplace

The Codex marketplace manifest is `.agents/plugins/marketplace.json`; plugin sources live under `plugins/`.

Install the local checkout as a marketplace, then install a plugin:

```powershell
codex plugin marketplace add C:\path\to\agent-plugins
codex plugin add session-improvement-loop@fakoli-agent-plugins
```

## Plugins

| Plugin | Purpose |
|---|---|
| `session-improvement-loop` | Convert recurring session friction into validated reusable improvements. |
| `host-operations` | Diagnose Windows GPU ownership and environment credential loading safely. |
| `workflow-intake` | Pin and adapt external procedures before executing them locally. |
| `workspace-coordination` | Coordinate related repositories, worktrees, and ownership boundaries. |

Install any catalog entry with
`codex plugin add <plugin-name>@fakoli-agent-plugins`.
