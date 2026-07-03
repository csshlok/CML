param(
  [Parameter(Mandatory = $false)]
  [string]$BaseUrl = "http://127.0.0.1:7343/api/v1",
  [Parameter(Mandatory = $false)]
  [string]$ModelId = "",
  [Parameter(Mandatory = $false)]
  [string]$PairId = "",
  [Parameter(Mandatory = $false)]
  [double]$Score = 0,
  [Parameter(Mandatory = $false)]
  [double]$EstimatedTokPerSec = 0,
  [Parameter(Mandatory = $false)]
  [double]$StartupSeconds = 0,
  [Parameter(Mandatory = $false)]
  [string]$ApiToken = $env:CML_API_TOKEN,
  [Parameter(Mandatory = $false)]
  [Nullable[bool]]$RuntimeSuccess = $null,
  [Parameter(Mandatory = $false)]
  [Nullable[bool]]$TrainingSuccess = $null
)

if (-not $ModelId -and -not $PairId) {
  throw "Provide -ModelId or -PairId."
}

$payload = @{
  measured_at = [DateTime]::UtcNow.ToString("o")
}

if ($ModelId) {
  $payload.model_id = $ModelId
}
if ($PairId) {
  $payload.pair_id = $PairId
}
if ($Score -ne 0) {
  $payload.score = $Score
}
if ($EstimatedTokPerSec -ne 0) {
  $payload.estimated_tok_per_sec = $EstimatedTokPerSec
}
if ($StartupSeconds -ne 0) {
  $payload.startup_seconds = $StartupSeconds
}
if ($RuntimeSuccess -ne $null) {
  $payload.runtime_success = $RuntimeSuccess
}
if ($TrainingSuccess -ne $null) {
  $payload.training_success = $TrainingSuccess
}

$body = $payload | ConvertTo-Json -Depth 4
$headers = @{}
if ($ApiToken) {
  $headers["x-cml-api-token"] = $ApiToken
}
Invoke-RestMethod -Method Post -Uri "$BaseUrl/models/recommendations/measurements" -Headers $headers -ContentType "application/json" -Body $body
