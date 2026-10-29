# DocSync

**Documentation that follows your code, reviewed from your terminal.**

[What is this?](#what-is-this) · [Get started](#get-started) · [Gemini](#use-gemini) · [Commands](#commands) · [How it works](#how-it-works) · [FAQ](#faq)

## What is this?

DocSync is a local-first documentation agent for Python Git repositories. It watches saved code changes, retrieves related code and documentation, investigates through read-only MCP tools, and proposes Markdown updates under `docs/`.

Use it directly from your repository:

```text
$ docsync init
$ docsync draft
$ docsync review
$ docsync watch
```

Review the diff and supporting source lines before accepting, editing, or rejecting a proposal. Existing documentation is only written after approval, and stale proposals are blocked if code or documentation changed in the meantime.

DocSync combines Python AST parsing, hybrid RAG, LangGraph, MCP, Ollama, Qdrant, and SQLite. The terminal and optional FastAPI/Streamlit interface share the same application service and approval protections.

### Status

DocSync is a portfolio-stage application. Python repositories and UTF-8 Markdown are supported; model quality and CPU latency depend on your machine and model. Tests with simulated models verify application behavior, not factual correctness. See [validation results](docs/validation.md) for measured results and remaining gaps.

## Get started

### Install from npm

Install [**`@aadityarajput75/docsync`**](https://www.npmjs.com/package/@aadityarajput75/docsync) from npm in your IDE terminal or an ordinary shell:

```powershell
npm install -g @aadityarajput75/docsync
cd C:\path\to\your-python-project
docsync
```

No DocSync source checkout, Python installation, virtual-environment commands, API server, browser, or Docker container is required for this npm workflow. You need Node.js 20+, Git, an existing local Python Git repository, and [Ollama installed and running](https://ollama.com/download). Ollama provides local embeddings even when Gemini generates the documentation.

The first `docsync` launch downloads an isolated Python runtime and pinned application dependencies into a user cache. It uses an existing `uv` installation, or bootstraps a version-pinned, checksum-verified official Astral installer. It does not change your project's Python environment. Setup needs internet and can take several minutes.

Then DocSync:

1. Finds the current Git repository and offers local Ollama or Gemini generation.
2. Checks Ollama and asks before downloading missing models.
3. Registers and indexes the project using embedded local Qdrant storage.
4. Prepares `docs/overview.md` if no overview or prior pending/accepted/rejected overview proposal exists.
5. Watches future saves and reports progress in the terminal.

Use a second terminal inside the same repository to review:

```powershell
docsync proposals
docsync review
```

Review offers accept, reject, edit, or quit. Files are written only after approval, with stale-source/destination checks and backups. Keep the watch terminal open; Ctrl+C stops it. Installation itself does not launch background jobs or read your repository.

Add `.docsync/` to your repository's `.gitignore`: it contains source snapshots, vectors, checkpoints, and backups. DocSync excludes it from indexing but does not automatically edit your ignore file.

### Install a release tarball

The release build produces `aadityarajput75-docsync-0.1.0.tgz`. It can be installed directly without cloning the source:

```powershell
npm install -g C:\path\to\aadityarajput75-docsync-0.1.0.tgz
cd C:\path\to\your-python-project
docsync
```

To build the tarball from this checkout:

```powershell
cd npm
npm test
npm pack
```

The tarball includes the launcher and bundled Python application. See [publishing instructions](docs/publishing.md) for release checks and registry publication.

### Manual commands

For explicit control instead of the combined startup flow:

```powershell
docsync run --no-watch          # Guided setup and initial proposal, then exit
docsync run --yes               # Approve model downloads, but not cloud use or doc writes
docsync init                    # Register and index; models must already be installed
docsync draft                   # Prepare an initial overview
docsync scan                    # Analyze saved changes once
docsync watch                   # Keep watching until Ctrl+C
docsync review                  # Inspect and decide what to apply
```

Once setup is complete, subsequent commands reuse the installed runtime. Generation may take minutes on a CPU. An existing overview is updated through saved code changes rather than overwritten by bootstrap. Re-running `init` preserves an established baseline.

### Run from source

Requirements: Git, [uv](https://docs.astral.sh/uv/), Python 3.11 to 3.13 (3.12 recommended), and [Ollama](https://ollama.com/download) running locally. Node.js 20+ is needed only for the npm launcher. Docker is optional when using embedded Qdrant.

From your checkout of this repository, install the locked dependencies and local models:

```powershell
uv sync --locked
ollama pull nomic-embed-text:v1.5
ollama pull qwen2.5-coder:3b
$env:DOCSYNC_QDRANT_MODE = "embedded"
uv run docsync doctor
```

Then initialize a Python Git repository and prepare a proposal. Replace the example path with your project's Git root:

```powershell
uv run docsync init --project C:\path\to\your-python-project
uv run docsync draft --project C:\path\to\your-python-project
uv run docsync review --project C:\path\to\your-python-project
uv run docsync watch --project C:\path\to\your-python-project
```

Keep the source terminal in this checkout so `uv run` uses DocSync's environment. Run review in another terminal with the same environment setting and project path. Add `.docsync/` to the target project's `.gitignore` before use. Existing documentation is written only after review approval.

### Developing or running from Python source

Maintainers can still run `uv sync --locked` and `uv run docsync --help` in the source checkout, or install with `uv tool install --python 3.12 --editable .`. Python-source mode retains the original Qdrant server default; use the provided `compose.yaml`, or set `DOCSYNC_QDRANT_MODE=embedded` before starting all processes. The npm launcher defaults to embedded storage automatically.

## Use Gemini

**Gemini sends selected source code, changes, existing documentation, and investigation evidence to Google. Embeddings and repository tools stay local.** Opt-in is stored separately for each project.

Set your key in the terminal that will run `init`, `draft`, `scan`, or `watch`:

```powershell
$env:GEMINI_API_KEY = "your-key"
docsync models
```

Choose a model returned by discovery, then initialize with explicit consent:

```powershell
$env:DOCSYNC_GEMINI_MODEL = "MODEL_ID_FROM_LIST"
docsync init --provider gemini --allow-cloud
docsync draft
docsync review
```

Replace `MODEL_ID_FROM_LIST` with an actual returned identifier. For an already initialized project:

```powershell
docsync config --provider gemini --allow-cloud
```

In an interactive terminal, omitting `--allow-cloud` prompts for consent. In scripts it fails instead of assuming approval. Switch back to local generation and revoke consent with:

```powershell
docsync config --provider local
```

Keys are read from environment variables, not stored in project state. Repository `.env` files are not loaded. Set the variables again in each processing terminal, or configure your shell securely. An already-running worker uses its own environment; restart it after changing keys or model settings. There is no automatic cloud fallback.

## Commands

Run `docsync COMMAND --help` for options.

| Command | Purpose |
|---|---|
| `docsync` / `docsync run` | Guided setup, initial overview proposal, then watching (bare command via npm) |
| `docsync init` | Register the current repository and build its initial index |
| `docsync index` | Refresh the index and establish a baseline without generation |
| `docsync draft` | Propose an initial `docs/overview.md` |
| `docsync scan` | Analyze saved Python changes and wait for the result |
| `docsync watch` | Watch saves and process jobs with terminal progress |
| `docsync status` | Show settings, recent jobs, skipped files, and pending count |
| `docsync proposals` | List pending proposals; add `--all` for history |
| `docsync review [ID]` | Inspect a proposal and choose a review action |
| `docsync config` | Show or change provider, watching, and ignore settings |
| `docsync doctor` | Check Ollama, Qdrant, and configured models |
| `docsync models` | Discover Gemini generation models using your key |
| `docsync start` | Start the optional browser dashboard, API, and worker |
| `docsync api`, `worker`, `ui` | Run individual backend/dashboard processes |

Repository commands (`run` through `config`) accept `--project PATH` and `--data-dir PATH`. Without `--project`, they locate the nearest Git root from your current directory, including subfolders. Proposal IDs can be unique prefixes; ambiguous IDs are rejected.

### Review from scripts or your editor

```powershell
docsync review PROPOSAL_ID --show
docsync review PROPOSAL_ID --accept
docsync review PROPOSAL_ID --reject
docsync review PROPOSAL_ID --file C:\path\to\reviewed.md
```

Replace `PROPOSAL_ID` with an ID from `docsync proposals`. `--accept` and `--file` are explicit approval and apply immediately after validation. Without an action flag, non-interactive review only displays a preview. Multiple pending proposals require an ID or interactive selection.

Interactive editing uses `VISUAL`, then `EDITOR`, then Notepad on Windows or `vi` elsewhere. Configure an editor that waits until editing is complete, for example:

```powershell
$env:VISUAL = 'code --wait'
docsync review PROPOSAL_ID --edit
```

### Project settings

```powershell
docsync config --ignore "experiments/**" --ignore "local_data/**"
docsync config --watching off
```

Ignore patterns are added to existing patterns. `watch` enables watching again. One repository is actively watched per state directory, and a worker lock prevents two processes from processing the same queue simultaneously. A manual processing command waits for an existing worker when one owns that state directory.

## Moving from the dashboard

Your previous dashboard state remains intact. To access it from the CLI, point to the original state directory rather than creating a new one:

```powershell
$env:DOCSYNC_DATA_DIR = "C:\path\to\docsync-source\.docsync"
cd C:\path\to\your-python-project
docsync status
docsync proposals --all
docsync review
```

You can instead pass `--data-dir` on each repository command. No state is moved or copied. Keep the same state path for all processes that should share project history. If your existing dashboard uses Docker Qdrant, also set `DOCSYNC_QDRANT_MODE=server` in both terminals. Switching vector backends requires a fresh `docsync index`; do not mix backends against the same live state.

Streamlit remains available with `docsync start`. Run it from the repository root, or set `DOCSYNC_DATA_DIR` explicitly. The dashboard uses `http://127.0.0.1:8501`; FastAPI uses `http://127.0.0.1:8000`, with API documentation at `/docs`. CLI commands call the same application service directly, so an HTTP server is optional.

## How it works

```text
Saved Python change
    → immutable snapshot and AST parsing
    → local embeddings and keyword/vector retrieval
    → bounded LangGraph investigation through MCP tools
    → update / no update / insufficient evidence
    → Markdown draft and deterministic diff
    → validation and developer review
    → freshness checks, backup, and approved write
```

- **RAG:** BM25, vector similarity, symbol matches, and approximate static references contribute to reciprocal rank fusion. Up to eight retrieved chunks supplement the code change; content/model hashes cache embeddings.
- **MCP:** `list_tree`, `read_file`, `search_text`, `find_symbol`, and `get_related_symbols` inspect the stored snapshot through a local stdio client/server. They cannot execute code or write files.
- **Agent workflow:** structured decisions allow up to six tool calls. LangGraph persists checkpoints, including pending reviews. Malformed structured output gets one retry.
- **Review:** generated changes outside allowed sections are rejected. Approval rechecks source and destination hashes, retains a backup, and replaces the Markdown file through a temporary file.

See [architecture](docs/architecture.md) for details. Python code and tests are inspected as source, never executed by the agent.

## FAQ

**Does this answer questions about my repository like Autodoc?**

Not in this version. DocSync focuses on preparing and reviewing documentation updates. There is no repository-chat command.

**Why does Gemini mode still need Ollama and Qdrant?**

Ollama creates local embeddings and Qdrant searches them. The npm installation embeds Qdrant inside the worker, so it does not need Docker. Gemini handles investigation decisions and writing.

**Why did a job finish without creating a proposal?**

There may be no saved changes, an overview may already exist, or the agent may decide the change does not affect documentation. `docsync status` shows the reason. Insufficient evidence and syntax errors are reported rather than forcing a draft.

**Can I run commands from another folder?**

Yes: `docsync scan --project C:\path\to\repo`. Use the same `--data-dir` or environment setting if reusing dashboard history.

**What do I do after HTTP 404 or an unavailable-model error?**

Run `docsync doctor`. For Gemini, run `docsync models` with your key and choose an available model; discovery does not guarantee quota or structured-output compatibility. For local generation, download the configured model with Ollama. Restart a persistent worker after changing its environment.

**What happens if I edit code or documentation before accepting?**

The stale proposal is blocked and regeneration is queued. Keep `watch` running or run `scan` to process queued work. Rejected proposals do not recur for the same analyzed revision.

**Is my source private?**

Local mode keeps model processing on local services. Gemini mode transmits selected evidence after consent. `.docsync` (including embedded vectors), or the server-mode Qdrant volume, contain source-derived material and are not encrypted by DocSync. Filename/ignore filtering is not a secret scanner; secrets embedded in ordinary source text can still be included.

**Where are backups and settings?**

Repository commands default to `<git-root>/.docsync`. `--data-dir` takes precedence over `DOCSYNC_DATA_DIR`, which takes precedence over that default. Backups are under `backups/<proposal-id>/`; `original.md` contains prior bytes when the destination existed, and `target.txt` identifies the destination. Review later edits before manually restoring a backup. State has no automatic retention policy.

## Configuration

`.env.example` lists environment settings; it is not loaded automatically.

| Variable | Purpose / default |
|---|---|
| `DOCSYNC_DATA_DIR` | Explicit shared state directory; otherwise repository commands use the Git root's `.docsync` |
| `DOCSYNC_OLLAMA_URL` | `http://127.0.0.1:11434` |
| `DOCSYNC_QDRANT_MODE` | `embedded` for npm; `server` for Python-source mode |
| `DOCSYNC_QDRANT_URL` | `http://127.0.0.1:6333` |
| `DOCSYNC_MODEL` | Local generation: `qwen2.5-coder:3b` |
| `DOCSYNC_EMBED_MODEL` | Local embeddings: `nomic-embed-text:v1.5` |
| `DOCSYNC_GEMINI_MODEL` | Gemini identifier; use `docsync models` to discover available choices |
| `GEMINI_API_KEY` | Required only for Gemini generation/discovery |
| `DOCSYNC_API_URL` | Optional dashboard API: `http://127.0.0.1:8000` |
| `VISUAL` / `EDITOR` | Editor command for interactive proposal editing |

Defaults limit eligible files to 2,000, file size to 1 MB, documents per run to five, and job duration to 15 minutes. Large changes may exceed the prompt budget. Dynamic references are approximate, and source citations do not prove factual accuracy.

## Development and evaluation

From the DocSync source directory:

```powershell
uv sync --locked
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/init_examples.py
uv run python scripts/evaluate.py
```

For a CLI demo, connect `examples/shop_api`, run `docsync init`, change `list_products`' default limit from `10` to `20`, then run `docsync scan` and `docsync review`. The existing deployment section should remain unchanged.

The evaluation includes 30 annotated cases across two example repositories and compares changed code only, keyword/symbol retrieval, and hybrid retrieval. Model-backed runs need local services and manual scoring of factual accuracy and editing effort. Vector retrieval's quality benefit has not yet been established. See [evaluation guidance](eval/README.md), [validation results](docs/validation.md), and the [walkthrough](docs/walkthrough.md).

For implementation changes, add behavioral tests where useful and keep cloud opt-in, repository boundaries, human review, and stale-write protection intact. Source lives in `src/docsync/`; tests in `tests/`; evaluation cases in `eval/`. `uv.lock` records the development dependency resolution.

## Repository layout

| Path | Contents |
|---|---|
| `src/docsync/` | CLI, shared service, agent, retrieval, MCP tools, API, and dashboard |
| `tests/` | Automated Python behavior and integration tests |
| `npm/` | Node launcher, bundling script, and launcher tests |
| `docs/` | Architecture, walkthrough, validation history, and publishing guide |
| `examples/` | Small Python repositories for demos and evaluation |
| `eval/` | Annotated cases and retrieval experiment reports |
| `scripts/` | Evaluation, example initialization, and release tooling |

## License

DocSync is licensed under the [MIT License](LICENSE). Contributions are welcome: open an issue to discuss a change, or submit a pull request with a clear description and relevant validation. Contributions are provided under the same MIT license.
