# Connector And Extension Architecture

Last updated: 2026-05-31

## Goal

Vault should accept memory from local files first, then cloud folders, then browser capture. The rule is simple: source ingestion must produce the same durable `sources -> source_pages -> source_chunks` records regardless of where the content came from.

## V1 Order

1. Local synced folders:
   - Google Drive Desktop
   - Dropbox
   - OneDrive
   - iCloud Drive
   - ordinary local folders
2. Obsidian local vaults:
   - Markdown notes
   - frontmatter
   - local attachments
3. Browser extension:
   - save current page
   - save selected text
   - save PDF URL or downloaded PDF
   - save screenshot/image later after OCR is stable
4. Cloud OAuth connectors:
   - Google Drive first
   - Dropbox second
   - OneDrive/Microsoft Graph third
   - Notion after page/database ingestion is reliable

## Local Folder Contract

The backend owns a scan endpoint:

```txt
POST /api/v1/integrations/local-folder/scan
```

It returns:

- detected integration type
- supported file paths
- supported count
- skipped count
- truncation flag

The scan endpoint does not ingest by itself. Import remains an explicit user action so a folder scan cannot accidentally populate the vault.

## Browser Extension Contract

The browser extension should not talk directly to SQLite. It sends capture requests to Vault's local authenticated API.

Minimum endpoints needed:

```txt
GET  /api/v1/extension/status
POST /api/v1/extension/capture/page
POST /api/v1/extension/capture/selection
POST /api/v1/extension/capture/file
```

Each request must include:

- local API token or extension-scoped token
- target vault ID
- optional cluster ID
- source URL
- title
- content payload or file reference
- capture timestamp

The extension cannot be advertised until core loopback auth and per-client Bridge/extension identities are finished.

## Cloud OAuth Contract

Cloud connectors are not a shortcut around ingestion. They fetch metadata/content and then call the same source creation path used by local files.

OAuth connector records need:

- provider
- account label
- token storage reference
- granted scopes
- last sync cursor
- last sync status
- created/updated timestamps

Tokens must use OS credential storage or an encrypted local token store. They must not be stored in plaintext SQLite.

## Deletion Rule

Deleting a source from Vault deletes Vault's local extracted text, pages, chunks, embeddings, snapshots, and derived artifacts. It does not delete the original cloud/local file unless the user explicitly asks for external deletion in a future connector-specific flow.

## Open Decisions

- Extension token onboarding flow.
- Whether browser capture defaults to global vault context or asks for a cluster.
- Whether synced-folder imports should support watched refresh in V1 or manual refresh only.
- OAuth token storage implementation on Windows V1.
- Conflict behavior when a cloud file changes after it has been indexed.
