$ErrorActionPreference = "Stop"

$python = if ($env:CML_PYTHON) { $env:CML_PYTHON } else { "python" }
& $python -m backend.app.odin_cli @args
exit $LASTEXITCODE
