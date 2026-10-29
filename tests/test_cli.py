import argparse
import io
from pathlib import Path

import pytest
from filelock import FileLock
from helpers import MemoryRetriever, ScriptedLLM

from docsync import terminal
from docsync.cli import main
from docsync.models import Decision, Draft
from docsync.repository import capture
from docsync.worker import Worker


@pytest.fixture
def cli_environment(environment, monkeypatch):
    root, settings, store, service, project = environment
    monkeypatch.chdir(root)
    monkeypatch.setenv("DOCSYNC_DATA_DIR", str(settings.data_dir))
    monkeypatch.setattr("sys.stdin", io.StringIO())
    monkeypatch.setattr(terminal, "Worker", lambda config: Worker(config, MemoryRetriever(store), ScriptedLLM))
    return environment


def prepare_proposal(env):
    root, _, _, service, project = env
    main(["init"])
    (root / "api.py").write_text("def list_items(limit=20):\n    return []\n\n", encoding="utf-8")
    main(["scan"])
    return service.proposals(project["id"])[0]


def test_cli_scan_review_and_apply_without_api(cli_environment, capsys):
    root, settings, store, _, _ = cli_environment
    p = prepare_proposal(cli_environment)
    assert "limit is 10" in (root / "docs/api.md").read_text()
    main(["proposals"])
    main(["review", p["id"][:12], "--show"])
    assert "Evidence: api.py:1-3" in capsys.readouterr().out
    assert store.get("proposal", p["id"])["state"] == "pending"
    main(["review", p["id"], "--accept"])
    assert "limit is 20" in (root / "docs/api.md").read_text()
    assert "Keep this human-written section." in (root / "docs/api.md").read_text()
    assert (settings.data_dir / "backups" / p["id"] / "original.md").exists()
    assert store.get("proposal", p["id"])["state"] == "accepted"


def test_cli_preview_reject_and_repeat_scan(cli_environment):
    root, _, store, service, project = cli_environment
    p = prepare_proposal(cli_environment)
    main(["review"])
    assert store.get("proposal", p["id"])["state"] == "pending"
    main(["review", "--reject"])
    main(["scan"])
    assert len(service.proposals(project["id"])) == 1
    assert store.get("proposal", p["id"])["state"] == "rejected"
    assert "limit is 10" in (root / "docs/api.md").read_text()


