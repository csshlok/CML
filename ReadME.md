# CML

Context Management Layer is a local-first desktop AI workspace. It turns a user's local vault of files, links, screenshots, notes, and chat transcripts into context clusters, trains a local expert for each cluster, and uses those experts to feed focused context into a larger synthesis model.

## Current Status

Stage 1 has started. The repo now has:

- `docs/` for PRDs and project context.
- `UI-CML-V0/` as the preserved V0 UI reference.
- `apps/desktop/` as the real desktop app workspace.
- `backend/` for the local Python service.

## Development

Install frontend dependencies:

```bash
npm install
```

Run the desktop app in development mode:

```bash
npm run dev
```

Run the backend service:

```bash
npm run backend
```

The desktop app is Electron-based for the first build because Node is available in the current environment and Rust is not installed. Tauri can be reconsidered later if installer size becomes more important than setup speed.

## Docs

- `docs/PRODUCT_PRD.md`
- `docs/UI_PRD.md`
- `docs/PROJECT_CONTEXT.md`
