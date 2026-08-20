# Agent instructions

- Treat every tracked file as public.
- Never copy raw session text, credentials, private paths, hostnames, account identifiers, capability-bearing URLs, or infrastructure topology into this repository.
- Prefer improving an existing artifact over creating a near-duplicate.
- New skills must be initialized and validated with the installed `skill-creator` workflow.
- New plugins and marketplace entries must use the installed `plugin-creator` workflow.
- Keep runtime code dependency-free unless a dependency has a documented, compelling benefit.
- Use synthetic fixtures for session parsers and privacy tests.
- Before committing, run relevant tests, skill validation, plugin validation, secret scanning when available, and `git diff --check`.
- Scheduled reviews may create branches and draft pull requests when explicitly authorized, but must never merge automatically.
