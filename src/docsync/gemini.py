"""Gemini discovery without repository content or credential logging."""
import os
import re

import httpx

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def model_identifier(value):
    value = value.strip().removeprefix("models/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", value):
        raise ValueError("Invalid Gemini model identifier; use a name from 'uv run docsync models'")
    return value


def key_headers():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in this terminal/worker environment")
    return {"x-goog-api-key": key}


async def list_generation_models():
    headers = key_headers()
    names, seen = set(), set()
    page_token = None
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        while True:
            params = {"pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            response = await client.get(BASE_URL + "/models", headers=headers, params=params)
            response.raise_for_status()
            body = response.json()
            for model in body.get("models", []):
                if "generateContent" in model.get("supportedGenerationMethods", []):
                    names.add(model_identifier(model["name"]))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
            if page_token in seen or len(seen) >= 100:
                raise ValueError("Unexpected pagination from Gemini model discovery")
            seen.add(page_token)
    return sorted(names)


def service_http_error(exc):
    """Use known URL fields, never response bodies, headers, queries, or API keys."""
    status = exc.response.status_code
    host, path = exc.request.url.host, exc.request.url.path
    if host == "generativelanguage.googleapis.com":
        match = re.search(r"/models/([A-Za-z0-9._-]+):generateContent$", path)
        model = match.group(1) if match else "model discovery"
        prefix = f"Gemini returned HTTP {status} for {model}. "
        if status == 404:
            return prefix + "Check availability with 'uv run docsync models', set DOCSYNC_GEMINI_MODEL to a listed text model, and restart DocSync."
        if status in {401, 403}:
            return prefix + "Check the API key, project permissions, and API restrictions in Google AI Studio."
        if status == 429:
            return prefix + "The API quota or rate limit was reached. Check your Gemini usage and retry later."
        if status == 400:
            return prefix + "Check the API key and whether the model supports this structured-output request."
        return prefix + "Check Gemini service status and configuration."
    if path.startswith("/api/"):
        if status == 404 and path == "/api/embed":
            return "Ollama embeddings returned HTTP 404. Check that nomic-embed-text:v1.5 is downloaded and your Ollama version supports /api/embed."
        return f"Ollama returned HTTP {status}. Check the downloaded model and local service configuration."
    return f"Retrieval service returned HTTP {status}. Check Qdrant and its configured URL."
