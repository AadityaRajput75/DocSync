# Retrieval evaluation

30 independently annotated synthetic changes across two bundled Python repositories.
No model-generated quality score is substituted for human review. File-level evidence recall is reported at eight chunks.

| Mode | Measured cases | Mean evidence recall@8 | Unavailable/failed |
|---|---:|---:|---:|
| none | 30 | 0.000 | 0 |
| keyword | 30 | 1.000 | 0 |
| hybrid | 0 | Not measured | 30 |

Generation requested: False

The baseline still receives the current target document for editing. MCP follow-up is disabled in this controlled evaluation; integration tests exercise MCP separately.
Without local Ollama/Qdrant services, hybrid results remain unavailable. Run with --generate after installing services to collect real model outputs, then annotate factual_accuracy and reviewer_editing_seconds manually.
Synthetic fixtures are small and do not establish performance on large repositories. Latencies depend on hardware and warm caches.
