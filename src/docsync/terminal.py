"""Repository-first CLI using the same application service as FastAPI."""
import asyncio
import contextlib
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from docsync.config import Settings
from docsync.models import ProjectCreate, ProjectPatch, Review
from docsync.repository import validate_root
from docsync.service import Service
from docsync.store import Store
from docsync.worker import Worker

COMMANDS = ("run", "init", "index", "draft", "scan", "watch", "status", "proposals", "review", "config")
BUSY = {"queued", "running"}
CLOUD_NOTICE = "Gemini sends selected source code, docs, changes and tool evidence to Google. Embeddings stay local."


def say(value=""):
    # Repository/model strings are untrusted: strip terminal control characters.
    text = "".join(c for c in str(value) if c in "\n\t" or (c.isprintable() and c != "\x7f"))
    print(text, flush=True)


def add_commands(commands):
    descriptions = {
        "run": "Set up this project, prepare an initial overview, and watch saves",
        "init": "Register this repository and build its initial index",
        "index": "Refresh the index without generating documentation",
        "draft": "Prepare an initial docs/overview.md proposal",
        "scan": "Analyze saved changes and prepare proposals",
        "watch": "Watch saves and report progress until Ctrl+C",
        "status": "Show configuration, jobs and pending reviews",
        "proposals": "List documentation proposals",
        "review": "Inspect, accept, reject or edit a proposal",
        "config": "Show or change project settings",
    }
    for name in COMMANDS:
        parser = commands.add_parser(name, help=descriptions[name], description=descriptions[name])
        parser.add_argument("--project", type=Path, help="Repository root (default: find from current folder)")
        parser.add_argument("--data-dir", type=Path, help="Use existing state, e.g. from the dashboard")
        if name in {"run", "init", "config"}:
            parser.add_argument("--provider", choices=("local", "gemini"))
            parser.add_argument("--allow-cloud", action="store_true", help=CLOUD_NOTICE)
            parser.add_argument("--ignore", action="append", help="Add an ignore pattern; repeat for more")
        if name == "run":
            parser.add_argument("--yes", action="store_true", help="Approve missing local model downloads (not cloud consent or doc writes)")
            parser.add_argument("--no-watch", action="store_true", help="Finish after setup and initial draft")
        if name == "config":
            parser.add_argument("--watching", choices=("on", "off"))
        if name == "review":
            parser.add_argument("proposal", nargs="?", help="Proposal ID or unique prefix")
            group = parser.add_mutually_exclusive_group()
            group.add_argument("--accept", action="store_true", help="Apply the proposal after freshness checks")
            group.add_argument("--reject", action="store_true")
            group.add_argument("--edit", action="store_true", help="Open $VISUAL/$EDITOR, then confirm")
            group.add_argument("--file", type=Path, help="Apply edited Markdown from this file")
            group.add_argument("--show", action="store_true", help="Only display the diff and evidence")
        if name == "proposals":
            parser.add_argument("--all", action="store_true", help="Include accepted, rejected and stale proposals")


def repository_root(explicit=None):
    if explicit:
        return validate_root(explicit)
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return validate_root(candidate)
    raise ValueError("Run inside a local Git repository or pass --project PATH.")


def context(args):
    root = repository_root(args.project)
    state = args.data_dir or os.getenv("DOCSYNC_DATA_DIR") or root / ".docsync"
    settings = Settings(data_dir=Path(state).expanduser().resolve())
    store = Store(settings)
    service = Service(settings, store)
    project = next((p for p in store.all("project") if Path(p["root"]).resolve() == root), None)
    return root, settings, store, service, project


def configure(args, service, project):
    values = {}
    provider = args.provider or project["provider"]
    if args.allow_cloud and provider != "gemini":
        raise ValueError("--allow-cloud requires the Gemini provider.")
    if args.provider:
        values["provider"] = provider
        if provider == "local":
            values["cloud_consent"] = False
    if provider == "gemini" and not project["cloud_consent"]:
        say(CLOUD_NOTICE)
        consent = args.allow_cloud
        if not consent and sys.stdin.isatty():
            consent = input("Enable cloud generation for this project? [y/N] ").strip().lower() == "y"
        if not consent:
            raise ValueError("Cloud generation was not enabled. Use --allow-cloud to give explicit consent.")
        values["cloud_consent"] = True
    if args.ignore:
        values["ignore"] = list(dict.fromkeys(project["ignore"] + args.ignore))
    watching = getattr(args, "watching", None)
    if watching:
        values["watching"] = watching == "on"
    return service.configure(project["id"], ProjectPatch(**values)) if values else project


