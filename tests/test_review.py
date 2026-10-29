import pytest

from docsync.documentation import targets, validate_draft
from docsync.models import Draft, Review
from docsync.repository import capture
from docsync.service import Conflict


def proposal(environment):
    _, settings, store, _, project = environment
    snapshot = capture(project, settings)
    store.put("snapshot", snapshot)
    obj = dict(id="proposal-1", project_id=project["id"], job_id="job-1", snapshot_id=snapshot["id"],
               source_hash=snapshot["source_hash"], destination_hash=snapshot["files"]["docs/api.md"]["hash"],
               path="docs/api.md", before=snapshot["files"]["docs/api.md"]["text"],
               content="# API\nUpdated.\n", sources=["api.py"], state="pending", created=1,
               citations=[{"path": "api.py", "start": 1, "end": 2}])
    store.put("proposal", obj)
    return obj


@pytest.mark.parametrize("changed", ["api.py", "docs/api.md"])
def test_stale_source_or_destination_blocks_apply(environment, changed):
    root, _, store, service, _ = environment
    obj = proposal(environment)
    (root / changed).write_text("# edited\n" if changed.endswith("md") else "x = 9\n")
    with pytest.raises(Conflict):
        service.review(obj["id"], Review(decision="accept"))
    assert store.get("proposal", obj["id"])["state"] == "superseded"
    assert (root / "docs/api.md").read_text() != obj["content"]


def test_accept_backup_and_reject(environment):
    root, settings, store, service, _ = environment
    obj = proposal(environment)
    source = (root / "api.py").read_bytes()
    service.review(obj["id"], Review(decision="accept"))
    assert (root / "docs/api.md").read_text() == obj["content"]
    assert (settings.data_dir / "backups/proposal-1/original.md").read_text() == obj["before"]
    assert (root / "api.py").read_bytes() == source
    obj = proposal(environment)
    service.review(obj["id"], Review(decision="reject"))
    assert store.get("proposal", obj["id"])["state"] == "rejected"


def test_manual_edit_requires_valid_markdown(environment):
    _, _, _, service, _ = environment
    obj = proposal(environment)
    with pytest.raises(ValueError):
        service.review(obj["id"], Review(decision="edit", content="plain text"))
    result = service.review(obj["id"], Review(decision="edit", content="# Edited\nHuman content.\n"))
    assert result["state"] == "accepted"


def test_unrelated_section_and_invalid_citation(environment):
    _, settings, _, _, project = environment
    snapshot = capture(project, settings)
    target = targets(snapshot, ["api.py"], [])[0]
    content = snapshot["files"]["docs/api.md"]["text"].replace("10", "20")
    draft = Draft(content=content, summary="default", citations=[dict(path="api.py", start=1, end=3)])
    validate_draft(project, snapshot, target, draft)
    draft.content = content.replace("Keep this human-written section.", "Oops")
    with pytest.raises(ValueError, match="unrelated"):
        validate_draft(project, snapshot, target, draft)
    draft.content = content
    draft.citations[0].end = 999
    with pytest.raises(ValueError, match="citation"):
        validate_draft(project, snapshot, target, draft)


def test_recover_applied_write(environment):
    root, _, store, service, _ = environment
    from docsync.repository import digest
    obj = proposal(environment)
    (root / obj["path"]).write_bytes(obj["content"].encode())
    store.patch("proposal", obj["id"], state="applying", applied_hash=digest(obj["content"]))
    service.recover_applications()
    assert store.get("proposal", obj["id"])["state"] == "accepted"

