"""Controlled retrieval ablation; optional real-model generation, never fabricated quality scores."""
import argparse
import asyncio
import json
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from docsync.config import Settings
from docsync.documentation import targets, validate_draft
from docsync.llm import LLM
from docsync.models import Draft
from docsync.repository import capture, changed_symbols, chunks
from docsync.retrieval import Retriever
from docsync.store import Store


class EvaluationOutput(BaseModel):
    action: Literal["draft", "no_update", "insufficient_evidence"]
    path: str | None = None
    draft: Draft | None = None
    summary: str = Field(max_length=500)


async def evaluate(args):
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "eval/cases.json").read_text())
    modes = args.modes.split(",")
    if set(modes) - {"none", "keyword", "hybrid"}:
        raise ValueError("Modes must be none,keyword,hybrid")
    rows = []
    with tempfile.TemporaryDirectory(prefix="docsync-evaluation-") as temp:
        settings = Settings(data_dir=Path(temp) / "state")
        store = Store(settings)
        retriever = Retriever(settings, store)
        # One preflight avoids repeated connection attempts when local services are unavailable.
        hybrid_error = None
        if "hybrid" in modes:
            try:
                await retriever.embeddings.fingerprint()
                retriever.client.get_collections()
            except Exception as exc:
                hybrid_error = f"Required local service unavailable ({type(exc).__name__})"
        for case in cases:
            project_root = Path(temp) / case["id"]
            shutil.copytree(root / "examples" / case["repo"], project_root,
                            ignore=shutil.ignore_patterns(".git", "__pycache__"))
            subprocess.run(["git", "init", "-q", str(project_root)], check=True)
            project = dict(id=case["id"], root=str(project_root), ignore=[], provider="local", cloud_consent=False)
            store.put("project", project)
            before = capture(project, settings)
            source_path = project_root / case["path"]
            text = source_path.read_text(encoding="utf-8")
            if text.count(case["before"]) != 1:
                raise ValueError(f"Case {case['id']} replacement is not unique")
            source_path.write_text(text.replace(case["before"], case["after"]), encoding="utf-8")
            snapshot = capture(project, settings)
            if snapshot["errors"]:
                raise ValueError(f"Case {case['id']} produces invalid Python")
            store.put("snapshot", snapshot)
            items, symbols = chunks(snapshot)
            store.put("index", {"id": snapshot["id"], "chunks": items, "symbols": symbols})
            query = case["path"] + " " + " ".join(changed_symbols(before, snapshot, case["path"]))
            for mode in modes:
                row = dict(case_id=case["id"], repo=case["repo"], mode=mode, description=case["description"],
                           requires_update=case["requires_update"], expected_document=case["expected_document"],
                           factual_accuracy=None, reviewer_editing_seconds=None,
                           human_notes="Not reviewed", generation="not_requested")
                start = time.perf_counter()
                if mode == "hybrid" and hybrid_error:
                    row.update(status="unavailable", reason=hybrid_error)
                    rows.append(row)
                    continue
                try:
                    if mode == "hybrid":
                        await retriever.index(snapshot)
                    hits = await retriever.search(snapshot, query, mode)
                    retrieved_paths = {hit["path"] for hit in hits}
                    required = set(case["required_evidence"])
                    row.update(status="measured", retrieved_paths=sorted(retrieved_paths),
                               evidence_recall_at_8=len(required & retrieved_paths) / len(required) if required else None,
                               retrieval_seconds=time.perf_counter() - start)
                    if args.generate:
                        # Identical drafting instructions and target-document candidates across variants.
                        # MCP follow-up is intentionally excluded to isolate the retrieval contribution.
                        candidates = targets(snapshot, [case["path"]], [], old_snapshot=before)
                        prompt = json.dumps({"task": "Decide whether docs need updating. If so, choose a target and return its complete updated Markdown. Preserve unrelated sections.",
                                             "before": before["files"][case["path"]]["text"],
                                             "after": snapshot["files"][case["path"]]["text"],
                                             "changed_path": case["path"], "targets": candidates, "evidence": hits})
                        llm = LLM(settings, store)
                        generation_start = time.perf_counter()
                        output = await llm.structured(project["id"], prompt, EvaluationOutput)
                        row.update(generation="measured", output=output.model_dump(), usage=llm.usage,
                                   generation_seconds=time.perf_counter() - generation_start,
                                   update_decision_correct=(output.action == "draft") == case["requires_update"],
                                   target_correct=output.path == case["expected_document"] if case["requires_update"] else None,
                                   unnecessary_update=(output.action == "draft") if not case["requires_update"] else None)
                        if output.action == "draft":
                            target = next((t for t in candidates if t["path"] == output.path), None)
                            if not target or not output.draft:
                                row["validation"] = "invalid target or missing draft"
                            else:
                                try:
                                    validate_draft(project, snapshot, target, output.draft)
                                    row["validation"] = "passed"
                                except ValueError as exc:
                                    row["validation"] = str(exc)
                except Exception as exc:
                    row.update(status="failed", reason=type(exc).__name__)
                rows.append(row)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    report = ["# Retrieval evaluation", "", "30 independently annotated synthetic changes across two bundled Python repositories.",
              "No model-generated quality score is substituted for human review. File-level evidence recall is reported at eight chunks.",
              "", "| Mode | Measured cases | Mean evidence recall@8 | Unavailable/failed |", "|---|---:|---:|---:|"]
    for mode in modes:
        group = [row for row in rows if row["mode"] == mode]
        measured = [row for row in group if row["status"] == "measured"]
        values = [row["evidence_recall_at_8"] for row in measured if row["evidence_recall_at_8"] is not None]
        average = f"{statistics.mean(values):.3f}" if values else "Not measured"
        report.append(f"| {mode} | {len(measured)} | {average} | {len(group)-len(measured)} |")
    report.extend(["", "Generation requested: " + str(args.generate), "",
                   "The baseline still receives the current target document for editing. MCP follow-up is disabled in this controlled evaluation; integration tests exercise MCP separately.",
                   "Without local Ollama/Qdrant services, hybrid results remain unavailable. Run with --generate after installing services to collect real model outputs, then annotate factual_accuracy and reviewer_editing_seconds manually.",
                   "Synthetic fixtures are small and do not establish performance on large repositories. Latencies depend on hardware and warm caches."])
    output.with_suffix(".md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", default="none,keyword,hybrid")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output", default="eval/results/retrieval.jsonl")
    asyncio.run(evaluate(parser.parse_args()))
