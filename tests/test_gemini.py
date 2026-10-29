import json

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docsync.gemini import list_generation_models, model_identifier, service_http_error
from docsync.llm import LLM
from docsync.models import Decision
from docsync.worker import Worker


async def test_model_discovery_pages_filters_and_never_sends_source(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert not request.content
        assert request.headers["x-goog-api-key"] == "test-key-not-real"
        assert "test-key-not-real" not in str(request.url)
        if request.url.params.get("pageToken"):
            return httpx.Response(200, json={"models": [{"name": "models/gemini-3.8-flash",
                "supportedGenerationMethods": ["generateContent"]}]})
        return httpx.Response(200, json={"models": [
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]}],
            "nextPageToken": "next-page"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    assert await list_generation_models() == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert len(requests) == 2


@pytest.mark.parametrize("value", ["models/../../secret", "https://example.com", "gemini?key=secret"])
def test_model_identifier_rejects_paths(value):
    with pytest.raises(ValueError):
        model_identifier(value)


async def test_gemini_request_prefix_schema_and_usage(environment, monkeypatch):
    _, settings, store, _, project = environment
    store.patch("project", project["id"], provider="gemini", cloud_consent=True)
    settings.gemini_model = "models/gemini-3.5-flash-lite"
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    original = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url).endswith("/models/gemini-3.5-flash-lite:generateContent")
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["type"] == "object"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": json.dumps({"action": "no_update", "summary": "Unchanged behavior"})}]}}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 6}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    llm = LLM(settings, store)
    result = await llm.structured(project["id"], "A test prompt", Decision)
    assert result.action == "no_update"
    assert len(calls) == 1
    assert llm.usage == {"calls": 1, "input_tokens": 5, "output_tokens": 6}


@pytest.mark.parametrize("status", [400, 403, 404, 429])
def test_errors_identify_gemini_without_echoing_credentials(status):
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=test-secret",
                            headers={"x-goog-api-key": "test-secret"})
    response = httpx.Response(status, json={"error": {"message": "echoed key test-secret"}}, request=request)
    exc = httpx.HTTPStatusError("untrusted error test-secret", request=request, response=response)
    message = service_http_error(exc)
    assert "Gemini" in message and str(status) in message
    assert "gemini-2.5-flash" in message
    assert "test-secret" not in message
    if status == 404:
        assert "docsync models" in message


async def test_worker_records_actionable_404(environment):
    _, settings, store, _, _ = environment
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent")
    response = httpx.Response(404, request=request)

    class FailingService:
        async def index(self, snapshot):
            response.raise_for_status()

    worker = Worker(settings, FailingService())
    job = store.claim()
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "cp.db")) as saver:
        await worker.process(job, saver)
    message = store.job(job["id"])["message"]
    assert "Gemini returned HTTP 404 for gemini-2.5-flash" in message
    assert "DOCSYNC_GEMINI_MODEL" in message


async def test_model_discovery_requires_key_before_network(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        await list_generation_models()
