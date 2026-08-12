from backend.app.core.code_structure import extract_structure


def _symbol(structure, label):
    return next(item for item in structure.symbols if item.label == label)


def test_python_extractor_records_only_literal_runtime_boundaries() -> None:
    structure = extract_structure(
        "src/api.py",
        '''
import requests

def upload(cursor, queue, dynamic_url):
    try:
        requests.post("/v1/store")
        requests.get(dynamic_url)
        cursor.execute("INSERT INTO assets VALUES (?)")
        queue.add_task(process_asset, "asset")
    except ValueError:
        raise RuntimeError("bad asset")
''',
        "Python",
        None,
    )

    upload = _symbol(structure, "upload")
    boundaries = {(item.edge_type, item.label) for item in upload.boundaries}
    assert ("http_request", "POST /v1/store") in boundaries
    assert not any(label.endswith("dynamic_url") for _, label in boundaries)
    assert ("writes_data", "assets") in boundaries
    assert ("handles_failure", "Handles ValueError") in boundaries
    assert ("raises_failure", "Raises RuntimeError") in boundaries
    assert upload.dispatches == [("process_asset", 9)]


def test_python_extractor_reads_literal_flask_route_methods() -> None:
    structure = extract_structure(
        "src/api.py",
        '''
@app.route("/api/signup", methods=["POST"])
def signup():
    return {"ok": True}
''',
        "Python",
        None,
    )

    assert _symbol(structure, "signup").routes == [("POST", "/api/signup", 2)]


def test_typescript_extractor_keeps_boundaries_on_the_enclosing_function() -> None:
    structure = extract_structure(
        "src/client.ts",
        '''
export async function load() {
  const response = await fetch("/api/items", { method: "POST" });
  ipcRenderer.send("items:loaded");
  queue.add("refresh");
  return response;
}
''',
        "TypeScript",
        None,
    )

    load = _symbol(structure, "load")
    boundaries = {(item.edge_type, item.label) for item in load.boundaries}
    assert ("http_request", "POST /api/items") in boundaries
    assert ("sends_ipc", "IPC items:loaded") in boundaries
    assert ("dispatches_job", "Job refresh") in boundaries
    assert not any(item.label == "response" for item in structure.symbols)
