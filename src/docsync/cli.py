import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from docsync.config import Settings
from docsync.gemini import list_generation_models, model_identifier, service_http_error


def doctor(settings):
    services = [("Ollama", settings.ollama_url + "/api/tags")]
    if settings.qdrant_mode == "server":
        services.append(("Qdrant", settings.qdrant_url + "/collections"))
    else:
        print("Qdrant: embedded local storage (no Docker required)")
    for name, url in services:
        try:
            response = httpx.get(url, timeout=5, trust_env=False)
            response.raise_for_status()
            print(f"{name}: reachable")
            if name == "Ollama":
                names = [m["name"] for m in response.json()["models"]]
                for model in (settings.model, settings.embed_model):
                    print(f"  {model}: {'installed' if model in names else 'missing — ollama pull ' + model}")
        except Exception:
            print(f"{name}: unavailable")
    print(f"State directory: {settings.data_dir}")
    print("Cloud: disabled unless explicitly enabled per project; Gemini key " +
          ("present" if os.getenv("GEMINI_API_KEY") else "absent"))
    print(f"Configured Gemini model: {settings.gemini_model}")


async def models(settings):
    try:
        names = await list_generation_models()
        current = model_identifier(settings.gemini_model)
        print("Models advertising generateContent for this key (quota and structured-output support still apply):")
        for name in names:
            print(f"  {name}" + (" [configured]" if name == current else ""))
        if current not in names:
            print(f"Configured model {current} is not in this list. Set DOCSYNC_GEMINI_MODEL and restart.")
    except httpx.HTTPStatusError as exc:
        print(service_http_error(exc))
        raise SystemExit(1) from None
    except httpx.RequestError:
        print("Cannot reach Gemini model discovery. Check your network connection.")
        raise SystemExit(1) from None
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1) from None


def main(argv=None):
    from docsync.terminal import add_commands, dispatch

    parser = argparse.ArgumentParser(prog="docsync", description="Local documentation proposals with review")
    commands = parser.add_subparsers(dest="command")
    add_commands(commands)
    for command in ("start", "api", "worker", "ui", "doctor", "models"):
        commands.add_parser(command, help={"start": "Start the optional browser dashboard and backend",
            "api": "Run the FastAPI server", "worker": "Run the background worker",
            "ui": "Run the optional Streamlit dashboard", "doctor": "Check local services and models",
            "models": "List Gemini generation models"}[command])
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    try:
        if dispatch(args):
            return
    except KeyboardInterrupt:
        print("\nStopped. Saved jobs and proposals remain available.")
        raise SystemExit(130) from None
    except EOFError:
        print("Input closed. No approval was given; use explicit command options for non-interactive operation.")
        raise SystemExit(1) from None
    except (ValueError, KeyError, OSError) as exc:
        from docsync.terminal import say
        say(f"Error: {exc}")
        raise SystemExit(1) from None
    settings = Settings()
    settings.prepare()
    os.environ["DOCSYNC_DATA_DIR"] = str(settings.data_dir)
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    if args.command == "doctor":
        doctor(settings)
    elif args.command == "models":
        asyncio.run(models(settings))
    elif args.command == "api":
        import uvicorn
        uvicorn.run("docsync.api:create_app", factory=True, host="127.0.0.1", port=8000)
    elif args.command == "worker":
        from docsync.worker import Worker
        asyncio.run(Worker(settings).run())
    elif args.command == "ui":
        subprocess.run([sys.executable, "-I", "-m", "streamlit", "run", str(Path(__file__).with_name("ui.py")),
                        "--server.address=127.0.0.1", "--server.headless=true",
                        "--browser.gatherUsageStats=false"], check=True)
    else:
        children = []
        try:
            for command in ("api", "worker", "ui"):
                children.append(subprocess.Popen([sys.executable, "-I", "-m", "docsync.cli", command]))
            print("DocSync: http://127.0.0.1:8501 — press Ctrl+C to stop")
            while all(p.poll() is None for p in children):
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            for child in children:
                if child.poll() is None:
                    # Windows /T closes the Streamlit child as well as the launcher process.
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
                    else:
                        child.terminate()
            for child in children:
                child.wait(timeout=15)


if __name__ == "__main__":
    main()
