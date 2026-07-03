param(
  [Parameter(Mandatory = $false)]
  [string]$BaseUrl = "http://127.0.0.1:7343/api/v1",
  [Parameter(Mandatory = $false)]
  [string]$Prompt = "Reply with a short sentence confirming the runtime is working.",
  [Parameter(Mandatory = $false)]
  [string]$AdapterPath = "",
  [Parameter(Mandatory = $false)]
  [string]$BaseModel = "",
  [Parameter(Mandatory = $false)]
  [int]$MaxNewTokens = 48,
  [Parameter(Mandatory = $false)]
  [string]$OutputPath = "",
  [Parameter(Mandatory = $false)]
  [string]$ApiToken = $env:CML_API_TOKEN,
  [Parameter(Mandatory = $false)]
  [switch]$SkipChatMeasurement,
  [Parameter(Mandatory = $false)]
  [switch]$SkipPairMeasurement,
  [Parameter(Mandatory = $false)]
  [switch]$Refresh
)

$headers = @{}
if ($ApiToken) {
  $headers["x-cml-api-token"] = $ApiToken
}

$refreshValue = if ($Refresh) { "true" } else { "false" }
$recommendation = Invoke-RestMethod -Method Get -Uri "$BaseUrl/models/recommendations?refresh=$refreshValue" -Headers $headers

$campaign = @{
  generated_at = [DateTime]::UtcNow.ToString("o")
  recommendation = $recommendation
  chat_measurement = $null
  pair_measurement = $null
}

if (-not $SkipChatMeasurement) {
  $chatModelId = [string]$recommendation.recommended_chat_model_id
  if ($chatModelId) {
    $chatBody = @{
      model_id = $chatModelId
      prompt = $Prompt
    } | ConvertTo-Json -Depth 4
    $campaign.chat_measurement = Invoke-RestMethod -Method Post -Uri "$BaseUrl/models/recommendations/measurements/run" -Headers $headers -ContentType "application/json" -Body $chatBody
  }
}

if (-not $SkipPairMeasurement) {
  $pairId = [string]$recommendation.recommended_pair_id
  if ($pairId) {
    if (-not $AdapterPath -or -not $BaseModel) {
      throw "Pair measurement requires -AdapterPath and -BaseModel."
    }
    $pairBody = @{
      pair_id = $pairId
      prompt = $Prompt
      adapter_path = $AdapterPath
      base_model = $BaseModel
      max_new_tokens = $MaxNewTokens
    } | ConvertTo-Json -Depth 4
    $campaign.pair_measurement = Invoke-RestMethod -Method Post -Uri "$BaseUrl/models/recommendations/measurements/run" -Headers $headers -ContentType "application/json" -Body $pairBody
  }
}

$campaign.diagnostics = Invoke-RestMethod -Method Get -Uri "$BaseUrl/models/recommendations/diagnostics?refresh=true" -Headers $headers

if ($OutputPath) {
  $directory = Split-Path -Parent $OutputPath
  if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
  }
  $campaign | ConvertTo-Json -Depth 12 | Set-Content -Path $OutputPath -Encoding utf8
}
else {
  $campaign
}
