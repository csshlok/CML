param(
  [string]$RunDir = ".tmp\open-rag-bench\full-qa-v1",
  [switch]$Watch,
  [int]$IntervalSeconds = 15
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
if ([System.IO.Path]::IsPathRooted($RunDir)) {
  $runPath = [System.IO.Path]::GetFullPath($RunDir)
}
else {
  $runPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $RunDir))
}
$statePath = Join-Path $runPath "run-state.json"
$progressPath = Join-Path $runPath "qa-full.progress.json"
$retrievalProgressPath = Join-Path $runPath "retrieval-full.progress.json"
$retrievalReportPath = Join-Path $runPath "retrieval-full.json"
$costEstimatePath = Join-Path $runPath "qa-full.cost-estimate.json"
$qaReportPath = Join-Path $runPath "qa-full.json"
$logPath = Join-Path $runPath "run.log"

function Get-SharedText {
  param(
    [string]$Path,
    [long]$TailBytes = 0
  )
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
  $stream = [System.IO.File]::Open(
    $Path,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    $share
  )
  try {
    $encoding = [System.Text.UTF8Encoding]::new($false)
    if ($stream.Length -ge 2) {
      $first = $stream.ReadByte()
      $second = $stream.ReadByte()
      if ($first -eq 0xFF -and $second -eq 0xFE) {
        $encoding = [System.Text.Encoding]::Unicode
      }
      elseif ($first -eq 0xFE -and $second -eq 0xFF) {
        $encoding = [System.Text.Encoding]::BigEndianUnicode
      }
      elseif ($stream.Length -ge 3) {
        $third = $stream.ReadByte()
        if ($first -eq 0xEF -and $second -eq 0xBB -and $third -eq 0xBF) {
          $encoding = [System.Text.UTF8Encoding]::new($true)
        }
      }
    }
    if ($TailBytes -gt 0 -and $stream.Length -gt $TailBytes) {
      $offset = $stream.Length - $TailBytes
      if (
        $encoding -eq [System.Text.Encoding]::Unicode -or
        $encoding -eq [System.Text.Encoding]::BigEndianUnicode
      ) {
        $offset -= $offset % 2
      }
      [void]$stream.Seek($offset, [System.IO.SeekOrigin]::Begin)
    }
    else {
      [void]$stream.Seek(0, [System.IO.SeekOrigin]::Begin)
    }
    $reader = [System.IO.StreamReader]::new(
      $stream,
      $encoding,
      $false,
      4096,
      $true
    )
    try {
      return $reader.ReadToEnd()
    }
    finally {
      $reader.Dispose()
    }
  }
  finally {
    $stream.Dispose()
  }
}

function Get-JsonIfPresent {
  param([string]$Path)
  try {
    $text = Get-SharedText -Path $Path
    if ([string]::IsNullOrWhiteSpace($text)) {
      return $null
    }
    return $text | ConvertFrom-Json
  }
  catch {
    return $null
  }
}

function Get-JsonlCount {
  param([string]$Path)
  $text = Get-SharedText -Path $Path
  if ([string]::IsNullOrEmpty($text)) {
    return 0
  }
  return [regex]::Matches($text, "`n").Count + [int](-not $text.EndsWith("`n"))
}

