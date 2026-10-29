import difflib
import re

from docsync.repository import changed_symbols, documentation_symbols, safe_path, tokens


def sections(text):
    lines = text.splitlines(keepends=True)
    boundaries = [i for i, line in enumerate(lines) if re.match(r"^#{1,6}\s", line)]
    starts = sorted(set([0] + boundaries))
    return [(a, b) for a, b in zip(starts, starts[1:] + [len(lines)]) if b > a]


def targets(snapshot, changed, associations, bootstrap=False, old_snapshot=None, evidence=None):
    docs = {p: f["text"] for p, f in snapshot["files"].items() if p.startswith("docs/")}
    evidence = evidence or []
    retrieved_docs = {e["path"]: 1 / (rank + 1) for rank, e in reversed(list(enumerate(evidence)))
                      if e["path"] in docs}
    if bootstrap:
        return [{"path": "docs/overview.md", "old": docs.get("docs/overview.md", ""),
                 "ranges": [(0, len(docs.get("docs/overview.md", "").splitlines()))],
                 "reason": "Initial project overview", "sources": changed}]
    result = {}
    for source in changed:
        words = set(tokens(source)) - {"py", "src", "tests", "test"}
        text = snapshot["files"].get(source, {}).get("text", "")
        names = changed_symbols(old_snapshot, snapshot, source) if old_snapshot else re.findall(r"(?:def|class)\s+(\w+)", text)
        words.update(tokens(" ".join(names)))
        linked = [a["document"] for a in associations if source in a["sources"] and a["document"] in docs]
        def score(path):
            return len(words & set(tokens(path + " " + docs[path]))) + retrieved_docs.get(path, 0)
        ranked = sorted(docs, key=score, reverse=True)
        paths = linked or ([ranked[0]] if ranked and score(ranked[0]) > 0 else [])
        if not paths:
            slug = re.sub(r"[^a-z0-9]+", "-", source[:-3].lower()).strip("-")
            paths = [f"docs/{slug}.md"]
        for path in paths:
            old = docs.get(path, "")
            lines = old.splitlines(keepends=True)
            scored = [(len(words & set(tokens("".join(lines[a:b])))), a, b) for a, b in sections(old)]
            selected = [(a, b) for score, a, b in scored if score > 0]
            if not selected:
                selected = [(a, b) for a, b in sections(old) if any(
                    e["path"] == path and e["start"] - 1 < b and e["end"] > a for e in evidence)]
            # Existing document with no matching section needs more evidence, not wholesale rewrite.
            target = result.setdefault(path, {"path": path, "old": old, "ranges": [], "sources": [],
                                              "reason": "Existing source association" if linked else
                                              ("Related documentation" if old else "New module guide")})
            target["ranges"] = sorted(set(target["ranges"] + selected))
            target["sources"].append(source)
    return list(result.values())


def validate_markdown(content):
    if not re.search(r"(?m)^#{1,6}\s+\S", content):
        raise ValueError("Documentation must contain a Markdown heading")
    fences = re.findall(r"(?m)^\s*(`{3,}|~{3,})", content)
    opened = None
    for fence in fences:
        if opened is None:
            opened = fence
        elif fence[0] == opened[0] and len(fence) >= len(opened):
            opened = None
    if opened:
        raise ValueError("Unclosed Markdown code fence")
    if re.search(r"(?mi)<\s*(script|iframe|object)\b|javascript:", content):
        raise ValueError("Active HTML is not supported in documentation")


def validate_draft(project, snapshot, target, draft):
    safe_path(project["root"], target["path"], docs_only=True)
    validate_markdown(draft.content)
    if target["old"]:
        before, after = target["old"].splitlines(keepends=True), draft.content.splitlines(keepends=True)
        for op, a, b, _, _ in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            allowed = any(start <= a and b <= end and (a < end or a == b == end)
                          for start, end in target["ranges"])
            if not allowed:
                raise ValueError("Draft changes an unrelated section; narrow the update and retry")
    known = documentation_symbols(snapshot)
    unknown = sorted(set(draft.symbols) - known)
    if unknown:
        names = ", ".join(name[:80] for name in unknown[:5])
        raise ValueError(f"Draft references symbols not found in source: {names}")
    for citation in draft.citations:
        file = snapshot["files"].get(citation.path)
        if not file or citation.end < citation.start or citation.end > len(file["text"].splitlines()):
            raise ValueError("Draft contains an invalid source citation")
    # Inspect explicit code-style call references, while allowing preserved old text and builtin calls.
    import builtins
    calls = set(re.findall(r"`([A-Za-z_]\w*)\(\)`", draft.content))
    existing_calls = set(re.findall(r"`([A-Za-z_]\w*)\(\)`", target["old"]))
    if calls - known - set(dir(builtins)) - existing_calls:
        raise ValueError("Draft introduces an unverifiable function reference")


def unified_diff(path, before, after):
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                       fromfile=path, tofile=path))


def preview_markdown(content):
    """Do not let untrusted Markdown trigger automatic remote image requests in local mode."""
    return re.sub(r"!\[([^\]]*)\](?:\([^)]*\)|\[[^\]]*\])?",
                  lambda match: f"[Image omitted from local preview: {match.group(1)}]", content)
