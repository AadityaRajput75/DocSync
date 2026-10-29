"""Initialize the bundled examples as local Git repositories (never commit automatically)."""
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ("shop_api", "task_api"):
    path = root / "examples" / name
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    print(path)
