param(
  [Parameter(Mandatory = $false)]
  [string]$BaseUrl = "http://127.0.0.1:8000/api/v1",
  [Parameter(Mandatory = $false)]
  [string]$OutputPath = "",
  [Parameter(Mandatory = $false)]
  [string]$HardwareJsonPath = "",
  [Parameter(Mandatory = $false)]
  [switch]$Refresh
)

if ($HardwareJsonPath) {
  $hardwarePayload = Get-Content -Path $HardwareJsonPath -Raw | ConvertFrom-Json -AsHashtable
  $body = @{
    hardware = $hardwarePayload
    refresh = [bool]$Refresh
  } | ConvertTo-Json -Depth 8
  $result = Invoke-RestMethod -Method Post -Uri "$BaseUrl/models/recommendations/diagnostics/preview" -ContentType "application/json" -Body $body
}
else {
  $refreshValue = if ($Refresh) { "true" } else { "false" }
  $result = Invoke-RestMethod -Method Get -Uri "$BaseUrl/models/recommendations/diagnostics?refresh=$refreshValue"
}

if ($OutputPath) {
  $directory = Split-Path -Parent $OutputPath
  if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
  }
  $result | ConvertTo-Json -Depth 12 | Set-Content -Path $OutputPath -Encoding utf8
}
else {
  $result
}
