import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def local_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Local services must use an HTTP loopback address")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Unexpected credentials or parameters in local service URL")
    return value.rstrip("/")


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DOCSYNC_DATA_DIR", ".docsync")).resolve())
    ollama_url: str = field(default_factory=lambda: local_url(os.getenv("DOCSYNC_OLLAMA_URL", "http://127.0.0.1:11434")))
    qdrant_url: str = field(default_factory=lambda: local_url(os.getenv("DOCSYNC_QDRANT_URL", "http://127.0.0.1:6333")))
    qdrant_mode: str = field(default_factory=lambda: os.getenv("DOCSYNC_QDRANT_MODE", "server"))
    model: str = field(default_factory=lambda: os.getenv("DOCSYNC_MODEL", "qwen2.5-coder:3b"))
    embed_model: str = field(default_factory=lambda: os.getenv("DOCSYNC_EMBED_MODEL", "nomic-embed-text:v1.5"))
    gemini_model: str = field(default_factory=lambda: os.getenv("DOCSYNC_GEMINI_MODEL", "gemini-3.5-flash-lite"))
    max_files: int = 2000
    max_file_bytes: int = 1_000_000
    debounce: float = 3.0
    max_tools: int = 6
    context_chars: int = 24_000
    job_timeout: float = 900.0

    def prepare(self):
        if self.qdrant_mode not in {"server", "embedded"}:
            raise ValueError("DOCSYNC_QDRANT_MODE must be server or embedded")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["ANONYMIZED_TELEMETRY"] = "false"
