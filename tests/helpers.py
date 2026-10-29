import hashlib

from docsync.models import Decision, Draft
from docsync.repository import chunks


class FakeEmbeddings:
    async def fingerprint(self):
        return "test-embeddings-not-a-semantic-model"

    async def embed(self, text, query=False):
        values = hashlib.sha256(text.encode()).digest()
        return [value / 255 for value in values[:16]]


class MemoryRetriever:
    def __init__(self, store):
        self.store = store

    async def index(self, snapshot):
        items, symbols = chunks(snapshot)
        self.store.put("index", {"id": snapshot["id"], "chunks": items, "symbols": symbols})
        return len(items)

    async def search(self, snapshot, query, mode="hybrid"):
        return chunks(snapshot)[0][:8] if mode != "none" else []


class ScriptedLLM:
    def __init__(self, action="draft", tool=False):
        self.action, self.tool = action, tool
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    async def structured(self, project_id, prompt, schema):
        self.usage["calls"] += 1
        if schema == Decision:
            if self.tool and self.usage["calls"] == 1:
                return Decision(action="tool", summary="Inspect the function", tool="read_file",
                                arguments={"path": "api.py", "start": 1, "end": 3})
            return Decision(action=self.action, summary="Document the changed public default" if self.action == "draft" else "Internal implementation only")
        return Draft(content="# API\n\n## list_items\nThe default limit is 20.\n\n## Deployment\nKeep this human-written section.\n",
                     summary="Update default limit", citations=[{"path": "api.py", "start": 1, "end": 3}],
                     symbols=["list_items"])

