# External procedure intake record

Use this compact record before execution.

```yaml
source:
  url: "https://example.test/procedure"
  revision_or_hash: "<exact revision or hash>"
  observed_at: "YYYY-MM-DD"
  published_or_modified_at: "YYYY-MM-DD or unknown"
  evidence_class: "official | repository | issue | community | benchmark"
current_system:
  repository_revision: "<revision>"
  runtime_versions: []
  hardware: []
comparison:
  - source_step: "<literal step identifier>"
    disposition: "exact | adapt | replace | reject | unresolved"
    local_action: "<reviewable action>"
    reason: "<evidence-backed reason>"
gates:
  storage: "pass | fail | unresolved"
  credentials: "pass | fail | unresolved"
  authorization: "pass | fail | unresolved"
  capacity: "pass | fail | unresolved"
  conflicts: "pass | fail | unresolved"
  rollback: "pass | fail | unresolved"
result:
  status: "not_run | passed | failed | blocked"
  restored: false
  evidence: []
```

Do not store literal credentials, private endpoints, personal paths, or raw
unsanitized logs in this record.
