import os
import time
from pathlib import Path

from filelock import FileLock

from docsync.documentation import unified_diff, validate_markdown
from docsync.repository import capture, digest, safe_path, validate_root
from docsync.store import identifier


class Conflict(ValueError):
    pass


class Service:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def register(self, request):
        root = str(validate_root(request.root))
        existing = [p for p in self.store.all("project") if p["root"] == root]
        if existing:
            return existing[0]
        # v1 watches one active repository, while preserving earlier project history.
        if request.watching:
            for project in self.store.all("project"):
                self.store.patch("project", project["id"], watching=False)
        project = self.store.put("project", dict(id=identifier(), root=root, name=Path(root).name,
                                                  watching=request.watching, ignore=request.ignore,
                                                  provider="local", cloud_consent=False,
                                                  last_snapshot=None, latest_snapshot=None, created=time.time()))
        job = self.store.enqueue(project["id"], "index")
        return {**project, "job_id": job["id"]}

    def configure(self, project_id, request):
        project = self.store.get("project", project_id)
        values = request.model_dump(exclude_none=True)
        provider = values.get("provider", project["provider"])
        consent = values.get("cloud_consent", project["cloud_consent"])
        if provider == "gemini" and not consent:
            raise ValueError("Enabling Gemini sends selected code and docs to Google; explicit cloud consent is required")
        if values.get("watching"):
            for other in self.store.all("project"):
                if other["id"] != project_id:
                    self.store.patch("project", other["id"], watching=False)
        updated = self.store.patch("project", project_id, **values)
        if "ignore" in values:
            self.store.enqueue(project_id, "scan")
        return updated

    def proposals(self, project_id):
        return sorted([p for p in self.store.all("proposal") if p["project_id"] == project_id],
                      key=lambda p: p["created"], reverse=True)

    def status(self, project_id):
        project = self.store.get("project", project_id)
        snapshot = self.store.get("snapshot", project["latest_snapshot"]) if project.get("latest_snapshot") else None
        return {"project": project, "jobs": self.store.jobs(project_id),
                "generation_model": self.settings.gemini_model if project["provider"] == "gemini" else self.settings.model,
                "skipped": snapshot["skipped"] if snapshot else [],
                "parse_errors": snapshot["errors"] if snapshot else [],
                "pending": sum(p["state"] == "pending" for p in self.proposals(project_id))}

    def _finish_review(self, proposal):
        siblings = [p for p in self.proposals(proposal["project_id"]) if p["job_id"] == proposal["job_id"]]
        if all(p["state"] not in {"pending", "applying"} for p in siblings):
            self.store.enqueue(proposal["project_id"], "resume", thread_id=proposal["job_id"])

    def recover_applications(self):
        for proposal in self.store.all("proposal"):
            if proposal["state"] != "applying":
                continue
            project = self.store.get("project", proposal["project_id"])
            with FileLock(str(self.settings.data_dir / f"{project['id']}.lock")):
                path = safe_path(project["root"], proposal["path"], docs_only=True)
                expected = proposal["applied_hash"]
                if path.exists() and digest(path.read_bytes()) == expected:
                    self._accepted(proposal)
                else:
                    self.store.patch("proposal", proposal["id"], state="pending", recovery="Apply interrupted; review again")

    def _accepted(self, proposal):
        self.store.patch("proposal", proposal["id"], state="accepted", reviewed=time.time())
        association_id = digest(proposal["project_id"] + proposal["path"])
        try:
            previous = self.store.get("association", association_id)["sources"]
        except KeyError:
            previous = []
        self.store.put("association", {"id": association_id,
                                        "project_id": proposal["project_id"], "document": proposal["path"],
                                        "sources": sorted(set(previous + proposal["sources"]))})
        self.store.enqueue(proposal["project_id"], "index_docs")
        self._finish_review(proposal)

    def review(self, proposal_id, request):
        proposal = self.store.get("proposal", proposal_id)
        project = self.store.get("project", proposal["project_id"])
        with FileLock(str(self.settings.data_dir / f"{project['id']}.lock")):
            proposal = self.store.get("proposal", proposal_id)
            if proposal["state"] != "pending":
                raise Conflict("Proposal is no longer pending")
            if request.decision == "reject":
                updated = self.store.patch("proposal", proposal_id, state="rejected", reviewed=time.time())
                self._finish_review(updated)
                return updated
            current = capture(project, self.settings)
            destination = safe_path(project["root"], proposal["path"], docs_only=True)
            destination_hash = digest(destination.read_bytes()) if destination.exists() else None
            if current["errors"] or current["source_hash"] != proposal["source_hash"] or destination_hash != proposal["destination_hash"]:
                self.store.patch("proposal", proposal_id, state="superseded")
                self._finish_review(proposal)
                self.store.enqueue(project["id"], "scan", regenerate=True)
                raise Conflict("Source or documentation changed. This proposal is stale; regeneration was queued")
            content = request.content if request.decision == "edit" else proposal["content"]
            if not content:
                raise ValueError("Edited Markdown cannot be empty")
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            validate_markdown(content)
            old_file = self.store.get("snapshot", proposal["snapshot_id"])["files"].get(proposal["path"], {})
            raw_content = content.replace("\n", old_file.get("newline", "\n")).encode("utf-8")
            if old_file.get("bom"):
                raw_content = b"\xef\xbb\xbf" + raw_content
            backup_dir = self.settings.data_dir / "backups" / proposal_id
            backup_dir.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                (backup_dir / "original.md").write_bytes(destination.read_bytes())
            (backup_dir / "target.txt").write_text(str(destination), encoding="utf-8")
            proposal = self.store.patch("proposal", proposal_id, state="applying", applied_hash=digest(raw_content),
                                        applied_content=content, diff=unified_diff(proposal["path"], proposal["before"], content),
                                        backup=str(backup_dir))
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Revalidate after parent creation, then stage within the destination filesystem.
            destination = safe_path(project["root"], proposal["path"], docs_only=True)
            temporary = destination.with_name(f".{destination.name}.{identifier()}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(raw_content)
                    stream.flush()
                    os.fsync(stream.fileno())
                latest_hash = digest(destination.read_bytes()) if destination.exists() else None
                if latest_hash != proposal["destination_hash"]:
                    self.store.patch("proposal", proposal_id, state="superseded")
                    raise Conflict("Documentation changed during approval")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            self._accepted(proposal)
        return self.store.get("proposal", proposal_id)
