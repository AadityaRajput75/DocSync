from pathlib import Path

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from docsync.api import create_app
from docsync.documentation import unified_diff
from docsync.repository import capture


def test_streamlit_status_diff_and_evidence(environment, monkeypatch):
    _, settings, store, _, project = environment
    snapshot = capture(project, settings)
    store.put("snapshot", snapshot)
    original = snapshot["files"]["docs/api.md"]["text"]
    updated = original.replace("10", "20")
    store.put("proposal", {"id": "ui-proposal", "project_id": project["id"], "job_id": "ui-job",
                           "snapshot_id": snapshot["id"], "source_hash": snapshot["source_hash"],
                           "path": "docs/api.md", "before": original, "content": updated,
                           "summary": "Update default limit", "reason": "Related documentation",
                           "citations": [{"path": "api.py", "start": 1, "end": 3}],
                           "state": "pending", "created": 1, "diff": unified_diff("docs/api.md", original, updated)})
    client = TestClient(create_app(settings))
    class LocalClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def request(self, method, url, json=None):
            path = url.removeprefix("http://127.0.0.1:8000")
            return client.request(method, path, json=json)

    monkeypatch.setattr("httpx.Client", LocalClient)
    ui = Path(__file__).resolve().parents[1] / "src/docsync/ui.py"
    app = AppTest.from_file(str(ui)).run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "DocSync"
    assert any("default limit" in element.value for element in app.markdown)
    assert any("+The default limit is 20" in element.value for element in app.code)
    assert any(button.label == "Accept and apply" for button in app.button)
