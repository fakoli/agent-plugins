---
name: credential-source-diagnostics
description: Trace why an application, CLI, service, WSL process, or container cannot see an expected environment-backed credential without revealing its value. Use when a token exists in a .env file but is not used, authentication differs across shells or hosts, Docker or WSL loses a variable, or an authorization failure must be separated from credential loading.
---

# Credential Source Diagnostics

Trace the exact consumer process and launch boundary. A `.env` file is inert
unless the application, shell, Compose project, service manager, or library is
configured to load it.

## Workflow

1. Name the consumer, expected variable name, launch command, host boundary,
   working directory, and configuration file that declares the credential.
   Do not assume common aliases such as `HF_TOKEN` and
   `HUGGING_FACE_HUB_TOKEN` are interchangeable for every client.
2. Inventory sources in precedence order: explicit command environment,
   parent-process environment, application dotenv loading, shell profile,
   service configuration, Compose interpolation, Compose `environment`,
   Compose `env_file`, image defaults, and application-specific credential
   stores. Treat Windows, WSL distributions, remote shells, and containers as
   distinct process environments.
3. Check presence only. Report a boolean, source class, and process boundary;
   never print, log, hash, partially reveal, or copy the credential. Avoid
   blanket environment dumps and shell tracing.
4. Inspect the real launch path. Confirm the working directory used for dotenv
   discovery, service restart/reload requirements, and whether a long-lived
   daemon inherited an older environment. Prefer a product-provided
   metadata-only render for Compose. Do not display `docker compose config` or
   equivalent resolved output when it can interpolate credential values;
   capture and redact it before inspection or use narrower field queries.
5. Separate failure classes:

   - `not_loaded`: the variable is absent from the consumer;
   - `wrong_name_or_precedence`: another source wins or the client expects a
     different name;
   - `loaded_not_forwarded`: the launcher has it but the child/container does
     not;
   - `credential_rejected`: the provider rejects the presented credential;
   - `authorization_or_license`: authentication succeeded but resource access
     is denied;
   - `network_or_client`: the failure occurs before provider authorization;
   - `unresolved`: evidence is insufficient.

6. Apply the narrowest durable fix at the owning boundary. Prefer documented
   environment references over literal values. Do not use global persistent
   setters when a scoped launch configuration is sufficient.
7. Restart only the exact long-lived consumer that must inherit the change,
   with user authorization when that restart changes active service state.
8. Re-probe presence inside the final consumer and run the smallest provider
   identity or access check that distinguishes valid authentication from
   entitlement. Redact response headers and tokens.

Return the consumer, variable name, source class, losing boundary, failure
classification, remediation location, restart requirement, and redacted
verification. Never claim "bad token" from absence alone.
