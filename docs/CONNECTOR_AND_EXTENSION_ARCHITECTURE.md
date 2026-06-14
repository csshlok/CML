# Connector And Extension Architecture

Last updated: 2026-06-14

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
   - save PDF URL or a downloaded local file through popup upload
   - save screenshot/image through visible-tab capture plus local upload
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
The local API auth layer intentionally leaves the public extension contract callable without the desktop API token; the extension endpoints are instead guarded by the extension-scoped token itself.
The intended user surface is the browser action popup, not a standalone extension page workflow.

Minimum endpoints used by the current V1 package:

```txt
GET  /api/v1/extension/status
POST /api/v1/extension/capture
POST /api/v1/extension/capture-upload
```

Each request must include:

- extension-scoped token
- target vault ID
- optional cluster ID
- source URL
- title
- `capture_type` such as `page` or `selection`
- text payload
- capture timestamp

Current package path:

- `apps/browser-extension`

Current packaging script:

- `scripts/extension/package-browser-extension.ps1`

The extension now has a real local package and setup flow, but it should still stay conservative in public claims until live browser smoke and richer capture modes are verified.

Current shipped capture modes:

- current page text
- selected text
- PDF URL capture for tabs whose URL ends in `.pdf`
- downloaded local file upload through the popup file picker
- visible-tab screenshot upload

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
