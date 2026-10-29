import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

import pathspec


def digest(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def safe_path(root, relative, docs_only=False):
    path = PurePosixPath(relative)
    if not relative or "\\" in relative or ":" in relative or path.is_absolute() or ".." in path.parts:
        raise ValueError("Invalid repository-relative path")
    if docs_only and (len(path.parts) < 2 or path.parts[0] != "docs" or path.suffix != ".md"):
        raise ValueError("Documentation targets must be Markdown files inside docs/")
    root = Path(root).resolve()
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("Linked files and directories are not supported")
    resolved = current.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Path escapes registered repository")
    return resolved


def validate_root(root):
    root = Path(root).expanduser().resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise ValueError("Choose the root of an existing local Git repository")
    return root


EXCLUDED_PARTS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "dist", "build",
                  ".docsync", ".aws", ".ssh", ".idea", ".pytest_cache", "site-packages", "vendor"}


def excluded(path):
    parts = PurePosixPath(path.lower()).parts
    name = parts[-1] if parts else ""
    return (any(p in EXCLUDED_PARTS for p in parts) or name.startswith(".env")
            or any(word in name for word in ("credential", "secret", "private_key"))
            or name.endswith((".pem", ".key", "_pb2.py", "_pb2_grpc.py")))


def candidates(root):
    proc = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), "ls-files", "-z",
                           "--cached", "--others", "--exclude-standard"],
                          capture_output=True, timeout=30, check=True)
    return sorted(set(proc.stdout.decode("utf-8", errors="replace").split("\0")) - {""})


def capture(project, settings):
    root = validate_root(project["root"])
    ignores = pathspec.PathSpec.from_lines("gitwildmatch", project.get("ignore", []))
    files, skipped, errors = {}, [], []
    paths = candidates(root)
    # check-ignore applies .gitignore to tracked files as well, including nested rules.
    proc = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), "check-ignore",
                           "--no-index", "-z", "--stdin"], input="\0".join(paths).encode(),
                          capture_output=True, timeout=30)
    if proc.returncode not in (0, 1):
        raise ValueError("Cannot evaluate repository ignore rules")
    git_ignored = set(proc.stdout.decode("utf-8", errors="replace").split("\0"))
    for relative in paths:
        if not (relative.endswith(".py") or (relative.startswith("docs/") and relative.endswith(".md"))):
            continue
        reason = None
        if excluded(relative) or relative in git_ignored or ignores.match_file(relative):
            reason = "Excluded by privacy or ignore rules"
        try:
            path = safe_path(root, relative)
            if path.is_relative_to(settings.data_dir.resolve()):
                reason = "Application state"
            if not path.exists():
                continue
            if len(files) >= settings.max_files:
                reason = "File-count limit"
            elif path.stat().st_size > settings.max_file_bytes:
                reason = "File-size limit"
            if reason:
                skipped.append({"path": relative, "reason": reason})
                continue
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            if "\x00" in text:
                raise ValueError("Binary content")
            files[relative] = {"text": text, "hash": digest(raw),
                               "newline": "\r\n" if b"\r\n" in raw else "\n", "bom": raw.startswith(b"\xef\xbb\xbf")}
            if relative.endswith(".py"):
                try:
                    ast.parse(text)
                except SyntaxError as exc:
                    errors.append({"path": relative, "line": exc.lineno, "reason": "Python syntax error"})
        except (OSError, UnicodeError, ValueError) as exc:
            skipped.append({"path": relative, "reason": str(exc)[:160]})
    hashes = {p: f["hash"] for p, f in files.items()}
    source_hash = digest(json.dumps({p: h for p, h in hashes.items() if p.endswith(".py")}, sort_keys=True))
    return {"id": digest(project["id"] + json.dumps(hashes, sort_keys=True)), "project_id": project["id"],
            "files": files, "source_hash": source_hash, "skipped": skipped, "errors": errors}


def changes(old, new):
    a, b = old.get("files", {}) if old else {}, new["files"]
    return [p for p in sorted(set(a) | set(b)) if p.endswith(".py")
            and a.get(p, {}).get("hash") != b.get(p, {}).get("hash")]


