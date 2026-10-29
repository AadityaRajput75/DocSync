from fastapi import FastAPI

from storage import list_tasks, save_task

app = FastAPI()


@app.get("/tasks")
def get_tasks(limit: int = 25):
    """Return the first tasks up to the requested limit."""
    return list_tasks(limit)


@app.post("/tasks")
def create_task(title: str, priority: int = 1):
    """Save a task and return its stored fields."""
    return save_task(title, priority)


@app.get("/health")
def health():
    """Report application readiness."""
    return {"status": "ready"}
