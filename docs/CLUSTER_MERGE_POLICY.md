# Cluster Merge Policy

Every cluster merge must write a merge artifact so that the operation is auditable, reversible, and safe for local vault data.

- Merges must preserve source ownership, chat session scope, and user-facing metadata.
- Rollback must restore the previous cluster assignment and retain the merge artifact for inspection.
- Merge operations must be blocked when the vault is locked or the source set is incomplete.
