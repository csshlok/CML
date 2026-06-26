param(
  [string]$WorkDir = "T:\cml-lora-sample-vault-1p5b-full105",
  [int]$RefreshSeconds = 5
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

& powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\backend\monitor-lora-training.ps1" `
  -WorkDir $WorkDir `
  -RefreshSeconds $RefreshSeconds

