# Vault Figma Export Workflow

Repository: https://github.com/csshlok/CML

This repo includes a dev-only workflow for copying the current onboarding screen from the running web app into Figma as editable layers. It does not use Figma MCP.

## What It Uses

- App route: `apps/desktop/src/routes/onboarding.tsx`
- Export helper: `apps/desktop/src/lib/figmaExport.ts`
- Converter package: `@figit/dom-to-figma`

## Install

From the repo root:

```powershell
npm install
```

## Run The Web Preview

From the repo root:

```powershell
npm run dev:web
```

Open:

```text
http://127.0.0.1:5173/onboarding
```

## Copy The Current Screen To Figma

1. Open the onboarding page in the browser.
2. Use the `Copy to Figma` button in the onboarding card header.
3. Switch to Figma.
4. Paste into the canvas with `Ctrl+V`.

The button is dev-only and is intended for browser preview use, not the packaged desktop app.

## Notes

- The export copies the currently rendered onboarding screen, including the sidebar.
- Text should remain editable in Figma.
- Some cleanup in Figma may still be needed for fonts, spacing, or image handling.
- If clipboard export fails, confirm the page is opened in a browser context that allows `navigator.clipboard.write`.

## Recommended Workflow For Collaboration

1. Pull the latest `main`.
2. Run `npm install`.
3. Run `npm run dev:web`.
4. Navigate to the onboarding step you want to export.
5. Click `Copy to Figma`.
6. Paste into Figma and continue editing there.
