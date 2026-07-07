param(
  [Parameter(Mandatory = $false)]
  [string]$BaseUrl = "http://127.0.0.1:7343/api/v1",
  [Parameter(Mandatory = $false)]
  [string]$ModelId = "",
  [Parameter(Mandatory = $false)]
  [string]$Prompt = "Reply with a short sentence confirming the runtime is working.",
  [Parameter(Mandatory = $false)]
  [string]$ApiToken = $env:CML_API_TOKEN,
  [Parameter(Mandatory = $false)]
  [int]$MaxNewTokens = 48
)

if (-not $ModelId) {
  throw "Provide -ModelId."
}

$payload = @{
  prompt = $Prompt
}

$payload.model_id = $ModelId
$payload.max_new_tokens = $MaxNewTokens

$body = $payload | ConvertTo-Json -Depth 4
$headers = @{}
if ($ApiToken) {
  $headers["x-cml-api-token"] = $ApiToken
}
Invoke-RestMethod -Method Post -Uri "$BaseUrl/models/recommendations/measurements/run" -Headers $headers -ContentType "application/json" -Body $body
