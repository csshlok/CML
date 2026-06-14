param(
  [string]$ReportPath = "",
  [int]$Port = 7487
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$smokeRoot = Join-Path $env:TEMP ("cml-extension-browser-smoke-" + [guid]::NewGuid().ToString("n"))
$dataDir = Join-Path $smokeRoot "data"
$vaultRoot = Join-Path $smokeRoot "vault-root"
$dbPath = Join-Path $dataDir "cml.sqlite3"
$statusPath = Join-Path $smokeRoot "startup-status.json"
$logOut = Join-Path $smokeRoot "backend.stdout.log"
$logErr = Join-Path $smokeRoot "backend.stderr.log"
$apiToken = "extension-browser-smoke-token"
$extensionRoot = Join-Path $repoRoot "apps\browser-extension"
$browserRoot = Join-Path $repoRoot "apps\desktop\packaging\ms-playwright"
$uploadFile = Join-Path $smokeRoot "upload-note.txt"
if (-not $ReportPath) {
  $ReportPath = Join-Path $smokeRoot "extension-browser-smoke-report.json"
}

New-Item -ItemType Directory -Force -Path $dataDir, $vaultRoot | Out-Null
"playwright browser extension upload smoke" | Set-Content -Path $uploadFile -Encoding UTF8

$env:PYTHONPATH = $repoRoot
$env:CML_BACKEND_MODE = "full_vault"
$env:CML_DATA_DIR = $dataDir
$env:CML_DATABASE_PATH = $dbPath
$env:CML_STARTUP_STATUS_PATH = $statusPath
$env:CML_API_TOKEN = $apiToken
$env:CML_ALLOW_UNAUTHENTICATED_API = "0"
$env:CML_ALLOW_HASH_EMBEDDINGS = "1"
$env:CML_EMBEDDING_PROVIDER = "hash"

$process = Start-Process `
  -FilePath $python `
  -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput $logOut `
  -RedirectStandardError $logErr

function Wait-BackendReady([string]$BaseUrl) {
  $deadline = (Get-Date).AddSeconds(25)
  while ((Get-Date) -lt $deadline) {
    try {
      $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 2
      if ($health.status -eq "ok") {
        return
      }
    } catch {
      Start-Sleep -Milliseconds 300
    }
  }
  throw "Browser extension Playwright smoke backend did not become healthy."
}

function Invoke-ApiJson([string]$Method, [string]$Uri, [object]$Payload = $null, [hashtable]$Headers = @{}) {
  $params = @{
    Uri        = $Uri
    Method     = $Method
    Headers    = $Headers
    TimeoutSec = 60
  }
  if ($null -ne $Payload) {
    $params.ContentType = "application/json"
    $params.Body = ($Payload | ConvertTo-Json -Depth 8)
  }
  return Invoke-RestMethod @params
}

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $adminHeaders = @{ "x-cml-api-token" = $apiToken }
  Wait-BackendReady $baseUrl

  $vault = Invoke-ApiJson "POST" "$baseUrl/api/v1/vaults" @{
    name = "Extension Browser Smoke Vault"
    path = $vaultRoot
  } $adminHeaders

  $unlock = Invoke-ApiJson "POST" "$baseUrl/api/v1/system/unlock/initialize" @{
    vault_id = $vault.id
    passphrase = "extension-browser-smoke-passphrase"
    unlock_mode = "convenience"
  } $adminHeaders

  $extensionClient = Invoke-ApiJson "POST" "$baseUrl/api/v1/extension/clients" @{
    name = "Browser smoke extension"
    allowed_vault_ids = @($vault.id)
  } $adminHeaders

  $setupJson = @{
    backend_url = $baseUrl
    extension_token = $extensionClient.token
    default_vault_id = $vault.id
    client_name = "Browser smoke extension"
  } | ConvertTo-Json -Compress

  $env:PLAYWRIGHT_BROWSERS_PATH = $browserRoot
  $env:CML_EXTENSION_SMOKE_EXTENSION_ROOT = $extensionRoot
  $env:CML_EXTENSION_SMOKE_SETUP_JSON = $setupJson
  $env:CML_EXTENSION_SMOKE_BASE_URL = $baseUrl
  $env:CML_EXTENSION_SMOKE_UPLOAD_FILE = $uploadFile

  $code = @'
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

extension_root = Path(os.environ["CML_EXTENSION_SMOKE_EXTENSION_ROOT"])
setup_json = os.environ["CML_EXTENSION_SMOKE_SETUP_JSON"]
base_url = os.environ["CML_EXTENSION_SMOKE_BASE_URL"]
upload_file = os.environ["CML_EXTENSION_SMOKE_UPLOAD_FILE"]

profile_dir = tempfile.mkdtemp(prefix="cml-extension-browser-profile-")
result = {}

with sync_playwright() as playwright:
    context = playwright.chromium.launch_persistent_context(
        profile_dir,
        headless=False,
        args=[
            f"--disable-extensions-except={extension_root}",
            f"--load-extension={extension_root}",
            "--no-first-run",
            "--disable-default-apps",
        ],
    )
    try:
        service_worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
        extension_id = service_worker.url.split("/")[2]
        browser_session = context.browser.new_browser_cdp_session()
        service_worker.evaluate("() => chrome.action.openPopup()")
        time.sleep(1)
        targets = browser_session.send("Target.getTargets")
        popup_targets = [
            target
            for target in targets.get("targetInfos", [])
            if target.get("type") == "page" and target.get("url", "").endswith("/popup.html")
        ]
        popup_page = context.new_page()
        popup_page.goto(f"chrome-extension://{extension_id}/popup.html", wait_until="domcontentloaded")
        popup_page.locator("#setupJson").fill(setup_json)
        popup_page.locator("#importSetup").click()
        popup_page.wait_for_function("() => document.querySelector('#status')?.textContent?.includes('Setup imported and saved.')")
        popup_page.locator("#checkStatus").click()
        popup_page.wait_for_function("() => document.querySelector('#status')?.textContent?.includes('available')")

        popup_controls = popup_page.evaluate(
            """
            () => ({
              buttons: Array.from(document.querySelectorAll('button')).map((node) => node.textContent.trim()),
              fields: Array.from(document.querySelectorAll('input, textarea')).map((node) => ({
                id: node.id || '',
                type: node.tagName.toLowerCase() === 'textarea' ? 'textarea' : (node.getAttribute('type') || 'text'),
              })),
            })
            """
        )

        content_page = context.new_page()
        content_page.goto(f"{base_url}/docs", wait_until="domcontentloaded")
        content_page.bring_to_front()
        content_page.wait_for_function("() => document.documentElement?.getAttribute('data-cml-capture-ready') === '1'")
        selected_text = content_page.evaluate(
            """
            () => {
              const target = document.querySelector('h1, h2, .title, .opblock-tag') || document.body;
              const range = document.createRange();
              range.selectNodeContents(target);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event('selectionchange'));
              document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
              return (target.innerText || target.textContent || '').trim();
            }
            """
        )
        time.sleep(0.6)

        selection_result = None
        screenshot_result = None
        try:
            selection_result = popup_page.evaluate(
                "() => chrome.runtime.sendMessage({ type: 'cml:capture', captureMode: 'selection' })"
            )
        except Exception as exc:
            selection_result = {"ok": False, "error": str(exc)}
        try:
            screenshot_result = popup_page.evaluate(
                "() => chrome.runtime.sendMessage({ type: 'cml:capture', captureMode: 'screenshot' })"
            )
        except Exception as exc:
            screenshot_result = {"ok": False, "error": str(exc)}

        popup_page.bring_to_front()
        popup_page.locator("#uploadFile").set_input_files(upload_file)
        popup_page.locator("#uploadFileButton").click()
        popup_page.wait_for_function("() => document.querySelector('#status')?.textContent?.includes('Saved upload-note.txt to CML.')")

        result = {
            "extension_id": extension_id,
            "real_popup_target_seen": bool(popup_targets),
            "real_popup_target_title": popup_targets[0].get("title", "") if popup_targets else "",
            "popup_controls": popup_controls,
            "selected_text_sample": selected_text[:120],
            "selection_result": selection_result,
            "screenshot_result": screenshot_result,
            "popup_status": popup_page.locator("#status").inner_text(),
        }
    finally:
        context.close()
        shutil.rmtree(profile_dir, ignore_errors=True)

print(json.dumps(result))
'@

  $playwrightJson = $code | & $python -
  $playwrightResult = $playwrightJson | ConvertFrom-Json

  $captures = Invoke-ApiJson "GET" "$baseUrl/api/v1/extension/captures?vault_id=$($vault.id)" $null $adminHeaders
  $captureItems = @($captures)
  $uploadCapture = $captureItems | Where-Object { $_.title -eq "upload-note.txt" } | Sort-Object created_at -Descending | Select-Object -First 1

  $uploadSource = Invoke-ApiJson "GET" "$baseUrl/api/v1/sources/$($uploadCapture.source_id)" $null $adminHeaders

  $buttonLabels = @($playwrightResult.popup_controls.buttons)
  $fieldIds = @($playwrightResult.popup_controls.fields | ForEach-Object { $_.id })

  $report = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    smoke_root = $smokeRoot
    backend_ready = $true
    unlock_state = $unlock.state
    extension_client_id = $extensionClient.id
    browser_extension_id = $playwrightResult.extension_id
    real_popup_target_seen = $playwrightResult.real_popup_target_seen
    real_popup_target_title = $playwrightResult.real_popup_target_title
    popup_button_labels = $buttonLabels
    popup_field_ids = $fieldIds
    popup_status = $playwrightResult.popup_status
    selection_capture_attempt = $playwrightResult.selection_result
    screenshot_capture_attempt = $playwrightResult.screenshot_result
    upload_capture_status = $uploadCapture.status
    capture_count = $captureItems.Count
    upload_source_type = $uploadSource.source_type
    selected_text_sample = $playwrightResult.selected_text_sample
    pass = (
      $unlock.state -eq "ready" -and
      $playwrightResult.real_popup_target_seen -eq $true -and
      $playwrightResult.popup_status -like "Saved upload-note.txt to CML.*" -and
      $captureItems.Count -ge 1 -and
      $uploadSource.source_type -eq "extension_note" -and
      $buttonLabels -contains "Import setup" -and
      $buttonLabels -contains "Check connection" -and
      $buttonLabels -contains "Save current page" -and
      $buttonLabels -contains "Save selected text" -and
      $buttonLabels -contains "Save PDF URL" -and
      $buttonLabels -contains "Save screenshot" -and
      $buttonLabels -contains "Save selected file" -and
      $fieldIds -contains "setupJson" -and
      $fieldIds -contains "backendUrl" -and
      $fieldIds -contains "token" -and
      $fieldIds -contains "vaultId" -and
      $fieldIds -contains "clusterId" -and
      $fieldIds -contains "uploadFile"
    )
  }

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
  $report | ConvertTo-Json -Depth 8 | Set-Content -Path $ReportPath -Encoding UTF8
  $report | ConvertTo-Json -Depth 8
} finally {
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}
