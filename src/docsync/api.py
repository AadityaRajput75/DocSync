from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from docsync.config import Settings
from docsync.models import ProjectCreate, ProjectPatch, Review
from docsync.service import Conflict, Service
from docsync.store import Store


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings)
    service = Service(settings, store)
    app = FastAPI(title="DocSync", version="0.1.0")
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        # The Streamlit server calls the API directly; browsers from other origins need no write access.
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            if origin not in {"http://127.0.0.1:8501", "http://localhost:8501"}:
                return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409 if isinstance(exc, Conflict) else 400)

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "local-first"}

    @app.get("/projects")
    def projects():
        return store.all("project")

    @app.post("/projects", status_code=201)
    def register(request: ProjectCreate):
        return service.register(request)

    @app.patch("/projects/{project_id}")
    def configure(project_id: str, request: ProjectPatch):
        return service.configure(project_id, request)

    @app.post("/projects/{project_id}/bootstrap", status_code=202)
    def bootstrap(project_id: str):
        store.get("project", project_id)
        return store.enqueue(project_id, "bootstrap")

    @app.post("/projects/{project_id}/scan", status_code=202)
    def scan(project_id: str):
        store.get("project", project_id)
        return store.enqueue(project_id, "scan")

    @app.get("/projects/{project_id}/status")
    def status(project_id: str):
        return service.status(project_id)

    @app.get("/projects/{project_id}/proposals")
    def proposals(project_id: str):
        store.get("project", project_id)
        return service.proposals(project_id)

    @app.get("/proposals/{proposal_id}")
    def proposal(proposal_id: str):
        result = store.get("proposal", proposal_id)
        snapshot = store.get("snapshot", result["snapshot_id"])
        result["evidence"] = [{**c, "text": "\n".join(snapshot["files"][c["path"]]["text"].splitlines()[c["start"]-1:c["end"]])}
                              for c in result["citations"]]
        return result

    @app.post("/proposals/{proposal_id}/review")
    def review(proposal_id: str, request: Review):
        return service.review(proposal_id, request)

    return app

