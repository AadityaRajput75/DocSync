"""Exercise an installed npm CLI with a local simulated Ollama server, never a live LLM."""
import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ModelServer(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, body):
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.reply({"models": [{"name": name, "digest": "smoke-test-model"} for name in
                               ("nomic-embed-text:v1.5", "qwen2.5-coder:3b")]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/embed":
            data = hashlib.sha256(body["input"].encode()).digest()
            self.reply({"embeddings": [[v / 255 for v in data[:16]]]})
            return
        if "action" in body["format"].get("properties", {}):
            result = {"action": "draft", "summary": "Document greet"}
        else:
            prompt = body["messages"][-1]["content"]
            default = "friend" if "friend" in prompt else "world"
            result = {"content": f"# Overview\n\n## greet\nThe default name is {default}.\n",
                      "summary": "Document the default", "symbols": ["greet"],
                      "citations": [{"path": "example.py", "start": 1, "end": 2}]}
        self.reply({"message": {"content": json.dumps(result)}, "done_reason": "stop"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", type=Path, required=True, help="Installed docsync command")
    parser.add_argument("--runtime-home", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="installed-cli-", dir=args.work_dir) as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            code = root / "example.py"
            code.write_text('def greet(name="world"):\n    return f"Hello {name}"\n', encoding="utf-8")
            # A repository module must not shadow the installed tool or execute during startup.
            (root / "docsync.py").write_text('raise RuntimeError("Repository code was executed")\n')
            env = {**os.environ, "DOCSYNC_RUNTIME_HOME": str(args.runtime_home.resolve()),
                   "DOCSYNC_DATA_DIR": str(root / ".docsync"), "DOCSYNC_QDRANT_MODE": "embedded",
                   "DOCSYNC_OLLAMA_URL": f"http://127.0.0.1:{server.server_port}"}
            env.pop("GEMINI_API_KEY", None)

            def cli(*arguments, expected=0):
                result = subprocess.run([str(args.command.resolve()), *arguments], cwd=root, env=env,
                                        stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                        encoding="utf-8", timeout=240)
                if result.returncode != expected:
                    raise AssertionError(result.stdout + result.stderr)
                return result.stdout

            cli("run", "--provider", "local", "--no-watch", "--yes")
            assert not (root / "docs/overview.md").exists()
            assert "pending" in cli("proposals")
            assert "Evidence:" in cli("review", "--show")
            cli("review", "--accept")
            assert "world" in (root / "docs/overview.md").read_text()
            code.write_text('def greet(name="friend"):\n    return f"Hello {name}"\n', encoding="utf-8")
            cli("scan")
            cli("review", "--accept")
            assert "friend" in (root / "docs/overview.md").read_text()
            with contextlib.closing(sqlite3.connect(root / ".docsync/state.sqlite3")) as db:
                proposals = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE kind='proposal'")]
            assert len(proposals) == 2 and all(p["state"] == "accepted" for p in proposals)
            assert not (root / ".venv").exists()
            print("Installed npm CLI passed: setup, embedded retrieval, real MCP, proposal review, approval, "
                  "changed-code update, and repository-module isolation. Model responses were simulated.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
