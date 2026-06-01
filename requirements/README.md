# Contributor Requirements

Use these files to reproduce the current contributor state.

- `contributors-backend.txt` installs the backend/test dependencies used by the current app workspace.
- `contributors-lora-trainer.txt` is for a separate Python 3.11/3.12 LoRA trainer environment used by `CML_LORA_TRAINER_COMMAND`.

Continuous-update rule:

- Any PR or agent task that adds, removes, or changes Python imports, trainer packages, OCR packages, or test dependencies must update the matching file in this directory.
- After changing dependencies, run `.\scripts\dev\update-requirements.ps1` or manually update these pinned files if the active environment is intentionally split.
- Record dependency caveats in `docs/PROJECT_CONTEXT.md` when the active `.venv` cannot satisfy all optional trainer constraints.

Suggested setup:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements\contributors-backend.txt
npm install
```

For real LoRA training smoke, use a separate ML environment:

```powershell
py -3.11 -m venv .venv-lora
.\.venv-lora\Scripts\python -m pip install -r requirements\contributors-lora-trainer.txt
$env:CML_LORA_TRAINER_COMMAND = ".\.venv-lora\Scripts\llamafactory-cli.exe train --config {config_path}"
```
