import subprocess

import pytest

from docsync.config import Settings
from docsync.models import ProjectCreate
from docsync.service import Service
from docsync.store import Store


@pytest.fixture
def environment(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "api.py").write_text('def list_items(limit: int = 10):\n    """Return items."""\n    return list(range(limit))\n', encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "api.md").write_text("# API\n\n## list_items\nThe default limit is 10.\n\n## Deployment\nKeep this human-written section.\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "state")
    store = Store(settings)
    service = Service(settings, store)
    project = service.register(ProjectCreate(root=str(root)))
    return root, settings, store, service, project

