# Evaluation protocol

`cases.json` contains 30 independent, annotated changes across `shop_api` and `task_api`: 24 behavior changes and six equivalent refactors/comments that should not produce documentation updates. Each case names a replacement, expected document, and required supporting files.

Run `uv run python scripts/evaluate.py` for retrieval results. Run with `--generate` once local services are available to also collect actual model decisions, drafts, token counts, and latency. The script copies examples into temporary repositories; it never changes the originals.

All variants share the same local generation model, changed source, candidate target docs, and drafting instruction. Only the supplementary retrieved evidence differs. No MCP follow-up is allowed in this ablation, so it cannot compensate for a missing retrieval variant. Actual MCP investigation is covered by integration tests and the walkthrough.

Metrics:

- **Evidence recall@8:** fraction of annotated supporting files represented in the eight retrieved chunks. This is file-level recall, not exact relevant-line recall. No-update cases without evidence annotations are excluded from its mean.
- **Update decision correctness:** whether a model draft/no-draft decision matches the annotation.
- **Target correctness:** whether the selected documentation path matches the annotation.
- **Unnecessary-update rate:** drafts on the six no-update cases.
- **Validation:** target, Markdown, protected sections, declared symbols, and citation bounds.
- **Latency/usage:** measured retrieval and generation time, plus provider-reported token counts.
- **Factual accuracy:** human score from 0 to 1, based on supported claims and completeness. Leave null until reviewed.
- **Reviewer editing effort:** measured seconds required to produce acceptable documentation. Leave null until reviewed.

Review source changes and drafts without seeing the retrieval variant when practical. Record corrections and unsupported claims in `human_notes`. Report quality for each model separately; do not combine local and cloud outputs into one score.

The supplied repositories are intentionally small. Their lexical recall can saturate, so the initial result cannot justify a vector database on its own. Extend this benchmark with larger repos, ambiguous identifiers, deleted symbols, and cross-module changes before drawing a general conclusion. The suite separately tests deletions, initial drafts, stale writes, and restart behavior.

Unavailable services are reported as unavailable, never as zero-quality model results. Automated fixture responses in tests are not included in model-quality scores.
