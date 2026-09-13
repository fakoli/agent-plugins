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
| `session-improvement-loop` | Research uncertain decisions, evaluate scoped skill changes, and turn session friction into validated improvements. |
| `host-operations` | Diagnose Windows GPU ownership and environment credential loading safely. |
| `workflow-intake` | Pin and adapt external procedures before executing them locally. |
| `workspace-coordination` | Coordinate related repositories, worktrees, and ownership boundaries. |

Install any catalog entry with
`codex plugin add <plugin-name>@fakoli-agent-plugins`.

## Research and improvement

The `session-improvement-loop` plugin provides three entrypoints:

- `$research-synthesis`: independent evidence gathering and one synthesis for
  a material unresolved decision, with native host agents and a shared budget.
- `$skill-improvement`: one evidence-backed instruction proposal, frozen
  versions, independent checks, and scoped adoption or rejection.
- `$review-session-improvements`: bounded session inventory and evidence
  selection, followed by the shared methods when useful.

These skills work without Anvil Serving. The caller supplies the actual task,
ranked objectives, tools, evidence location, success checks, authorized changes,
and stop budget. Project-specific skills retain operational commands and gates.
Astra-specific guidance is loaded only when relevant; the plugin preserves the
host's configured model roles. No daemon, hooks, or model runtime is added.

Start a new task after installation to refresh native discovery. Resources
resolve relative to the installed skill; no checkout or fixed cache path is
required. A host without delegation can complete lead-only research, labeled
as reduced coverage rather than a three-answer panel. Independent evaluation
still requires a separate reviewer or executable acceptance evidence.