do {
  if ($Watch) {
    Clear-Host
  }
  $state = Get-JsonIfPresent -Path $statePath
  $progress = Get-JsonIfPresent -Path $progressPath
  $retrievalProgress = Get-JsonIfPresent -Path $retrievalProgressPath
  if ($null -eq $state) {
    Write-Host "No run state exists yet at $statePath"
  }
  else {
    Write-Host "Status: $($state.status)"
    Write-Host "Stage:  $($state.stage)"
    Write-Host "Detail: $($state.detail)"
    if (
      $null -ne $state.process_id -and
      $null -ne $state.runner_process_id
    ) {
      $benchmarkProcess = Get-Process -Id $state.process_id -ErrorAction SilentlyContinue
      $processStatus = if ($null -eq $benchmarkProcess) { "not running" } else { "running" }
      Write-Host "Python PID: $($state.process_id) ($processStatus)"
    }
    elseif ($null -ne $state.process_id) {
      Write-Host "Python PID: unavailable (legacy state recorded the terminal PID)"
    }
    else {
      Write-Host "Python PID: none"
    }
    if ($null -ne $state.runner_process_id) {
      Write-Host "Runner PID: $($state.runner_process_id)"
    }
    Write-Host "Updated: $($state.updated_at)"
  }
  if ($null -ne $progress) {
    Write-Host ""
    Write-Host "QA progress: $($progress.completed)/$($progress.total) ($($progress.percent)%)"
    Write-Host "QA stage:    $($progress.stage)"
    Write-Host "Last item:   $($progress.detail)"
  }
  if ($null -ne $retrievalProgress) {
    Write-Host ""
    Write-Host "Retrieval: $($retrievalProgress.completed)/$($retrievalProgress.total) ($($retrievalProgress.percent)%)"
    Write-Host "Last query: $($retrievalProgress.detail)"
  }
  if ($null -ne $state -and $state.status -in @("paused", "complete")) {
    $retrievalReport = Get-JsonIfPresent -Path $retrievalReportPath
    if ($null -ne $retrievalReport) {
      Write-Host ""
      Write-Host "Offline retrieval results:"
      Write-Host "  Questions:       $($retrievalReport.summary.question_count)"
      Write-Host "  Section Hit@1:   $($retrievalReport.summary.section.hit_at_1)"
      Write-Host "  Section Hit@5:   $($retrievalReport.summary.section.hit_at_5)"
      Write-Host "  Section Hit@10:  $($retrievalReport.summary.section.hit_at_10)"
      Write-Host "  Section MRR@10:  $($retrievalReport.summary.section.mrr_at_10)"
      Write-Host "  Document Hit@10: $($retrievalReport.summary.document.hit_at_10)"
      Write-Host "  Mean latency:    $($retrievalReport.summary.mean_query_latency_seconds)s"
    }
    $costEstimate = Get-JsonIfPresent -Path $costEstimatePath
    if ($null -ne $costEstimate) {
      Write-Host ""
      Write-Host "Paid QA estimate: `$$($costEstimate.total_estimated_usd)"
    }
    $qaReport = Get-JsonIfPresent -Path $qaReportPath
    if ($null -ne $qaReport) {
      Write-Host ""
      Write-Host "Paid QA results:"
      Write-Host "  Scope:          $($qaReport.evaluation_scope.kind)"
      Write-Host "  Questions:      $($qaReport.question_count)/$($qaReport.full_question_count)"
      Write-Host "  Kimi accuracy:  $($qaReport.primary_judge.accuracy)"
      Write-Host "  OpenAI accuracy: $($qaReport.independent_judge.accuracy)"
      Write-Host "  Agreement:      $($qaReport.judge_agreement)"
      Write-Host "  Cohen kappa:    $($qaReport.judge_cohen_kappa)"
      Write-Host "  Token F1:       $($qaReport.mean_token_f1)"
      Write-Host (
        "  Measured cost:  `$$($qaReport.usage_and_estimated_cost.total_estimated_usd)"
      )
    }
  }

  $retrievalRows = Join-Path $runPath "retrieval-full.retrieval.jsonl"
  $hypotheses = Join-Path $runPath "qa-full.hypotheses.jsonl"
  $primary = Join-Path $runPath "qa-full.primary-evaluated.jsonl"
  $independent = Join-Path $runPath "qa-full.independent-evaluated.jsonl"
  Write-Host ""
  Write-Host "Retrieval rows:   $(Get-JsonlCount -Path $retrievalRows)"
  Write-Host "Reader rows:      $(Get-JsonlCount -Path $hypotheses)"
  Write-Host "Primary judgments: $(Get-JsonlCount -Path $primary)"
  Write-Host "Independent rows:  $(Get-JsonlCount -Path $independent)"

  if (Test-Path -LiteralPath $logPath) {
    Write-Host ""
    Write-Host "Recent log:"
    $logTail = Get-SharedText -Path $logPath -TailBytes 65536
    if (-not [string]::IsNullOrWhiteSpace($logTail)) {
      @($logTail -split "`r?`n") | Select-Object -Last 8
    }
  }
  if (-not $Watch) {
    break
  }
  if ($null -ne $state -and $state.status -in @("complete", "failed", "paused")) {
    break
  }
  Start-Sleep -Seconds ([Math]::Max(5, $IntervalSeconds))
} while ($true)
