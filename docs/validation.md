# Validation results — 4 October 2026

## Verified in this workspace

- **40 automated tests passed** on Windows with Python 3.12.14.
- Ruff checks and Python compilation passed.
- `uv sync --locked` completed; source distribution and wheel built successfully.
- FastAPI started on `127.0.0.1:8000`; `/health` returned 200, and the generated OpenAPI document contained the requested routes.
- Streamlit started on `127.0.0.1:8501`; its health endpoint returned `ok`.
- Streamlit AppTest rendered the project, progress, documentation diff, evidence, and review buttons without exceptions.
- Actual MCP subprocess discovery and calls worked over stdio, including rejecting escaped paths and cross-project snapshots.
- Actual LangGraph SQLite checkpoints paused for review and resumed after acceptance.
- Qdrant’s in-memory engine exercised hybrid-ranking integration and snapshot filtering using deterministic test embeddings.
- Tests covered initial drafts, no-update decisions, accepted/rejected/edited proposals, stale code/docs, preserved sections, backups, apply recovery, queue recovery, invalid syntax, limits, save coalescing, additional changes during generation, local endpoint restrictions, cloud consent, and malformed model output.

The test model responses are scripted fixtures. They verify application behavior, not an LLM’s ability to produce correct documentation. In-memory Qdrant tests do not substitute for a live Docker-service compatibility test.

## Retrieval experiment

The included 30-case benchmark ran with 24 behavior-changing cases and six no-update cases:

| Variant | Cases executed | Mean file-level evidence recall@8 |
|---|---:|---:|
| Changed code only / no supplementary retrieval | 30 | 0.000 |
| Keyword + symbol retrieval | 30 | 1.000 |
| Hybrid retrieval with real embeddings | 0 | Not measured |

Recall averages exclude cases without annotated supporting files. The small fixtures allow lexical retrieval to saturate; these results do **not** establish a benefit from vectors. See [the generated report](../eval/results/retrieval.md) and [raw observations](../eval/results/retrieval.jsonl).

## Not verified here

Docker and Ollama were not installed/running, and no Gemini key was configured. Therefore:

- No real local-model generation, CPU latency, or memory benchmark was performed.
- No live Qdrant Docker test or real-embedding hybrid quality result was produced.
- No live Gemini response/schema compatibility test was performed.
- Factual accuracy and reviewer editing effort remain unscored.
- No model-backed five-minute video was recorded. A [timed presentation runbook](walkthrough.md) is included.

Run `uv run docsync doctor`, the setup commands in the README, and then `uv run python scripts/evaluate.py --generate` to collect these measurements on the target machine. Exercise the walkthrough with the real model before presenting model behavior as validated.

## Gemini troubleshooting update — 10 October 2026

- Updated the default to `gemini-3.5-flash-lite`, following Google's current model guide. Explicit environment overrides still take precedence.
- Added `uv run docsync models` to list models advertising `generateContent`, with pagination and no repository-content transmission.
- Accepted model resource names with the `models/` prefix and displayed the configured generation model in the interface.
- Replaced generic HTTP errors with service-specific messages and model-selection guidance. Response bodies, URL queries, and credentials are excluded from recorded errors.
- **51 automated tests passed**, including 11 new simulated Gemini/discovery/error regression cases. Ruff checks passed. The sandbox emitted a temporary-directory cleanup permission warning after the successful test run.
- No live request with the user's key was possible from the testing process. Account access, quota, and actual generation must still be checked from the user's keyed terminal.

## Imported-symbol validation fix — 10 October 2026

- Documentation validation now recognizes explicit imports, aliases, and qualified import paths using AST inspection only. Wildcard imports and unobserved module members do not establish symbol evidence.
- Replayed the previously failed LinearRegression draft from its saved checkpoint against its original snapshot: full validation passed without another model request or documentation write.
- **64 automated tests passed**, including 13 new imported-symbol and unsupported-reference regression cases. Ruff checks passed. A sandbox temporary-directory cleanup permission warning appeared after the successful test run.
- Recognizing a symbol name does not verify runtime availability or the factual accuracy of the generated description; developer review remains necessary.

## Terminal workflow — 28 October 2026

- Added repository-first `init`, `index`, `draft`, `scan`, `watch`, `status`, `proposals`, `review`, and `config` commands. FastAPI and the CLI share the same service; terminal use does not require a running HTTP server or browser.
- Added repository-root discovery, explicit state-directory reuse, per-project cloud consent, progress output, non-interactive preview and approval flags, and editor-based review with confirmation.
- **80 automated tests passed**, including 16 CLI tests covering registration/bootstrap, changed-code proposals, approval/backups, rejection suppression, edited files, stale writes, cloud consent/revocation, idempotent initialization, syntax failures, state discovery, project isolation, worker contention, restart recovery, and editor cancellation.
- Ruff and `uv lock --check --offline` passed. The source distribution and wheel built successfully offline. Console-script and `python -m docsync` help commands were exercised.
- A sandbox temporary-directory cleanup permission warning appeared after the successful full test run. Generation in CLI tests used scripted models; these results do not establish live Gemini/local-model quality, CPU latency, or an offline end-to-end model run.

## Installable npm package — 28 October 2026

- Prepared `@aadityarajput75/docsync@0.1.0` with a `docsync` executable, bundled Python application/lockfile, checksum-verified uv bootstrap, isolated managed Python, and automatic first-run setup. No install/postinstall script runs repository work.
- The npm launcher defaults to embedded Qdrant storage, eliminating Docker from this installation path. Ollama remains a prerequisite for local embeddings. Bare `docsync` guides provider setup, offers model downloads, prepares an initial proposal, and starts watching.
- **89 Python tests and 8 Node launcher tests passed.** Ruff passed. A sandbox temporary-directory cleanup warning appeared after the successful Python suite.
- Packed the npm tarball and installed it globally into a disposable prefix with lifecycle scripts disabled. The installed Windows command downloaded Python 3.12 and locked dependencies into its cache and displayed help from outside the source checkout. Separately verified automatic uv installation when no uv command was available to the bootstrap probe.
- The installed-package smoke test used a loopback simulated Ollama server with actual embedded Qdrant and actual MCP subprocess communication. It verified initial setup, no writes before approval, evidence display, approval, a later saved-code update, and startup isolation from a repository module named `docsync.py`. The test exited successfully and its temporary fixture was cleaned up.
- This does not constitute a real-model quality test. Linux/macOS bootstrap paths are implemented but have not been exercised here. At the time of this validation run, npm publication was pending. Version `0.1.0` was subsequently verified on the registry on 30 October 2026.
