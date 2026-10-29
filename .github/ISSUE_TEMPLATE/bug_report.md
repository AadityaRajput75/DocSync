---
name: Bug report
about: Report a reproducible problem with DocSync
title: ""
labels: ""
assignees: ""
---

## What happened?

Describe the problem and what you expected instead.

## Steps to reproduce

1. Installation or setup used:
2. Command or action:
3. Result:

Include a minimal, sanitized Python or Markdown example if it helps.

## Environment

- DocSync version:
- Installation method (npm, tarball, or source):
- Operating system:
- Node.js version (for npm installs):
- Python version (for source installs):
- Generation provider and model (Ollama or Gemini):
- Qdrant mode (embedded or server):

## Diagnostics

Paste relevant error output and, if useful, sanitized output from `docsync doctor` or `docsync status` (`uv run docsync ...` for source installs).

```text
Paste sanitized output here.
```

Remove API keys, credentials, private paths, and proprietary source. Do not upload `.env` files or `.docsync` state.

## Additional context

Does this happen consistently? Is there a workaround?
