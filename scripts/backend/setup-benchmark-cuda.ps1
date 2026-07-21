param(
  [string]$TorchVersion = "2.12.0",
  [string]$CudaIndex = "https://download.pytorch.org/whl/cu130"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$python = (Resolve-Path -LiteralPath (Join-Path $repoRoot ".venv\Scripts\python.exe")).Path
$check = (Resolve-Path -LiteralPath (Join-Path $repoRoot "scripts\backend\check_cuda_runtime.py")).Path

& $python -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)"
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing the official CUDA-enabled PyTorch wheel into .venv..."
  & $python -m pip install --upgrade --force-reinstall "torch==$TorchVersion" --index-url $CudaIndex
  if ($LASTEXITCODE -ne 0) {
    throw "CUDA PyTorch installation failed."
  }
}

& $python $check
if ($LASTEXITCODE -ne 0) {
  throw "CUDA runtime verification failed."
}
