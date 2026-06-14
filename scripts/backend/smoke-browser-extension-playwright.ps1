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
  $env:CML_EXTENSION_SMOKE_DEBUG_PORT = "9339"

  $code = @'
import json
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
from websockets.sync.client import connect as ws_connect

extension_root = Path(os.environ["CML_EXTENSION_SMOKE_EXTENSION_ROOT"])
setup_json = os.environ["CML_EXTENSION_SMOKE_SETUP_JSON"]
base_url = os.environ["CML_EXTENSION_SMOKE_BASE_URL"]
upload_file = os.environ["CML_EXTENSION_SMOKE_UPLOAD_FILE"]
debug_port = int(os.environ["CML_EXTENSION_SMOKE_DEBUG_PORT"])

profile_dir = tempfile.mkdtemp(prefix="cml-extension-browser-profile-")
result = {}


class BrowserCdp:
    def __init__(self, port: int) -> None:
        self._port = int(port)
        self._ws = None
        self._next_id = 1

    def __enter__(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/json/version") as response:
            version = json.load(response)
        self._ws = ws_connect(version["webSocketDebuggerUrl"])
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def send(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        payload = {
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        if session_id:
            payload["sessionId"] = session_id
        self._ws.send(json.dumps(payload))
        current_id = self._next_id
        self._next_id += 1
        while True:
            raw = json.loads(self._ws.recv())
            if raw.get("id") == current_id:
                return raw

    def wait_for_popup_target(self, timeout_seconds: float = 10.0) -> dict | None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            targets = self.send("Target.getTargets")["result"]["targetInfos"]
            popup = next(
                (
                    target
                    for target in targets
                    if target.get("type") == "page" and target.get("url", "").endswith("/popup.html")
                ),
                None,
            )
            if popup is not None:
                return popup
            time.sleep(0.2)
        return None

    def attach_target(self, target_id: str) -> str:
        attached = self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = attached["result"]["sessionId"]
        self.send("Runtime.enable", session_id=session_id)
        self.send("DOM.enable", session_id=session_id)
        self.send("Page.enable", session_id=session_id)
        return session_id

    def attach_page_target_by_url(self, page_url: str) -> str | None:
        targets = self.send("Target.getTargets")["result"]["targetInfos"]
        target = next(
            (
                item
                for item in targets
                if item.get("type") == "page" and item.get("url") == page_url
            ),
            None,
        )
        if target is None:
            return None
        return self.attach_target(target["targetId"])

    def attach_popup(self, target_id: str) -> str:
        return self.attach_target(target_id)

    def evaluate(
        self,
        session_id: str,
        expression: str,
        *,
        user_gesture: bool = False,
        await_promise: bool = False,
        return_by_value: bool = True,
    ):
        response = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "userGesture": user_gesture,
                "awaitPromise": await_promise,
                "returnByValue": return_by_value,
            },
            session_id=session_id,
        )
        result = response.get("result", {}).get("result", {})
        if "exceptionDetails" in response.get("result", {}):
            raise RuntimeError(str(response["result"]["exceptionDetails"]))
        return result.get("value")

    def set_file_input_files(self, session_id: str, selector: str, files: list[str]) -> None:
        root = self.send("DOM.getDocument", session_id=session_id)["result"]["root"]["nodeId"]
        node_id = self.send(
            "DOM.querySelector",
            {"nodeId": root, "selector": selector},
            session_id=session_id,
        )["result"]["nodeId"]
        self.send(
            "DOM.setFileInputFiles",
            {"nodeId": node_id, "files": files},
            session_id=session_id,
        )

    def status_text(self, session_id: str) -> str:
        return str(
            self.evaluate(
                session_id,
                "document.querySelector('#status')?.textContent || ''",
            )
            or ""
        )

    def wait_for_status(self, session_id: str, expected_text: str, timeout_seconds: float = 12.0) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status = self.status_text(session_id)
            if expected_text in status:
                return status
            time.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for popup status containing {expected_text!r}")

    def dispatch_shortcut(self, session_id: str, key: str) -> None:
        upper = str(key).upper()
        key_code = ord(upper)
        self.send(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": "Control",
                "code": "ControlLeft",
                "windowsVirtualKeyCode": 17,
                "nativeVirtualKeyCode": 17,
            },
            session_id=session_id,
        )
        self.send(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": "Shift",
                "code": "ShiftLeft",
                "windowsVirtualKeyCode": 16,
                "nativeVirtualKeyCode": 16,
                "modifiers": 2,
            },
            session_id=session_id,
        )
        self.send(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "key": upper,
                "code": f"Key{upper}",
                "windowsVirtualKeyCode": key_code,
                "nativeVirtualKeyCode": key_code,
                "modifiers": 10,
            },
            session_id=session_id,
        )
        self.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": upper,
                "code": f"Key{upper}",
                "windowsVirtualKeyCode": key_code,
                "nativeVirtualKeyCode": key_code,
                "modifiers": 10,
            },
            session_id=session_id,
        )
        self.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "Shift",
                "code": "ShiftLeft",
                "windowsVirtualKeyCode": 16,
                "nativeVirtualKeyCode": 16,
                "modifiers": 8,
            },
            session_id=session_id,
        )
        self.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": "Control",
                "code": "ControlLeft",
                "windowsVirtualKeyCode": 17,
                "nativeVirtualKeyCode": 17,
            },
            session_id=session_id,
        )

