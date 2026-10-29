import json

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import FakeEmbeddings, MemoryRetriever, ScriptedLLM
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from qdrant_client import QdrantClient

from docsync.agent import repository_session
from docsync.api import create_app
from docsync.llm import LLM
from docsync.mcp_server import RepositoryTools
from docsync.models import Decision, Review
from docsync.repository import capture
from docsync.retrieval import Retriever
from docsync.worker import Worker


async def test_real_mcp_stdio_and_isolation(environment):
    _, settings, store, _, project = environment
    snapshot = capture(project, settings)
    store.put("snapshot", snapshot)
    async with repository_session(settings) as session:
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == {"list_tree", "read_file", "search_text", "find_symbol", "get_related_symbols"}
        result = await session.call_tool("read_file", {"project_id": project["id"], "snapshot_id": snapshot["id"],
                                                      "path": "api.py", "start": 1, "end": 3})
        assert not result.isError
        assert "list_items" in result.content[0].text
        bad = await session.call_tool("read_file", {"project_id": project["id"], "snapshot_id": snapshot["id"],
                                                   "path": "../api.py"})
        assert bad.isError
    store.put("project", {**project, "id": "another"})
    with pytest.raises(ValueError, match="another project"):
        RepositoryTools(store).snapshot("another", snapshot["id"])


async def test_qdrant_hybrid_filters_snapshot(environment):
    root, settings, store, _, project = environment
    retriever = Retriever(settings, store, FakeEmbeddings(), QdrantClient(":memory:"))
    first = capture(project, settings)
    await retriever.index(first)
    (root / "api.py").write_text("def totally_new():\n    return 5\n")
    second = capture(project, settings)
    await retriever.index(second)
    hits = await retriever.search(second, "totally_new")
    assert hits
    assert not any("def list_items" in hit["text"] for hit in hits)
    assert any("totally_new" in hit["text"] for hit in hits)


async def test_complete_worker_mcp_graph_review_and_resume(environment):
    root, settings, store, service, project = environment
    worker = Worker(settings, MemoryRetriever(store), lambda: ScriptedLLM(tool=True))
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "test-checkpoints.db")) as saver:
        await worker.process(store.claim(), saver)
        (root / "api.py").write_text('def list_items(limit: int = 20):\n    """Return items."""\n    return list(range(limit))\n')
        store.enqueue(project["id"], "scan")
        job = store.claim()
        await worker.process(job, saver)
        finished = store.job(job["id"])
        assert finished["state"] == "awaiting_review", finished
        assert any(a.get("tool") == "read_file" for a in finished["activity"])
        proposals = service.proposals(project["id"])
        assert len(proposals) == 1
        # Review interrupt is durable across a fresh worker/graph instance.
        service.review(proposals[0]["id"], Review(decision="accept"))
        while next_job := store.claim():
            await worker.process(next_job, saver)
        assert store.job(job["id"])["state"] == "reviewed"
        assert "default limit is 20" in (root / "docs/api.md").read_text()
        assert "Keep this human-written section." in (root / "docs/api.md").read_text()


async def test_no_update_and_syntax_postponement(environment):
    root, settings, store, _, project = environment
    worker = Worker(settings, MemoryRetriever(store), lambda: ScriptedLLM(action="no_update"))
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "checkpoint.db")) as saver:
        await worker.process(store.claim(), saver)
        (root / "api.py").write_text("def broken(\n")
        store.enqueue(project["id"], "scan")
        job = store.claim()
        await worker.process(job, saver)
        assert store.job(job["id"])["state"] == "postponed"
        (root / "api.py").write_text("def list_items(limit=10):\n    values = list(range(limit))\n    return values\n")
        store.enqueue(project["id"], "scan")
        job = store.claim()
        await worker.process(job, saver)
        assert store.job(job["id"])["state"] == "no_update"
        assert not store.all("proposal")


def test_api_consent_origin_and_jobs(environment):
    root, settings, _, _, project = environment
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.patch(f"/projects/{project['id']}", json={"provider": "gemini"}).status_code == 400
        assert client.patch(f"/projects/{project['id']}", json={"provider": "gemini", "cloud_consent": True}).status_code == 200
        assert client.post(f"/projects/{project['id']}/scan").status_code == 202
        assert client.post(f"/projects/{project['id']}/scan", headers={"origin": "https://evil.example"}).status_code == 403
        assert client.get("/projects/missing/status").status_code == 404


async def test_llm_one_retry_and_no_secret_error(environment, monkeypatch):
    _, settings, store, _, project = environment
    llm = LLM(settings, store)
    calls = []
    async def generate(*args):
        calls.append(1)
        return "not json"
    monkeypatch.setattr(llm, "generate", generate)
    with pytest.raises(ValueError, match="twice"):
        await llm.structured(project["id"], "task", Decision)
    assert len(calls) == 2


async def test_local_provider_network_destinations(environment, monkeypatch):
    _, settings, store, _, project = environment
    original = httpx.AsyncClient
    destinations = []
    def respond(request):
        destinations.append(str(request.url))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": settings.model}]})
        return httpx.Response(200, json={"message": {"content": json.dumps({"action": "no_update", "summary": "Same behavior"})}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    result = await LLM(settings, store).structured(project["id"], "task", Decision)
    assert result.action == "no_update"
    assert destinations == ["http://127.0.0.1:11434/api/tags", "http://127.0.0.1:11434/api/chat"]


def test_durable_job_recovery(environment):
    _, _, store, _, _ = environment
    job = store.claim()
    assert job["state"] == "running"
    store.recover()
    assert store.claim()["id"] == job["id"]
