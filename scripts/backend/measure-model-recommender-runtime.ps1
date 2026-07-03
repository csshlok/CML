param(
  [Parameter(Mandatory = $false)]
  [string]$BaseUrl = "http://127.0.0.1:7343/api/v1",
  [Parameter(Mandatory = $false)]
  [string]$ModelId = "",
  [Parameter(Mandatory = $false)]
  [string]$PairId = "",
  [Parameter(Mandatory = $false)]
  [string]$Prompt = "Reply with a short sentence confirming the runtime is working.",
  [Parameter(Mandatory = $false)]
  [string]$AdapterPath = "",
  [Parameter(Mandatory = $false)]
  [string]$BaseModel = "",
  [Parameter(Mandatory = $false)]
  [int]$MaxNewTokens = 48
)

if (-not $ModelId -and -not $PairId) {
  throw "Provide -ModelId or -PairId."
}

$payload = @{
  prompt = $Prompt
}

if ($ModelId) {
  $payload.model_id = $ModelId
}
if ($PairId) {
  $payload.pair_id = $PairId
  if (-not $AdapterPath -or -not $BaseModel) {
    throw "Pair measurement requires -AdapterPath and -BaseModel."
  }
  $payload.adapter_path = $AdapterPath
  $payload.base_model = $BaseModel
  $payload.max_new_tokens = $MaxNewTokens
}

$body = $payload | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri "$BaseUrl/models/recommendations/measurements/run" -ContentType "application/json" -Body $body
