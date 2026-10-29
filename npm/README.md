# DocSync


**Documentation that follows your Python code, reviewed from your terminal.**

DocSync watches your local Git repository, investigates saved changes using hybrid retrieval and MCP tools, and prepares Markdown updates for your approval.

## Install and start

Install `@aadityarajput75/docsync` directly from npm:

```sh
npm install -g @aadityarajput75/docsync
cd your-python-project
docsync
```

Alternatively, install a supplied release tarball:

```sh
npm install -g ./aadityarajput75-docsync-0.1.0.tgz
```

Run in VS Code's terminal, another IDE, or a normal shell. Requirements: Node.js 20+, Git, a local Python Git repository, and [Ollama installed and running](https://ollama.com/download). No separate Python, uv, Docker, API server, or Streamlit setup is needed.

First launch prepares isolated Python 3.12 and locked dependencies outside your repository. It uses uv if available, otherwise downloads a pinned official Astral installer and verifies its checksum. This needs internet; repeated commands reuse the runtime. It does not change your project's Python environment.

`docsync` offers provider setup, checks/downloads local models with consent, builds an index, prepares an initial overview when appropriate, and starts watching saves. Local generation uses Ollama. Gemini requires explicit project-level consent. Embeddings always run locally. Qdrant is embedded, so Docker is unnecessary.

In a second terminal inside the repository:

```sh
docsync status
docsync proposals
docsync review
```

Review the diff and source evidence, then accept, reject, edit, or quit. Documentation is written only after approval. If source or destination changed, the stale proposal is blocked. Ctrl+C stops the watcher. Installing the npm package alone does not start processes or read your repository.

## Gemini

Set your API key in the terminal that runs DocSync. PowerShell:

```powershell
$env:GEMINI_API_KEY = "your-key"
docsync models
$env:DOCSYNC_GEMINI_MODEL = "MODEL_ID_FROM_LIST"
docsync run --provider gemini --allow-cloud
```

Replace the model placeholder with an available returned identifier. Bash/zsh use `export GEMINI_API_KEY="your-key"` and `export DOCSYNC_GEMINI_MODEL="..."` instead.

**Gemini receives selected code, documentation, changes, and tool evidence.** Embeddings stay local, so Ollama is still required. Keys are read from environment variables and are not persisted. Restart a running worker after changing its model or key. There is no automatic cloud fallback.

## Commands

| Command | Purpose |
|---|---|
| `docsync` | Guided setup, initial overview proposal, and watching |
| `docsync run --no-watch` | Setup and initial proposal, then exit |
| `docsync init` | Register/index with models already installed |
| `docsync draft` | Propose an initial `docs/overview.md` |
| `docsync scan` | Analyze saved changes once |
| `docsync watch` | Watch saves until Ctrl+C |
| `docsync status` | Show recent jobs and pending reviews |
| `docsync proposals` | List pending proposals; `--all` includes history |
| `docsync review [ID]` | Inspect diff/evidence and choose a review action |
| `docsync config` | Show settings; change provider, ignores, or watching |
| `docsync doctor` | Check local services and models |
| `docsync models` | Discover available Gemini generation models |
| `docsync --help` | Show all commands, including optional API/dashboard commands |

Repository commands accept `--project PATH` and `--data-dir PATH`. Review supports `--show`, `--accept`, `--reject`, `--edit`, and `--file reviewed.md`. The last option explicitly approves applying your edited Markdown. Interactive editing uses `VISUAL` or `EDITOR`; for VS Code set `VISUAL` to `code --wait`.

`docsync run --yes` approves required model downloads only. It does not approve cloud transmission or documentation writes. Large model downloads and CPU generation can take several minutes.

## Local data and limits

Add `.docsync/` to your repository's `.gitignore`. Source snapshots, checkpoints, backups, and embedded vectors are stored there. `DOCSYNC_DATA_DIR` or `--data-dir` can select existing dashboard state. If that state uses a Qdrant server, set `DOCSYNC_QDRANT_MODE=server` consistently across processes; do not mix live vector backends.

Runtime files are cached under the user cache's `docsync-runtime` directory, configurable with `DOCSYNC_RUNTIME_HOME`. Uninstalling the npm package does not erase runtime caches or repository history. The cache contains dependencies; repository source remains in the selected state directory.

This version supports Python and UTF-8 Markdown in local Git repositories. It inspects code without executing it. It prepares updates under `docs/`, not source edits or docstrings. It has no repository-chat command or VS Code extension UI. Filename exclusions are not a secret scanner; sensitive literals in ordinary code can be included in selected evidence. Generated claims still need human review.

## Troubleshooting

- **Ollama not ready:** install/open Ollama or run `ollama serve`, then retry `docsync`.
- **Model missing:** approve the model download, or run the displayed `ollama pull` command yourself.
- **Runtime installation failed:** check your internet/proxy settings and retry. You can install uv yourself from [Astral's official guide](https://docs.astral.sh/uv/getting-started/installation/).
- **Install lock timeout:** after ensuring no DocSync installer is running, remove the `install.lock` path shown in the error and retry.
- **Command not found:** ensure npm's global command directory is on PATH and reopen your IDE terminal.
- **No proposal:** check `docsync status`; an unchanged revision or internal refactor can correctly require no update.
- **Gemini 404:** use `docsync models`, select a returned model, and restart the worker. Quota/access still apply.

This is a portfolio-stage release. Automated tests use simulated models; they do not establish real-model factual accuracy, CPU speed, or fully offline operation on every platform.
