import difflib
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from docsync.documentation import targets, unified_diff, validate_draft
from docsync.models import Decision, Draft


@asynccontextmanager
async def repository_session(settings):
    params = StdioServerParameters(command=sys.executable, args=["-I", "-m", "docsync.mcp_server"], env={
        "DOCSYNC_DATA_DIR": str(settings.data_dir), "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false", "PYTHONIOENCODING": "utf-8",
        **({"SYSTEMROOT": os.environ["SYSTEMROOT"]} if "SYSTEMROOT" in os.environ else {})})
    with (settings.data_dir / "mcp.log").open("a", encoding="utf-8") as log:
        async with stdio_client(params, errlog=log) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


class AgentState(TypedDict, total=False):
    job_id: str
    project_id: str
    snapshot_id: str
    old_snapshot_id: str | None
    changed: list[str]
    bootstrap: bool
    evidence: list[dict]
    activity: list[dict]
    tool_calls: int
    decision: dict
    targets: list[dict]
    target_index: int
    proposals: list[str]
    draft: dict
    outcome: str
    retrieval_mode: str
    reviewed: bool


class Agent:
    def __init__(self, settings, store, retriever, llm, session):
        self.settings, self.store, self.retriever, self.llm, self.session = settings, store, retriever, llm, session
        self.tool_schemas = []

    def snapshot(self, state):
        return self.store.get("snapshot", state["snapshot_id"])

    def activity(self, state, message, **details):
        activity = state.get("activity", []) + [{"message": message, **details}]
        self.store.update_job(state["job_id"], message=message, activity=activity,
                              usage=dict(self.llm.usage))
        return activity

    def prompt(self, state):
        snapshot = self.snapshot(state)
        old = self.store.get("snapshot", state["old_snapshot_id"]) if state.get("old_snapshot_id") else {"files": {}}
        changed = []
        for path in ([] if state["bootstrap"] else state["changed"]):
            before = old["files"].get(path, {}).get("text", "")
            after = snapshot["files"].get(path, {}).get("text", "")
            changed.append({"path": path, "diff": "".join(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=path, tofile=path, n=5)), "current_line_count": len(after.splitlines())})
        payload = {"task": "Draft initial project overview" if state["bootstrap"] else "Update docs only when needed",
                   "changes": changed, "evidence": state.get("evidence", []),
                   "tool_activity": state.get("activity", [])}
        if state["bootstrap"]:
            payload["repository_paths"] = sorted(snapshot["files"])[:100]
            payload["instruction"] = "Describe only the major modules supported by evidence; use tools to inspect entry points. State coverage limits."
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > self.settings.context_chars:
            raise ValueError("Change exceeds local context budget; split the change into smaller batches")
        return text

    async def retrieve(self, state):
        snapshot = self.snapshot(state)
        query = " ".join(state["changed"])
        from docsync.repository import changed_symbols
        old = self.store.get("snapshot", state["old_snapshot_id"]) if state.get("old_snapshot_id") else None
        query += " " + " ".join(name for path in state["changed"] for name in changed_symbols(old, snapshot, path))
        evidence = await self.retriever.search(snapshot, query, state.get("retrieval_mode", "hybrid"))
        associations = [a for a in self.store.all("association") if a["project_id"] == state["project_id"]]
        selected = targets(snapshot, state["changed"], associations, state["bootstrap"], old, evidence)
        if len(selected) > 5:
            raise ValueError("More than five documents affected; narrow the change batch")
        return {"evidence": evidence, "targets": selected, "target_index": 0, "proposals": [], "tool_calls": 0,
                "activity": self.activity(state, "Retrieved supporting evidence", files=[e["path"] for e in evidence])}

    async def investigate(self, state):
        if not self.tool_schemas:
            tools = await self.session.list_tools()
            self.tool_schemas = [{"name": t.name, "description": t.description, "arguments": t.inputSchema}
                                 for t in tools.tools]
        prompt = self.prompt(state) + "\nAvailable read-only tools:\n" + json.dumps(self.tool_schemas)
        if state["tool_calls"] >= self.settings.max_tools:
            prompt += "\nTool budget exhausted. Choose draft, no_update, or insufficient_evidence."
        decision = await self.llm.structured(state["project_id"], prompt, Decision)
        if decision.action == "tool" and state["tool_calls"] >= self.settings.max_tools:
            decision = Decision(action="insufficient_evidence", summary="Investigation reached its tool limit")
        return {"decision": decision.model_dump(),
                "activity": self.activity(state, decision.summary, action=decision.action)}

    async def tool(self, state):
        decision = state["decision"]
        arguments = dict(decision["arguments"])
        arguments.update(project_id=state["project_id"], snapshot_id=state["snapshot_id"])
        if decision["tool"] not in {t["name"] for t in self.tool_schemas}:
            result = {"error": "Unknown tool"}
        else:
            response = await self.session.call_tool(decision["tool"], arguments)
            result = {"error": response.isError, "content": [c.text for c in response.content if c.type == "text"]}
        return {"tool_calls": state["tool_calls"] + 1,
                "activity": self.activity(state, "Inspected repository evidence", tool=decision["tool"],
                                          result=json.dumps(result, ensure_ascii=False)[:7000])}

    async def draft(self, state):
        target = state["targets"][state["target_index"]]
        prompt_target = {**target, "sources": target["sources"][:100]}
        prompt = self.prompt(state) + "\nDocumentation target (ranges are zero-based, end-exclusive):\n" + json.dumps(prompt_target)
        prompt += "\nReturn the complete Markdown file. Preserve everything outside allowed ranges."
        if len(prompt) > self.settings.context_chars + 6000:
            raise ValueError("Document exceeds generation budget; use a smaller guide")
        draft = await self.llm.structured(state["project_id"], prompt, Draft)
        return {"draft": draft.model_dump(), "activity": self.activity(state, "Prepared documentation draft",
                                                                        path=target["path"])}

    async def validate(self, state):
        snapshot = self.snapshot(state)
        project = self.store.get("project", state["project_id"])
        target = state["targets"][state["target_index"]]
        draft = Draft.model_validate(state["draft"])
        validate_draft(project, snapshot, target, draft)
        if draft.content == target["old"]:
            return {"target_index": state["target_index"] + 1}
        # Stable ID prevents duplicate proposals if the worker restarts between node checkpoints.
        from docsync.repository import digest
        proposal_id = digest(state["job_id"] + target["path"])[:32]
        try:
            proposal = self.store.get("proposal", proposal_id)
        except KeyError:
            proposal = {"id": proposal_id, "project_id": state["project_id"], "job_id": state["job_id"],
                        "snapshot_id": snapshot["id"], "source_hash": snapshot["source_hash"],
                        "path": target["path"], "before": target["old"], "content": draft.content,
                        "destination_hash": snapshot["files"].get(target["path"], {}).get("hash"),
                        "summary": draft.summary, "citations": [c.model_dump() for c in draft.citations],
                        "symbols": draft.symbols, "sources": target["sources"], "reason": target["reason"],
                        "diff": unified_diff(target["path"], target["old"], draft.content),
                        "state": "pending", "created": __import__("time").time()}
            self.store.put("proposal", proposal)
        return {"proposals": state["proposals"] + [proposal_id], "target_index": state["target_index"] + 1,
                "activity": self.activity(state, "Validated documentation and source locations", path=target["path"])}

    async def review(self, state):
        if state["proposals"]:
            interrupt({"proposal_ids": state["proposals"], "message": "Review proposed documentation updates"})
        return {"reviewed": True}

    async def finish(self, state):
        outcome = state.get("decision", {}).get("action", "insufficient_evidence")
        return {"outcome": "reviewed" if state.get("reviewed") and state.get("proposals") else
                ("no_update" if outcome == "draft" else outcome)}

    def build(self, checkpointer):
        graph = StateGraph(AgentState)
        for name in ("retrieve", "investigate", "tool", "draft", "validate", "review", "finish"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "investigate")
        graph.add_conditional_edges("investigate", lambda s: "tool" if s["decision"]["action"] == "tool" else
                                    ("draft" if s["decision"]["action"] == "draft" and s["targets"] else "finish"))
        graph.add_edge("tool", "investigate")
        graph.add_edge("draft", "validate")
        graph.add_conditional_edges("validate", lambda s: "draft" if s["target_index"] < len(s["targets"]) else "review")
        graph.add_edge("review", "finish")
        graph.add_edge("finish", END)
        return graph.compile(checkpointer=checkpointer)
