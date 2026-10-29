import asyncio
import time

import httpx
from filelock import FileLock
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from docsync.agent import Agent, repository_session
from docsync.config import Settings
from docsync.gemini import service_http_error
from docsync.llm import LLM
from docsync.repository import capture, changes
from docsync.retrieval import Retriever
from docsync.service import Service
from docsync.store import Store


class Debouncer(FileSystemEventHandler):
    def __init__(self, delay):
        self.delay = delay
        self.python_at = None
        self.docs_at = None

    def on_any_event(self, event):
        if event.is_directory or event.event_type not in {"created", "modified", "deleted", "moved"}:
            return
        paths = [event.src_path, getattr(event, "dest_path", "")]
        if any(p.endswith(".py") for p in paths):
            self.python_at = time.monotonic()
        elif any(p.endswith(".md") for p in paths):
            self.docs_at = time.monotonic()

    def ready(self, now=None):
        now = now if now is not None else time.monotonic()
        for field, action in (("python_at", "scan"), ("docs_at", "index_docs")):
            value = getattr(self, field)
            if value is not None and now - value >= self.delay:
                setattr(self, field, None)
                yield action


class Worker:
    def __init__(self, settings=None, retriever=None, llm_factory=None, session_factory=None):
        self.settings = settings or Settings()
        self.store = Store(self.settings)
        self.service = Service(self.settings, self.store)
        self.retriever = retriever or Retriever(self.settings, self.store)
        self.llm_factory = llm_factory or (lambda: LLM(self.settings, self.store))
        self.session_factory = session_factory or repository_session

    async def process(self, job, saver):
        try:
            async with asyncio.timeout(self.settings.job_timeout):
                await self._process(job, saver)
        except Exception as exc:
            while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
                exc = exc.exceptions[0]
            # Never persist raw provider response bodies, headers, or credential-bearing exceptions.
            if isinstance(exc, httpx.HTTPStatusError):
                message = service_http_error(exc)
            elif isinstance(exc, (httpx.RequestError, ConnectionError)):
                message = "Cannot reach a required service. Check Ollama and Qdrant; no cloud fallback was used."
            elif isinstance(exc, TimeoutError):
                message = "Job timed out; retry manually or use a smaller change/model."
            elif isinstance(exc, ValueError):
                message = str(exc)[:400]
            else:
                message = f"Job failed ({type(exc).__name__}). Check local services and retry."
            for proposal in self.service.proposals(job["project_id"]):
                if proposal["job_id"] == job["id"] and proposal["state"] == "pending":
                    self.store.patch("proposal", proposal["id"], state="failed")
            self.store.update_job(job["id"], state="failed", message=message, finished=time.time())

    async def _process(self, job, saver):
        project = self.store.get("project", job["project_id"])
        if job["action"] == "resume":
            async with self.session_factory(self.settings) as session:
                graph = Agent(self.settings, self.store, self.retriever, self.llm_factory(), session).build(saver)
                config = {"configurable": {"thread_id": job["thread_id"]}}
                saved = await graph.aget_state(config)
                if saved.next:
                    await graph.ainvoke(Command(resume={"reviewed": True}), config)
                self.store.update_job(job["thread_id"], state="reviewed", message="Review complete")
            self.store.update_job(job["id"], state="complete", message="Review checkpoint resumed")
            return
        current = capture(project, self.settings)
        self.store.put("snapshot", current)
        self.store.patch("project", project["id"], latest_snapshot=current["id"])
        if current["errors"]:
            self.store.update_job(job["id"], state="postponed", message="Waiting for valid Python syntax")
            return
        old = self.store.get("snapshot", project["last_snapshot"]) if project.get("last_snapshot") else None
        changed = changes(old, current)
        self.store.update_job(job["id"], message="Indexing local repository", snapshot_id=current["id"])
        await self.retriever.index(current)
        if job["action"] == "index" or (not old and job["action"] != "bootstrap"):
            self.store.patch("project", project["id"], last_snapshot=current["id"])
            self.store.update_job(job["id"], state="complete", message="Indexed. Initial documentation can now be drafted.")
            return
        if job["action"] == "index_docs":
            self.store.update_job(job["id"], state="complete", message="Documentation index refreshed")
            return
        for proposal in self.service.proposals(project["id"]):
            if proposal["state"] == "pending" and proposal["source_hash"] != current["source_hash"]:
                self.store.patch("proposal", proposal["id"], state="superseded")
                self.service._finish_review(proposal)
        if job["action"] == "bootstrap":
            if "docs/overview.md" in current["files"]:
                self.store.update_job(job["id"], state="no_update", message="An overview already exists; saved code changes update existing documentation")
                return
            changed = [p for p in current["files"] if p.endswith(".py")]
        if not changed and job.get("regenerate"):
            changed = sorted({s for p in self.service.proposals(project["id"]) if p["state"] == "superseded" for s in p["sources"]})
        if not changed:
            self.store.update_job(job["id"], state="no_update", message="No saved Python changes")
            return
        llm = self.llm_factory()
        async with self.session_factory(self.settings) as session:
            graph = Agent(self.settings, self.store, self.retriever, llm, session).build(saver)
            config = {"configurable": {"thread_id": job["id"]}, "recursion_limit": 40}
            saved = await graph.aget_state(config)
            initial = {"job_id": job["id"], "project_id": project["id"], "snapshot_id": current["id"],
                       "old_snapshot_id": old["id"] if old else None, "changed": changed,
                       "bootstrap": job["action"] == "bootstrap", "retrieval_mode": job.get("retrieval_mode", "hybrid")}
            # Interrupted review is already durable; never regenerate it on restart.
            if saved.values and saved.next == ("review",):
                state = saved.values
            else:
                state = await graph.ainvoke(None if saved.values else initial, config)
        snapshot_id = state.get("snapshot_id", current["id"])
        processed = self.store.get("snapshot", snapshot_id)
        latest = capture(project, self.settings)
        pending = state.get("proposals", [])
        if latest["source_hash"] != processed["source_hash"]:
            for proposal_id in pending:
                self.store.patch("proposal", proposal_id, state="superseded")
            self.store.enqueue(project["id"], "scan")
            status, message = "superseded", "New saved changes detected; a fresh investigation was queued"
        elif pending:
            status, message = "awaiting_review", "Documentation updates are ready to review"
        else:
            status = state.get("outcome", "insufficient_evidence")
            message = state.get("decision", {}).get("summary", status)
        if status not in {"insufficient_evidence"}:
            self.store.patch("project", project["id"], last_snapshot=snapshot_id)
        self.store.update_job(job["id"], state=status, message=message, proposals=pending,
                              usage=dict(llm.usage), finished=time.time())

    async def run(self):
        with FileLock(str(self.settings.data_dir / "worker.lock"), timeout=0):
            self.store.recover()
            self.service.recover_applications()
            observer, handler, active = None, None, None
            try:
                async with AsyncSqliteSaver.from_conn_string(str(self.settings.data_dir / "checkpoints.sqlite3")) as saver:
                    while True:
                        projects = [p for p in self.store.all("project") if p["watching"]]
                        selected = projects[0] if projects else None
                        if (selected["id"] if selected else None) != active:
                            if observer:
                                observer.stop()
                                observer.join()
                            observer, handler, active = None, None, selected["id"] if selected else None
                            if selected:
                                handler, observer = Debouncer(self.settings.debounce), Observer()
                                observer.schedule(handler, selected["root"], recursive=True)
                                observer.start()
                                self.store.enqueue(active, "scan")  # reconcile changes made while worker was stopped
                        if handler:
                            for action in handler.ready():
                                self.store.enqueue(active, action)
                        job = self.store.claim()
                        if job:
                            await self.process(job, saver)
                        else:
                            await asyncio.sleep(0.5)
            finally:
                if observer:
                    observer.stop()
                    observer.join()


if __name__ == "__main__":
    asyncio.run(Worker().run())
