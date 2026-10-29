"""Create a clean source bundle alongside the project, excluding environments and private state."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
destination = root.parent / "DocSync-source.zip"
excluded = {".venv", ".git", ".docsync", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "node_modules"}
with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[:2] == ("npm", "runtime") or relative.as_posix() == "npm/runtime-manifest.json":
            continue
        if not path.is_file() or any(part in excluded for part in relative.parts):
            continue
        if path.name == ".env" or path.suffix in {".pyc", ".log", ".db", ".sqlite3", ".tgz"}:
            continue
        archive.write(path, str(Path("docsync") / relative))
print(destination)
