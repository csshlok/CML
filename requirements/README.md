# Contributor Requirements

Use these files to reproduce the current contributor state.

- `contributors-backend.txt` installs the backend/test dependencies used by the current app workspace.

Continuous-update rule:

- Any change that adds, removes, or changes Python imports, OCR packages, or test dependencies must update the backend requirements file.
- After changing dependencies, run `.\scripts\dev\update-requirements.ps1` or manually update these pinned files if the active environment is intentionally split.
- Record dependency caveats in `docs/PROJECT_CONTEXT.md` when the active `.venv` cannot reproduce the supported backend.

Suggested setup:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements\contributors-backend.txt
npm install
```
