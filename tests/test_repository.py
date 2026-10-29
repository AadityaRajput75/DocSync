import subprocess

import pytest

from docsync.repository import capture, changes, chunks, safe_path
from docsync.worker import Debouncer


def test_snapshot_hash_and_changes(environment):
    root, settings, _, _, project = environment
    before = capture(project, settings)
    (root / "api.py").write_text("def list_items(limit=20):\n    return []\n")
    after = capture(project, settings)
    assert changes(before, after) == ["api.py"]
    assert before["files"]["api.py"]["text"].find("10") >= 0
    (root / "api.py").unlink()
    assert changes(after, capture(project, settings)) == ["api.py"]


def test_nested_gitignore_tracked_secrets_and_extra_ignore(environment):
    root, settings, _, _, project = environment
    for name in ("secrets.py", "ignored.py", "custom.py"):
        (root / name).write_text("TOKEN = 'sensitive'\n")
    (root / ".gitignore").write_text("ignored.py\n")
    subprocess.run(["git", "-C", str(root), "add", "-f", "ignored.py"], check=True)
    (root / "nested").mkdir()
    (root / "nested" / ".gitignore").write_text("skip.py\n")
    (root / "nested" / "skip.py").write_text("x = 1\n")
    project["ignore"] = ["custom.py"]
    snapshot = capture(project, settings)
    assert set(snapshot["files"]) == {"api.py", "docs/api.md"}
    assert len(snapshot["skipped"]) >= 3


@pytest.mark.parametrize("path", ["../secret.py", "/etc/passwd", "C:/secret.py", "docs/../../secret.py", "docs\\x.md"])
def test_path_escape(environment, path):
    with pytest.raises(ValueError):
        safe_path(environment[0], path)


@pytest.mark.parametrize("path", ["api.py", "docs.py", "docs/x.html", "other/x.md"])
def test_writes_restricted_to_docs(environment, path):
    with pytest.raises(ValueError):
        safe_path(environment[0], path, docs_only=True)


def test_parse_errors_and_chunk_locations(environment):
    root, settings, _, _, project = environment
    snapshot = capture(project, settings)
    items, symbols = chunks(snapshot)
    assert symbols[0]["name"] == "list_items"
    for item in items:
        assert item["start"] >= 1 and item["end"] >= item["start"]
        assert len(item["text"].encode()) <= 1400
    (root / "api.py").write_text("def broken(\n")
    assert capture(project, settings)["errors"][0]["path"] == "api.py"


def test_file_limits(environment):
    root, settings, _, _, project = environment
    settings.max_file_bytes = 5
    assert not capture(project, settings)["files"]
    settings.max_file_bytes, settings.max_files = 1_000_000, 1
    snapshot = capture(project, settings)
    assert len(snapshot["files"]) == 1
    assert any(f["reason"] == "File-count limit" for f in snapshot["skipped"])


def test_save_debounce_and_docs_do_not_trigger_generation():
    from watchdog.events import FileModifiedEvent
    handler = Debouncer(3)
    handler.on_any_event(FileModifiedEvent("api.py"))
    first = handler.python_at
    assert list(handler.ready(first + 2)) == []
    handler.python_at = first + 1
    assert list(handler.ready(first + 3)) == []
    assert list(handler.ready(first + 4)) == ["scan"]
    handler.on_any_event(FileModifiedEvent("docs/api.md"))
    assert list(handler.ready(handler.docs_at + 4)) == ["index_docs"]

