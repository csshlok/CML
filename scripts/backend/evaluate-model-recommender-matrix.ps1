param(
  [Parameter(Mandatory = $false)]
  [string]$BaseUrl = "http://127.0.0.1:8000/api/v1",
  [Parameter(Mandatory = $false)]
  [string]$ProfilesDir = "backend/tests/fixtures/model_recommender_profiles",
  [Parameter(Mandatory = $false)]
  [string]$OutputPath = "",
  [Parameter(Mandatory = $false)]
  [switch]$Refresh
)

if (-not (Test-Path -Path $ProfilesDir)) {
  throw "Profiles directory does not exist: $ProfilesDir"
}

$rows = @()
foreach ($profilePath in Get-ChildItem -Path $ProfilesDir -Filter *.json | Sort-Object Name) {
  $hardwarePayload = Get-Content -Path $profilePath.FullName -Raw | ConvertFrom-Json -AsHashtable
  $body = @{
    hardware = $hardwarePayload
    refresh = [bool]$Refresh
  } | ConvertTo-Json -Depth 8
  $result = Invoke-RestMethod -Method Post -Uri "$BaseUrl/models/recommendations/diagnostics/preview" -ContentType "application/json" -Body $body
  $rows += @{
    fixture = $profilePath.BaseName
    hardware_tier = $result.hardware.hardware_tier
    recommended_chat_model_id = $result.recommendation.recommended_chat_model_id
    recommended_pair_id = $result.recommendation.recommended_pair_id
    chat_fit_type = $result.recommendation.chat_fit_type
    expert_training_fit_type = $result.recommendation.expert_training_fit_type
    confidence = $result.recommendation.confidence
    speed_band_match_rate = $result.calibration_summary.speed_band_match_rate
    fit_mismatch_rate = $result.calibration_summary.fit_mismatch_rate
  }
}

$summary = @{
  generated_at = [DateTime]::UtcNow.ToString("o")
  profile_count = $rows.Count
  profiles_dir = (Resolve-Path $ProfilesDir).Path
  rows = $rows
}

if ($OutputPath) {
  $directory = Split-Path -Parent $OutputPath
  if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
  }
  $summary | ConvertTo-Json -Depth 10 | Set-Content -Path $OutputPath -Encoding utf8
}
else {
  $summary
}