class Progress:
    def __init__(self, store, project_id):
        self.store, self.project_id = store, project_id
        self.seen = {}

    def show(self):
        for job in reversed(self.store.jobs(self.project_id)):
            state = (job["state"], job["message"])
            if self.seen.get(job["id"]) != state:
                say(f"[{job['id'][:8]}] {job['state']}: {job['message']}")
                self.seen[job["id"]] = state

    async def follow(self):
        while True:
            self.show()
            await asyncio.sleep(0.5)


async def run_job(settings, store, project, job, worker=None):
    """Run queued work ourselves, or wait for the existing worker holding the lock."""
    progress = Progress(store, project["id"])
    reporter = asyncio.create_task(progress.follow())
    lock = FileLock(str(settings.data_dir / "worker.lock"), timeout=0)
    acquired = False
    owned_worker = worker is None
    try:
        try:
            lock.acquire()
            acquired = True
        except Timeout:
            say("A worker is already running; waiting for this job.")
        if acquired:
            worker = worker or Worker(settings)
            store.recover()
            worker.service.recover_applications()
            async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "checkpoints.sqlite3")) as saver:
                while store.job(job["id"])["state"] in BUSY:
                    pending = store.claim()
                    if pending is None:
                        raise ValueError("Job could not be claimed; retry the command.")
                    await worker.process(pending, saver)
        else:
            try:
                async with asyncio.timeout(settings.job_timeout * 3):
                    while store.job(job["id"])["state"] in BUSY:
                        await asyncio.sleep(0.5)
            except TimeoutError:
                raise ValueError("Still waiting for the worker. Check docsync status; the job remains queued/running.") from None
        result = store.job(job["id"])
        progress.show()
        if result["state"] in {"failed", "postponed", "insufficient_evidence", "superseded"}:
            raise ValueError(result["message"])
        if result.get("proposals"):
            say("Run docsync review to inspect the proposed documentation.")
        return result
    finally:
        reporter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reporter
        if acquired:
            try:
                if owned_worker and worker is not None and hasattr(worker.retriever, "close"):
                    worker.retriever.close()
            finally:
                lock.release()


async def watch(settings, store, project):
    progress = Progress(store, project["id"])
    reporter = asyncio.create_task(progress.follow())
    worker = None
    try:
        say(f"Watching {project['root']}\nSave Python files to prepare proposals. Press Ctrl+C to stop.")
        say("Review in a second terminal with docsync review.")
        worker = Worker(settings)
        await worker.run()
    except Timeout:
        raise ValueError("A worker already uses this state directory. Use docsync status or stop that worker first.") from None
    finally:
        reporter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reporter
        if worker is not None and hasattr(worker.retriever, "close"):
            worker.retriever.close()


def show_config(settings, project):
    say(f"Project: {project['name']}\nRepository: {project['root']}\nState: {settings.data_dir}")
    say(f"Provider: {project['provider']} | Cloud consent: {project['cloud_consent']} | Watching: {project['watching']}")
    say(f"Generation model: {settings.gemini_model if project['provider'] == 'gemini' else settings.model}")
    say(f"Local embeddings: {settings.embed_model}\nIgnore patterns: {', '.join(project['ignore']) or '(none)'}")
    say(f"Vector storage: {settings.qdrant_mode}")


def list_proposals(service, project, include_all=False):
    proposals = [p for p in service.proposals(project["id"]) if include_all or p["state"] == "pending"]
    if not proposals:
        say("No proposals to review. Use docsync draft for an initial overview, or save changes and run docsync scan.")
    for p in proposals:
        say(f"{p['id']}  {p['state']}  {p['path']}\n  {p.get('summary', '')}")
    return proposals


def select_proposal(service, project, prefix):
    proposals = service.proposals(project["id"])
    if prefix:
        matches = [p for p in proposals if p["id"].startswith(prefix)]
        if len(matches) != 1:
            raise ValueError("Proposal ID is unknown or ambiguous for this project. Run docsync proposals --all.")
        return matches[0]
    pending = [p for p in proposals if p["state"] == "pending"]
    if len(pending) == 1:
        return pending[0]
    if not pending:
        say("No pending proposals. Run docsync draft or docsync scan first.")
        return None
    list_proposals(service, project)
    if not sys.stdin.isatty():
        raise ValueError("Multiple pending proposals; supply a proposal ID.")
    prefix = input("Proposal ID (or unique prefix): ").strip()
    if not prefix:
        return None
    return select_proposal(service, project, prefix)


