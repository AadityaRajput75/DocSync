# Publishing the npm installer

Package: **@aadityarajput75/docsync**, version **0.1.0**. It bundles the Python application and lockfile, so users do not need a source checkout or a separate PyPI publication.

The package is prepared locally, not published. The registry account must own the `aadityarajput75` npm scope. A GitHub account with that name does not establish npm ownership. Authentication uses npm's normal browser/terminal flow; do not paste tokens into a chat or commit them.

## Build and inspect

From the `npm/` directory of this source tree, with Node.js and npm installed:

```sh
npm test
npm pack
```

`prepack` copies only `pyproject.toml`, `uv.lock`, the source README, `LICENSE`, and Python application files into `runtime/`. It generates a SHA-256 manifest. The package `files` allowlist includes the launcher, runtime, manifest, and npm README. It excludes development environments, user repositories, `.docsync`, model files, and credentials.

There is no install/postinstall script. First invocation performs dependency setup in a user cache; normal npm installation does not inspect repositories or start daemons. The uv installer is pinned to 0.12.18 with separate shell/PowerShell SHA-256 checksums. When updating it, inspect the official installer and update its version and checksums.

Test a release artifact before publishing:

```sh
npm install -g ./aadityarajput75-docsync-0.1.0.tgz
docsync --help
```

From a disposable Python Git repository, run `docsync`, review a proposal, save a change, and verify another proposal. First-run runtime setup needs internet. Ollama must be running. A full real-model smoke test remains required before making model-quality claims.

## Publish under the owner's account

DocSync is licensed under the MIT License. Python and npm metadata declare `MIT`; the root `LICENSE` is included in Python distributions and copied into the npm package and bundled runtime. Keep the copyright and permission notice in release artifacts.

```sh
npm login
npm whoami
```

Confirm the authenticated account owns `@aadityarajput75`. Update the README publication-status wording when actually publishing, then rebuild and inspect the tarball. Publish that exact inspected artifact:

```sh
npm publish ./aadityarajput75-docsync-0.1.0.tgz --access public
```

npm may require browser authorization or a one-time code. Only after publishing succeeds, verify:

```sh
npm view @aadityarajput75/docsync version
npm install -g @aadityarajput75/docsync
```

Do not advertise registry installation as currently working until that succeeds. If 0.1.0 already exists, use a new version rather than replacing it. Keep npm and Python application versions coordinated for subsequent releases.
