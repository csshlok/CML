# CML Browser Extension

This is a static Manifest V3 browser extension popup package for saving:

- the current page
- selected text
- a downloaded local file chosen in the popup
- a visible-tab screenshot
- a PDF link from the active tab

into a local CML vault through the local `/api/v1/extension/*` API.

## Setup

1. Open the CML desktop app.
2. Go to `Bridge`.
3. Create or approve an extension client.
4. Click `Copy extension setup JSON`.
5. Load this folder as an unpacked extension in Chromium-based browsers.
6. Click the browser action so the real extension popup opens, then paste the copied JSON into `Import setup JSON`.

The popup stores:

- backend URL
- extension token
- default vault ID
- optional cluster ID

in browser local extension storage.

## Packaging

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/extension/package-browser-extension.ps1
```

That produces a zip archive under `.tmp/browser-extension-dist/`.

## Current capabilities

- Runs as a browser action popup, not as a standalone app page in normal use.
- Save current page text through readability-style `document.body.innerText` capture.
- Save currently selected text from the active tab.
- Save the current tab as a PDF URL capture when the tab URL points to a `.pdf`.
- Save a downloaded local file through the popup file picker and local extension upload endpoint.
- Save a visible-tab screenshot through Chromium's capture API and the local extension upload endpoint.
- Validate extension token connectivity against the local CML backend.
- Persist local backend/token/vault/cluster config in extension storage.

## Current limits

- Real browser smoke against Chromium is still separate from the static package and helper tests.
