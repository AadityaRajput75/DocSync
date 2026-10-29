# Contributing to DocSync

Thanks for helping improve DocSync. Bug reports, documentation fixes, tests, and feature proposals are welcome. Use [GitHub issues](https://github.com/AadityaRajput75/DocSync/issues) to report a problem or discuss a substantial change before implementing it.

## Set up a development checkout

Install Git and [uv](https://docs.astral.sh/uv/). DocSync supports Python 3.11 to 3.13; Python 3.12 is recommended. Node.js 20+ is required for launcher work.

Fork the repository on GitHub, then replace `YOUR_USERNAME` below:

```sh
git clone https://github.com/YOUR_USERNAME/DocSync.git
cd DocSync
git remote add upstream https://github.com/AadityaRajput75/DocSync.git
git switch -c describe-your-change
uv sync --locked
uv run docsync --help
```

Run commands from the checkout root unless a command explicitly changes directory. `uv sync --locked` includes the development test and lint dependencies.

## Run tests and checks

For Python changes:

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv lock --check
```

The automated suite uses scripted model responses and local test services; it does not require an Ollama server, Docker, or a Gemini API key. It checks application behavior rather than real-model documentation quality. If Windows restricts the default temporary directory, use `uv run pytest -q --basetemp=dist/pytest-local` with a disposable directory; pytest owns and clears that directory.

For npm launcher or packaging changes:

```sh
cd npm
npm test
npm pack --dry-run
cd ..
```

`npm pack --dry-run` runs the bundling step and refreshes generated runtime files. `npm/runtime/`, the generated manifest, and tarballs are ignored; do not commit them. No npm dependency installation is needed for the current launcher tests.

Documentation-only changes should have working relative links, accurate commands, and clean Markdown. Run `git diff --check`; a full model-backed run is unnecessary for wording changes.

## Try the application locally

For a manual test, install and start [Ollama](https://ollama.com/download), then prepare the models:

```sh
ollama pull nomic-embed-text:v1.5
ollama pull qwen2.5-coder:3b
```

Set `DOCSYNC_QDRANT_MODE=embedded` in every processing terminal to use Qdrant without Docker. In PowerShell:

```powershell
$env:DOCSYNC_QDRANT_MODE = "embedded"
uv run docsync doctor
uv run docsync init --project C:\path\to\disposable-python-repo
uv run docsync draft --project C:\path\to\disposable-python-repo
uv run docsync review --project C:\path\to\disposable-python-repo
```

Use a disposable Python Git repository and add `.docsync/` to its `.gitignore`. Repository `.env` files are not loaded automatically. Gemini needs a key in the processing terminal and explicit cloud consent for that project. See the [README](README.md) for provider setup, watching, and review commands.

## Prepare a pull request

- Keep the change focused and explain the problem and resulting behavior.
- Add or update behavioral tests for fixes and features where useful. Update documentation when commands or user-visible behavior change.
- Preserve explicit cloud opt-in, repository boundaries, human approval, backups, and stale-write protections.
- Run the checks relevant to your change and describe their results, including any checks you could not run. Distinguish scripted tests from real-model validation.
- Open a pull request against `main` from your fork. Link a related issue when one exists and include reproduction steps or before/after examples when useful.

Do not commit API keys, `.env` files, user source snapshots, `.docsync` state, model downloads, or generated release artifacts. Use minimal, sanitized examples in issues and pull requests. Never include credentials in diagnostic output.

Maintainers handle release version bumps and registry publication. See the [publishing guide](docs/publishing.md) for the release process.

## License

By submitting a contribution, you agree to provide it under the project's [MIT License](LICENSE).
