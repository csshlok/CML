param(
    [string]$PythonPath = "",
    [string]$ResourcesRoot = "",
    [string]$InspectorVersion = "0.21.2"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $PythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
$resolvedPython = (Resolve-Path -LiteralPath $PythonPath).Path
$resolvedResources = if ($ResourcesRoot) {
    (Resolve-Path -LiteralPath $ResourcesRoot).Path
} else {
    $repoRoot
}

function Invoke-InspectorProfile {
    param([ValidateSet("read_only", "read_write")][string]$Profile)

    $previousProfile = $env:CML_MCP_CAPABILITY_PROFILE
    $previousPythonPath = $env:PYTHONPATH
    $previousPythonHome = $env:PYTHONHOME
    $previousNoUserSite = $env:PYTHONNOUSERSITE
    try {
        $env:CML_MCP_CAPABILITY_PROFILE = $Profile
        $env:PYTHONPATH = $resolvedResources
        $env:PYTHONHOME = if ($ResourcesRoot) { Split-Path -Parent $resolvedPython } else { $null }
        $env:PYTHONNOUSERSITE = "1"
        $output = & npx.cmd -y "@modelcontextprotocol/inspector@$InspectorVersion" --cli `
            -e "CML_MCP_CAPABILITY_PROFILE=$Profile" `
            $resolvedPython -s -m backend.app.bridge_mcp_stdio --method tools/list 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "MCP Inspector failed for $Profile.`n$($output -join [Environment]::NewLine)"
        }
        $text = $output -join [Environment]::NewLine
        if ($text -notmatch '"name"\s*:\s*"list_clusters"') {
            throw "MCP Inspector did not discover list_clusters for $Profile."
        }
        $hasWriteTool = $text -match '"name"\s*:\s*"capture_external_artifact"'
        if ($Profile -eq "read_only" -and $hasWriteTool) {
            throw "The read-only profile exposed a write tool."
        }
        if ($Profile -eq "read_write" -and -not $hasWriteTool) {
            throw "The read/write profile did not expose write tools."
        }
        Write-Host "MCP Inspector $Profile profile passed."
    }
    finally {
        $env:CML_MCP_CAPABILITY_PROFILE = $previousProfile
        $env:PYTHONPATH = $previousPythonPath
        $env:PYTHONHOME = $previousPythonHome
        $env:PYTHONNOUSERSITE = $previousNoUserSite
    }
}

Push-Location $resolvedResources
try {
    Invoke-InspectorProfile -Profile "read_only"
    Invoke-InspectorProfile -Profile "read_write"
}
finally {
    Pop-Location
}
