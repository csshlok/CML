# Threat Model

This document captures the local security posture for the CML product.

- Bridge/MCP capture flows must stay local-first and validate extension tokens before any source ingestion.
- Vault lock, startup audit, and embedding policy checks are expected to run before user-owned data is exposed.
- Every release must verify the packaged runtime, local OCR, and model-loading paths with explicit smoke tests.
