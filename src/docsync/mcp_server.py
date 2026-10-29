"""Read-only tools over immutable snapshots, never the changing working tree."""
from mcp.server.fastmcp import FastMCP

from docsync.config import Settings
from docsync.repository import chunks, safe_path
from docsync.store import Store


class RepositoryTools:
    def __init__(self, store):
        self.store = store

    def snapshot(self, project_id, snapshot_id):
        project = self.store.get("project", project_id)
        snapshot = self.store.get("snapshot", snapshot_id)
        if snapshot["project_id"] != project_id:
            raise ValueError("Snapshot belongs to another project")
        return project, snapshot

    def list_tree(self, project_id, snapshot_id):
        _, snapshot = self.snapshot(project_id, snapshot_id)
        return {"paths": sorted(snapshot["files"])[:200], "total": len(snapshot["files"])}

    def read_file(self, project_id, snapshot_id, path, start=1, end=80):
        project, snapshot = self.snapshot(project_id, snapshot_id)
        safe_path(project["root"], path)
        if path not in snapshot["files"]:
            raise ValueError("File is absent from this snapshot")
        lines = snapshot["files"][path]["text"].splitlines()
        if start < 1 or end < start or start > len(lines):
            raise ValueError("Invalid line range")
        end = min(end, start + 79, len(lines))
        selected, count = [], 0
        for line in lines[start-1:end]:
            if count + len(line) + 1 > 6000:
                break
            selected.append(line)
            count += len(line) + 1
        if not selected:
            raise ValueError("Line exceeds tool output limit")
        return {"path": path, "start": start, "end": start + len(selected) - 1,
                "text": "\n".join(selected)}

    def search_text(self, project_id, snapshot_id, query):
        _, snapshot = self.snapshot(project_id, snapshot_id)
        if not query or len(query) > 200:
            raise ValueError("Query must contain 1–200 characters")
        found = []
        for path, file in snapshot["files"].items():
            for n, line in enumerate(file["text"].splitlines(), 1):
                if query.casefold() in line.casefold():
                    found.append({"path": path, "start": n, "end": n, "text": line[:400]})
                    if len(found) == 20:
                        return found
        return found

    def find_symbol(self, project_id, snapshot_id, name):
        _, snapshot = self.snapshot(project_id, snapshot_id)
        _, symbols = chunks(snapshot)
        return [s for s in symbols if name.casefold() in s["name"].casefold()][:12]

    def get_related_symbols(self, project_id, snapshot_id, name):
        _, snapshot = self.snapshot(project_id, snapshot_id)
        _, symbols = chunks(snapshot)
        found = [s for s in symbols if s["name"] == name or s["name"].split(".")[-1] == name]
        calls = {c.split(".")[-1] for s in found for c in s["calls"]}
        related = [s for s in symbols if s["name"].split(".")[-1] in calls
                   or any(c.split(".")[-1] == name.split(".")[-1] for c in s["calls"])]
        return {"note": "Static references are approximate; dynamic dispatch is not resolved.",
                "symbols": related[:12]}


def create_server(store=None):
    tools = RepositoryTools(store or Store(Settings()))
    server = FastMCP("DocSync repository tools")
    for name in ("list_tree", "read_file", "search_text", "find_symbol", "get_related_symbols"):
        server.tool()(getattr(tools, name))
    return server


if __name__ == "__main__":
    create_server().run(transport="stdio")
