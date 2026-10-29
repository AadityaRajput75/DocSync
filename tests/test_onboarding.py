import io

import httpx
import pytest
from helpers import FakeEmbeddings, MemoryRetriever, ScriptedLLM

from docsync import onboarding, terminal
from docsync.cli import main
from docsync.models import Decision, Draft
from docsync.repository import capture
from docsync.retrieval import Retriever
from docsync.worker import Worker


def mock_ollama(monkeypatch, settings, installed=(), failure=False):
    requests = []
    original = httpx.Client
    def respond(request):
        requests.append(request)
        if failure:
            return httpx.Response(500)
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={"models": [{"name": n} for n in installed]})
        return httpx.Response(200, json={"status": "success"})
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr("sys.stdin", io.StringIO())
    return requests


def test_setup_installed_models_never_download(environment, monkeypatch):
    _, settings, _, _, _ = environment
    requests = mock_ollama(monkeypatch, settings, (settings.model, settings.embed_model))
    onboarding.setup_models(settings, "local")
    assert [r.method for r in requests] == ["GET"]


def test_setup_downloads_only_embeddings_for_gemini(environment, monkeypatch):
    _, settings, _, _, _ = environment
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    requests = mock_ollama(monkeypatch, settings)
    onboarding.setup_models(settings, "gemini", yes=True)
    assert len(requests) == 2
    assert settings.embed_model.encode() in requests[-1].content
    assert all("test-key" not in str(r.headers) for r in requests)


def test_setup_requires_download_consent(environment, monkeypatch):
    _, settings, _, _, _ = environment
    requests = mock_ollama(monkeypatch, settings)
    with pytest.raises(ValueError, match="declined"):
        onboarding.setup_models(settings, "local")
    assert len(requests) == 1


def test_setup_missing_service_is_actionable(environment, monkeypatch):
    _, settings, _, _, _ = environment
    mock_ollama(monkeypatch, settings, failure=True)
    with pytest.raises(ValueError, match="Ollama is not ready"):
        onboarding.setup_models(settings, "local", yes=True)


def test_setup_missing_key_precedes_network(environment, monkeypatch):
    _, settings, _, _, _ = environment
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    requests = mock_ollama(monkeypatch, settings)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        onboarding.setup_models(settings, "gemini", yes=True)
    assert requests == []


def test_setup_rejects_cloud_ollama(environment, monkeypatch):
    _, settings, _, _, _ = environment
    settings.model = "example:cloud"
    requests = mock_ollama(monkeypatch, settings, (settings.embed_model,))
    with pytest.raises(ValueError, match="cloud model"):
        onboarding.setup_models(settings, "local", yes=True)
    assert len(requests) == 1


async def test_embedded_retrieval_survives_reopen(environment):
    _, settings, store, _, project = environment
    settings.qdrant_mode = "embedded"
    snapshot = capture(project, settings)
    first = Retriever(settings, store, embeddings=FakeEmbeddings())
    second = Retriever(settings, store, embeddings=FakeEmbeddings())
    assert first._client is None and second._client is None
    try:
        await first.index(snapshot)
        first.close()
        results = await second.search(snapshot, "list_items")
        assert any(r["path"] == "api.py" for r in results)
    finally:
        first.close()
        second.close()


def test_run_initializes_drafts_and_does_not_repeat_pending_overview(environment, monkeypatch):
    root, settings, store, service, project = environment
    monkeypatch.chdir(root)
    monkeypatch.setenv("DOCSYNC_DATA_DIR", str(settings.data_dir))
    monkeypatch.setattr("sys.stdin", io.StringIO())
    monkeypatch.setattr(onboarding, "setup_models", lambda *a: None)
    class Overview(ScriptedLLM):
        async def structured(self, project_id, prompt, schema):
            if schema is Decision:
                return Decision(action="draft", summary="Initial overview")
            return Draft(content="# Overview\nUse `list_items()`.\n", summary="Overview",
                         citations=[dict(path="api.py", start=1, end=3)], symbols=["list_items"])
    monkeypatch.setattr(terminal, "Worker", lambda config: Worker(config, MemoryRetriever(store), Overview))
    main(["run", "--no-watch"])
    main(["run", "--no-watch"])
    assert len(service.proposals(project["id"])) == 1
    assert service.proposals(project["id"])[0]["state"] == "pending"
    assert not (root / "docs/overview.md").exists()


def test_yes_does_not_grant_cloud_consent(environment, monkeypatch):
    root, settings, store, _, project = environment
    monkeypatch.chdir(root)
    monkeypatch.setenv("DOCSYNC_DATA_DIR", str(settings.data_dir))
    monkeypatch.setattr("sys.stdin", io.StringIO())
    with pytest.raises(SystemExit):
        main(["run", "--provider", "gemini", "--yes", "--no-watch"])
    assert not store.get("project", project["id"])["cloud_consent"]