with sync_playwright() as playwright:
    context = playwright.chromium.launch_persistent_context(
        profile_dir,
        headless=False,
        args=[
            f"--remote-debugging-port={debug_port}",
            f"--disable-extensions-except={extension_root}",
            f"--load-extension={extension_root}",
            "--no-first-run",
            "--disable-default-apps",
        ],
    )
    try:
        service_worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
        extension_id = service_worker.url.split("/")[2]
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

        popup_mode = "fallback_tab"
        popup_target = None
        popup_session_id = None
        popup_controls = {"buttons": [], "fields": []}
        selection_result = None
        screenshot_result = None
        screenshot_shortcut_result = None
        upload_result = None
        popup_status = ""

        with BrowserCdp(debug_port) as cdp:
            content_page_session_id = cdp.attach_page_target_by_url(content_page.url)
            if content_page_session_id is not None:
                cdp.dispatch_shortcut(content_page_session_id, "Y")
            else:
                service_worker.evaluate("() => chrome.action.openPopup()")
            popup_target = cdp.wait_for_popup_target()

            if popup_target is not None:
                popup_mode = "real_popup_cdp"
                popup_session_id = cdp.attach_popup(popup_target["targetId"])
                cdp.evaluate(
                    popup_session_id,
                    f"""
                    (() => {{
                      const node = document.querySelector('#setupJson');
                      if (node) node.value = {json.dumps(setup_json)};
                      document.querySelector('#importSetup')?.click();
                      return true;
                    }})()
                    """,
                    user_gesture=True,
                )
                cdp.wait_for_status(popup_session_id, "Setup imported and saved.")
                cdp.evaluate(
                    popup_session_id,
                    "document.querySelector('#checkStatus')?.click(); true",
                    user_gesture=True,
                )
                cdp.wait_for_status(popup_session_id, "available")
                popup_controls = cdp.evaluate(
                    popup_session_id,
                    """
                    (() => ({
                      buttons: Array.from(document.querySelectorAll('button')).map((node) => node.textContent.trim()),
                      fields: Array.from(document.querySelectorAll('input, textarea')).map((node) => ({
                        id: node.id || '',
                        type: node.tagName.toLowerCase() === 'textarea' ? 'textarea' : (node.getAttribute('type') || 'text'),
                      })),
                    }))()
                    """,
                )

                def click_popup_action_cdp(button_id: str, expected_text: str):
                    try:
                        cdp.evaluate(
                            popup_session_id,
                            f"document.querySelector({json.dumps(button_id)})?.click(); true",
                            user_gesture=True,
                        )
                        status_text = cdp.wait_for_status(popup_session_id, expected_text)
                        return {"ok": True, "status": status_text}
                    except Exception as exc:
                        return {
                            "ok": False,
                            "error": str(exc),
                            "status": cdp.status_text(popup_session_id),
                        }

                selection_result = click_popup_action_cdp("#captureSelection", "Saved to CML as selection.")
                screenshot_result = click_popup_action_cdp("#captureScreenshot", "Saved to CML as screenshot.")
                content_page.bring_to_front()
                try:
                    if content_page_session_id is None:
                        raise RuntimeError("Content page target session was unavailable.")
                    cdp.dispatch_shortcut(content_page_session_id, "U")
                    time.sleep(2)
                    screenshot_shortcut_result = {"ok": True, "status": "Triggered screenshot shortcut from content page."}
                except Exception as exc:
                    screenshot_shortcut_result = {"ok": False, "error": str(exc)}

                try:
                    cdp.set_file_input_files(popup_session_id, "#uploadFile", [upload_file])
                    cdp.evaluate(
                        popup_session_id,
                        "document.querySelector('#uploadFileButton')?.click(); true",
                        user_gesture=True,
                    )
                    upload_status = cdp.wait_for_status(popup_session_id, "Saved upload-note.txt to CML.")
                    upload_result = {"ok": True, "status": upload_status}
                except Exception as exc:
                    upload_result = {
                        "ok": False,
                        "error": str(exc),
                        "status": cdp.status_text(popup_session_id),
                    }
                popup_status = cdp.status_text(popup_session_id)
            else:
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

                def click_popup_action(button_id: str, expected_text: str):
                    try:
                        popup_page.locator(button_id).click()
                        popup_page.wait_for_function(
                            "(expected) => document.querySelector('#status')?.textContent?.includes(expected)",
                            arg=expected_text,
                            timeout=12000,
                        )
                        return {
                            "ok": True,
                            "status": popup_page.locator("#status").inner_text(),
                        }
                    except Exception as exc:
                        status_text = ""
                        try:
                            status_text = popup_page.locator("#status").inner_text()
                        except Exception:
                            status_text = ""
                        return {
                            "ok": False,
                            "error": str(exc),
                            "status": status_text,
                        }

                selection_result = click_popup_action("#captureSelection", "Saved to CML as selection.")
                screenshot_result = click_popup_action("#captureScreenshot", "Saved to CML as screenshot.")
                content_page.bring_to_front()
                try:
                    if content_page_session_id is None:
                        raise RuntimeError("Content page target session was unavailable.")
                    cdp.dispatch_shortcut(content_page_session_id, "U")
                    time.sleep(2)
                    screenshot_shortcut_result = {"ok": True, "status": "Triggered screenshot shortcut from content page."}
                except Exception as exc:
                    screenshot_shortcut_result = {"ok": False, "error": str(exc)}
                try:
                    popup_page.locator("#uploadFile").set_input_files(upload_file)
                    popup_page.locator("#uploadFileButton").click()
                    popup_page.wait_for_function("() => document.querySelector('#status')?.textContent?.includes('Saved upload-note.txt to CML.')")
                    upload_result = {
                        "ok": True,
                        "status": popup_page.locator("#status").inner_text(),
                    }
                except Exception as exc:
                    upload_result = {
                        "ok": False,
                        "error": str(exc),
                        "status": popup_page.locator("#status").inner_text(),
                    }
                popup_status = popup_page.locator("#status").inner_text()

        result = {
            "extension_id": extension_id,
            "popup_mode": popup_mode,
            "real_popup_target_seen": bool(popup_target),
            "real_popup_target_title": popup_target.get("title", "") if popup_target else "",
            "popup_controls": popup_controls,
            "selected_text_sample": selected_text[:120],
            "selection_result": selection_result,
            "screenshot_result": screenshot_result,
            "screenshot_shortcut_result": screenshot_shortcut_result,
            "upload_result": upload_result,
            "popup_status": popup_status,
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
  $selectionCapture = $captureItems | Where-Object { $_.capture_type -eq "selection" } | Sort-Object created_at -Descending | Select-Object -First 1
  $screenshotCapture = $captureItems | Where-Object { $_.capture_type -eq "screenshot" } | Sort-Object created_at -Descending | Select-Object -First 1
  $uploadCapture = $captureItems | Where-Object { $_.title -eq "upload-note.txt" } | Sort-Object created_at -Descending | Select-Object -First 1

  $selectionSource = $null
  if ($selectionCapture) {
    $selectionSource = Invoke-ApiJson "GET" "$baseUrl/api/v1/sources/$($selectionCapture.source_id)" $null $adminHeaders
  }
  $screenshotSource = $null
  if ($screenshotCapture) {
    $screenshotSource = Invoke-ApiJson "GET" "$baseUrl/api/v1/sources/$($screenshotCapture.source_id)" $null $adminHeaders
  }
  $uploadSource = $null
  if ($uploadCapture) {
    $uploadSource = Invoke-ApiJson "GET" "$baseUrl/api/v1/sources/$($uploadCapture.source_id)" $null $adminHeaders
  }

  $buttonLabels = @($playwrightResult.popup_controls.buttons)
  $fieldIds = @($playwrightResult.popup_controls.fields | ForEach-Object { $_.id })

  $report = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    smoke_root = $smokeRoot
    backend_ready = $true
    unlock_state = $unlock.state
    extension_client_id = $extensionClient.id
    browser_extension_id = $playwrightResult.extension_id
    popup_mode = $playwrightResult.popup_mode
    real_popup_target_seen = $playwrightResult.real_popup_target_seen
    real_popup_target_title = $playwrightResult.real_popup_target_title
    popup_button_labels = $buttonLabels
    popup_field_ids = $fieldIds
    popup_status = $playwrightResult.popup_status
    selection_capture_attempt = $playwrightResult.selection_result
    screenshot_capture_attempt = $playwrightResult.screenshot_result
    screenshot_shortcut_attempt = $playwrightResult.screenshot_shortcut_result
    upload_capture_attempt = $playwrightResult.upload_result
    selection_capture_id = $selectionCapture.id
    screenshot_capture_id = $screenshotCapture.id
    selection_source_type = $selectionSource.source_type
    screenshot_source_type = $screenshotSource.source_type
    upload_capture_status = $uploadCapture.status
    capture_count = $captureItems.Count
    upload_source_type = $uploadSource.source_type
    selected_text_sample = $playwrightResult.selected_text_sample
    pass = (
      $unlock.state -eq "ready" -and
      $playwrightResult.real_popup_target_seen -eq $true -and
      $playwrightResult.popup_mode -eq "real_popup_cdp" -and
      $playwrightResult.selection_result.ok -eq $true -and
      $playwrightResult.screenshot_shortcut_result.ok -eq $true -and
      $playwrightResult.upload_result.ok -eq $true -and
      $playwrightResult.popup_status -like "Saved upload-note.txt to CML.*" -and
      $captureItems.Count -ge 3 -and
      $selectionCapture.status -eq "stored" -and
      $screenshotCapture.status -eq "stored" -and
      $uploadSource.source_type -eq "extension_note" -and
      $selectionSource.source_type -eq "extension_selection" -and
      $screenshotSource.source_type -eq "extension_screenshot" -and
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
