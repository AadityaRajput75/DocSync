"""First-run experience shared by the npm launcher and Python CLI."""
import asyncio
import os
import sys

import httpx

from docsync.models import ProjectCreate, ProjectPatch


def setup_models(settings, provider, yes=False):
    from docsync.terminal import say

    if provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
        raise ValueError("Set GEMINI_API_KEY in this terminal, then run docsync again. Keys are never stored.")
    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            response = client.get(settings.ollama_url + "/api/tags")
            response.raise_for_status()
            installed = {m["name"]: m for m in response.json().get("models", [])}
    except (httpx.HTTPError, ValueError, KeyError):
        raise ValueError("Ollama is not ready. Install it from https://ollama.com/download, open Ollama "
                         "(or run ollama serve), then run docsync again. Gemini also needs local embeddings.") from None
    required = [settings.embed_model] + ([settings.model] if provider == "local" else [])
    for name in dict.fromkeys(required):
        model = installed.get(name, {})
        if "cloud" in name.lower() or model.get("remote_host") or model.get("remote_model"):
            raise ValueError("Use downloaded local Ollama models; cloud model references are not allowed.")
        if name in installed:
            continue
        say(f"Download required local model: {name}. Downloads may use several GB of disk and bandwidth.")
        allowed = yes or (sys.stdin.isatty() and input("Download this model? [y/N] ").strip().lower() == "y")
        if not allowed:
            raise ValueError(f"Model download declined. Run ollama pull {name}, or docsync run --yes.")
        try:
            with httpx.Client(trust_env=False, timeout=1800) as client:
                result = client.post(settings.ollama_url + "/api/pull", json={"model": name, "stream": False})
                result.raise_for_status()
                body = result.json()
                if body.get("error") or body.get("status") != "success":
                    raise ValueError("Model download was not confirmed")
            say(f"Downloaded {name}.")
        except (httpx.HTTPError, ValueError):
            raise ValueError(f"Could not download {name}. Try ollama pull {name}, then run docsync again.") from None


def run(args, root, settings, store, service, project):
    from docsync.terminal import configure, run_job, say, show_config, watch

    if project is None:
        if not args.provider and sys.stdin.isatty():
            choice = input("Generation provider: [l]ocal Ollama or [g]emini? [l] ").strip().lower()
            if choice not in {"", "l", "local", "g", "gemini"}:
                raise ValueError("Choose local or gemini with --provider.")
            args.provider = "gemini" if choice in {"g", "gemini"} else "local"
        project = service.register(ProjectCreate(root=str(root)))
    project = configure(args, service, project)
    show_config(settings, project)
    setup_models(settings, project["provider"], args.yes)
    say("Keep .docsync/ out of version control; it contains source snapshots and backups.")
    if not project.get("last_snapshot"):
        job = store.enqueue(project["id"], "index")
        asyncio.run(run_job(settings, store, project, job))
    previous = [p for p in service.proposals(project["id"]) if p["path"] == "docs/overview.md"
                and p["state"] in {"pending", "accepted", "rejected"}]
    if not (root / "docs/overview.md").exists() and not previous:
        job = store.enqueue(project["id"], "bootstrap")
        asyncio.run(run_job(settings, store, project, job))
    say("Review proposals in another terminal: docsync review")
    if not args.no_watch:
        project = service.configure(project["id"], ProjectPatch(watching=True))
        asyncio.run(watch(settings, store, project))