def changed_symbols(old, new, path):
    def bodies(snapshot):
        text = (snapshot or {}).get("files", {}).get(path, {}).get("text", "")
        if not text:
            return {}
        symbols, _ = python_symbols(text, path)
        lines = text.splitlines()
        return {s["name"]: "\n".join(lines[s["start"]-1:s["end"]]) for s in symbols}
    before, after = bodies(old), bodies(new)
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


def python_symbols(text, path):
    tree = ast.parse(text)
    result = []
    lines = text.splitlines()

    def walk(node, parent=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{parent}.{child.name}" if parent else child.name
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                calls = sorted({ast.unparse(n.func) for n in ast.walk(child) if isinstance(n, ast.Call)})
                result.append({"name": name, "path": path, "start": start, "end": child.end_lineno,
                               "signature": lines[child.lineno - 1].strip(),
                               "docstring": ast.get_docstring(child) or "", "calls": calls})
                walk(child, name)
            else:
                walk(child, parent)
    walk(tree)
    return result, sorted({ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))})


def documentation_symbols(snapshot):
    """Source-defined and explicitly imported names; never import repository code.

    This establishes name evidence, not runtime availability or API behavior.
    Wildcard imports cannot establish which names exist.
    """
    known = set()
    for path, file in snapshot["files"].items():
        if not path.endswith(".py"):
            continue
        symbols, _ = python_symbols(file["text"], path)
        for symbol in symbols:
            known.update((symbol["name"], symbol["name"].split(".")[-1]))
        for node in ast.walk(ast.parse(file["text"])):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    known.update((alias.asname or alias.name.split(".")[0], alias.name))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    known.add(alias.asname or alias.name)
                    module = "." * node.level + (node.module or "")
                    qualified = module + ("" if module.endswith(".") else ".") + alias.name
                    known.add(qualified)
    return known


def split_lines(lines, start, byte_limit=1400):
    """UTF-8 byte bound conservatively bounds byte-level tokens; never silently truncate."""
    text, begin = "", start
    for number, line in enumerate(lines, start):
        # Unusual huge single lines are split into bounded pieces with the same citation line.
        pieces, piece = [], ""
        for char in line + "\n":
            if len((piece + char).encode()) > byte_limit:
                pieces.append(piece)
                piece = ""
            piece += char
        pieces.append(piece)
        for piece in pieces:
            if text and len((text + piece).encode()) > byte_limit:
                yield begin, max(begin, number - 1), text
                text, begin = "", number
            text += piece
    if text:
        yield begin, start + len(lines) - 1, text


def chunks(snapshot):
    result, symbols = [], []
    for path, file in snapshot["files"].items():
        lines = file["text"].splitlines()
        regions = []
        if path.endswith(".py"):
            syms, imports = python_symbols(file["text"], path)
            symbols.extend(syms)
            regions = [(s["start"], s["end"], s["name"]) for s in syms]
            covered = {n for a, b, _ in regions for n in range(a, b + 1)}
            # Also index module-level assignments, imports, and routes outside functions.
            for n in range(1, len(lines) + 1):
                if n not in covered:
                    if regions and regions[-1][2] == "<module>" and regions[-1][1] == n - 1:
                        a, _, name = regions[-1]
                        regions[-1] = (a, n, name)
                    else:
                        regions.append((n, n, "<module>"))
        else:
            starts = [i for i, line in enumerate(lines, 1) if re.match(r"^#{1,6}\s", line)]
            starts = sorted(set([1] + starts))
            regions = [(a, b - 1, lines[a - 1] if lines else "")
                       for a, b in zip(starts, starts[1:] + [len(lines) + 1])]
        for start, end, symbol in regions:
            for a, b, text in split_lines(lines[start-1:end], start):
                if not text.strip():
                    continue
                chunk = {"path": path, "start": a, "end": b, "symbol": symbol, "text": text}
                chunk["id"] = digest(json.dumps(chunk, sort_keys=True))
                result.append(chunk)
    return result, symbols


def tokens(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9]+", text.lower())
