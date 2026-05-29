param(
  [string]$BaseUrl = "http://127.0.0.1:8084/v1",
  [string]$Model = "cml-local",
  [string]$Prompt = "In one sentence, explain what CML does. /no_think",
  [int]$MaxTokens = 96
)

$ErrorActionPreference = "Stop"

$body = @{
  model = $Model
  messages = @(
    @{
      role = "system"
      content = "CML means Context Management Layer, a local second-brain app that organizes user-controlled context."
    },
    @{
      role = "user"
      content = $Prompt
    }
  )
  temperature = 0.2
  max_tokens = $MaxTokens
  stream = $false
} | ConvertTo-Json -Depth 8

$started = Get-Date
$response = Invoke-RestMethod `
  -Uri "$BaseUrl/chat/completions" `
  -Method Post `
  -Body $body `
  -ContentType "application/json" `
  -TimeoutSec 180
$elapsed = ((Get-Date) - $started).TotalSeconds

Write-Host "Answer:" -ForegroundColor Cyan
Write-Host $response.choices[0].message.content
Write-Host ""
Write-Host "Timing:" -ForegroundColor Cyan
if ($response.timings) {
  $response.timings | ConvertTo-Json -Depth 4
} else {
  Write-Host "Elapsed seconds: $([Math]::Round($elapsed, 2))"
}