def test_cli_stale_approval_fails_without_overwrite(cli_environment):
    root, _, store, _, _ = cli_environment
    p = prepare_proposal(cli_environment)
    (root / "docs/api.md").write_text("# Human edit\nKeep me.\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["review", p["id"], "--accept"])
    assert exc.value.code == 1
    assert store.get("proposal", p["id"])["state"] == "superseded"
    assert (root / "docs/api.md").read_text() == "# Human edit\nKeep me.\n"


def test_cli_apply_edited_file(cli_environment):
    root, _, store, _, _ = cli_environment
    p = prepare_proposal(cli_environment)
    edit = root / "edited.md"
    edit.write_text("# API\nReviewed by a developer.\n", encoding="utf-8")
    main(["review", p["id"], "--file", str(edit)])
    assert (root / "docs/api.md").read_text() == edit.read_text()
    assert store.get("proposal", p["id"])["applied_content"] == edit.read_text()


def test_cli_config_cloud_opt_in_and_revoke(cli_environment, capsys):
    _, _, store, _, project = cli_environment
    with pytest.raises(SystemExit) as exc:
        main(["config", "--provider", "gemini"])
    assert exc.value.code == 1
    assert store.get("project", project["id"])["provider"] == "local"
    main(["config", "--provider", "gemini", "--allow-cloud"])
    assert store.get("project", project["id"])["cloud_consent"] is True
    assert "sends selected source code" in capsys.readouterr().out
    main(["config", "--provider", "local"])
    assert store.get("project", project["id"])["cloud_consent"] is False


def test_cli_repeat_init_preserves_baseline(cli_environment):
    root, _, store, _, project = cli_environment
    main(["init"])
    baseline = store.get("project", project["id"])["last_snapshot"]
    (root / "api.py").write_text("def list_items(limit=20):\n    return []\n")
    main(["init"])
    assert store.get("project", project["id"])["last_snapshot"] == baseline


def test_cli_failure_is_nonzero_and_syntax_is_reported(cli_environment, capsys):
    root, _, _, _, _ = cli_environment
    (root / "api.py").write_text("def broken(\n")
    with pytest.raises(SystemExit) as exc:
        main(["init"])
    assert exc.value.code == 1
    assert "Waiting for valid Python syntax" in capsys.readouterr().out


def test_root_discovery_and_state_from_subdirectory(cli_environment, monkeypatch):
    root, _, _, _, _ = cli_environment
    subdir = root / "src"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    monkeypatch.delenv("DOCSYNC_DATA_DIR")
    assert terminal.repository_root() == root.resolve()
    _, settings, _, _, project = terminal.context(argparse.Namespace(project=None, data_dir=None))
    assert settings.data_dir == root / ".docsync"
    assert project is None


def test_cli_missing_registration_and_explicit_state(cli_environment, tmp_path, capsys):
    state = tmp_path / "new state"
    with pytest.raises(SystemExit):
        main(["status", "--data-dir", str(state)])
    assert "docsync init" in capsys.readouterr().out
    main(["status"])
    assert "Project:" in capsys.readouterr().out


def test_cli_proposal_id_scoped_to_project(cli_environment):
    _, _, store, service, project = cli_environment
    store.put("proposal", {"id": "foreign", "project_id": "other", "created": 1, "state": "pending"})
    with pytest.raises(ValueError, match="unknown or ambiguous"):
        terminal.select_proposal(service, project, "foreign")


def test_cli_help_and_control_characters(capsys):
    main([])
    assert "watch" in capsys.readouterr().out
    terminal.say("before\x1b[2Jafter\x07")
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out


def test_cli_new_registration_and_initial_draft(cli_environment, monkeypatch):
    root, _, store, service, _ = cli_environment
    # Remove only the fixture's registration; simulate a never-connected repository.
    with store.connect() as db:
        db.execute("DELETE FROM objects WHERE kind='project'")
        db.execute("DELETE FROM jobs")
    class OverviewLLM(ScriptedLLM):
        async def structured(self, project_id, prompt, schema):
            if schema is Decision:
                return Decision(action="draft", summary="Prepare initial overview")
            return Draft(content="# Overview\nUse `list_items()`.\n", summary="Overview",
                         symbols=["list_items"], citations=[dict(path="api.py", start=1, end=3)])
    monkeypatch.setattr(terminal, "Worker", lambda config: Worker(config, MemoryRetriever(store), OverviewLLM))
    main(["init"])
    main(["draft"])
    project = store.all("project")[0]
    p = service.proposals(project["id"])[0]
    assert p["path"] == "docs/overview.md"
    assert not (root / p["path"]).exists()
    main(["review", "--accept"])
    assert (root / p["path"]).read_text() == p["content"]


async def test_watch_reports_existing_worker(environment):
    _, settings, store, _, project = environment
    with FileLock(str(settings.data_dir / "worker.lock")):
        with pytest.raises(ValueError, match="worker already"):
            await terminal.watch(settings, store, project)


async def test_one_shot_waits_for_existing_worker(environment):
    import asyncio

    _, settings, store, _, project = environment
    job = store.jobs(project["id"])[0]
    async def finish():
        await asyncio.sleep(0.05)
        store.update_job(job["id"], state="complete", message="Another worker completed this job")
    with FileLock(str(settings.data_dir / "worker.lock")):
        task = asyncio.create_task(finish())
        result = await terminal.run_job(settings, store, project, job)
        await task
    assert result["state"] == "complete"


async def test_one_shot_recovers_running_job(environment):
    _, settings, store, _, project = environment
    job = store.claim()
    worker = Worker(settings, MemoryRetriever(store), ScriptedLLM)
    result = await terminal.run_job(settings, store, project, job, worker)
    assert result["state"] == "complete"
    assert store.get("project", project["id"])["last_snapshot"] == capture(project, settings)["id"]


def test_editor_path_with_spaces_and_cancel_does_not_apply(cli_environment, monkeypatch):
    _, _, store, _, _ = cli_environment
    p = prepare_proposal(cli_environment)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setenv("VISUAL", '"C:/Program Files/Editor/editor.exe" --wait')
    called = []
    def edit(command, **kwargs):
        called.append(command)
        Path(command[-1]).write_text("# Edited\nReview me.\n")
        return argparse.Namespace(returncode=0)
    monkeypatch.setattr(terminal.subprocess, "run", edit)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    main(["review", p["id"], "--edit"])
    assert called[0][0] == "C:/Program Files/Editor/editor.exe"
    assert called[0][1] == "--wait"
    assert store.get("proposal", p["id"])["state"] == "pending"
