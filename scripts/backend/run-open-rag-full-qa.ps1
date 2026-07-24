param(
  [string]$Python = ".\.venv\Scripts\python.exe",
  [string]$DatasetRoot = ".tmp\open-rag-bench\source\pdf\arxiv",
  [string]$Model = ".tmp\models\all-MiniLM-L6-v2",
  [string]$WorkDir = ".tmp\open-rag-bench\vault-index",
  [string]$RunDir = ".tmp\open-rag-bench\full-qa-v1",
  [double]$MaxEstimatedCostUsd = 15.0,
  [switch]$ApprovePaidQa,
  [int]$PilotQuestions = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $repoRoot

function Resolve-RepoPath {
  param([string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return [System.IO.Path]::GetFullPath($Path)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$datasetPath = (Resolve-Path -LiteralPath $DatasetRoot).Path
$modelPath = (Resolve-Path -LiteralPath $Model).Path
$runPath = Resolve-RepoPath -Path $RunDir
$workPath = Resolve-RepoPath -Path $WorkDir
$retrievalPath = Join-Path $runPath "retrieval-full.json"
$qaPath = Join-Path $runPath "qa-full.json"
$logPath = Join-Path $runPath "run.log"
$statePath = Join-Path $runPath "run-state.json"
$script:currentStage = "starting"
$script:currentStatus = "running"
$script:currentDetail = "Preparing benchmark"

New-Item -ItemType Directory -Path $runPath -Force | Out-Null

function Write-RunState {
  param(
    [string]$Stage,
    [string]$Status,
    [string]$Detail,
    [Nullable[int]]$ProcessId = $null
  )
  $script:currentStage = $Stage
  $script:currentStatus = $Status
  $script:currentDetail = $Detail
  $payload = [ordered]@{
    schema_version = 1
    stage = $Stage
    status = $Status
    detail = $Detail
    process_id = $ProcessId
    runner_process_id = $PID
    retrieval = $retrievalPath
    qa_report = $qaPath
    log = $logPath
    updated_at = [DateTimeOffset]::UtcNow.ToString("o")
  }
  $temporary = Join-Path $runPath (
    ".run-state.json.$PID.$([Guid]::NewGuid().ToString('N')).tmp"
  )
  try {
    $payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding utf8
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
      try {
        Move-Item -LiteralPath $temporary -Destination $statePath -Force
        return
      }
      catch {
        if ($attempt -eq 7) {
          Write-Warning "Could not publish run state after 8 attempts: $($_.Exception.Message)"
          return
        }
        Start-Sleep -Milliseconds ([Math]::Min(25 * [Math]::Pow(2, $attempt), 500))
      }
    }
  }
  finally {
    if (Test-Path -LiteralPath $temporary) {
      Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
  }
}

function ConvertTo-NativeArgument {
  param([AllowEmptyString()][string]$Argument)
  if ($Argument.Length -gt 0 -and $Argument -notmatch '[\s"]') {
    return $Argument
  }
  $builder = [System.Text.StringBuilder]::new()
  [void]$builder.Append('"')
  $backslashes = 0
  foreach ($character in $Argument.ToCharArray()) {
    if ($character -eq '\') {
      $backslashes++
      continue
    }
    if ($character -eq '"') {
      [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
      [void]$builder.Append('"')
      $backslashes = 0
      continue
    }
    if ($backslashes -gt 0) {
      [void]$builder.Append(('\' * $backslashes))
      $backslashes = 0
    }
    [void]$builder.Append($character)
  }
  if ($backslashes -gt 0) {
    [void]$builder.Append(('\' * ($backslashes * 2)))
  }
  [void]$builder.Append('"')
  return $builder.ToString()
}

function Invoke-LoggedPython {
  param([string[]]$Arguments)
  $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $pythonPath
  $startInfo.Arguments = (($Arguments | ForEach-Object {
    ConvertTo-NativeArgument -Argument $_
  }) -join " ")
  $startInfo.WorkingDirectory = $repoRoot
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true

  $process = [System.Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  if (-not $process.Start()) {
    throw "Failed to start Python process."
  }
  Write-RunState `
    -Stage $script:currentStage `
    -Status $script:currentStatus `
    -Detail $script:currentDetail `
    -ProcessId $process.Id

  $stdoutTask = $process.StandardOutput.ReadToEndAsync()
  $stderrTask = $process.StandardError.ReadToEndAsync()
  $process.WaitForExit()
  $stdout = $stdoutTask.GetAwaiter().GetResult()
  $stderr = $stderrTask.GetAwaiter().GetResult()
  $exitCode = $process.ExitCode
  $process.Dispose()

  foreach ($text in @($stdout, $stderr)) {
    if (-not [string]::IsNullOrEmpty($text)) {
      $rendered = $text.TrimEnd("`r", "`n")
      Write-Host $rendered
      $encoding = [System.Text.UTF8Encoding]::new($false)
      if (Test-Path -LiteralPath $logPath) {
        $stream = [System.IO.File]::Open(
          $logPath,
          [System.IO.FileMode]::Open,
          [System.IO.FileAccess]::Read,
          [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        )
        try {
          if ($stream.Length -ge 2) {
            $first = $stream.ReadByte()
            $second = $stream.ReadByte()
            if ($first -eq 0xFF -and $second -eq 0xFE) {
              $encoding = [System.Text.Encoding]::Unicode
            }
            elseif ($first -eq 0xFE -and $second -eq 0xFF) {
              $encoding = [System.Text.Encoding]::BigEndianUnicode
            }
          }
        }
        finally {
          $stream.Dispose()
        }
      }
      [System.IO.File]::AppendAllText(
        $logPath,
        "$rendered$([Environment]::NewLine)",
        $encoding
      )
    }
  }
  if ($exitCode -ne 0) {
    throw "Python command failed with exit code $exitCode. Full output is in $logPath"
  }
}

if ($ApprovePaidQa) {
  if ([string]::IsNullOrWhiteSpace($env:KIMI_API_KEY)) {
    throw "KIMI_API_KEY is not set in this PowerShell session."
  }
  if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    throw "OPENAI_API_KEY is not set in this PowerShell session."
  }
}
if ($MaxEstimatedCostUsd -le 0) {
  throw "MaxEstimatedCostUsd must be positive."
}
if ($PilotQuestions -lt 0) {
  throw "PilotQuestions cannot be negative."
}

$pilotArguments = @()
if ($PilotQuestions -gt 0) {
  $pilotArguments = @("--pilot-questions", [string]$PilotQuestions)
}

try {
  Write-RunState -Stage "retrieval" -Status "running" -Detail "Full 3,045-query retrieval"
  Invoke-LoggedPython -Arguments @(
    "scripts\backend\benchmark_vault_open_rag_bench.py",
    "--dataset-root", $datasetPath,
    "--dataset-revision", "63f6b052ff83508b08e242db42263ee708815c26",
    "--selection", "all",
    "--top-k", "10",
    "--model", $modelPath,
    "--embedding-batch-size", "64",
    "--work-dir", $workPath,
    "--output", $retrievalPath
  )

  Write-RunState -Stage "cost_preflight" -Status "running" -Detail "No-call QA cost projection"
  Invoke-LoggedPython -Arguments (@(
    "scripts\backend\evaluate_vault_open_rag_bench_api.py",
    "--retrieval", $retrievalPath,
    "--dataset-root", $datasetPath,
    "--output", $qaPath,
    "--max-context-chars", "24000",
    "--max-answer-tokens", "192",
    "--reader-provider", "kimi",
    "--reader-model", "kimi-k2.6",
    "--primary-judge-provider", "kimi",
    "--primary-judge-model", "kimi-k2.6",
    "--independent-judge-provider", "openai",
    "--independent-judge-model", "gpt-5.4-2026-03-05",
    "--estimate-only"
  ) + $pilotArguments)

  if (-not $ApprovePaidQa) {
    Write-RunState `
      -Stage "awaiting_paid_qa_approval" `
      -Status "paused" `
      -Detail (
        "Offline retrieval and no-call cost estimate complete. " +
        "Review retrieval-full.json and qa-full.cost-estimate.json, then rerun " +
        "with -ApprovePaidQa to authorize paid reader and judge calls."
      )
    Write-Host ""
    Write-Host "PAUSED BEFORE PAID QA"
    Write-Host "Offline retrieval: $retrievalPath"
    Write-Host "Cost estimate:     $(Join-Path $runPath 'qa-full.cost-estimate.json')"
    Write-Host (
      "To authorize paid QA, rerun this command with -ApprovePaidQa. " +
      "The completed retrieval checkpoint will be reused."
    )
    return
  }

  Write-RunState -Stage "qa" -Status "running" -Detail "Reader and dual judges"
  Invoke-LoggedPython -Arguments (@(
    "scripts\backend\evaluate_vault_open_rag_bench_api.py",
    "--retrieval", $retrievalPath,
    "--dataset-root", $datasetPath,
    "--output", $qaPath,
    "--max-context-chars", "24000",
    "--max-answer-tokens", "192",
    "--reader-provider", "kimi",
    "--reader-model", "kimi-k2.6",
    "--primary-judge-provider", "kimi",
    "--primary-judge-model", "kimi-k2.6",
    "--independent-judge-provider", "openai",
    "--independent-judge-model", "gpt-5.4-2026-03-05",
    "--max-estimated-cost-usd", ([string]::Format(
      [System.Globalization.CultureInfo]::InvariantCulture,
      "{0:F2}",
      $MaxEstimatedCostUsd
    ))
  ) + $pilotArguments)

  if ($PilotQuestions -gt 0) {
    Write-RunState `
      -Stage "pilot_complete" `
      -Status "paused" `
      -Detail (
        "Paid $PilotQuestions-question pilot complete. Review qa-full.json before " +
        "authorizing the remaining questions."
      )
  }
  else {
    Write-RunState -Stage "complete" -Status "complete" -Detail "Full QA report written"
  }
}
catch {
  Write-RunState -Stage "failed" -Status "failed" -Detail $_.Exception.Message
  throw
}
