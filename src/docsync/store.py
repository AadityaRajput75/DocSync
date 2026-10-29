import json
import sqlite3
import time
import uuid
from contextlib import contextmanager


def identifier():
    return uuid.uuid4().hex


class Store:
    def __init__(self, settings):
        self.settings = settings
        settings.prepare()
        self.path = settings.data_dir / "state.sqlite3"
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS objects (
                kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def put(self, kind, body):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO objects VALUES (?,?,?)",
                       (kind, body["id"], json.dumps(body)))
        return body

    def get(self, kind, object_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM objects WHERE kind=? AND id=?", (kind, object_id)).fetchone()
        if not row:
            raise KeyError(f"Unknown {kind}")
        return json.loads(row[0])

    def all(self, kind):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM objects WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def patch(self, kind, object_id, **changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM objects WHERE kind=? AND id=?", (kind, object_id)).fetchone()
            if not row:
                raise KeyError(f"Unknown {kind}")
            body = json.loads(row[0])
            body.update(changes)
            db.execute("UPDATE objects SET body=? WHERE kind=? AND id=?", (json.dumps(body), kind, object_id))
        return body

    def enqueue(self, project_id, action, **extra):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if action in {"scan", "index"}:
                row = db.execute("SELECT body FROM jobs WHERE project_id=? AND action=? AND state='queued'",
                                 (project_id, action)).fetchone()
                if row:
                    return json.loads(row[0])
            body = dict(id=identifier(), project_id=project_id, action=action, state="queued",
                        created=time.time(), message="Queued", **extra)
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                       (body["id"], project_id, action, "queued", body["created"], json.dumps(body)))
        return body

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError("Unknown job")
        return json.loads(row[0])

    def jobs(self, project_id):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 30",
                              (project_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def update_job(self, job_id, **changes):
        body = self.job(job_id)
        body.update(changes)
        with self.connect() as db:
            db.execute("UPDATE jobs SET state=?,body=? WHERE id=?", (body["state"], json.dumps(body), job_id))
        return body

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            body = json.loads(row[0])
            body.update(state="running", message="Starting", started=time.time())
            db.execute("UPDATE jobs SET state='running', body=? WHERE id=?", (json.dumps(body), body["id"]))
        return body

    def recover(self):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM jobs WHERE state='running'").fetchall()
            for row in rows:
                body = json.loads(row[0])
                body.update(state="queued", message="Recovered after worker restart")
                db.execute("UPDATE jobs SET state='queued',body=? WHERE id=?", (json.dumps(body), body["id"]))

    def vector(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO embeddings VALUES (?,?)", (key, json.dumps(value)))
                return value
            row = db.execute("SELECT vector FROM embeddings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None
