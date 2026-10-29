import json

import httpx
import pytest
from helpers import MemoryRetriever, ScriptedLLM
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docsync.config import local_url
from docsync.llm import LLM
from docsync.models import Decision
from docsync.worker import Worker


async def test_missing_service_no_cloud_fallback(environment):
    _, settings, store, _, _ = environment
    class BrokenRetriever:
        async def index(self, snapshot):
            raise httpx.ConnectError("unavailable")
    worker = Worker(settings, BrokenRetriever())
    job = store.claim()
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "cp.db")) as saver:
        await worker.process(job, saver)
    result = store.job(job["id"])
    assert result["state"] == "failed"
    assert "no cloud fallback" in result["message"]


async def test_tool_budget(environment):
    root, settings, store, _, project = environment
    class EndlessToolLLM(ScriptedLLM):
        async def structured(self, project_id, prompt, schema):
            return Decision(action="tool", summary="Inspect", tool="list_tree", arguments={})
    worker = Worker(settings, MemoryRetriever(store), EndlessToolLLM)
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "cp.db")) as saver:
        await worker.process(store.claim(), saver)
        (root / "api.py").write_text("def list_items(limit=20):\n    return []\n")
        store.enqueue(project["id"], "scan")
        job = store.claim()
        await worker.process(job, saver)
        result = store.job(job["id"])
        assert result["state"] == "insufficient_evidence", result
        assert len([a for a in result["activity"] if a.get("tool")]) == 6


async def test_consent_rechecked_before_every_call(environment, monkeypatch):
    _, settings, store, _, project = environment
    store.patch("project", project["id"], provider="gemini", cloud_consent=False)
    llm = LLM(settings, store)
    with pytest.raises(ValueError, match="consent"):
        await llm.structured(project["id"], "task", Decision)


@pytest.mark.parametrize("url", ["https://api.example.com", "http://192.168.1.1:11434", "http://localhost@evil.example", "http://localhost:11434?key=abc"])
def test_local_endpoints_cannot_be_remote(url):
    with pytest.raises(ValueError):
        local_url(url)


async def test_changes_during_generation_supersede(environment):
    root, settings, store, service, project = environment
    class EditingLLM(ScriptedLLM):
        async def structured(self, project_id, prompt, schema):
            result = await super().structured(project_id, prompt, schema)
            if schema != Decision:
                (root / "api.py").write_text("def list_items(limit=30):\n    return []\n")
            return result
    worker = Worker(settings, MemoryRetriever(store), EditingLLM)
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "cp.db")) as saver:
        await worker.process(store.claim(), saver)
        (root / "api.py").write_text('def list_items(limit=20):\n    """Return items."""\n    return []\n')
        store.enqueue(project["id"], "scan")
        job = store.claim()
        await worker.process(job, saver)
        assert store.job(job["id"])["state"] == "superseded"
        assert all(p["state"] == "superseded" for p in service.proposals(project["id"]))
        assert any(j["state"] == "queued" for j in store.jobs(project["id"]))


def test_fixtures_are_thirty_unique_annotated_cases():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "eval/cases.json").read_text())
    assert len(cases) == len({case["id"] for case in cases}) == 30
    assert {case["repo"] for case in cases} == {"shop_api", "task_api"}
    assert sum(not case["requires_update"] for case in cases) == 6
    import ast
    for case in cases:
        text = (root / "examples" / case["repo"] / case["path"]).read_text()
        assert text.count(case["before"]) == 1
        ast.parse(text.replace(case["before"], case["after"]))
