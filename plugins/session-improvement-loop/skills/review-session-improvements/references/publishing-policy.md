# Publishing policy

Use the narrowest destination that safely preserves the improvement.

## Public repository

Store portable workflows, stdlib helpers, synthetic fixtures, generic examples, and sanitized documentation. Replace personal paths, hostnames, repository topology, account names, session identifiers, and reachable URLs with neutral placeholders. Public artifacts must work without the author's private environment.

## Private repository

Store personal workflow preferences, private repository coordination, real infrastructure topology, organization-specific procedures, and sanitized operational references that are not suitable for public release. A private repository is not a secret store.

## Neither repository

Never store credentials, tokens, cookies, license material, private keys, raw session logs, full transcripts, capability-bearing URLs, runtime databases, logs, caches, or unredacted evidence. Keep temporary slices and inventories outside repositories and remove them after the review when practical.

## Classification test

Before writing, ask:

1. Is the artifact useful without personal context?
2. Can every example be synthetic without reducing its value?
3. Does it reveal how to reach or operate a real system?
4. Does it reproduce any user or assistant text from a session?

Use public only when the first two answers are yes and the last two are no. Use private for legitimate personal or operational context that contains no secrets. Otherwise do not store it.