def edited_content(content, settings):
    editor = os.getenv("VISUAL") or os.getenv("EDITOR") or ("notepad.exe" if os.name == "nt" else "vi")
    command = shlex.split(editor, posix=os.name != "nt")
    if os.name == "nt":
        command = [part.strip('"') for part in command]
    if not command:
        raise ValueError("Set VISUAL or EDITOR, or use --file PATH.")
    with tempfile.TemporaryDirectory(prefix="review-", dir=settings.data_dir) as directory:
        path = Path(directory) / "proposal.md"
        path.write_text(content, encoding="utf-8")
        result = subprocess.run([*command, str(path)], check=False)
        if result.returncode:
            raise ValueError("Editor failed; documentation was not applied.")
        return path.read_text(encoding="utf-8-sig")


def review(args, settings, store, service, project):
    proposal = select_proposal(service, project, args.proposal)
    if proposal is None:
        return
    say(f"Proposal {proposal['id']} | {proposal['state']} | {proposal['path']}")
    say(proposal.get("summary", ""))
    say(f"Target reason: {proposal.get('reason', '')}")
    say(proposal.get("diff", ""))
    snapshot = store.get("snapshot", proposal["snapshot_id"])
    for citation in proposal.get("citations", []):
        say(f"Evidence: {citation['path']}:{citation['start']}-{citation['end']}")
        lines = snapshot["files"][citation["path"]]["text"].splitlines()
        say("\n".join(lines[citation["start"]-1:citation["end"]])[:6000])
    if args.show:
        return
    action = "accept" if args.accept else "reject" if args.reject else "edit" if args.edit or args.file else None
    if action is None:
        if not sys.stdin.isatty():
            say("Preview only. Use --accept, --reject, --file PATH, or review in an interactive terminal.")
            return
        choice = input("[a]ccept / [r]eject / [e]dit / [q]uit [q]: ").strip().lower()
        action = {"a": "accept", "r": "reject", "e": "edit"}.get(choice)
    if action is None:
        return
    if proposal["state"] != "pending":
        raise ValueError("This proposal is no longer pending.")
    content = None
    if action == "edit":
        if args.file:
            content = args.file.read_text(encoding="utf-8-sig")
        else:
            if not sys.stdin.isatty():
                raise ValueError("Interactive editing requires a terminal. Use --file PATH instead.")
            content = edited_content(proposal["content"], settings)
            from docsync.documentation import unified_diff
            say(unified_diff(proposal["path"], proposal["before"], content))
            if input("Apply this edited proposal? [y/N] ").strip().lower() != "y":
                say("Not applied. The original proposal is still pending.")
                return
    result = service.review(proposal["id"], Review(decision=action, content=content))
    say(f"{result['state']}: {result['path']}")
    if result["state"] == "accepted":
        say("Documentation saved. Index refresh is queued for watch or the next processing command.")


def dispatch(args):
    if args.command not in COMMANDS:
        return False
    root, settings, store, service, project = context(args)
    if args.command == "run":
        from docsync.onboarding import run
        run(args, root, settings, store, service, project)
        return True
    if args.command == "init":
        if project is None:
            project = service.register(ProjectCreate(root=str(root), watching=True))
        project = configure(args, service, project)
        show_config(settings, project)
        say("Keep .docsync/ out of version control; it contains source snapshots and backups.")
        if project.get("last_snapshot"):
            say("Already initialized. Use docsync scan to analyze changes, or docsync index to reset the baseline.")
            return True
        job = store.enqueue(project["id"], "index")
        asyncio.run(run_job(settings, store, project, job))
        say("Ready. Run docsync draft for an overview, or docsync watch to follow saved changes.")
        return True
    if project is None:
        raise ValueError("This repository is not registered in this state directory. Run docsync init first.")
    if args.command in {"index", "draft", "scan"}:
        job = store.enqueue(project["id"], "bootstrap" if args.command == "draft" else args.command)
        asyncio.run(run_job(settings, store, project, job))
    elif args.command == "watch":
        project = service.configure(project["id"], ProjectPatch(watching=True))
        asyncio.run(watch(settings, store, project))
    elif args.command == "config":
        project = configure(args, service, project)
        show_config(settings, project)
    elif args.command == "status":
        show_config(settings, project)
        status = service.status(project["id"])
        say(f"Pending proposals: {status['pending']}")
        Progress(store, project["id"]).show()
        for item in status["skipped"] + status["parse_errors"]:
            say(f"{item['path']}: {item['reason']}")
    elif args.command == "proposals":
        list_proposals(service, project, args.all)
    elif args.command == "review":
        review(args, settings, store, service, project)
    return True
