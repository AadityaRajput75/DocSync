from helpers import MemoryRetriever, ScriptedLLM
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docsync.models import Decision, Draft, Review
from docsync.worker import Worker


async def test_initial_overview_then_no_overwrite(environment):
    root, settings, store, service, project = environment
    (root / "docs/api.md").unlink()
    class OverviewLLM(ScriptedLLM):
        async def structured(self, project_id, prompt, schema):
            if schema is Decision:
                return Decision(action="draft", summary="Create project overview")
            return Draft(content="# Project overview\n\nThe `list_items()` function returns item identifiers.\n",
                         summary="Explain the available entry point", symbols=["list_items"],
                         citations=[{"path": "api.py", "start": 1, "end": 3}])
    worker = Worker(settings, MemoryRetriever(store), OverviewLLM)
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "cp.db")) as saver:
        await worker.process(store.claim(), saver)
        store.enqueue(project["id"], "bootstrap")
        await worker.process(store.claim(), saver)
        proposal = service.proposals(project["id"])[0]
        assert proposal["path"] == "docs/overview.md"
        service.review(proposal["id"], Review(decision="accept"))
        while job := store.claim():
            await worker.process(job, saver)
        store.enqueue(project["id"], "bootstrap")
        job = store.claim()
        await worker.process(job, saver)
        assert store.job(job["id"])["state"] == "no_update"
        assert len(service.proposals(project["id"])) == 1


async def test_reject_suppresses_identical_revision(environment):
    root, settings, store, service, project = environment
    worker = Worker(settings, MemoryRetriever(store), ScriptedLLM)
    async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "cp.db")) as saver:
        await worker.process(store.claim(), saver)
        (root / "api.py").write_text('def list_items(limit=20):\n    """Return items."""\n    return []\n')
        store.enqueue(project["id"], "scan")
        await worker.process(store.claim(), saver)
        proposal = service.proposals(project["id"])[0]
        service.review(proposal["id"], Review(decision="reject"))
        while job := store.claim():
            await worker.process(job, saver)
        store.enqueue(project["id"], "scan")
        job = store.claim()
        await worker.process(job, saver)
        assert store.job(job["id"])["state"] == "no_update"
        assert len(service.proposals(project["id"])) == 1
