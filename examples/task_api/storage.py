TASKS = []


def list_tasks(limit: int):
    """Return tasks in insertion order."""
    return TASKS[:limit]


def save_task(title: str, priority: int):
    """Append a task with its title and priority."""
    task = {"title": title.strip(), "priority": priority}
    TASKS.append(task)
    return task
