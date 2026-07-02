#!/usr/bin/env python3
"""Deterministic optimizer for a PARA-style brain vault."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_SCOPES: list[str] = ["Projects", "Areas", "Resources", "Archive"]
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "dclid", "igshid"}
TRACKING_PREFIXES = ("utm_",)
MIN_OWNERSHIP_AREA_MATERIALS = 3
MIN_OWNERSHIP_AREA_CONCEPTS = 3
MIN_OWNERSHIP_SPLIT_TOPIC_MATERIALS = 5
MIN_OWNERSHIP_SPLIT_CLUSTER_MATERIALS = 3
MIN_RESOURCE_TOPIC_SPLIT_MATERIALS = 5
MIN_RESOURCE_TOPIC_SPLIT_CLUSTER_MATERIALS = 3
WIKILINK_RE = re.compile(r"!?(?<!\!)\[\[([^\]]+)\]\]")
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")
COMMIT_HASH_RE = re.compile(r"^[0-9a-f]{40}$")
RESOURCE_INDEX_BEGIN = "<!-- BEGIN: resource-index -->"
RESOURCE_INDEX_END = "<!-- END: resource-index -->"
OWNERSHIP_INDEX_BEGIN = "<!-- BEGIN: ownership-index -->"
OWNERSHIP_INDEX_END = "<!-- END: ownership-index -->"
UNDERSTANDING_PROFILE_BEGIN = "<!-- BEGIN: understanding-profile -->"
UNDERSTANDING_PROFILE_END = "<!-- END: understanding-profile -->"
TOPIC_RELATIONS_BEGIN = "<!-- BEGIN: topic-relations -->"
TOPIC_RELATIONS_END = "<!-- END: topic-relations -->"
OWNERSHIP_RELATIONS_BEGIN = "<!-- BEGIN: ownership-relations -->"
OWNERSHIP_RELATIONS_END = "<!-- END: ownership-relations -->"
FIXED_REPORT_DIR = Path(tempfile.gettempdir()).resolve()
FIXED_JSON_REPORT = FIXED_REPORT_DIR / "meditate.json"
FIXED_MARKDOWN_REPORT = FIXED_REPORT_DIR / "meditate.md"
SOURCE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".pdf",
    ".txt",
    ".text",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".html",
    ".htm",
    ".epub",
    ".ipynb",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".wav",
    ".mp3",
    ".m4a",
    ".mp4",
    ".mov",
    ".aac",
    ".aiff",
    ".flac",
    ".ogg",
    ".opus",
    ".webm",
}


def load_sibling_module(module_name: str, filename: str):
    module_path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


knowledge_model = load_sibling_module("meditate_knowledge_model", "knowledge_model.py")


@dataclass
class Note:
    path: str
    abs_path: Path
    title: str
    aliases: list[str]
    frontmatter: dict[str, str]
    wikilinks: list[str]
    normalized_urls: list[str]
    fingerprint: str
    stored_fingerprint: str | None
    stored_fingerprint_field: str | None
    fingerprint_valid: bool
    invalid_frontmatter: str | None
    content_length: int
    has_summary: bool
    inbound_count: int = 0
    outbound_count: int = 0
    duplicate_of: str | None = None
    protected: bool = False
    _model_note_cache: object | None = field(default=None, init=False, repr=False, compare=False)
    _concept_counts_cache: Counter[str] | None = field(default=None, init=False, repr=False, compare=False)


@dataclass
class TopicProfile:
    topic: str
    dir: str
    names: list[str] = field(default_factory=list)
    material_count: int = 0
    has_readme: bool = False
    concept_counts: Counter[str] = field(default_factory=Counter)


@dataclass
class OwnershipProfile:
    note: Note
    concept_counts: Counter[str] = field(default_factory=Counter)


def fail(message: str) -> int:
    print(f"meditate: {message}", file=sys.stderr)
    return 2


def progress(enabled: bool, message: str) -> None:
    if enabled:
        print(f"meditate: {message}", file=sys.stderr, flush=True)


def run_git(vault: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=vault,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_status(vault: Path) -> str:
    completed = run_git(
        vault,
        ["status", "--short", "--", ".", ":!Inbox/**", ":!.claude/meditate.log"],
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def protected_paths(vault: Path) -> set[str]:
    paths: set[str] = set()
    for line in git_status(vault).splitlines():
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        raw = raw.strip('"')
        if (
            not raw
            or raw == ".claude/skills/meditate"
            or raw.startswith(".claude/skills/meditate/")
            or raw == ".agents"
            or raw.startswith(".agents/")
            or raw == ".codex"
            or raw.startswith(".codex/")
            or raw == ".copilot"
            or raw.startswith(".copilot/")
            or raw == ".github"
            or raw.startswith(".github/")
        ):
            continue
        paths.add(raw)
    return paths


def is_protected(rel: str, protected: set[str]) -> bool:
    if rel in protected:
        return True
    return any(item.endswith("/") and rel.startswith(item) for item in protected)


def is_relative_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[str], str]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines[:5]):
        if line.strip() == "---":
            start = idx
            break
        if line.strip() and not line.startswith("> 整理自 Inbox"):
            break
    if start is None:
        return {}, [], text
    end = None
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, [], text

    frontmatter: dict[str, str] = {}
    aliases: list[str] = []
    current_key: str | None = None
    for line in lines[start + 1 : end]:
        if re.match(r"^[A-Za-z0-9_-]+:\s*", line):
            key, raw_value = line.split(":", 1)
            current_key = key.strip()
            value = strip_quotes(raw_value.strip())
            frontmatter[current_key] = value
            if current_key == "aliases" and value and not value.startswith("["):
                aliases.append(value)
            elif current_key == "aliases" and value.startswith("["):
                aliases.extend(strip_quotes(v.strip()) for v in value.strip("[]").split(",") if v.strip())
        elif current_key == "aliases" and line.lstrip().startswith("-"):
            aliases.append(strip_quotes(line.split("-", 1)[1].strip()))
    body = "\n".join(lines[:start] + lines[end + 1 :])
    return frontmatter, aliases, body


def find_invalid_frontmatter(text: str) -> str | None:
    """Detect a structurally-present frontmatter whose unquoted scalar value
    contains ': ' (colon+space), which YAML parses as a nested mapping and breaks
    Obsidian properties / Dataview even though the `---` fences are on line 1.

    Also detects smart/curly quotes (“”‘’) which YAML does not
    recognize as string delimiters — values wrapped in them are effectively unquoted.

    Returns a description of the first offending line, or None. Only unquoted
    scalars are flagged; properly quoted strings (straight "" or ''), flow
    collections ([...]/{...}), list items, and empty values are skipped.
    `sha256:abc` (colon with no space) is safe and not flagged.
    """
    SMART_QUOTES = {"“", "”", "‘", "’"}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("-"):
            continue  # list item
        m = re.match(r"^[A-Za-z0-9_.-]+:\s*(.*)$", line)
        if not m:
            continue
        value = m.group(1).strip()
        if not value:
            continue
        # Check for smart/curly quotes — if the value starts or ends with one,
        # YAML won't recognize it as a quoted string.
        if value[0] in SMART_QUOTES or (len(value) > 1 and value[-1] in SMART_QUOTES):
            key = line.split(":", 1)[0].strip()
            return f'smart/curly quotes in `{key}`: {line.strip()}'
        if value[0] in {'"', "'"} or value[0] in {'[', '{'}:
            continue  # quoted scalar or flow collection
        if ": " in value:
            key = line.split(":", 1)[0].strip()
            return f'unquoted value with ": " in `{key}`: {line.strip()}'
    return None


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def heading_title(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def wikilink_target(raw: str) -> str:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return target


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", Path(name).stem.strip()).lower()


def has_path_component(target: str) -> bool:
    return "/" in target or "\\" in target


def markdown_link_path_candidates(target: str) -> list[str]:
    cleaned = target.replace("\\", "/").strip()
    if not cleaned:
        return []
    suffix = Path(cleaned).suffix.lower()
    if suffix and suffix != ".md":
        return []
    if suffix == ".md":
        return [normalize_relpath(cleaned)]
    return [normalize_relpath(f"{cleaned}.md")]


def expected_markdown_stub_path(link: str) -> str | None:
    candidates = markdown_link_path_candidates(wikilink_target(link))
    return candidates[0] if candidates else None


def normalize_relpath(path: str | Path) -> str:
    return Path(path).as_posix().lower()


def normalize_url(url: str) -> str:
    url = strip_quotes(url.strip())
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return url
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower = key.lower()
        if lower in TRACKING_PARAMS or any(lower.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query.append((key, value))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query, doseq=True), ""))


DISTILLATION_HEADING_RE = re.compile(r"^##\s*(提炼|摘要|总结|TL;DR)\s*$", re.IGNORECASE)
SOURCE_HEADING_RE = re.compile(r"^##\s*(原文|原文\s*/\s*摘录|摘录|原始内容|正文|Transcript)\s*$", re.IGNORECASE)
CURATED_TRAILING_HEADING_RE = re.compile(
    r"^##\s*(关联|可能相关|相关资料|相关项目|资料索引|重复归档|后续行动|下一步)\s*$"
)


def source_body_for_hash(text: str) -> str:
    """Return the source-material view used for source identity fingerprints.

    `content_fingerprint` was historically produced before the model added
    distillation and links. Recomputing it over the edited note makes normal
    curated notes look stale. The stable identity should come from the original
    material: keep any title/source preamble, skip the generated distillation
    block, omit the source-section heading itself, and stop before later
    hand-written relationship/index sections.
    """
    _frontmatter, _aliases, body = parse_frontmatter(text)
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        marker_end = {
            RESOURCE_INDEX_BEGIN: RESOURCE_INDEX_END,
            OWNERSHIP_INDEX_BEGIN: OWNERSHIP_INDEX_END,
            UNDERSTANDING_PROFILE_BEGIN: UNDERSTANDING_PROFILE_END,
            TOPIC_RELATIONS_BEGIN: TOPIC_RELATIONS_END,
            OWNERSHIP_RELATIONS_BEGIN: OWNERSHIP_RELATIONS_END,
        }.get(stripped)
        if marker_end is not None:
            i += 1
            while i < len(lines) and lines[i].strip() != marker_end:
                i += 1
            if i < len(lines):
                i += 1
            continue
        if DISTILLATION_HEADING_RE.match(stripped):
            source_start: int | None = None
            j = i + 1
            while j < len(lines):
                if SOURCE_HEADING_RE.match(lines[j].strip()):
                    source_start = j + 1
                    break
                j += 1
            if source_start is not None:
                i = source_start
                continue
        if CURATED_TRAILING_HEADING_RE.match(stripped):
            break
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def normalize_body_for_hash(text: str) -> str:
    body = source_body_for_hash(text)
    out: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("> 整理自 Inbox"):
            continue
        if stripped in {
            "- 以下保留原始正文或转换文本，不删除原文证据。",
            "- 将当前正文整体保留到本节，必要时只做标题分隔，不删除原文证据。",
        }:
            continue
        if "内容指纹" in stripped or stripped.startswith("content_fingerprint:") or stripped.startswith("source_fingerprint:"):
            continue
        if stripped.startswith("source_url:") or stripped.startswith("canonical_url:"):
            continue
        if re.match(r"^source:\s*https?://", stripped):
            continue
        if re.match(r"^>\s*(来源 URL|来源|重复内容|重复依据|canonical)：?", stripped):
            continue
        out.append(line)
    body = "\n".join(out)
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)
    body = re.sub(r"\[[^\]]+\]\((https?://[^)]*)\)", " ", body)
    body = URL_RE.sub(" ", body)
    body = re.sub(r"[`*_>#|\-\[\]（）()，。；：:、,.!?！？\"“”‘’]", " ", body)
    return re.sub(r"\s+", " ", body).strip().lower()


def content_fingerprint(text: str) -> str:
    normalized = normalize_body_for_hash(text)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_urls(frontmatter: dict[str, str], text: str) -> list[str]:
    urls: list[str] = []
    for key in ("source_url", "canonical_url", "source"):
        value = frontmatter.get(key, "")
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(normalize_url(value))
    for line in text.splitlines():
        if any(marker in line for marker in ("来源 URL", "来源：", "来源:", "Source:", "source:")):
            for match in URL_RE.findall(line):
                urls.append(normalize_url(match))
    return list(dict.fromkeys(urls))


def iter_markdown(vault: Path, scopes: list[str]) -> list[Path]:
    files: list[Path] = []
    for scope in scopes:
        scope_path = (vault / scope).resolve()
        if not is_relative_inside(scope_path, vault) or not scope_path.exists():
            continue
        for path in scope_path.rglob("*.md"):
            if path.is_symlink() or not path.is_file():
                continue
            files.append(path)
    return sorted(files)


def iter_source_files(vault: Path, scopes: list[str]) -> list[Path]:
    files: list[Path] = []
    for scope in scopes:
        scope_path = (vault / scope).resolve()
        if not is_relative_inside(scope_path, vault) or not scope_path.exists():
            continue
        for path in scope_path.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() in SOURCE_EXTENSIONS:
                files.append(path)
    return sorted(files)


def read_note(vault: Path, path: Path, protected: set[str]) -> Note:
    rel = path.relative_to(vault).as_posix()
    text = path.read_text(encoding="utf-8")
    frontmatter, aliases, body = parse_frontmatter(text)
    title = frontmatter.get("title") or heading_title(body) or path.stem
    links = [wikilink_target(raw) for raw in WIKILINK_RE.findall(text)]
    computed_fingerprint = content_fingerprint(text)
    stored_fingerprint_field = None
    stored_fingerprint = None
    for field_name in ("source_fingerprint", "content_fingerprint"):
        if frontmatter.get(field_name):
            stored_fingerprint_field = field_name
            stored_fingerprint = frontmatter[field_name]
            break
    fingerprint_valid = (
        not stored_fingerprint
        or stored_fingerprint_field == "content_fingerprint"
        or stored_fingerprint == computed_fingerprint
    )
    urls = extract_urls(frontmatter, text)
    return Note(
        path=rel,
        abs_path=path,
        title=title,
        aliases=aliases,
        frontmatter=frontmatter,
        wikilinks=links,
        normalized_urls=urls,
        fingerprint=computed_fingerprint,
        stored_fingerprint=stored_fingerprint,
        stored_fingerprint_field=stored_fingerprint_field,
        fingerprint_valid=fingerprint_valid,
        invalid_frontmatter=find_invalid_frontmatter(text),
        content_length=len(normalize_body_for_hash(text)),
        has_summary="## 提炼" in text or "## 摘要" in text,
        outbound_count=len(links),
        protected=is_protected(rel, protected),
    )


def build_index(vault: Path, scopes: list[str], protected: set[str]) -> tuple[list[Note], dict[str, list[Note]], set[str], set[str]]:
    notes = [read_note(vault, path, protected) for path in iter_markdown(vault, scopes)]
    by_name: dict[str, list[Note]] = defaultdict(list)
    file_stems: set[str] = set()
    for note in notes:
        names = {note.title, Path(note.path).stem, *note.aliases}
        for name in names:
            if name:
                by_name[normalize_name(name)].append(note)
        file_stems.add(normalize_name(Path(note.path).stem))
    for note in notes:
        for link in note.wikilinks:
            matches = by_name.get(normalize_name(link), [])
            for match in matches:
                match.inbound_count += 1
    attachment_targets = {
        normalize_relpath(path.relative_to(vault)) for path in iter_source_files(vault, scopes)
    }
    return notes, by_name, file_stems, attachment_targets


def canonical_score(note: Note) -> tuple[int, int, int, int, int, str]:
    return (
        0 if note.path.startswith("Archive/Duplicates/") else 1,
        1 if note.path.startswith("Resources/") else 0,
        1 if note.has_summary else 0,
        note.inbound_count,
        note.content_length,
        note.path,
    )


def note_kind(note: Note) -> str:
    return strip_quotes(note.frontmatter.get("type", "")).strip().lower()


def is_material_note(note: Note) -> bool:
    if not (note.path.startswith("Resources/") or note.path.startswith("Archive/")):
        return False
    return note_kind(note) not in {"area", "project", "index"}


def is_fingerprint_duplicate_eligible(note: Note) -> bool:
    return is_material_note(note) and note.fingerprint_valid and note.content_length >= 80


def duplicate_groups(notes: list[Note]) -> list[dict]:
    candidates: dict[tuple[str, str], list[Note]] = defaultdict(list)
    source_file_candidates: dict[str, list[Note]] = defaultdict(list)
    for note in notes:
        if is_material_note(note):
            for url in note.normalized_urls:
                candidates[("url", url)].append(note)
        if note.fingerprint and is_fingerprint_duplicate_eligible(note):
            candidates[("source_fingerprint", note.fingerprint)].append(note)
        source_file = note.frontmatter.get("source_file")
        if source_file and is_fingerprint_duplicate_eligible(note):
            source_file_candidates[source_file].append(note)
    for source_file, group in source_file_candidates.items():
        by_fingerprint: dict[str, list[Note]] = defaultdict(list)
        for note in group:
            by_fingerprint[note.fingerprint].append(note)
        for fingerprint, same_body in by_fingerprint.items():
            if len(same_body) > 1:
                candidates[("source_file", f"{source_file}#{fingerprint}")].extend(same_body)

    grouped: dict[tuple[str, ...], dict] = {}
    for (kind, value), group in candidates.items():
        unique = sorted({note.path: note for note in group}.values(), key=lambda n: n.path)
        if len(unique) < 2:
            continue
        key = tuple(note.path for note in unique)
        item = grouped.setdefault(
            key,
            {"notes": unique, "evidence": [], "canonical": None, "duplicates": []},
        )
        item["evidence"].append({"type": kind, "value": value})
    results: list[dict] = []
    for item in grouped.values():
        ordered = sorted(item["notes"], key=canonical_score, reverse=True)
        canonical = ordered[0]
        item["canonical"] = canonical.path
        item["duplicates"] = [note.path for note in ordered[1:]]
        del item["notes"]
        results.append(item)
    return sorted(results, key=lambda item: item["canonical"])


def attachment_link_exists(note_path: str, link: str, attachment_targets: set[str]) -> bool:
    target = wikilink_target(link)
    if Path(target).suffix.lower() not in SOURCE_EXTENSIONS:
        return False
    note_dir = Path(note_path).parent
    candidates = [
        normalize_relpath(target),
        normalize_relpath(note_dir / target),
    ]
    return any(candidate in attachment_targets for candidate in candidates)


def broken_links(notes: list[Note], by_name: dict[str, list[Note]], file_stems: set[str], attachment_targets: set[str]) -> list[dict]:
    """Find wikilinks whose target does not match any existing file's filename stem.

    Obsidian resolves [[X]] → X.md by **filename**, not by frontmatter title
    or alias. A wikilink that matches a note's title but not its filename is
    still broken — Obsidian will create a 0-byte stub file when the link is
    clicked. Source-file links such as [[source/Paper.pdf]] are valid when
    the attachment exists. This function checks real filenames first;
    title/alias matches are treated as "soft match" findings that need the
    wikilink text updated to use the actual filename stem.
    """
    findings: list[dict] = []
    note_paths = {normalize_relpath(note.path) for note in notes}
    for note in notes:
        for link in sorted(set(note.wikilinks)):
            if attachment_link_exists(note.path, link, attachment_targets):
                continue
            target = wikilink_target(link)
            key = normalize_name(target)
            if has_path_component(target):
                if any(candidate in note_paths for candidate in markdown_link_path_candidates(target)):
                    continue  # Valid: path-qualified wikilink resolves to an existing Markdown file
            elif key in file_stems:
                continue  # Valid: bare wikilink resolves by filename stem
            # No file stem matches — the wikilink is broken in Obsidian
            # Check for soft matches via title/alias (notes that SHOULD be the target)
            soft_matches = [m.path for m in by_name.get(key, [])]
            if soft_matches:
                # Wikilink matches a note's title/alias but not its filename
                # → Obsidian will create a stub; fix by changing link to actual filename
                unique_matches = sorted(set(soft_matches))
                findings.append({
                    "source": note.path,
                    "link": link,
                    "matches": unique_matches,
                    "status": "unique" if len(unique_matches) == 1 else "ambiguous",
                })
            else:
                # No match at all — try loose substring fallback on title
                loose = [n.path for n in notes if key and key in normalize_name(n.title)]
                finding = {"source": note.path, "link": link, "matches": sorted(set(loose))}
                finding["status"] = "unique" if len(set(loose)) == 1 else "ambiguous"
                findings.append(finding)
    return findings


def clean_source_ref(value: str) -> str:
    value = strip_quotes(value.strip())
    value = value.strip("`").strip()
    value = value.rstrip("。.;；")
    return wikilink_target(value)


def source_marker_tail(line: str) -> str | None:
    for marker in ("原始文件", "Original file"):
        if marker in line:
            _head, _sep, tail = line.partition(marker)
            return tail.lstrip("：:").strip()
    return None


def source_refs_from_text(note: Note) -> list[dict]:
    text = note.abs_path.read_text(encoding="utf-8")
    refs: list[dict] = []
    source_file = note.frontmatter.get("source_file")
    if source_file:
        refs.append({"kind": "frontmatter", "ref": clean_source_ref(source_file)})
    for line in text.splitlines():
        tail = source_marker_tail(line)
        if tail is None:
            continue
        wikilinks = WIKILINK_RE.findall(line)
        if wikilinks:
            refs.append({"kind": "body", "ref": clean_source_ref(wikilinks[0])})
            continue
        backtick = re.search(r"`([^`]+)`", line)
        if backtick:
            refs.append({"kind": "body", "ref": clean_source_ref(backtick.group(1))})
            continue
        if tail:
            refs.append({"kind": "body", "ref": clean_source_ref(tail)})
    return refs


def resolve_source_ref(vault: Path, note_path: str, ref: str) -> str | None:
    if not ref:
        return None
    raw = Path(ref)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        note_dir = Path(note_path).parent
        candidates.extend([vault / raw, vault / note_dir / raw])
    for candidate in candidates:
        try:
            rel = candidate.resolve().relative_to(vault.resolve()).as_posix()
        except ValueError:
            continue
        if (vault / rel).exists():
            return rel
    try:
        fallback = (vault / Path(note_path).parent / raw).resolve().relative_to(vault.resolve()).as_posix()
    except ValueError:
        return None
    return fallback


def expected_source_rel(note_path: str, source_rel: str) -> str:
    note = Path(note_path)
    suffix = Path(source_rel).suffix
    return (note.parent / "source" / f"{note.stem}{suffix}").as_posix()


def canonical_source_ref(note_path: str, source_rel: str) -> str:
    note = Path(note_path)
    suffix = Path(source_rel).suffix
    return f"source/{note.stem}{suffix}"


def infer_note_for_source(source_rel: str, notes_by_path: dict[str, Note]) -> Note | None:
    source_path = Path(source_rel)
    parent = source_path.parent
    note_dir = parent.parent if parent.name.lower() == "source" or parent.name.lower() == "sources" else parent
    candidate = (note_dir / f"{source_path.stem}.md").as_posix()
    return notes_by_path.get(candidate)


def is_source_attachment_context(source_rel: str) -> bool:
    return any(part.lower() in {"source", "sources"} for part in Path(source_rel).parts)


def source_policy_status(vault: Path, note: Note, actual: str, expected: str, protected: set[str]) -> tuple[str, str]:
    if is_protected(note.path, protected) or is_protected(actual, protected) or is_protected(expected, protected):
        return "protected", "note or source file has pre-existing uncommitted changes"
    if actual != expected and (vault / expected).exists():
        return "destination_exists", "expected source destination already exists"
    if Path(actual).suffix.lower() not in SOURCE_EXTENSIONS:
        return "unsupported_extension", "source file extension is outside the managed source policy"
    return "fixable", "source file can be moved and note references can be normalized"


def source_file_anomalies(vault: Path, scopes: list[str], notes: list[Note], protected: set[str]) -> list[dict]:
    findings: list[dict] = []
    notes_by_path = {note.path: note for note in notes}
    referenced_sources: set[str] = set()
    seen: set[tuple[str, str]] = set()

    for note in notes:
        refs = source_refs_from_text(note)
        if not refs:
            continue
        resolved = [resolve_source_ref(vault, note.path, item["ref"]) for item in refs]
        actual = next((item for item in resolved if item), None)
        if actual is None or not (vault / actual).exists():
            findings.append({
                "note": note.path,
                "actual": refs[0]["ref"] if refs else "",
                "expected": "",
                "status": "missing_source",
                "reason": "source reference does not resolve to an existing file",
            })
            continue
        referenced_sources.add(actual)
        expected = expected_source_rel(note.path, actual)
        canonical_ref = canonical_source_ref(note.path, actual)
        ref_values = {item["ref"] for item in refs}
        has_frontmatter = any(item["kind"] == "frontmatter" for item in refs)
        canonical_refs = ref_values == {canonical_ref} and has_frontmatter
        if actual == expected and canonical_refs:
            continue
        status, reason = source_policy_status(vault, note, actual, expected, protected)
        key = (note.path, actual)
        if key in seen:
            continue
        seen.add(key)
        findings.append({
            "note": note.path,
            "actual": actual,
            "expected": expected,
            "canonical_ref": canonical_ref,
            "status": status,
            "reason": reason,
        })

    for path in iter_source_files(vault, scopes):
        source_rel = path.relative_to(vault).as_posix()
        if source_rel in referenced_sources:
            continue
        note = infer_note_for_source(source_rel, notes_by_path)
        if note is None:
            if not is_source_attachment_context(source_rel):
                continue
            findings.append({
                "note": "",
                "actual": source_rel,
                "expected": "",
                "status": "unmatched_note",
                "reason": "source file has no same-stem Markdown note and no source_file reference",
            })
            continue
        expected = expected_source_rel(note.path, source_rel)
        canonical_ref = canonical_source_ref(note.path, source_rel)
        if source_rel == expected:
            status, reason = source_policy_status(vault, note, source_rel, expected, protected)
        else:
            status, reason = source_policy_status(vault, note, source_rel, expected, protected)
        findings.append({
            "note": note.path,
            "actual": source_rel,
            "expected": expected,
            "canonical_ref": canonical_ref,
            "status": status,
            "reason": reason,
        })
    return sorted(findings, key=lambda item: (item.get("note", ""), item.get("actual", "")))


def empty_stubs(vault: Path, notes: list[Note], by_name: dict[str, list[Note]]) -> list[dict]:
    """Detect 0-byte .md stubs auto-created by Obsidian when a broken wikilink is clicked.

    Obsidian creates a 0-byte file at the path the wikilink expects when the user
    clicks a [[wikilink]] whose target does not exist. For bare [[Note Name]], the
    stub lands at the vault root; for [[Inbox/Note Name]], it lands in Inbox/.

    These stubs are invisible to the script's normal scan (only PARA dirs), and
    their existence causes further issues: the next meditate scan sees the
    stub as an existing file and considers the link "resolved", even though the
    stub is empty and the real note lives elsewhere.

    Returns a list of findings, each with:
      - stub: relative path of the 0-byte stub
      - references: list of {source path, link text} that point to this stub
      - suggested_target: path of the closest-matching real note (or None)
    """
    skip_prefixes = (".claude/", ".agents/", ".codex/", ".copilot/", ".github/", ".git/", ".obsidian/")
    findings: list[dict] = []

    # Collect all known note names for matching
    all_names: dict[str, list[str]] = defaultdict(list)  # normalized → [path]
    for note in notes:
        for name in {note.title, Path(note.path).stem, *note.aliases}:
            if name:
                all_names[normalize_name(name)].append(note.path)

    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault).as_posix()
        if any(rel.startswith(p) for p in skip_prefixes):
            continue
        if path.stat().st_size != 0:
            continue
        # 0-byte .md file found — almost certainly an Obsidian stub
        stub_stem = path.stem
        stub_key = normalize_name(stub_stem)
        # Find wikilinks across all notes that resolve to this stub
        references: list[dict] = []
        normalized_stub_rel = normalize_relpath(rel)
        for note in notes:
            for link in sorted(set(note.wikilinks)):
                expected_stub = expected_markdown_stub_path(link)
                if expected_stub == normalized_stub_rel:
                    references.append({"source": note.path, "link": link})
        # Find the closest real note: prefer loose title match (stub stem is
        # a prefix/substring of the real note's name)
        suggested_target: str | None = None
        match_candidates: list[str] = []
        for norm_name, paths in all_names.items():
            if stub_key and stub_key in norm_name:
                match_candidates.extend(paths)
        # For Inbox/ stubs, also check if there's a note with the same stem
        # in a PARA directory (common after ingest moves)
        if not match_candidates:
            for note in notes:
                if Path(note.path).stem == stub_stem:
                    match_candidates.append(note.path)
        if len(match_candidates) == 1:
            suggested_target = match_candidates[0]
        elif len(match_candidates) > 1:
            # Prefer Resources/ → non-Duplicates → shortest path
            def _stub_target_score(p: str) -> tuple:
                return (
                    0 if p.startswith("Resources/") else 1,
                    0 if "Duplicates" not in p else 1,
                    len(p),
                )
            suggested_target = sorted(set(match_candidates), key=_stub_target_score)[0]

        findings.append(
            {
                "stub": rel,
                "references": references,
                "suggested_target": suggested_target,
                "status": "fixable" if suggested_target and references else ("orphan_stub" if not references else "unmatched"),
            }
        )
    return findings


def metadata_missing(notes: list[Note]) -> list[dict]:
    missing: list[dict] = []
    for note in notes:
        if not is_material_note(note):
            continue
        fields: list[str] = []
        if not (note.frontmatter.get("source_fingerprint") or note.frontmatter.get("content_fingerprint")):
            fields.append("source_fingerprint")
        if note.normalized_urls and not note.frontmatter.get("source_url"):
            fields.append("source_url")
        if fields:
            missing.append({"path": note.path, "fields": fields})
    return missing


def orphan_notes(notes: list[Note]) -> list[str]:
    return sorted(note.path for note in notes if note.inbound_count == 0 and note.outbound_count == 0 and note.path.startswith("Resources/"))


def is_ownership_note(note: Note) -> bool:
    if note.path.startswith("Archive/Duplicates/"):
        return False
    return note.path.startswith("Areas/") or note.path.startswith("Projects/") or note_kind(note) in {"area", "project"}


def is_understanding_target(note: Note) -> bool:
    if note.path.startswith("Archive/Duplicates/"):
        return False
    return is_ownership_note(note) or is_material_note(note)


def meaningful_entity_name(name: str) -> bool:
    normalized = normalize_name(name)
    compact = re.sub(r"\s+", "", normalized)
    if not compact or compact in {"readme", "index"}:
        return False
    if re.fullmatch(r"[a-z0-9_-]+", compact) and len(compact) < 4:
        return False
    if len(compact) < 2:
        return False
    return True


def candidate_names(note: Note) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for name in (Path(note.path).stem, note.title, *note.aliases):
        cleaned = strip_quotes(name).strip()
        key = normalize_name(cleaned)
        if key and key not in seen and meaningful_entity_name(cleaned):
            seen.add(key)
            names.append(cleaned)
    return names


def text_mentions_name(text: str, name: str) -> bool:
    return knowledge_model.text_mentions_name(text, name)


LOW_SIGNAL_MENTION_RE = re.compile(
    r"\b(find me|follow|subscribe|reshare|share with|for more insights|tutorials?|newsletter|social media|network)\b",
    re.IGNORECASE,
)


def text_mentions_name_in_signal_context(text: str, name: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    footer_start = max(0, len(lines) - 8)
    for index, line in enumerate(lines):
        if not text_mentions_name(line, name):
            continue
        if index >= footer_start and LOW_SIGNAL_MENTION_RE.search(line):
            continue
        return True
    return False


def source_text_without_wikilinks(note: Note) -> str:
    text = note.abs_path.read_text(encoding="utf-8")
    return WIKILINK_RE.sub(" ", source_body_for_hash(text))


def to_model_note(note: Note):
    if note._model_note_cache is not None:
        return note._model_note_cache
    note._model_note_cache = knowledge_model.ModelNote(
        path=note.path,
        title=note.title,
        aliases=note.aliases,
        body=source_text_without_wikilinks(note),
        kind=note_kind(note),
    )
    return note._model_note_cache


def to_model_topic_profile(profile: TopicProfile):
    return knowledge_model.TopicProfile(
        topic=profile.topic,
        dir=profile.dir,
        names=list(profile.names),
        material_count=profile.material_count,
        has_readme=profile.has_readme,
        concept_counts=profile.concept_counts.copy(),
    )


def to_model_ownership_profile(profile: OwnershipProfile):
    return knowledge_model.OwnershipProfile(
        path=profile.note.path,
        title=profile.note.title,
        aliases=profile.note.aliases,
        body=source_text_without_wikilinks(profile.note),
        concept_counts=profile.concept_counts.copy(),
    )


def note_links_to_target(note: Note, target: Note) -> bool:
    target_names = {normalize_name(Path(target.path).stem), normalize_name(target.title)}
    target_names.update(normalize_name(alias) for alias in target.aliases)
    return any(normalize_name(link) in target_names for link in note.wikilinks)


CONCEPT_STOPWORDS = {
    "about",
    "across",
    "after",
    "agent",
    "agents",
    "also",
    "analysis",
    "actual",
    "because",
    "before",
    "being",
    "between",
    "build",
    "could",
    "data",
    "does",
    "every",
    "from",
    "have",
    "into",
    "like",
    "long",
    "look",
    "make",
    "more",
    "most",
    "note",
    "notes",
    "once",
    "only",
    "over",
    "part",
    "pattern",
    "people",
    "preserve",
    "preserves",
    "reference",
    "rather",
    "running",
    "session",
    "sessions",
    "should",
    "single",
    "system",
    "that",
    "than",
    "this",
    "through",
    "uses",
    "using",
    "with",
    "work",
    "works",
    "would",
    "your",
}

GENERIC_CONCEPT_PHRASES = {
    "actually get",
    "actually gets",
    "next step",
    "obsidian vault",
    "project folder",
    "what changed",
}


def normalize_concept_token(token: str) -> str:
    return knowledge_model.normalize_concept_token(token)


def meaningful_concept_token(token: str) -> bool:
    return knowledge_model.meaningful_concept_token(token)


def concept_counts_for_text(text: str) -> Counter[str]:
    return knowledge_model.concept_counts_for_text(text)


def note_concept_counts(note: Note) -> Counter[str]:
    if note._concept_counts_cache is None:
        note._concept_counts_cache = knowledge_model.note_concept_counts(to_model_note(note))
    return note._concept_counts_cache.copy()


def concept_can_drive_structure(term: str) -> bool:
    return knowledge_model.concept_can_drive_structure(term)


def top_concepts(profile: TopicProfile, limit: int = 12) -> list[str]:
    return knowledge_model.top_concepts(to_model_topic_profile(profile), limit)


def top_concepts_from_counts(counts: Counter[str], limit: int = 12) -> list[str]:
    return knowledge_model.top_concepts_from_counts(counts, limit)


def concept_topic_frequency(profiles: dict[str, TopicProfile]) -> Counter[str]:
    return knowledge_model.concept_topic_frequency(
        {topic: to_model_topic_profile(profile) for topic, profile in profiles.items()}
    )


def ownership_profiles(notes: list[Note]) -> dict[str, OwnershipProfile]:
    profiles: dict[str, OwnershipProfile] = {}
    for note in notes:
        if not is_ownership_note(note):
            continue
        text = f"{Path(note.path).stem}\n{note.title}\n{source_text_without_wikilinks(note)}"
        profiles[note.path] = OwnershipProfile(note=note, concept_counts=concept_counts_for_text(text))
    return profiles


def ownership_concept_frequency(profiles: dict[str, OwnershipProfile]) -> Counter[str]:
    return knowledge_model.ownership_concept_frequency(
        {path: to_model_ownership_profile(profile) for path, profile in profiles.items()}
    )


def ownership_concept_match_score(note: Note, profile: OwnershipProfile, concept_frequency: Counter[str]) -> tuple[int, list[str]]:
    return knowledge_model.ownership_concept_match_score(
        to_model_note(note),
        to_model_ownership_profile(profile),
        concept_frequency,
    )


def resource_topic_material_notes(notes: list[Note], topic: str) -> list[Note]:
    return sorted(
        (
            note
            for note in notes
            if resource_topic_name(note.path) == topic and is_material_note(note)
        ),
        key=lambda item: item.path,
    )


def stable_topic_concepts(notes: list[Note], topic: str, limit: int = 12) -> list[str]:
    return knowledge_model.stable_topic_concepts([to_model_note(note) for note in notes], topic, limit)


def existing_ownership_match_for_topic(topic: str, concepts: list[str], notes: list[Note]) -> dict | None:
    owner_notes = [note for note in notes if is_ownership_note(note)]
    topic_key = normalize_name(topic)
    for owner in sorted(owner_notes, key=lambda item: item.path):
        for name in candidate_names(owner):
            if normalize_name(name) == topic_key:
                return {
                    "path": owner.path,
                    "reason": "existing ownership note has the same topic name",
                    "matched": [name],
                }

    owner_profiles = ownership_profiles(notes)
    owner_frequency = ownership_concept_frequency(owner_profiles)
    topic_terms = set(concepts)
    matches: list[tuple[int, str, list[str]]] = []
    for owner_path, profile in sorted(owner_profiles.items()):
        owner_terms = {
            term
            for term in top_concepts_from_counts(profile.concept_counts, limit=20)
            if owner_frequency.get(term, 0) == 1
        }
        matched = sorted(topic_terms & owner_terms)
        if len(matched) >= MIN_OWNERSHIP_AREA_CONCEPTS:
            matches.append((len(matched), owner_path, matched))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, best_path, matched = matches[0]
    return {
        "path": best_path,
        "reason": "existing ownership profile already covers the stable topic concepts",
        "matched": matched[:best_score],
    }


def ownership_area_candidates(vault: Path, notes: list[Note], protected: set[str]) -> list[dict]:
    profiles = resource_topic_profiles(notes)
    candidates: list[dict] = []
    for profile in sorted(profiles.values(), key=lambda item: item.dir):
        if profile.material_count < MIN_OWNERSHIP_AREA_MATERIALS:
            continue
        concepts = stable_topic_concepts(notes, profile.topic)
        if len(concepts) < MIN_OWNERSHIP_AREA_CONCEPTS:
            continue
        existing_owner = existing_ownership_match_for_topic(profile.topic, concepts, notes)
        if existing_owner is not None:
            continue
        material_notes = [note.path for note in resource_topic_material_notes(notes, profile.topic)]
        target = (Path("Areas") / f"{profile.topic}.md").as_posix()
        protected_paths = [
            path
            for path in [target, *material_notes]
            if is_protected(path, protected)
        ]
        target_exists = (vault / target).exists()
        if protected_paths:
            status = "protected"
            reason = "target Area or material notes have pre-existing uncommitted changes"
        elif target_exists:
            status = "destination_exists"
            reason = "target Area already exists"
        else:
            status = "fixable"
            reason = "stable resource topic has no suitable Area / Project ownership"
        candidates.append(
            {
                "topic": profile.topic,
                "topic_dir": profile.dir,
                "target": target,
                "material_count": profile.material_count,
                "material_notes": material_notes,
                "concepts": concepts[:8],
                "status": status,
                "reason": reason,
                "fixable": status == "fixable",
            }
        )
    return candidates


def ownership_area_source_topic(note: Note) -> str | None:
    if not note.path.startswith("Areas/"):
        return None
    text = note.abs_path.read_text(encoding="utf-8")
    match = re.search(r"主题来源：`(Resources/[^`]+)`", text)
    if not match:
        return None
    topic_dir = normalize_relpath(match.group(1)).split("/", 2)
    if len(topic_dir) < 2 or topic_dir[0] != "resources":
        return None
    return f"Resources/{match.group(1).split('/', 1)[1]}"


def render_area_understanding_profile(concepts: list[str], material_count: int) -> str:
    concept_text = "、".join(concepts) if concepts else "待积累"
    return (
        f"{UNDERSTANDING_PROFILE_BEGIN}\n\n"
        f"- 核心概念：{concept_text}\n"
        f"- 资料数量：{material_count}\n\n"
        f"{UNDERSTANDING_PROFILE_END}"
    )


def render_area_scope_concepts(concepts: list[str]) -> str:
    concept_text = "、".join(concepts) if concepts else "待积累"
    return f"- 核心概念：{concept_text}"


def area_scope_concepts_line(text: str) -> str:
    lines = text.splitlines()
    in_scope = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## 适用范围":
            in_scope = True
            continue
        if in_scope and line.startswith("## "):
            return ""
        if in_scope and stripped.startswith("- 核心概念："):
            return stripped
    return ""


def upsert_area_scope_concepts(text: str, expected_line: str) -> str:
    if not expected_line:
        return text
    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    scope_heading = next((idx for idx, line in enumerate(lines) if line.strip() == "## 适用范围"), None)
    if scope_heading is None:
        return text

    next_heading = len(lines)
    for idx in range(scope_heading + 1, len(lines)):
        if lines[idx].startswith("## "):
            next_heading = idx
            break
    for idx in range(scope_heading + 1, next_heading):
        if lines[idx].strip().startswith("- 核心概念："):
            lines[idx] = expected_line
            return "\n".join(lines) + ("\n" if trailing_newline else "")
    for idx in range(scope_heading + 1, next_heading):
        if lines[idx].strip().startswith("- 主题来源："):
            lines.insert(idx + 1, expected_line)
            return "\n".join(lines) + ("\n" if trailing_newline else "")
    insert_at = scope_heading + 1
    lines.insert(insert_at, expected_line)
    return "\n".join(lines) + ("\n" if trailing_newline else "")


def ownership_area_profile_gaps(vault: Path, notes: list[Note], protected: set[str]) -> list[dict]:
    by_path = {note.path: note for note in notes}
    gaps: list[dict] = []
    for area in sorted((note for note in notes if note.path.startswith("Areas/")), key=lambda item: item.path):
        topic_dir = ownership_area_source_topic(area)
        if topic_dir is None:
            continue
        topic = Path(topic_dir).name
        material_notes = resource_topic_material_notes(notes, topic)
        if not material_notes:
            continue
        concepts = stable_topic_concepts(notes, topic)
        if len(concepts) < MIN_OWNERSHIP_AREA_CONCEPTS:
            profile = resource_topic_profiles(notes).get(topic)
            concepts = top_concepts(profile) if profile else []
        expected_profile = render_area_understanding_profile(concepts[:8], len(material_notes))
        expected_scope_concepts = render_area_scope_concepts(concepts[:8])
        expected_index = render_ownership_material_index([note.path for note in material_notes], topic_dir)
        area_text = area.abs_path.read_text(encoding="utf-8", errors="replace")
        span = understanding_profile_span(area_text)
        current_profile = area_text[span[0] : span[1]] if span is not None else ""
        profile_stale = current_profile != expected_profile
        current_scope_concepts = area_scope_concepts_line(area_text)
        scope_stale = current_scope_concepts != expected_scope_concepts
        index_span = ownership_index_span(area_text)
        current_index = area_text[index_span[0] : index_span[1]] if index_span is not None else ""
        index_stale = current_index != expected_index
        missing_index_links = [
            note.path
            for note in material_notes
            if f"[[{Path(note.path).stem}]]" not in area_text
        ]
        missing_reverse_links = [
            note.path
            for note in material_notes
            if not note_links_to_target(note, area)
        ]
        if (
            not profile_stale
            and not scope_stale
            and not index_stale
            and not missing_index_links
            and not missing_reverse_links
        ):
            continue
        protected_paths = [
            path
            for path in [area.path, *missing_reverse_links]
            if is_protected(path, protected)
        ]
        if protected_paths:
            status = "protected"
            reason = "Area or material notes have pre-existing uncommitted changes"
        elif span is None:
            status = "missing_markers"
            reason = "auto-created Area has no understanding-profile marker block"
        elif profile_stale or scope_stale:
            status = "stale"
            reason = "auto-created Area profile or material count differs from current resource topic"
        elif index_stale:
            status = "stale_index"
            reason = "auto-created Area material index differs from current resource topic"
        elif missing_index_links or missing_reverse_links:
            status = "missing_links"
            reason = "auto-created Area material index or reciprocal material links are incomplete"
        else:
            status = "current"
            reason = ""
        gaps.append(
            {
                "area": area.path,
                "topic_dir": topic_dir,
                "material_count": len(material_notes),
                "material_notes": [note.path for note in material_notes],
                "concepts": concepts[:8],
                "expected_profile": expected_profile,
                "current_profile": current_profile,
                "expected_scope_concepts": expected_scope_concepts,
                "current_scope_concepts": current_scope_concepts,
                "expected_index": expected_index,
                "current_index": current_index,
                "missing_index_links": missing_index_links,
                "missing_reverse_links": missing_reverse_links,
                "status": status,
                "reason": reason,
                "fixable": status != "protected",
            }
        )
    return gaps


def is_auto_created_area(note: Note) -> bool:
    if not note.path.startswith("Areas/") or note_kind(note) != "area":
        return False
    text = note.abs_path.read_text(encoding="utf-8", errors="replace")
    return "自动承接 `Resources/" in text or "主题来源：`Resources/" in text


def ownership_equivalence_keys(note: Note) -> set[str]:
    keys: set[str] = set()
    names = candidate_names(note)
    topic_dir = ownership_area_source_topic(note)
    if topic_dir:
        names.append(Path(topic_dir).name)
    for name in names:
        normalized = normalize_name(name)
        if not normalized:
            continue
        keys.add(normalized)
        if re.fullmatch(r"[a-z0-9 ._-]+", normalized):
            words = normalized.split()
            if words and words[-1].endswith("s") and len(words[-1]) > 3:
                words[-1] = words[-1][:-1]
                keys.add(" ".join(words))
    return keys


def ownership_index_link_count(note: Note) -> int:
    text = note.abs_path.read_text(encoding="utf-8", errors="replace")
    try:
        after_heading = text.split("## 资料索引", 1)[1]
    except IndexError:
        return 0
    next_heading = after_heading.find("\n## ")
    section = after_heading if next_heading == -1 else after_heading[:next_heading]
    return len(WIKILINK_RE.findall(section))


def canonical_ownership_area(group: list[Note]) -> Note:
    return sorted(
        group,
        key=lambda note: (
            Path(note.path).stem.endswith("s"),
            ownership_index_link_count(note),
            note.inbound_count,
            note.content_length,
            note.path,
        ),
        reverse=True,
    )[0]


def archive_duplicate_target(vault: Path, source_rel: str) -> str:
    stem = Path(source_rel).stem
    suffix = Path(source_rel).suffix
    target = f"Archive/Duplicates/{stem}{suffix}"
    counter = 2
    while (vault / target).exists():
        target = f"Archive/Duplicates/{stem}-{counter}{suffix}"
        counter += 1
    return target


def note_has_link_to_stem(note: Note, stem: str) -> bool:
    key = normalize_name(stem)
    return any(normalize_name(link) == key for link in note.wikilinks)


def ownership_structure_candidates(vault: Path, notes: list[Note], protected: set[str]) -> list[dict]:
    auto_areas = [note for note in notes if is_auto_created_area(note)]
    by_key: dict[str, list[Note]] = defaultdict(list)
    for note in auto_areas:
        for key in ownership_equivalence_keys(note):
            by_key[key].append(note)

    seen_sources: set[str] = set()
    candidates: list[dict] = []
    for key, group in sorted(by_key.items()):
        unique = sorted({note.path: note for note in group}.values(), key=lambda item: item.path)
        if len(unique) < 2:
            continue
        canonical = canonical_ownership_area(unique)
        for duplicate in unique:
            if duplicate.path == canonical.path or duplicate.path in seen_sources:
                continue
            target = archive_duplicate_target(vault, duplicate.path)
            duplicate_stem = Path(duplicate.path).stem
            canonical_stem = Path(canonical.path).stem
            link_sources = sorted(
                note.path
                for note in notes
                if note.path != duplicate.path and note_has_link_to_stem(note, duplicate_stem)
            )
            protected_paths = [
                path
                for path in [duplicate.path, canonical.path, target, *link_sources]
                if is_protected(path, protected)
            ]
            if protected_paths:
                status = "protected"
                reason = "equivalent ownership notes or their incoming links have pre-existing uncommitted changes"
            elif (vault / target).exists():
                status = "destination_exists"
                reason = "archive target already exists"
            else:
                status = "fixable"
                reason = "auto-created Area names or source topics are equivalent"
            candidates.append(
                {
                    "source": duplicate.path,
                    "canonical": canonical.path,
                    "target": target,
                    "kind": "ownership_merge",
                    "matched": [key],
                    "link_sources": link_sources,
                    "status": status,
                    "reason": reason,
                    "fixable": status == "fixable",
                }
            )
            seen_sources.add(duplicate.path)
    return candidates


def titleize_concept(term: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", term):
        return term
    return " ".join(part.capitalize() for part in term.split())


def title_starts_with_concept(note: Note, concept: str) -> bool:
    return knowledge_model.title_starts_with_concept(to_model_note(note), concept)


def title_mentions_concept(note: Note, concept: str) -> bool:
    return knowledge_model.title_mentions_concept(to_model_note(note), concept)


def area_for_resource_topic(notes: list[Note], topic: str) -> Note | None:
    target = f"Areas/{topic}.md"
    exact = next((note for note in notes if note.path == target and is_ownership_note(note)), None)
    if exact is not None:
        return exact
    topic_dir = f"Resources/{topic}"
    for note in sorted(notes, key=lambda item: item.path):
        if ownership_area_source_topic(note) == topic_dir:
            return note
    return None


def existing_ownership_named(notes: list[Note], name: str) -> Note | None:
    target_key = normalize_name(name)
    for note in sorted((item for item in notes if is_ownership_note(item)), key=lambda item: item.path):
        if any(normalize_name(candidate) == target_key for candidate in candidate_names(note)):
            return note
    return None


def existing_ownership_covers_materials(notes: list[Note], material_paths: list[str]) -> bool:
    material_stems = {Path(path).stem for path in material_paths}
    if not material_stems:
        return False
    for note in notes:
        if not is_ownership_note(note):
            continue
        text = note.abs_path.read_text(encoding="utf-8", errors="replace")
        linked_stems = {
            Path(wikilink_target(raw)).stem
            for raw in WIKILINK_RE.findall(text)
        }
        if material_stems <= linked_stems:
            return True
    return False


def scored_ownership_subclusters(
    notes: list[Note],
    material_notes: list[Note],
    topic_key: str,
    title_matcher,
) -> list[tuple[int, int, str, list[Note]]]:
    concept_notes: dict[str, list[Note]] = defaultdict(list)
    concept_counts: Counter[str] = Counter()
    for note in material_notes:
        counts = note_concept_counts(note)
        for term, count in counts.items():
            if not concept_can_drive_structure(term):
                continue
            if normalize_name(term) == topic_key:
                continue
            if not title_matcher(note, term):
                continue
            concept_notes[term].append(note)
            concept_counts[term] += count

    scored: list[tuple[int, int, str, list[Note]]] = []
    for term, group in concept_notes.items():
        unique_notes = sorted({note.path: note for note in group}.values(), key=lambda item: item.path)
        if len(unique_notes) < MIN_OWNERSHIP_SPLIT_CLUSTER_MATERIALS:
            continue
        if len(unique_notes) >= len(material_notes):
            continue
        material_paths = [note.path for note in unique_notes]
        if existing_ownership_covers_materials(notes, material_paths):
            continue
        target_name = titleize_concept(term)
        if existing_ownership_named(notes, target_name) is not None:
            continue
        scored.append((len(unique_notes), concept_counts[term], term, unique_notes))
    scored.sort(key=lambda item: (item[0], item[1], len(item[2].split()), item[2]), reverse=True)
    return scored


def ownership_split_candidates(vault: Path, notes: list[Note], protected: set[str]) -> list[dict]:
    profiles = resource_topic_profiles(notes)
    candidates: list[dict] = []
    for topic, profile in sorted(profiles.items()):
        material_notes = resource_topic_material_notes(notes, topic)
        if len(material_notes) < MIN_OWNERSHIP_SPLIT_TOPIC_MATERIALS:
            continue
        parent = area_for_resource_topic(notes, topic)
        if parent is None:
            continue
        topic_key = normalize_name(topic)
        scored = scored_ownership_subclusters(notes, material_notes, topic_key, title_starts_with_concept)
        if not scored:
            scored = scored_ownership_subclusters(notes, material_notes, topic_key, title_mentions_concept)
        if not scored:
            continue
        best_doc_count, _count, concept, cluster_notes = scored[0]
        tied = [item for item in scored if item[0] == best_doc_count and item[1] == _count]
        if len(tied) > 1:
            candidates.append(
                {
                    "parent": parent.path,
                    "topic_dir": f"Resources/{topic}",
                    "target": "",
                    "concept": concept,
                    "material_count": best_doc_count,
                    "material_notes": [note.path for note in cluster_notes],
                    "status": "ambiguous",
                    "reason": "multiple subclusters have the same evidence score",
                    "fixable": False,
                }
            )
            continue
        target_name = titleize_concept(concept)
        target = (Path("Areas") / f"{target_name}.md").as_posix()
        protected_paths = [
            path
            for path in [parent.path, target, *(note.path for note in cluster_notes)]
            if is_protected(path, protected)
        ]
        if protected_paths:
            status = "protected"
            reason = "parent Area, child target, or material notes have pre-existing uncommitted changes"
        elif (vault / target).exists():
            status = "destination_exists"
            reason = "target child Area already exists"
        else:
            status = "fixable"
            reason = "stable subcluster inside a broader resource topic"
        candidates.append(
            {
                "parent": parent.path,
                "topic_dir": f"Resources/{topic}",
                "target": target,
                "concept": concept,
                "material_count": best_doc_count,
                "material_notes": [note.path for note in cluster_notes],
                "status": status,
                "reason": reason,
                "fixable": status == "fixable",
            }
        )
    return candidates


def resource_topic_name(note_path: str) -> str | None:
    parts = Path(note_path).parts
    if len(parts) < 3 or parts[0] != "Resources":
        return None
    return parts[1]


def add_topic_name(profile: TopicProfile, name: str) -> None:
    cleaned = strip_quotes(name).strip()
    if not meaningful_entity_name(cleaned):
        return
    key = normalize_name(cleaned)
    if key in {normalize_name(item) for item in profile.names}:
        return
    profile.names.append(cleaned)


def resource_topic_profiles(notes: list[Note], exclude_path: str | None = None) -> dict[str, TopicProfile]:
    profiles: dict[str, TopicProfile] = {}
    for note in notes:
        topic = resource_topic_name(note.path)
        if topic is None:
            continue
        profile = profiles.setdefault(topic, TopicProfile(topic=topic, dir=f"Resources/{topic}"))
        add_topic_name(profile, topic)
        if is_material_note(note) and note.path != exclude_path:
            profile.material_count += 1
            profile.concept_counts.update(note_concept_counts(note))
        if Path(note.path).name.lower() == "readme.md" or note_kind(note) == "index":
            profile.has_readme = True
            add_topic_name(profile, note.title)
            for alias in note.aliases:
                add_topic_name(profile, alias)
    return profiles


def topic_equivalence_keys(profile: TopicProfile) -> set[str]:
    return knowledge_model.topic_equivalence_keys(to_model_topic_profile(profile))


def canonical_topic_for_equivalent_group(group: list[TopicProfile]) -> TopicProfile:
    winner = knowledge_model.canonical_topic_for_equivalent_group(
        [to_model_topic_profile(profile) for profile in group]
    )
    return next(profile for profile in group if profile.topic == winner.topic)


def equivalent_topic_canonical_map(profiles: dict[str, TopicProfile]) -> dict[str, str]:
    return knowledge_model.equivalent_topic_canonical_map(
        {topic: to_model_topic_profile(profile) for topic, profile in profiles.items()}
    )


def topic_match_score(note: Note, profile: TopicProfile) -> tuple[int, list[str]]:
    return knowledge_model.topic_match_score(to_model_note(note), to_model_topic_profile(profile))


def topic_concept_match_score(note: Note, profile: TopicProfile, concept_frequency: Counter[str] | None = None) -> tuple[int, list[str]]:
    return knowledge_model.topic_concept_match_score(
        to_model_note(note),
        to_model_topic_profile(profile),
        concept_frequency,
    )


def source_moves_for_note_move(vault: Path, note: Note, target_note_rel: str) -> list[dict]:
    moves: list[dict] = []
    note_dir = Path(note.path).parent
    target_dir = Path(target_note_rel).parent
    seen: set[str] = set()
    for ref in source_refs_from_text(note):
        resolved = resolve_source_ref(vault, note.path, ref["ref"])
        if not resolved or resolved in seen or not (vault / resolved).exists():
            continue
        try:
            relative_to_note = Path(resolved).relative_to(note_dir)
        except ValueError:
            continue
        target = (target_dir / relative_to_note).as_posix()
        moves.append({"old": resolved, "new": target})
        seen.add(resolved)
    return moves


def path_qualified_incoming_wikilink_sources(note: Note, notes: list[Note]) -> list[str]:
    target_path = normalize_relpath(note.path)
    sources: set[str] = set()
    for source in notes:
        for link in source.wikilinks:
            if not has_path_component(link):
                continue
            if target_path in set(markdown_link_path_candidates(link)):
                sources.add(source.path)
                break
    return sorted(sources)


def filename_stem_matches(note: Note, notes: list[Note]) -> list[str]:
    target_key = normalize_name(Path(note.path).stem)
    return sorted(
        note.path
        for note in notes
        if normalize_name(Path(note.path).stem) == target_key
    )


def structural_safety_notes(vault: Path, scopes: list[str], protected: set[str], notes: list[Note]) -> list[Note]:
    requested = {normalize_relpath(scope).strip("/") for scope in scopes}
    defaults = {normalize_relpath(scope).strip("/") for scope in DEFAULT_SCOPES}
    if requested == defaults:
        return notes
    all_notes, _by_name, _file_stems, _attachment_targets = build_index(vault, DEFAULT_SCOPES, protected)
    return all_notes


def structural_move_status(
    vault: Path,
    note: Note,
    target_note_rel: str,
    protected: set[str],
    notes: list[Note],
    all_notes: list[Note],
) -> tuple[str, str, list[dict]]:
    source_moves = source_moves_for_note_move(vault, note, target_note_rel)
    if is_protected(note.path, protected) or is_protected(target_note_rel, protected):
        return "protected", "note or target path has pre-existing uncommitted changes", source_moves
    if (vault / target_note_rel).exists():
        return "destination_exists", "target note already exists", source_moves
    for move in source_moves:
        if is_protected(move["old"], protected) or is_protected(move["new"], protected):
            return "protected", "referenced source file has pre-existing uncommitted changes", source_moves
        if (vault / move["new"]).exists():
            return "destination_exists", "target source file already exists", source_moves
    incoming_path_links = path_qualified_incoming_wikilink_sources(note, all_notes)
    scoped_paths = {source.path for source in notes}
    outside_scope_incoming_links = [
        source
        for source in incoming_path_links
        if source not in scoped_paths
    ]
    if outside_scope_incoming_links:
        return "outside_scope", "incoming path-qualified wikilinks exist outside the requested scope", source_moves
    protected_incoming_links = [
        source
        for source in incoming_path_links
        if is_protected(source, protected)
    ]
    if protected_incoming_links:
        return "protected", "incoming path-qualified wikilinks have pre-existing uncommitted changes", source_moves
    if incoming_path_links and len(filename_stem_matches(note, all_notes)) > 1:
        return "ambiguous_incoming_link", "incoming path-qualified wikilinks cannot be uniquely repaired to the target filename stem", source_moves
    return "fixable", "current-vault topic evidence points to a unique existing topic", source_moves


def resource_topic_split_decisions(notes: list[Note]) -> list[dict]:
    profiles = resource_topic_profiles(notes)
    decisions: list[dict] = []
    for topic, _profile in sorted(profiles.items()):
        decision = knowledge_model.resource_topic_split_decision(
            [to_model_note(note) for note in notes],
            topic,
            MIN_RESOURCE_TOPIC_SPLIT_MATERIALS,
            MIN_RESOURCE_TOPIC_SPLIT_CLUSTER_MATERIALS,
        )
        if decision["status"] == "insufficient_topic_materials":
            continue
        concept = decision.get("concept", "")
        decisions.append(
            {
                "topic": topic,
                "topic_dir": f"Resources/{topic}",
                "from_topic": topic,
                "to_topic": titleize_concept(concept) if concept else "",
                "status": decision["status"],
                "reason": decision["reason"],
                "matched": [concept] if concept else [],
                "material_count": decision["material_count"],
                "topic_material_count": decision["topic_material_count"],
                "evidence_count": decision["evidence_count"],
                "material_notes": decision["note_paths"],
            }
        )
    return decisions


def resource_topic_split_candidates(
    vault: Path,
    notes: list[Note],
    protected: set[str],
    all_notes: list[Note] | None = None,
) -> list[dict]:
    safety_notes = all_notes if all_notes is not None else notes
    candidates: list[dict] = []
    for decision in resource_topic_split_decisions(notes):
        if decision["status"] == "ambiguous":
            source = decision["material_notes"][0] if decision["material_notes"] else ""
            candidates.append(
                {
                    "source": source,
                    "target": "",
                    "kind": "topic_split",
                    "matched": decision["matched"],
                    "from_topic": decision["from_topic"],
                    "to_topic": decision["to_topic"],
                    "score": decision["material_count"],
                    "current_score": 0,
                    "status": "ambiguous",
                    "fixable": False,
                    "reason": decision["reason"],
                    "source_moves": [],
                }
            )
            continue

        if decision["status"] not in {"split_candidate", "whole_topic_rename"}:
            continue
        by_path = {note.path: note for note in notes}
        target_topic = decision["to_topic"]
        for note_path in decision["material_notes"]:
            note = by_path[note_path]
            target_note_rel = (Path("Resources") / target_topic / Path(note.path).name).as_posix()
            status, reason, source_moves = structural_move_status(
                vault,
                note,
                target_note_rel,
                protected,
                notes,
                safety_notes,
            )
            candidates.append(
                {
                    "source": note.path,
                    "target": target_note_rel,
                    "kind": "topic_rename" if decision["status"] == "whole_topic_rename" else "topic_split",
                    "matched": decision["matched"],
                    "from_topic": decision["from_topic"],
                    "to_topic": target_topic,
                    "score": decision["material_count"],
                    "current_score": 0,
                    "status": status,
                    "fixable": status == "fixable",
                    "reason": decision["reason"] if status == "fixable" else reason,
                    "source_moves": source_moves,
                }
            )
    return candidates


def structural_reunderstanding_candidates(
    vault: Path,
    notes: list[Note],
    protected: set[str],
    all_notes: list[Note] | None = None,
) -> list[dict]:
    safety_notes = all_notes if all_notes is not None else notes
    profiles = resource_topic_profiles(notes)
    topic_merge_targets = equivalent_topic_canonical_map(profiles)
    candidates: list[dict] = resource_topic_split_candidates(vault, notes, protected, safety_notes)
    for note in sorted(notes, key=lambda item: item.path):
        current_topic = resource_topic_name(note.path)
        if current_topic is None or not is_material_note(note):
            continue
        current_profile = profiles.get(current_topic)
        if current_profile is None:
            continue
        if current_topic in topic_merge_targets:
            target_topic = topic_merge_targets[current_topic]
            target_note_rel = (Path("Resources") / target_topic / Path(note.path).name).as_posix()
            status, reason, source_moves = structural_move_status(
                vault,
                note,
                target_note_rel,
                protected,
                notes,
                safety_notes,
            )
            candidates.append(
                {
                    "source": note.path,
                    "target": target_note_rel,
                    "kind": "topic_merge",
                    "matched": [current_topic, target_topic],
                    "from_topic": current_topic,
                    "to_topic": target_topic,
                    "score": 10,
                    "current_score": 0,
                    "status": status,
                    "fixable": status == "fixable",
                    "reason": "resource topic names are equivalent in the current vault",
                    "source_moves": source_moves,
                }
            )
            continue
        current_score, _current_matched = topic_match_score(note, current_profile)
        scored: list[tuple[int, str, list[str]]] = []
        for topic, profile in sorted(profiles.items()):
            if topic == current_topic:
                continue
            score, matched = topic_match_score(note, profile)
            if score:
                scored.append((score, topic, matched))
        if scored:
            scored.sort(key=lambda item: (item[0], profiles[item[1]].material_count, item[1]), reverse=True)
            best_score, best_topic, matched = scored[0]
            if best_score >= 4 and best_score >= current_score + 2:
                tied = [item for item in scored if item[0] == best_score]
                if len(tied) > 1:
                    candidates.append(
                        {
                            "source": note.path,
                            "target": "",
                            "kind": "topic_rehome",
                            "matched": matched,
                            "from_topic": current_topic,
                            "to_topic": best_topic,
                            "score": best_score,
                            "current_score": current_score,
                            "status": "ambiguous",
                            "fixable": False,
                            "reason": "multiple topics have the same evidence score",
                            "source_moves": [],
                        }
                    )
                    continue
                target_note_rel = (Path("Resources") / best_topic / Path(note.path).name).as_posix()
                status, reason, source_moves = structural_move_status(
                    vault,
                    note,
                    target_note_rel,
                    protected,
                    notes,
                    safety_notes,
                )
                candidates.append(
                    {
                        "source": note.path,
                        "target": target_note_rel,
                        "kind": "topic_rehome",
                        "matched": matched,
                        "from_topic": current_topic,
                        "to_topic": best_topic,
                        "score": best_score,
                        "current_score": current_score,
                        "status": status,
                        "fixable": status == "fixable",
                        "reason": reason,
                        "source_moves": source_moves,
                    }
                )
                continue

        concept_profiles = resource_topic_profiles(notes, exclude_path=note.path)
        concept_frequency = concept_topic_frequency(concept_profiles)
        current_concept_score = 0
        if current_topic in concept_profiles:
            current_concept_score, _current_concept_matched = topic_concept_match_score(
                note,
                concept_profiles[current_topic],
                concept_frequency,
            )
        concept_scored: list[tuple[int, str, list[str]]] = []
        for topic, profile in sorted(concept_profiles.items()):
            if topic == current_topic:
                continue
            score, matched = topic_concept_match_score(note, profile, concept_frequency)
            if score:
                concept_scored.append((score, topic, matched))
        if not concept_scored:
            continue
        concept_scored.sort(key=lambda item: (item[0], concept_profiles[item[1]].material_count, item[1]), reverse=True)
        best_score, best_topic, matched = concept_scored[0]
        if best_score < 3 or best_score < current_concept_score + 2:
            continue
        tied = [item for item in concept_scored if item[0] == best_score]
        if len(tied) > 1:
            candidates.append(
                {
                    "source": note.path,
                    "target": "",
                    "kind": "concept_rehome",
                    "matched": matched,
                    "from_topic": current_topic,
                    "to_topic": best_topic,
                    "score": best_score,
                    "current_score": current_concept_score,
                    "status": "ambiguous",
                    "fixable": False,
                    "reason": "multiple topics have the same concept-overlap score",
                    "source_moves": [],
                }
            )
            continue
        target_note_rel = (Path("Resources") / best_topic / Path(note.path).name).as_posix()
        status, reason, source_moves = structural_move_status(
            vault,
            note,
            target_note_rel,
            protected,
            notes,
            safety_notes,
        )
        candidates.append(
            {
                "source": note.path,
                "target": target_note_rel,
                "kind": "concept_rehome",
                "matched": matched,
                "from_topic": current_topic,
                "to_topic": best_topic,
                "score": best_score,
                "current_score": current_concept_score,
                "status": status,
                "fixable": status == "fixable",
                "reason": "current-vault concept profile points to a unique existing topic" if status == "fixable" else reason,
                "source_moves": source_moves,
            }
        )
    return candidates


def same_topic_peer_link_candidates(notes: list[Note], existing_candidates: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    source_counts = Counter(item["source"] for item in existing_candidates)
    existing_pairs = {(item["source"], item["target"]) for item in existing_candidates}
    by_topic: dict[str, list[Note]] = defaultdict(list)
    for note in notes:
        topic = resource_topic_name(note.path)
        if topic is not None and is_material_note(note):
            by_topic[topic].append(note)

    scored_pairs: list[tuple[int, str, str, list[str], Note, Note]] = []
    for topic, topic_notes in sorted(by_topic.items()):
        if len(topic_notes) < 2:
            continue
        topic_key = normalize_name(topic)
        note_terms: dict[str, set[str]] = {}
        term_frequency: Counter[str] = Counter()
        for note in topic_notes:
            terms = {
                term
                for term in note_concept_counts(note)
                if concept_can_drive_structure(term) and normalize_name(term) != topic_key
            }
            note_terms[note.path] = terms
            term_frequency.update(terms)

        sorted_notes = sorted(topic_notes, key=lambda item: item.path)
        for left_index, left in enumerate(sorted_notes):
            for right in sorted_notes[left_index + 1 :]:
                shared = sorted(
                    term
                    for term in note_terms[left.path] & note_terms[right.path]
                    if term_frequency.get(term, 0) == 2
                )
                title_shared = [
                    term
                    for term in shared
                    if title_mentions_concept(left, term) and title_mentions_concept(right, term)
                ]
                if not title_shared:
                    continue
                if len(shared) < 3:
                    continue
                matched = [*title_shared, *[term for term in shared if term not in title_shared]][:5]
                scored_pairs.append((len(shared), left.path, right.path, matched, left, right))

    scored_pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    for score, _left_path, _right_path, shared, left, right in scored_pairs:
        for source, target in ((left, right), (right, left)):
            if source_counts[source.path] >= 5:
                continue
            if (source.path, target.path) in existing_pairs or note_links_to_target(source, target):
                continue
            candidates.append(
                {
                    "source": source.path,
                    "target": target.path,
                    "target_stem": Path(target.path).stem,
                    "source_stem": Path(source.path).stem,
                    "matched": shared,
                    "kind": "same_topic_concept",
                    "fixable": not source.protected,
                    "reason": f"same Resource topic shares distinctive concepts: {', '.join(shared)}",
                    "score": score,
                }
            )
            existing_pairs.add((source.path, target.path))
            source_counts[source.path] += 1
    return candidates


def understanding_link_candidates(notes: list[Note]) -> list[dict]:
    candidates: list[dict] = []
    targets = sorted((note for note in notes if is_understanding_target(note)), key=lambda note: note.path)
    owner_profiles = ownership_profiles(notes)
    owner_frequency = ownership_concept_frequency(owner_profiles)
    for source in sorted(notes, key=lambda note: note.path):
        if not is_material_note(source):
            continue
        body = source_text_without_wikilinks(source)
        source_count = 0
        for target in targets:
            if source.path == target.path:
                continue
            if note_links_to_target(source, target):
                continue
            matched_name = next(
                (name for name in candidate_names(target) if text_mentions_name_in_signal_context(body, name)),
                None,
            )
            if not matched_name:
                continue
            kind = "ownership" if is_ownership_note(target) else "explicit_entity"
            fixable = not source.protected and (kind != "ownership" or not target.protected)
            candidates.append(
                {
                    "source": source.path,
                    "target": target.path,
                    "target_stem": Path(target.path).stem,
                    "source_stem": Path(source.path).stem,
                    "matched": matched_name,
                    "kind": kind,
                    "fixable": fixable,
                    "reason": f"body mentions `{matched_name}`",
                }
            )
            source_count += 1
            if source_count >= 5:
                break
        if source_count >= 5:
            continue
        owner_scored: list[tuple[int, str, list[str]]] = []
        for owner_path, profile in sorted(owner_profiles.items()):
            target = profile.note
            if note_links_to_target(source, target):
                continue
            score, matched = ownership_concept_match_score(source, profile, owner_frequency)
            if score:
                owner_scored.append((score, owner_path, matched))
        if not owner_scored:
            continue
        owner_scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best_score, best_owner_path, matched = owner_scored[0]
        tied = [item for item in owner_scored if item[0] == best_score]
        if len(tied) > 1:
            continue
        target = owner_profiles[best_owner_path].note
        fixable = not source.protected and not target.protected
        candidates.append(
            {
                "source": source.path,
                "target": target.path,
                "target_stem": Path(target.path).stem,
                "source_stem": Path(source.path).stem,
                "matched": matched,
                "kind": "ownership_concept",
                "fixable": fixable,
                "reason": f"concept profile overlaps: {', '.join(matched)}",
            }
        )
    candidates.extend(same_topic_peer_link_candidates(notes, candidates))
    return candidates


def resource_topic_dirs(vault: Path, scopes: list[str]) -> list[Path]:
    topics: set[Path] = set()
    resources = vault / "Resources"
    for scope in scopes:
        rel = Path(scope)
        parts = rel.parts
        if not parts or parts[0] != "Resources":
            continue
        if len(parts) == 1:
            if resources.is_dir():
                topics.update(path for path in resources.iterdir() if path.is_dir())
            continue
        topic = resources / parts[1]
        if topic.is_dir():
            topics.add(topic)
    return sorted(topics)


def resource_index_items(topic_dir: Path) -> list[dict]:
    items: list[dict] = []
    for md in sorted(topic_dir.glob("*.md")):
        if md.name.lower() == "readme.md":
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, _aliases, _body = parse_frontmatter(text)
        if frontmatter.get("type", "reference").strip() not in ("reference", ""):
            continue
        title = strip_quotes(frontmatter.get("title", "")).strip() or md.stem
        created = frontmatter.get("created", "").strip()
        source = strip_quotes(
            frontmatter.get("source_url", "") or frontmatter.get("source_file", "") or frontmatter.get("source", "")
        ).strip()
        items.append({"title": title, "file": md.name, "created": created, "source": source})
    items.sort(key=lambda item: item["file"])
    items.sort(key=lambda item: item["created"], reverse=True)
    return items


def render_resource_index(items: list[dict]) -> str:
    if not items:
        return f"{RESOURCE_INDEX_BEGIN}\n\n> 暂无 reference 类资料。\n\n{RESOURCE_INDEX_END}"
    lines = [RESOURCE_INDEX_BEGIN, ""]
    for item in items:
        link = f"[[{item['file'][:-3]}]]"
        created = item["created"] or "—"
        if item["source"]:
            lines.append(f"- {link}（{created}）— {item['source']}")
        else:
            lines.append(f"- {link}（{created}）")
    lines.append("")
    lines.append(RESOURCE_INDEX_END)
    return "\n".join(lines)


def resource_index_span(text: str) -> tuple[int, int] | None:
    begin = text.find(RESOURCE_INDEX_BEGIN)
    if begin == -1:
        return None
    end = text.find(RESOURCE_INDEX_END, begin)
    if end == -1:
        return None
    return begin, end + len(RESOURCE_INDEX_END)


def ownership_index_span(text: str) -> tuple[int, int] | None:
    begin = text.find(OWNERSHIP_INDEX_BEGIN)
    if begin == -1:
        return None
    end = text.find(OWNERSHIP_INDEX_END, begin)
    if end == -1:
        return None
    return begin, end + len(OWNERSHIP_INDEX_END)


def render_ownership_material_index(material_notes: list[str], topic_dir: str) -> str:
    lines = [OWNERSHIP_INDEX_BEGIN, ""]
    if not material_notes:
        lines.append("> 暂无可承接资料。")
    for path in sorted(material_notes):
        lines.append(f"- [[{Path(path).stem}]]（自动承接：`{topic_dir}`）")
    lines.append("")
    lines.append(OWNERSHIP_INDEX_END)
    return "\n".join(lines)


def upsert_ownership_index_section(text: str, expected_index: str) -> str:
    span = ownership_index_span(text)
    if span is not None:
        return text[: span[0]] + expected_index + text[span[1] :]

    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    index_heading = next((idx for idx, line in enumerate(lines) if line.strip() == "## 资料索引"), None)
    if index_heading is None:
        base = text.rstrip()
        return base + "\n\n## 资料索引\n\n" + expected_index + "\n"

    next_heading = len(lines)
    for idx in range(index_heading + 1, len(lines)):
        if lines[idx].startswith("## ") and lines[idx].strip() != "## 资料索引":
            next_heading = idx
            break
    preserved_section = [
        line
        for line in lines[index_heading + 1 : next_heading]
        if "（自动承接：" not in line
    ]
    while preserved_section and not preserved_section[0].strip():
        preserved_section.pop(0)
    while preserved_section and not preserved_section[-1].strip():
        preserved_section.pop()
    output = lines[: index_heading + 1] + ["", expected_index]
    if preserved_section:
        output.extend(["", *preserved_section])
    if next_heading < len(lines):
        output.extend(["", *lines[next_heading:]])
    return "\n".join(output) + ("\n" if trailing_newline else "")


def render_topic_readme(topic: str, expected_index: str) -> str:
    return (
        "---\n"
        f"title: {quote_yaml(topic)}\n"
        "type: index\n"
        "---\n\n"
        f"# {topic}\n\n"
        "## 主题定位\n\n"
        "待补充：说明本主题的定位、承接 Area / Project，以及资料使用边界。\n\n"
        "## 资料索引\n\n"
        f"{expected_index}\n"
    )


def render_created_area(topic: str, topic_dir: str, concepts: list[str], material_notes: list[str], date: str) -> str:
    concept_text = "、".join(concepts) if concepts else "待积累"
    created = date if date and date != "未注明日期" else ""
    created_line = f"created: {quote_yaml(created)}\n" if created else ""
    return (
        "---\n"
        f"title: {quote_yaml(topic)}\n"
        "type: area\n"
        "status: active\n"
        f"{created_line}"
        "---\n\n"
        f"# {topic}\n\n"
        "## 定位\n\n"
        f"自动承接 `{topic_dir}` 中已经形成稳定知识簇的资料，作为长期复用和重新理解的 ownership note。\n\n"
        "## 适用范围\n\n"
        f"- 主题来源：`{topic_dir}`\n"
        f"- 核心概念：{concept_text}\n\n"
        "## 概念画像\n\n"
        f"{render_area_understanding_profile(concepts, len(material_notes))}\n\n"
        "## 资料索引\n\n"
        + render_ownership_material_index(material_notes, topic_dir)
        + "\n\n"
        "## 下一步\n\n"
        "- 持续由 meditate 自动补链、更新画像，并在知识增长后重构边界。\n"
    )


def render_child_area(
    title: str,
    parent_stem: str,
    topic_dir: str,
    concept: str,
    material_notes: list[str],
    date: str,
) -> str:
    created = date if date and date != "未注明日期" else ""
    created_line = f"created: {quote_yaml(created)}\n" if created else ""
    profile = render_area_understanding_profile([concept], len(material_notes))
    return (
        "---\n"
        f"title: {quote_yaml(title)}\n"
        "type: area\n"
        "status: active\n"
        f"{created_line}"
        "---\n\n"
        f"# {title}\n\n"
        "## 定位\n\n"
        f"自动从 [[{parent_stem}]] 分化出来，承接 `{topic_dir}` 中围绕 `{concept}` 形成的稳定子簇。\n\n"
        "## 适用范围\n\n"
        f"- 上级承接：[[{parent_stem}]]\n"
        f"- 主题来源：`{topic_dir}`\n"
        f"- 分化概念：{concept}\n\n"
        "## 概念画像\n\n"
        f"{profile}\n\n"
        "## 资料索引\n\n"
        + render_ownership_material_index(material_notes, topic_dir)
        + "\n\n"
        "## 下一步\n\n"
        "- 持续由 meditate 自动补链、更新画像，并在知识增长后重构边界。\n"
    )


def upsert_resource_index_section(text: str, expected_index: str) -> str:
    span = resource_index_span(text)
    if span is not None:
        return text[: span[0]] + expected_index + text[span[1] :]

    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    index_heading = next((idx for idx, line in enumerate(lines) if line.strip() == "## 资料索引"), None)
    if index_heading is None:
        base = text.rstrip()
        return base + "\n\n## 资料索引\n\n" + expected_index + "\n"

    next_heading = len(lines)
    for idx in range(index_heading + 1, len(lines)):
        if lines[idx].startswith("## ") and lines[idx].strip() != "## 资料索引":
            next_heading = idx
            break
    output = lines[: index_heading + 1] + ["", expected_index]
    if next_heading < len(lines):
        output.extend(["", *lines[next_heading:]])
    return "\n".join(output) + ("\n" if trailing_newline else "")


def understanding_profile_span(text: str) -> tuple[int, int] | None:
    begin = text.find(UNDERSTANDING_PROFILE_BEGIN)
    if begin == -1:
        return None
    end = text.find(UNDERSTANDING_PROFILE_END, begin)
    if end == -1:
        return None
    return begin, end + len(UNDERSTANDING_PROFILE_END)


def render_understanding_profile(profile: TopicProfile) -> str:
    concepts = top_concepts(profile)
    lines = [UNDERSTANDING_PROFILE_BEGIN, ""]
    if concepts:
        lines.append("- 核心概念：" + "、".join(concepts))
    else:
        lines.append("- 核心概念：待积累")
    lines.append(f"- 资料数量：{profile.material_count}")
    lines.append("")
    lines.append(UNDERSTANDING_PROFILE_END)
    return "\n".join(lines)


def upsert_understanding_profile_section(text: str, expected_profile: str) -> str:
    span = understanding_profile_span(text)
    if span is not None:
        return text[: span[0]] + expected_profile + text[span[1] :]

    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    profile_heading = next((idx for idx, line in enumerate(lines) if line.strip() == "## 概念画像"), None)
    if profile_heading is None:
        base = text.rstrip()
        return base + "\n\n## 概念画像\n\n" + expected_profile + "\n"

    next_heading = len(lines)
    for idx in range(profile_heading + 1, len(lines)):
        if lines[idx].startswith("## ") and lines[idx].strip() != "## 概念画像":
            next_heading = idx
            break
    output = lines[: profile_heading + 1] + ["", expected_profile]
    if next_heading < len(lines):
        output.extend(["", *lines[next_heading:]])
    return "\n".join(output) + ("\n" if trailing_newline else "")


def topic_relations_span(text: str) -> tuple[int, int] | None:
    begin = text.find(TOPIC_RELATIONS_BEGIN)
    if begin == -1:
        return None
    end = text.find(TOPIC_RELATIONS_END, begin)
    if end == -1:
        return None
    return begin, end + len(TOPIC_RELATIONS_END)


def render_topic_relations(relations: list[dict]) -> str:
    lines = [TOPIC_RELATIONS_BEGIN, ""]
    if not relations:
        lines.append("> 暂无稳定相关主题。")
    for relation in sorted(relations, key=lambda item: item["target_stem"]):
        concepts = relation.get("concepts", [])[:5]
        concept_text = "、".join(concepts) if concepts else "待积累"
        lines.append(
            f"- [[{relation['target_readme_stem']}|{relation['target_stem']}]]"
            f"（共享概念：{concept_text}）"
        )
    lines.append("")
    lines.append(TOPIC_RELATIONS_END)
    return "\n".join(lines)


def upsert_topic_relations_section(text: str, expected_relations: str) -> str:
    span = topic_relations_span(text)
    if span is not None:
        return text[: span[0]] + expected_relations + text[span[1] :]

    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    relations_heading = next((idx for idx, line in enumerate(lines) if line.strip() == "## 相关主题"), None)
    if relations_heading is None:
        base = text.rstrip()
        return base + "\n\n## 相关主题\n\n" + expected_relations + "\n"

    next_heading = len(lines)
    for idx in range(relations_heading + 1, len(lines)):
        if lines[idx].startswith("## ") and lines[idx].strip() != "## 相关主题":
            next_heading = idx
            break
    output = lines[: relations_heading + 1] + ["", expected_relations]
    if next_heading < len(lines):
        output.extend(["", *lines[next_heading:]])
    return "\n".join(output) + ("\n" if trailing_newline else "")


def ownership_relations_span(text: str) -> tuple[int, int] | None:
    begin = text.find(OWNERSHIP_RELATIONS_BEGIN)
    if begin == -1:
        return None
    end = text.find(OWNERSHIP_RELATIONS_END, begin)
    if end == -1:
        return None
    return begin, end + len(OWNERSHIP_RELATIONS_END)


def render_ownership_relations(relations: list[dict]) -> str:
    lines = [OWNERSHIP_RELATIONS_BEGIN, ""]
    if not relations:
        lines.append("> 暂无稳定相关承接。")
    for relation in sorted(relations, key=lambda item: item["target_stem"]):
        concept_text = "、".join(relation.get("concepts", [])[:5]) if relation.get("concepts") else "待积累"
        lines.append(
            f"- [[{relation['target_stem']}]]"
            f"（共享 Resource 概念：{concept_text}；"
            f"来源：`{relation['source_dir']}` ↔ `{relation['target_dir']}`）"
        )
    lines.append("")
    lines.append(OWNERSHIP_RELATIONS_END)
    return "\n".join(lines)


def upsert_ownership_relations_section(text: str, expected_relations: str) -> str:
    span = ownership_relations_span(text)
    if span is not None:
        return text[: span[0]] + expected_relations + text[span[1] :]

    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    relations_heading = next((idx for idx, line in enumerate(lines) if line.strip() == "## 相关承接"), None)
    if relations_heading is None:
        base = text.rstrip()
        return base + "\n\n## 相关承接\n\n" + expected_relations + "\n"

    next_heading = len(lines)
    for idx in range(relations_heading + 1, len(lines)):
        if lines[idx].startswith("## ") and lines[idx].strip() != "## 相关承接":
            next_heading = idx
            break
    output = lines[: relations_heading + 1] + ["", expected_relations]
    if next_heading < len(lines):
        output.extend(["", *lines[next_heading:]])
    return "\n".join(output) + ("\n" if trailing_newline else "")


def topic_index_gaps(vault: Path, scopes: list[str], protected: set[str]) -> list[dict]:
    gaps: list[dict] = []
    for topic_dir in resource_topic_dirs(vault, scopes):
        items = resource_index_items(topic_dir)
        readme = topic_dir / "README.md"
        topic_rel = topic_dir.relative_to(vault).as_posix()
        readme_rel = readme.relative_to(vault).as_posix()
        if len(items) < 3 and not readme.exists():
            continue
        expected_index = render_resource_index(items)
        status: str | None = None
        reason = ""
        current_index = ""
        if not readme.exists():
            status = "missing_readme"
            reason = "topic has 3+ reference notes but no README / Map of Content"
        else:
            text = readme.read_text(encoding="utf-8", errors="replace")
            span = resource_index_span(text)
            if span is None:
                status = "missing_markers"
                reason = "README exists but has no resource-index marker block"
            else:
                current_index = text[span[0] : span[1]]
                if current_index != expected_index:
                    status = "stale"
                    reason = "README resource-index marker block differs from current reference notes"
        if status is None:
            continue
        protected_item = is_protected(topic_rel + "/", protected) or is_protected(readme_rel, protected)
        gaps.append(
            {
                "topic": topic_dir.name,
                "topic_dir": topic_rel,
                "readme": readme_rel,
                "reference_count": len(items),
                "status": "protected" if protected_item else status,
                "reason": "topic README or directory has pre-existing uncommitted changes" if protected_item else reason,
                "expected_index": expected_index,
                "current_index": current_index,
                "fixable": not protected_item,
            }
        )
    return sorted(gaps, key=lambda item: (item["topic_dir"], item["status"]))


def topic_understanding_profiles(notes: list[Note]) -> list[dict]:
    profiles = resource_topic_profiles(notes)
    items: list[dict] = []
    for profile in sorted(profiles.values(), key=lambda item: item.dir):
        if profile.material_count == 0:
            continue
        items.append(
            {
                "topic": profile.topic,
                "topic_dir": profile.dir,
                "material_count": profile.material_count,
                "concepts": top_concepts(profile),
            }
        )
    return items


def topic_relation_candidates(notes: list[Note]) -> list[dict]:
    profiles = resource_topic_profiles(notes)
    return knowledge_model.topic_relation_candidates(
        {topic: to_model_topic_profile(profile) for topic, profile in profiles.items()}
    )


def ownership_understanding_profiles(notes: list[Note]) -> list[dict]:
    profiles = ownership_profiles(notes)
    items: list[dict] = []
    for profile in sorted(profiles.values(), key=lambda item: item.note.path):
        concepts = top_concepts_from_counts(profile.concept_counts)
        if not concepts:
            continue
        items.append(
            {
                "path": profile.note.path,
                "kind": "project" if profile.note.path.startswith("Projects/") else "area",
                "concepts": concepts,
            }
        )
    return items


def understanding_profile_gaps(vault: Path, notes: list[Note], protected: set[str]) -> list[dict]:
    profiles = resource_topic_profiles(notes)
    gaps: list[dict] = []
    for profile in sorted(profiles.values(), key=lambda item: item.dir):
        if profile.material_count < 2:
            continue
        readme = vault / profile.dir / "README.md"
        readme_rel = (Path(profile.dir) / "README.md").as_posix()
        if not readme.exists():
            continue
        expected_profile = render_understanding_profile(profile)
        text = readme.read_text(encoding="utf-8", errors="replace")
        span = understanding_profile_span(text)
        if span is None:
            status = "missing_markers"
            reason = "README exists but has no understanding-profile marker block"
            current_profile = ""
        else:
            current_profile = text[span[0] : span[1]]
            if current_profile == expected_profile:
                continue
            status = "stale"
            reason = "README understanding-profile marker block differs from current notes"
        protected_item = is_protected(profile.dir + "/", protected) or is_protected(readme_rel, protected)
        gaps.append(
            {
                "topic": profile.topic,
                "topic_dir": profile.dir,
                "readme": readme_rel,
                "status": "protected" if protected_item else status,
                "reason": "topic README or directory has pre-existing uncommitted changes" if protected_item else reason,
                "expected_profile": expected_profile,
                "current_profile": current_profile,
                "fixable": not protected_item,
            }
        )
    return gaps


def invalid_fingerprints(notes: list[Note]) -> list[dict]:
    return [
        {
            "path": note.path,
            "field": note.stored_fingerprint_field,
            "stored": note.stored_fingerprint,
            "computed": note.fingerprint,
            "reason": "stale_or_invalid_fingerprint",
        }
        for note in notes
        if not note.fingerprint_valid
    ]


def invalid_frontmatter_list(notes: list[Note]) -> list[dict]:
    return [
        {
            "path": note.path,
            "reason": "invalid_frontmatter_value",
            "detail": note.invalid_frontmatter,
        }
        for note in notes
        if note.invalid_frontmatter
    ]


def coverage(notes: list[Note]) -> dict:
    distribution = Counter(note.path.split("/", 1)[0] for note in notes)
    return {
        "markdown_count": len(notes),
        "distribution": dict(sorted(distribution.items())),
        "source_url_or_canonical": sum(1 for note in notes if note.normalized_urls),
        "source_fingerprint": sum(
            1 for note in notes if note.frontmatter.get("source_fingerprint") or note.frontmatter.get("content_fingerprint")
        ),
        "content_fingerprint": sum(1 for note in notes if note.frontmatter.get("content_fingerprint")),
        "invalid_fingerprint": sum(1 for note in notes if not note.fingerprint_valid),
        "invalid_frontmatter": sum(1 for note in notes if note.invalid_frontmatter),
    }


def quote_yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_frontmatter_block(lines: list[str]) -> tuple[int | None, int | None]:
    """Return (start, end) indices for a YAML frontmatter block anywhere in the file,
    or (None, None) if none found."""
    for idx in range(len(lines)):
        if lines[idx].strip() == "---":
            for j in range(idx + 1, min(idx + 50, len(lines))):
                if lines[j].strip() == "---":
                    block_text = "".join(lines[idx + 1 : j])
                    if re.search(r"^\w[\w-]*:\s+", block_text, re.MULTILINE):
                        return idx, j
            # Only check the first `---` if it's near the top; otherwise skip malformed.
            if idx > 10:
                break
    return None, None


def insert_frontmatter_fields(text: str, fields: dict[str, str]) -> str:
    """Insert metadata fields into the note's frontmatter.

    Searches the whole file for an existing frontmatter block (a real frontmatter
    may be buried after garbled PDF content). Only creates a new frontmatter block
    when no existing block is found anywhere.
    """
    lines = text.splitlines(keepends=True)

    # Quick check: frontmatter at line 0?
    start, end = None, None
    if lines and lines[0].strip() == "---":
        start = 0
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end = idx
                break
    else:
        # Check for preamble + frontmatter (blockquote then ---).
        for idx, line in enumerate(lines[:8]):
            if line.strip() == "---":
                start = idx
                for j in range(idx + 1, min(idx + 50, len(lines))):
                    if lines[j].strip() == "---":
                        end = j
                        break
                break
            if line.strip() and not line.startswith("> 整理自 Inbox"):
                break  # Non-preamble, non-fence content → no frontmatter at top.

    # If still not found, search deeper for any frontmatter block.
    if start is None:
        start, end = find_frontmatter_block(lines)

    if start is None:
        # No frontmatter anywhere; prepend a new one.
        block = ["---\n",
                 *[f"{key}: {quote_yaml(value)}\n" for key, value in fields.items()],
                 "---\n", "\n"]
        return "".join(block + lines)

    # Insert fields into the found frontmatter block.
    if end is None:
        return text

    existing = set()
    for line in lines[start + 1 : end]:
        if ":" in line:
            existing.add(line.split(":", 1)[0].strip())
    insert = [f"{key}: {quote_yaml(value)}\n" for key, value in fields.items() if key not in existing]
    if not insert:
        return text
    return "".join(lines[:end] + insert + lines[end:])


def add_duplicate_marker(text: str, canonical_title: str, evidence: list[dict], date: str) -> str:
    if "重复内容，canonical" in text:
        return text
    evidence_text = ", ".join(f"{item['type']}={item['value']}" for item in evidence)
    marker = f"> 重复内容，canonical：[[{canonical_title}]]\n> 重复依据：{evidence_text}\n> 优化日期：{date}\n\n"
    return marker + text


def append_canonical_record(text: str, duplicate_title: str) -> str:
    if duplicate_title in text and "重复" in text:
        return text
    return text.rstrip() + f"\n\n## 重复归档\n\n- [[{duplicate_title}]]：已归档为重复内容。\n"


def add_ownership_duplicate_marker(text: str, canonical_stem: str, matched: list[str], date: str) -> str:
    if "重复承接，canonical" in text:
        return text
    evidence_text = "、".join(matched)
    marker = (
        f"> 重复承接，canonical：[[{canonical_stem}]]\n"
        f"> 重复依据：等价 ownership topic（{evidence_text}）\n"
        f"> 优化日期：{date}\n\n"
    )
    return marker + text


def replace_wikilink(text: str, old: str, new: str) -> str:
    old_target = wikilink_target(old)

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        target, *rest = raw.split("|", 1)
        target_base, *anchor = target.split("#", 1)
        if has_path_component(old_target):
            if normalize_relpath(target_base) != normalize_relpath(old_target):
                return match.group(0)
        elif normalize_name(target_base) != normalize_name(old_target):
            return match.group(0)
        suffix = "#" + anchor[0] if anchor else ""
        alias = "|" + rest[0] if rest else ""
        return f"[[{new}{suffix}{alias}]]"

    return WIKILINK_RE.sub(repl, text)


def upsert_source_file_frontmatter(text: str, canonical_ref: str) -> str:
    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return text
    for idx in range(1, end):
        if lines[idx].startswith("source_file:"):
            lines[idx] = f'source_file: "{canonical_ref}"'
            return "\n".join(lines) + ("\n" if trailing_newline else "")
    lines.insert(end, f'source_file: "{canonical_ref}"')
    return "\n".join(lines) + ("\n" if trailing_newline else "")


def normalize_original_file_line(text: str, canonical_ref: str) -> str:
    trailing_newline = text.endswith("\n")
    lines = text[:-1].split("\n") if trailing_newline else text.split("\n")
    output: list[str] = []
    replaced = False
    use_english = "Original file" in text and "原始文件" not in text
    original_line = (
        f"Original file: [[{canonical_ref}]]"
        if use_english
        else f"原始文件：[[{canonical_ref}]]"
    )
    for line in lines:
        if line.startswith("> 整理自 Inbox") or line.startswith("> Organized from Inbox"):
            marker = line
            for original_marker in ("原始文件", "Original file"):
                if original_marker in marker:
                    marker = marker.split(original_marker, 1)[0].rstrip(" .。:：")
                    break
            output.append(marker)
            output.append(original_line)
            replaced = True
            continue
        if "原始文件" in line or "Original file" in line:
            if not replaced:
                output.append(original_line)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        insert_at = 0
        if output and output[0].strip() == "---":
            for idx in range(1, len(output)):
                if output[idx].strip() == "---":
                    insert_at = idx + 1
                    break
        output.insert(insert_at, original_line)
    return "\n".join(output) + ("\n" if trailing_newline else "")


def normalize_source_note_text(text: str, canonical_ref: str) -> str:
    text = upsert_source_file_frontmatter(text, canonical_ref)
    return normalize_original_file_line(text, canonical_ref)


def upsert_section_bullet(text: str, heading: str, bullet: str) -> str:
    if bullet in text:
        return text
    bullet_links = WIKILINK_RE.findall(bullet)
    bullet_target_stem = (
        Path(wikilink_target(bullet_links[0])).stem if bullet_links else None
    )
    heading_line = f"## {heading}"
    normalized = text.rstrip("\n")
    lines = normalized.split("\n") if normalized else []
    try:
        heading_idx = next(idx for idx, line in enumerate(lines) if line.strip() == heading_line)
    except StopIteration:
        return normalized + f"\n\n{heading_line}\n\n{bullet}\n"

    insert_idx = len(lines)
    for idx in range(heading_idx + 1, len(lines)):
        if lines[idx].startswith("## "):
            insert_idx = idx
            break

    if bullet_target_stem is not None:
        for line in lines[heading_idx + 1 : insert_idx]:
            for raw_link in WIKILINK_RE.findall(line):
                if Path(wikilink_target(raw_link)).stem == bullet_target_stem:
                    return text

    while insert_idx > heading_idx + 1 and not lines[insert_idx - 1].strip():
        insert_idx -= 1

    insert: list[str] = []
    if insert_idx == heading_idx + 1:
        insert.append("")
    insert.append(bullet)
    if insert_idx < len(lines) and lines[insert_idx].strip():
        insert.append("")
    lines[insert_idx:insert_idx] = insert
    return "\n".join(lines).rstrip("\n") + "\n"


def apply_understanding_links(vault: Path, report: dict) -> None:
    protected = set(report.get("protected_paths", []))
    notes, _by_name, _file_stems, _attachment_targets = build_index(vault, report["scope"], protected)
    by_path = {note.path: note for note in notes}
    applied = report["applied"].setdefault("understanding_links", [])
    for item in report.get("understanding", {}).get("link_candidates", []):
        source = by_path.get(item["source"])
        target = by_path.get(item["target"])
        if source is None or target is None:
            report["skipped_uncertain"].append({"type": "understanding_missing_note", **item})
            continue
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "protected_understanding_link", **item})
            continue

        source_text = source.abs_path.read_text(encoding="utf-8")
        matched_text = "、".join(item["matched"]) if isinstance(item.get("matched"), list) else item["matched"]
        source_bullet = f"- [[{item['target_stem']}]]（重新理解：{matched_text}）"
        new_source_text = upsert_section_bullet(source_text, "关联", source_bullet)
        source_changed = new_source_text != source_text
        if source_changed:
            source.abs_path.write_text(new_source_text, encoding="utf-8")

        target_changed = False
        if item["kind"] in {"ownership", "ownership_concept"}:
            target_text = target.abs_path.read_text(encoding="utf-8")
            target_bullet = f"- [[{item['source_stem']}]]（重新理解：{matched_text}）"
            new_target_text = upsert_section_bullet(target_text, "资料索引", target_bullet)
            target_changed = new_target_text != target_text
            if target_changed:
                target.abs_path.write_text(new_target_text, encoding="utf-8")

        if source_changed or target_changed:
            applied.append(
                {
                    "source": item["source"],
                    "target": item["target"],
                    "kind": item["kind"],
                    "matched": item["matched"],
                }
            )


def git_mv_checked(vault: Path, old: str, new: str) -> tuple[bool, str]:
    (vault / new).parent.mkdir(parents=True, exist_ok=True)
    completed = run_git(vault, ["mv", old, new])
    if completed.returncode == 0:
        return True, ""
    return False, completed.stderr.strip() or completed.stdout.strip() or "git mv failed"


def repair_structural_incoming_wikilinks(
    vault: Path,
    report: dict,
    old_note_rel: str,
    new_note_rel: str,
) -> None:
    protected = set(report.get("protected_paths", []))
    notes, _by_name, _file_stems, _attachment_targets = build_index(vault, report.get("scope", DEFAULT_SCOPES), protected)
    old_path = normalize_relpath(old_note_rel)
    target_stem = Path(new_note_rel).stem
    applied = report["applied"].setdefault("broken_links", [])
    for note in sorted(notes, key=lambda item: item.path):
        note_path = vault / note.path
        if not note_path.exists() or is_protected(note.path, protected):
            continue
        text = note_path.read_text(encoding="utf-8")
        new_text = text
        repaired: list[str] = []
        for raw in WIKILINK_RE.findall(text):
            if not has_path_component(raw):
                continue
            if old_path not in set(markdown_link_path_candidates(wikilink_target(raw))):
                continue
            new_text = replace_wikilink(new_text, raw, target_stem)
            repaired.append(raw)
        if new_text == text:
            continue
        note_path.write_text(new_text, encoding="utf-8")
        for raw in repaired:
            applied.append({"source": note.path, "old": raw, "new": target_stem})


def apply_structural_reorganization(vault: Path, report: dict) -> None:
    applied = report["applied"].setdefault("structural_moves", [])
    for item in report.get("understanding", {}).get("structure_candidates", []):
        if not item.get("fixable"):
            append_skipped_once(report, {"type": "structural_reunderstanding", **item})
            continue
        source = item["source"]
        target = item["target"]
        if not source or not target or not (vault / source).exists():
            append_skipped_once(report, {"type": "structural_missing_note", **item})
            continue
        moved_sources: list[dict] = []
        moved_note = False
        ok, error = git_mv_checked(vault, source, target)
        if not ok:
            append_skipped_once(report, {"type": "structural_git_mv_failed", "error": error, **item})
            continue
        moved_note = True
        failed_source_move: str | None = None
        for source_move in item.get("source_moves", []):
            old = source_move["old"]
            new = source_move["new"]
            if not (vault / old).exists():
                continue
            ok, error = git_mv_checked(vault, old, new)
            if not ok:
                failed_source_move = error
                break
            moved_sources.append({"old": old, "new": new})
        if failed_source_move:
            # Keep the note move. The next source-file policy pass will report
            # the remaining source issue instead of hiding it.
            append_skipped_once(
                report,
                {"type": "structural_source_git_mv_failed", "error": failed_source_move, **item},
            )
        if moved_note:
            repair_structural_incoming_wikilinks(vault, report, source, target)
            applied.append(
                {
                    "source": source,
                    "target": target,
                    "kind": item["kind"],
                    "matched": item["matched"],
                    "source_moves": moved_sources,
                }
            )


def apply_source_file_policy(vault: Path, report: dict) -> None:
    for item in report.get("source_file_anomalies", []):
        if item.get("status") != "fixable" or not item.get("note"):
            continue
        note_rel = item["note"]
        actual = item["actual"]
        expected = item["expected"]
        canonical_ref = item["canonical_ref"]
        if actual != expected:
            (vault / expected).parent.mkdir(parents=True, exist_ok=True)
            moved = run_git(vault, ["mv", actual, expected])
            if moved.returncode != 0:
                item["status"] = "git_mv_failed"
                item["reason"] = moved.stderr.strip() or "git mv failed"
                report["skipped_uncertain"].append({"type": "source_file_policy", **item})
                continue
        note_path = vault / note_rel
        text = note_path.read_text(encoding="utf-8")
        new_text = normalize_source_note_text(text, canonical_ref)
        if new_text != text:
            note_path.write_text(new_text, encoding="utf-8")
        report["applied"]["source_files"].append({
            "note": note_rel,
            "old": actual,
            "new": expected,
            "source_file": canonical_ref,
        })


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def apply_metadata(notes: list[Note], report: dict) -> None:
    for item in report["metadata_missing"]:
        note = next(note for note in notes if note.path == item["path"])
        if note.protected:
            report["skipped_uncertain"].append({"type": "protected_metadata", "path": note.path})
            continue
        text = note.abs_path.read_text(encoding="utf-8")
        fields: dict[str, str] = {}
        if "source_fingerprint" in item["fields"]:
            fields["source_fingerprint"] = content_fingerprint(text)
        if "content_fingerprint" in item["fields"]:
            fields["content_fingerprint"] = content_fingerprint(text)
        if "source_url" in item["fields"] and note.normalized_urls:
            fields["source_url"] = note.normalized_urls[0]
        new_text = insert_frontmatter_fields(text, fields)
        if new_text != text:
            note.abs_path.write_text(new_text, encoding="utf-8")
            report["applied"]["metadata"].append({"path": note.path, "fields": sorted(fields)})


def apply_topic_indexes(vault: Path, report: dict) -> None:
    applied = report["applied"].setdefault("topic_indexes", [])
    for item in report.get("topic_index_gaps", []):
        status = item.get("status")
        if not item.get("fixable"):
            append_skipped_once(report, {"type": "topic_index_gap", **item})
            continue
        readme_rel = item["readme"]
        readme_path = vault / readme_rel
        expected_index = item["expected_index"]
        if status == "missing_readme":
            readme_path.parent.mkdir(parents=True, exist_ok=True)
            readme_path.write_text(render_topic_readme(item["topic"], expected_index), encoding="utf-8")
            applied_status = "created"
        elif status in {"missing_markers", "stale"}:
            text = readme_path.read_text(encoding="utf-8")
            new_text = upsert_resource_index_section(text, expected_index)
            if new_text != text:
                readme_path.write_text(new_text, encoding="utf-8")
            applied_status = "inserted_markers" if status == "missing_markers" else "updated"
        else:
            continue
        item["applied_status"] = applied_status
        applied.append({"topic_dir": item["topic_dir"], "readme": readme_rel, "status": applied_status})


def apply_understanding_profiles(vault: Path, report: dict) -> None:
    applied = report["applied"].setdefault("understanding_profiles", [])
    for item in report.get("understanding_profile_gaps", []):
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "understanding_profile_gap", **item})
            continue
        readme_rel = item["readme"]
        readme_path = vault / readme_rel
        if not readme_path.exists():
            report["skipped_uncertain"].append({"type": "understanding_profile_missing_readme", **item})
            continue
        text = readme_path.read_text(encoding="utf-8")
        new_text = upsert_understanding_profile_section(text, item["expected_profile"])
        if new_text != text:
            readme_path.write_text(new_text, encoding="utf-8")
        item["applied_status"] = "updated"
        applied.append({"topic_dir": item["topic_dir"], "readme": readme_rel, "status": "updated"})


def apply_topic_relations(vault: Path, report: dict) -> None:
    protected = set(report.get("protected_paths", []))
    applied = report["applied"].setdefault("topic_relations", [])
    relations_by_topic: dict[str, list[dict]] = defaultdict(list)
    accepted_candidates: list[dict] = []

    for item in report.get("understanding", {}).get("topic_relation_candidates", []):
        source_dir = item.get("source_dir", "")
        target_dir = item.get("target_dir", "")
        if not source_dir or not target_dir:
            continue
        source_readme = (Path(source_dir) / "README.md").as_posix()
        target_readme = (Path(target_dir) / "README.md").as_posix()
        blocked = False
        for topic_dir, readme_rel in ((source_dir, source_readme), (target_dir, target_readme)):
            if is_protected(topic_dir + "/", protected) or is_protected(readme_rel, protected):
                report["skipped_uncertain"].append(
                    {
                        "type": "topic_relation_protected_readme",
                        "source_dir": source_dir,
                        "target_dir": target_dir,
                        "readme": readme_rel,
                    }
                )
                blocked = True
            elif not (vault / readme_rel).exists():
                report["skipped_uncertain"].append(
                    {
                        "type": "topic_relation_missing_readme",
                        "source_dir": source_dir,
                        "target_dir": target_dir,
                        "readme": readme_rel,
                    }
                )
                blocked = True
        if blocked:
            continue
        concepts = item.get("concepts", [])
        relations_by_topic[source_dir].append(
            {
                "target_dir": target_dir,
                "target_stem": Path(target_dir).name,
                "target_readme_stem": (Path(target_dir) / "README").as_posix(),
                "concepts": concepts,
            }
        )
        relations_by_topic[target_dir].append(
            {
                "target_dir": source_dir,
                "target_stem": Path(source_dir).name,
                "target_readme_stem": (Path(source_dir) / "README").as_posix(),
                "concepts": concepts,
            }
        )
        accepted_candidates.append(item)

    for topic_dir in resource_topic_dirs(vault, report["scope"]):
        topic_rel = topic_dir.relative_to(vault).as_posix()
        if topic_rel in relations_by_topic:
            continue
        readme_rel = (Path(topic_rel) / "README.md").as_posix()
        readme_path = vault / readme_rel
        if not readme_path.exists():
            continue
        if is_protected(topic_rel + "/", protected) or is_protected(readme_rel, protected):
            continue
        text = readme_path.read_text(encoding="utf-8")
        if topic_relations_span(text) is not None:
            relations_by_topic[topic_rel] = []

    changed_topics: set[str] = set()
    for topic_dir, relations in sorted(relations_by_topic.items()):
        readme_rel = (Path(topic_dir) / "README.md").as_posix()
        readme_path = vault / readme_rel
        text = readme_path.read_text(encoding="utf-8")
        expected_relations = render_topic_relations(relations)
        new_text = upsert_topic_relations_section(text, expected_relations)
        if new_text == text:
            continue
        readme_path.write_text(new_text, encoding="utf-8")
        changed_topics.add(topic_dir)
        applied.append(
            {
                "topic_dir": topic_dir,
                "readme": readme_rel,
                "relation_count": len(relations),
            }
        )

    for item in accepted_candidates:
        item["applied_status"] = "updated" if (
            item["source_dir"] in changed_topics or item["target_dir"] in changed_topics
        ) else "current"


def apply_ownership_relations(vault: Path, report: dict) -> None:
    protected = set(report.get("protected_paths", []))
    notes, _by_name, _file_stems, _attachment_targets = build_index(vault, report["scope"], protected)
    areas_by_topic = {
        topic_dir: area
        for area in notes
        if (topic_dir := ownership_area_source_topic(area)) is not None
    }
    relations_by_area: dict[str, list[dict]] = defaultdict(list)
    applied = report["applied"].setdefault("ownership_relations", [])

    for item in report.get("understanding", {}).get("topic_relation_candidates", []):
        source_dir = item.get("source_dir", "")
        target_dir = item.get("target_dir", "")
        source_area = areas_by_topic.get(source_dir)
        target_area = areas_by_topic.get(target_dir)
        if source_area is None or target_area is None:
            continue
        if source_area.protected or target_area.protected:
            report["skipped_uncertain"].append(
                {
                    "type": "ownership_relation_protected_area",
                    "source_dir": source_dir,
                    "target_dir": target_dir,
                    "source_area": source_area.path,
                    "target_area": target_area.path,
                }
            )
            continue
        concepts = item.get("concepts", [])[:5]
        relations_by_area[source_area.path].append(
            {
                "target_area": target_area.path,
                "target_stem": Path(target_area.path).stem,
                "source_dir": source_dir,
                "target_dir": target_dir,
                "concepts": concepts,
            }
        )
        relations_by_area[target_area.path].append(
            {
                "target_area": source_area.path,
                "target_stem": Path(source_area.path).stem,
                "source_dir": target_dir,
                "target_dir": source_dir,
                "concepts": concepts,
            }
        )

    by_path = {note.path: note for note in notes}
    for area in notes:
        if not area.path.startswith("Areas/") or area.protected or area.path in relations_by_area:
            continue
        text = area.abs_path.read_text(encoding="utf-8", errors="replace")
        if ownership_relations_span(text) is not None:
            relations_by_area[area.path] = []

    for area_rel, relations in sorted(relations_by_area.items()):
        area = by_path[area_rel]
        text = area.abs_path.read_text(encoding="utf-8")
        new_text = upsert_ownership_relations_section(text, render_ownership_relations(relations))
        if new_text == text:
            continue
        area.abs_path.write_text(new_text, encoding="utf-8")
        applied.append({"area": area_rel, "relation_count": len(relations)})


def apply_ownership_area_creations(vault: Path, report: dict, date: str) -> None:
    protected = set(report.get("protected_paths", []))
    notes, _by_name, _file_stems, _attachment_targets = build_index(vault, report["scope"], protected)
    by_path = {note.path: note for note in notes}
    applied = report["applied"].setdefault("ownership_areas", [])
    for item in report.get("understanding", {}).get("ownership_area_candidates", []):
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_area_creation", **item})
            continue
        target_rel = item["target"]
        target_path = vault / target_rel
        if target_path.exists():
            report["skipped_uncertain"].append(
                {"type": "ownership_area_destination_exists", **item}
            )
            continue

        material_notes: list[Note] = []
        missing_or_protected = False
        for material_rel in item.get("material_notes", []):
            note = by_path.get(material_rel)
            if note is None:
                missing_or_protected = True
                report["skipped_uncertain"].append(
                    {"type": "ownership_area_missing_material", "path": material_rel, **item}
                )
                continue
            if note.protected:
                missing_or_protected = True
                report["skipped_uncertain"].append(
                    {"type": "ownership_area_protected_material", "path": material_rel, **item}
                )
                continue
            material_notes.append(note)
        if missing_or_protected:
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            render_created_area(
                item["topic"],
                item["topic_dir"],
                item.get("concepts", []),
                item.get("material_notes", []),
                date,
            ),
            encoding="utf-8",
        )

        target_stem = Path(target_rel).stem
        for note in material_notes:
            text = note.abs_path.read_text(encoding="utf-8")
            bullet = f"- [[{target_stem}]]（自动承接：稳定主题 `{item['topic_dir']}`）"
            new_text = upsert_section_bullet(text, "关联", bullet)
            if new_text != text:
                note.abs_path.write_text(new_text, encoding="utf-8")

        applied.append(
            {
                "topic_dir": item["topic_dir"],
                "target": target_rel,
                "material_count": item["material_count"],
                "concepts": item.get("concepts", []),
            }
        )


def apply_ownership_area_profile_updates(vault: Path, report: dict) -> None:
    protected = set(report.get("protected_paths", []))
    notes, _by_name, _file_stems, _attachment_targets = build_index(vault, report["scope"], protected)
    by_path = {note.path: note for note in notes}
    applied = report["applied"].setdefault("ownership_area_profiles", [])
    for item in report.get("understanding", {}).get("ownership_area_profile_gaps", []):
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_area_profile_gap", **item})
            continue
        area = by_path.get(item["area"])
        if area is None:
            report["skipped_uncertain"].append({"type": "ownership_area_profile_missing_area", **item})
            continue
        area_text = area.abs_path.read_text(encoding="utf-8")
        new_area_text = upsert_understanding_profile_section(area_text, item["expected_profile"])
        new_area_text = upsert_area_scope_concepts(
            new_area_text,
            item.get("expected_scope_concepts", ""),
        )
        new_area_text = upsert_ownership_index_section(new_area_text, item["expected_index"])
        if new_area_text != area_text:
            area.abs_path.write_text(new_area_text, encoding="utf-8")

        reverse_updates = 0
        for material_rel in item.get("missing_reverse_links", []):
            note = by_path.get(material_rel)
            if note is None:
                report["skipped_uncertain"].append(
                    {"type": "ownership_area_profile_missing_material", "path": material_rel, **item}
                )
                continue
            if note.protected:
                report["skipped_uncertain"].append(
                    {"type": "ownership_area_profile_protected_material", "path": material_rel, **item}
                )
                continue
            text = note.abs_path.read_text(encoding="utf-8")
            bullet = f"- [[{Path(item['area']).stem}]]（自动承接：稳定主题 `{item['topic_dir']}`）"
            new_text = upsert_section_bullet(text, "关联", bullet)
            if new_text != text:
                note.abs_path.write_text(new_text, encoding="utf-8")
                reverse_updates += 1

        item["applied_status"] = "updated"
        applied.append(
            {
                "area": item["area"],
                "topic_dir": item["topic_dir"],
                "material_count": item["material_count"],
                "status": "updated",
                "reverse_updates": reverse_updates,
            }
        )


def apply_ownership_structure(vault: Path, report: dict, date: str) -> None:
    protected = set(report.get("protected_paths", []))
    notes, _by_name, _file_stems, _attachment_targets = build_index(vault, report["scope"], protected)
    by_path = {note.path: note for note in notes}
    applied = report["applied"].setdefault("ownership_structure", [])
    for item in report.get("understanding", {}).get("ownership_structure_candidates", []):
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_structure", **item})
            continue
        source = by_path.get(item["source"])
        canonical = by_path.get(item["canonical"])
        if source is None or canonical is None:
            report["skipped_uncertain"].append({"type": "ownership_structure_missing_note", **item})
            continue

        source_stem = Path(item["source"]).stem
        canonical_stem = Path(item["canonical"]).stem
        blocked = False
        for link_source in item.get("link_sources", []):
            note = by_path.get(link_source)
            if note is None:
                continue
            if note.protected:
                blocked = True
                report["skipped_uncertain"].append(
                    {"type": "ownership_structure_protected_link_source", "path": link_source, **item}
                )
                continue
            text = note.abs_path.read_text(encoding="utf-8")
            new_text = replace_wikilink(text, source_stem, canonical_stem)
            if new_text != text:
                note.abs_path.write_text(new_text, encoding="utf-8")
        if blocked:
            continue

        target = item["target"]
        ok, error = git_mv_checked(vault, item["source"], target)
        if not ok:
            report["skipped_uncertain"].append({"type": "ownership_structure_git_mv_failed", "error": error, **item})
            continue

        archived_path = vault / target
        archived_text = archived_path.read_text(encoding="utf-8")
        archived_path.write_text(
            add_ownership_duplicate_marker(archived_text, canonical_stem, item.get("matched", []), date),
            encoding="utf-8",
        )
        canonical_text = canonical.abs_path.read_text(encoding="utf-8")
        canonical.abs_path.write_text(append_canonical_record(canonical_text, Path(target).stem), encoding="utf-8")

        applied.append(
            {
                "source": item["source"],
                "target": target,
                "canonical": item["canonical"],
                "kind": item["kind"],
                "matched": item.get("matched", []),
            }
        )


def apply_ownership_splits(vault: Path, report: dict, date: str) -> None:
    protected = set(report.get("protected_paths", []))
    notes, _by_name, _file_stems, _attachment_targets = build_index(vault, report["scope"], protected)
    by_path = {note.path: note for note in notes}
    applied = report["applied"].setdefault("ownership_splits", [])
    for item in report.get("understanding", {}).get("ownership_split_candidates", []):
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_split", **item})
            continue
        parent = by_path.get(item["parent"])
        if parent is None:
            report["skipped_uncertain"].append({"type": "ownership_split_missing_parent", **item})
            continue
        target_rel = item["target"]
        target_path = vault / target_rel
        if target_path.exists():
            report["skipped_uncertain"].append({"type": "ownership_split_destination_exists", **item})
            continue

        material_notes: list[Note] = []
        blocked = False
        for material_rel in item.get("material_notes", []):
            note = by_path.get(material_rel)
            if note is None:
                blocked = True
                report["skipped_uncertain"].append(
                    {"type": "ownership_split_missing_material", "path": material_rel, **item}
                )
                continue
            if note.protected:
                blocked = True
                report["skipped_uncertain"].append(
                    {"type": "ownership_split_protected_material", "path": material_rel, **item}
                )
                continue
            material_notes.append(note)
        if blocked:
            continue

        target_title = Path(target_rel).stem
        parent_stem = Path(parent.path).stem
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            render_child_area(
                target_title,
                parent_stem,
                item["topic_dir"],
                item["concept"],
                item.get("material_notes", []),
                date,
            ),
            encoding="utf-8",
        )

        parent_text = parent.abs_path.read_text(encoding="utf-8")
        parent_bullet = f"- [[{target_title}]]（自动分化：`{item['topic_dir']}` / {item['concept']}）"
        new_parent_text = upsert_section_bullet(parent_text, "子承接", parent_bullet)
        if new_parent_text != parent_text:
            parent.abs_path.write_text(new_parent_text, encoding="utf-8")

        for note in material_notes:
            text = note.abs_path.read_text(encoding="utf-8")
            bullet = f"- [[{target_title}]]（自动分化：`{item['topic_dir']}` / {item['concept']}）"
            new_text = upsert_section_bullet(text, "关联", bullet)
            if new_text != text:
                note.abs_path.write_text(new_text, encoding="utf-8")

        applied.append(
            {
                "parent": item["parent"],
                "target": target_rel,
                "topic_dir": item["topic_dir"],
                "concept": item["concept"],
                "material_count": item["material_count"],
            }
        )


def apply_duplicates(vault: Path, notes: list[Note], report: dict, date: str) -> None:
    by_path = {note.path: note for note in notes}
    for group in report["duplicates"]:
        canonical = by_path[group["canonical"]]
        if canonical.protected:
            report["skipped_uncertain"].append({"type": "protected_canonical", "path": canonical.path})
            continue
        canonical_title = canonical.title
        for duplicate_path in group["duplicates"]:
            duplicate = by_path[duplicate_path]
            if duplicate.protected:
                report["skipped_uncertain"].append({"type": "protected_duplicate", "path": duplicate.path})
                continue
            if duplicate.path.startswith("Archive/Duplicates/"):
                target_rel = duplicate.path
            else:
                target_rel = "Archive/Duplicates/" + Path(duplicate.path).name
                counter = 2
                while (vault / target_rel).exists():
                    stem = Path(duplicate.path).stem
                    suffix = Path(duplicate.path).suffix
                    target_rel = f"Archive/Duplicates/{stem}-{counter}{suffix}"
                    counter += 1
                ensure_parent(vault / target_rel)
                completed = run_git(vault, ["mv", duplicate.path, target_rel])
                if completed.returncode != 0:
                    report["skipped_uncertain"].append({"type": "git_mv_failed", "path": duplicate.path, "stderr": completed.stderr.strip()})
                    continue
                duplicate.abs_path = vault / target_rel
                duplicate.path = target_rel
            text = duplicate.abs_path.read_text(encoding="utf-8")
            duplicate.abs_path.write_text(add_duplicate_marker(text, canonical_title, group["evidence"], date), encoding="utf-8")
            ctext = canonical.abs_path.read_text(encoding="utf-8")
            canonical.abs_path.write_text(append_canonical_record(ctext, Path(target_rel).stem), encoding="utf-8")
            report["applied"]["duplicates"].append({"canonical": canonical.path, "duplicate": target_rel, "evidence": group["evidence"]})


def apply_broken_links(vault: Path, notes: list[Note], report: dict) -> None:
    by_path = {note.path: note for note in notes}
    for item in report["broken_links"]:
        if item["status"] != "unique":
            continue
        note = by_path[item["source"]]
        if note.protected:
            report["skipped_uncertain"].append({"type": "protected_broken_link", "path": note.path})
            continue
        target_path = item["matches"][0]
        # Use filename stem (Obsidian resolves wikilinks by filename, not title)
        target_stem = Path(target_path).stem
        text = note.abs_path.read_text(encoding="utf-8")
        new_text = replace_wikilink(text, item["link"], target_stem)
        if new_text != text:
            note.abs_path.write_text(new_text, encoding="utf-8")
            report["applied"]["broken_links"].append({"source": note.path, "old": item["link"], "new": target_stem})


def apply_empty_stubs(vault: Path, report: dict) -> None:
    """Delete 0-byte Obsidian stub files and fix the wikilinks that caused them.

    For each fixable stub (has referencing wikilinks AND a suggested real target):
    1. Fix all wikilinks that point to the stub → point to the real note's filename stem
    2. Delete the stub file (via git rm --cached + rm, or just rm for untracked)

    Stubs with no suggested target (orphan_stub / unmatched) are only reported,
    not auto-deleted — manual review is needed to find the correct target.
    """
    for item in report.get("empty_stubs", []):
        if item["status"] != "fixable":
            report["skipped_uncertain"].append({"type": "unfixable_stub", **item})
            continue

        stub_path = vault / item["stub"]
        # Fix referencing wikilinks first
        target_path = item["suggested_target"]
        unresolved_references = False
        if target_path:
            # Find the source notes and fix their wikilinks
            for ref in item["references"]:
                source_note_path = vault / ref["source"]
                if not source_note_path.exists():
                    unresolved_references = True
                    report["skipped_uncertain"].append(
                        {"type": "missing_stub_reference", "stub": item["stub"], "source": ref["source"]}
                    )
                    continue
                # Check if protected
                if ref["source"] in set(report.get("protected_paths", [])):
                    unresolved_references = True
                    report["skipped_uncertain"].append(
                        {"type": "protected_stub_reference", "stub": item["stub"], "source": ref["source"]}
                    )
                    continue
                text = source_note_path.read_text(encoding="utf-8")
                new_text = replace_wikilink(text, ref["link"], Path(target_path).stem)
                if new_text != text:
                    source_note_path.write_text(new_text, encoding="utf-8")
                elif expected_markdown_stub_path(ref["link"]) == normalize_relpath(item["stub"]):
                    unresolved_references = True
                    report["skipped_uncertain"].append(
                        {"type": "unchanged_stub_reference", "stub": item["stub"], "source": ref["source"]}
                    )

        if unresolved_references:
            continue

        # Delete the stub file
        if stub_path.exists():
            # Check git tracking
            completed = run_git(vault, ["ls-files", "--error-unmatch", item["stub"]])
            if completed.returncode == 0:
                # Tracked — use git rm
                run_git(vault, ["rm", "-f", item["stub"]])
            else:
                # Untracked — just remove
                stub_path.unlink()

        report["applied"]["empty_stubs"].append(
            {"stub": item["stub"], "target": Path(target_path).stem if target_path else None}
        )


def append_log(vault: Path, report: dict, date: str) -> None:
    log_path = vault / ".claude" / "meditate.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"## {date} manual\n"
        f"- 范围：{', '.join(report['scope'])}\n"
        f"- 完全重复：{len(report['duplicates'])}\n"
        f"- 疑似重复：0\n"
        f"- 补链：{len(report['applied'].get('understanding_links', []))}\n"
        f"- 修复失效链接：{len(report['applied']['broken_links'])}\n"
        f"- 清理空残骸：{len(report['applied']['empty_stubs'])}\n"
        f"- 元数据补全：{len(report['applied']['metadata'])}\n"
        f"- 原文附件规范化：{len(report['applied'].get('source_files', []))}\n"
        f"- frontmatter 值非法：{len(report.get('invalid_frontmatter', []))}\n"
        f"- 结构建议：{len(report['orphan_notes']) + len(report.get('topic_index_gaps', []))}\n"
        f"- 主题索引：{len(report['applied'].get('topic_indexes', []))}\n"
        f"- 结构迁移：{len(report['applied'].get('structural_moves', []))}\n"
        f"- 概念画像：{len(report['applied'].get('understanding_profiles', []))}\n"
        f"- 主题关联：{len(report['applied'].get('topic_relations', []))}\n"
        f"- 新建承接：{len(report['applied'].get('ownership_areas', []))}\n"
        f"- 承接关联：{len(report['applied'].get('ownership_relations', []))}\n"
        f"- 承接刷新：{len(report['applied'].get('ownership_area_profiles', []))}\n"
        f"- 承接重构：{len(report['applied'].get('ownership_structure', []))}\n"
        f"- 承接分化：{len(report['applied'].get('ownership_splits', []))}\n"
        "commit: 无\n"
    )
    old = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    log_path.write_text(old + ("\n" if old and not old.endswith("\n") else "") + entry, encoding="utf-8")


def finalize_latest_log_commit(vault: Path, commit_hash: str) -> None:
    if not COMMIT_HASH_RE.fullmatch(commit_hash):
        raise ValueError("commit hash must be a 40-character lowercase hex SHA")
    log_path = vault / ".claude" / "meditate.log"
    if not log_path.exists():
        raise ValueError(".claude/meditate.log does not exist")
    lines = log_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == "commit: 无":
            newline = "\n" if lines[index].endswith("\n") else ""
            lines[index] = f"commit: {commit_hash}{newline}"
            log_path.write_text("".join(lines), encoding="utf-8")
            return
    raise ValueError("latest meditate log has no commit: 无 placeholder")


def append_skipped_once(report: dict, item: dict) -> None:
    if item not in report["skipped_uncertain"]:
        report["skipped_uncertain"].append(item)


def build_report(vault: Path, scopes: list[str]) -> dict:
    protected = protected_paths(vault)
    notes, by_name, file_stems, attachment_targets = build_index(vault, scopes, protected)
    safety_notes = structural_safety_notes(vault, scopes, protected, notes)
    empty_stub_findings = empty_stubs(vault, notes, by_name)
    topic_index_findings = topic_index_gaps(vault, scopes, protected)
    understanding_candidates = understanding_link_candidates(notes)
    structure_candidates = structural_reunderstanding_candidates(vault, notes, protected, safety_notes)
    split_decisions = resource_topic_split_decisions(notes)
    profile_findings = understanding_profile_gaps(vault, notes, protected)
    ownership_area_findings = ownership_area_candidates(vault, notes, protected)
    ownership_area_profile_findings = ownership_area_profile_gaps(vault, notes, protected)
    ownership_structure_findings = ownership_structure_candidates(vault, notes, protected)
    ownership_split_findings = ownership_split_candidates(vault, notes, protected)
    topic_profiles = topic_understanding_profiles(notes)
    topic_relation_findings = topic_relation_candidates(notes)
    owner_profiles = ownership_understanding_profiles(notes)
    report = {
        "scope": scopes,
        "coverage": coverage(notes),
        "protected_paths": sorted(protected),
        "duplicates": duplicate_groups(notes),
        "broken_links": broken_links(notes, by_name, file_stems, attachment_targets),
        "empty_stubs": empty_stub_findings,
        "source_file_anomalies": source_file_anomalies(vault, scopes, notes, protected),
        "metadata_missing": metadata_missing(notes),
        "orphan_notes": orphan_notes(notes),
        "topic_index_gaps": topic_index_findings,
        "understanding_profile_gaps": profile_findings,
        "invalid_fingerprints": invalid_fingerprints(notes),
        "invalid_frontmatter": invalid_frontmatter_list(notes),
        "understanding": {
            "link_candidates": understanding_candidates,
            "structure_candidates": structure_candidates,
            "resource_topic_split_decisions": split_decisions,
            "ownership_area_candidates": ownership_area_findings,
            "ownership_area_profile_gaps": ownership_area_profile_findings,
            "ownership_structure_candidates": ownership_structure_findings,
            "ownership_split_candidates": ownership_split_findings,
            "topic_profiles": topic_profiles,
            "topic_relation_candidates": topic_relation_findings,
            "ownership_profiles": owner_profiles,
        },
        "applied": {
            "duplicates": [],
            "metadata": [],
            "broken_links": [],
            "empty_stubs": [],
            "source_files": [],
            "topic_indexes": [],
            "understanding_links": [],
            "structural_moves": [],
            "understanding_profiles": [],
            "topic_relations": [],
            "ownership_areas": [],
            "ownership_relations": [],
            "ownership_area_profiles": [],
            "ownership_structure": [],
            "ownership_splits": [],
        },
        "report_only": {
            "suspected_duplicates": [],
            "structure_suggestions": [],
            "unmatched_source_files": [],
            "topic_index_gaps": topic_index_findings,
            "understanding_profile_gaps": profile_findings,
            "understanding_link_candidates": understanding_candidates,
            "structure_candidates": structure_candidates,
            "resource_topic_split_decisions": split_decisions,
            "ownership_area_candidates": ownership_area_findings,
            "ownership_area_profile_gaps": ownership_area_profile_findings,
            "ownership_structure_candidates": ownership_structure_findings,
            "ownership_split_candidates": ownership_split_findings,
            "topic_relation_candidates": topic_relation_findings,
        },
        "skipped_uncertain": [],
        "verification": {},
    }
    for item in report["broken_links"]:
        if item["status"] != "unique":
            report["skipped_uncertain"].append({"type": "ambiguous_broken_link", **item})
    for item in report["invalid_fingerprints"]:
        report["skipped_uncertain"].append({"type": "stale_or_invalid_fingerprint", **item})
    for item in report["invalid_frontmatter"]:
        report["skipped_uncertain"].append({"type": "invalid_frontmatter_value", **item})
    for item in report["source_file_anomalies"]:
        if item["status"] != "fixable":
            report["skipped_uncertain"].append({"type": "source_file_policy", **item})
    for item in report["understanding"]["structure_candidates"]:
        if not item.get("fixable"):
            append_skipped_once(report, {"type": "structural_reunderstanding", **item})
    for item in report["understanding_profile_gaps"]:
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "understanding_profile_gap", **item})
    for item in report["understanding"]["ownership_area_candidates"]:
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_area_creation", **item})
    for item in report["understanding"]["ownership_area_profile_gaps"]:
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_area_profile_gap", **item})
    for item in report["understanding"]["ownership_structure_candidates"]:
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_structure", **item})
    for item in report["understanding"]["ownership_split_candidates"]:
        if not item.get("fixable"):
            report["skipped_uncertain"].append({"type": "ownership_split", **item})
    return report


def refresh_report_findings(vault: Path, report: dict, include_structure: bool = True) -> tuple[list[Note], dict[str, list[Note]], set[str], set[str]]:
    protected = set(report.get("protected_paths", []))
    notes, by_name, file_stems, attachment_targets = build_index(vault, report["scope"], protected)
    safety_notes = structural_safety_notes(vault, report["scope"], protected, notes)
    report["duplicates"] = duplicate_groups(notes)
    report["broken_links"] = broken_links(notes, by_name, file_stems, attachment_targets)
    report["empty_stubs"] = empty_stubs(vault, notes, by_name)
    report["source_file_anomalies"] = source_file_anomalies(vault, report["scope"], notes, protected)
    report["metadata_missing"] = metadata_missing(notes)
    report["orphan_notes"] = orphan_notes(notes)
    report["topic_index_gaps"] = topic_index_gaps(vault, report["scope"], protected)
    report["understanding_profile_gaps"] = understanding_profile_gaps(vault, notes, protected)
    report["invalid_fingerprints"] = invalid_fingerprints(notes)
    report["invalid_frontmatter"] = invalid_frontmatter_list(notes)
    report["understanding"]["link_candidates"] = understanding_link_candidates(notes)
    report["understanding"]["resource_topic_split_decisions"] = resource_topic_split_decisions(notes)
    report["understanding"]["ownership_area_candidates"] = ownership_area_candidates(vault, notes, protected)
    report["understanding"]["ownership_area_profile_gaps"] = ownership_area_profile_gaps(vault, notes, protected)
    report["understanding"]["ownership_structure_candidates"] = ownership_structure_candidates(vault, notes, protected)
    report["understanding"]["ownership_split_candidates"] = ownership_split_candidates(vault, notes, protected)
    report["understanding"]["topic_profiles"] = topic_understanding_profiles(notes)
    report["understanding"]["topic_relation_candidates"] = topic_relation_candidates(notes)
    report["understanding"]["ownership_profiles"] = ownership_understanding_profiles(notes)
    if include_structure:
        report["understanding"]["structure_candidates"] = structural_reunderstanding_candidates(
            vault,
            notes,
            protected,
            safety_notes,
        )
    report["report_only"]["topic_index_gaps"] = report["topic_index_gaps"]
    report["report_only"]["understanding_profile_gaps"] = report["understanding_profile_gaps"]
    report["report_only"]["understanding_link_candidates"] = report["understanding"]["link_candidates"]
    report["report_only"]["structure_candidates"] = report["understanding"].get("structure_candidates", [])
    report["report_only"]["resource_topic_split_decisions"] = report["understanding"]["resource_topic_split_decisions"]
    report["report_only"]["ownership_area_candidates"] = report["understanding"]["ownership_area_candidates"]
    report["report_only"]["ownership_area_profile_gaps"] = report["understanding"]["ownership_area_profile_gaps"]
    report["report_only"]["ownership_structure_candidates"] = report["understanding"]["ownership_structure_candidates"]
    report["report_only"]["ownership_split_candidates"] = report["understanding"]["ownership_split_candidates"]
    report["report_only"]["topic_relation_candidates"] = report["understanding"]["topic_relation_candidates"]
    for item in report["broken_links"]:
        if item["status"] != "unique":
            skipped = {"type": "ambiguous_broken_link", **item}
            if skipped not in report["skipped_uncertain"]:
                report["skipped_uncertain"].append(skipped)
    for item in report["source_file_anomalies"]:
        if item["status"] != "fixable":
            skipped = {"type": "source_file_policy", **item}
            if skipped not in report["skipped_uncertain"]:
                report["skipped_uncertain"].append(skipped)
    for item in report["understanding_profile_gaps"]:
        if not item.get("fixable"):
            skipped = {"type": "understanding_profile_gap", **item}
            if skipped not in report["skipped_uncertain"]:
                report["skipped_uncertain"].append(skipped)
    for item in report["understanding"]["ownership_area_candidates"]:
        if not item.get("fixable"):
            skipped = {"type": "ownership_area_creation", **item}
            if skipped not in report["skipped_uncertain"]:
                report["skipped_uncertain"].append(skipped)
    for item in report["understanding"]["ownership_area_profile_gaps"]:
        if not item.get("fixable"):
            skipped = {"type": "ownership_area_profile_gap", **item}
            if skipped not in report["skipped_uncertain"]:
                report["skipped_uncertain"].append(skipped)
    for item in report["understanding"]["ownership_structure_candidates"]:
        if not item.get("fixable"):
            skipped = {"type": "ownership_structure", **item}
            if skipped not in report["skipped_uncertain"]:
                report["skipped_uncertain"].append(skipped)
    for item in report["understanding"]["ownership_split_candidates"]:
        if not item.get("fixable"):
            skipped = {"type": "ownership_split", **item}
            if skipped not in report["skipped_uncertain"]:
                report["skipped_uncertain"].append(skipped)
    return notes, by_name, file_stems, attachment_targets


def summarize_items(items: list, formatter, limit: int = 8) -> str:
    if not items:
        return "无"
    rendered = [formatter(item) for item in items[:limit]]
    extra = len(items) - limit
    suffix = f"；另有 {extra} 项" if extra > 0 else ""
    return "；".join(rendered) + suffix


def markdown_report(report: dict) -> str:
    coverage_data = report["coverage"]
    duplicate_lines = [
        f"- canonical `{item['canonical']}`；duplicates: {', '.join('`' + p + '`' for p in item['duplicates'])}"
        for item in report["duplicates"]
    ]
    suspected = report["report_only"].get("suspected_duplicates", [])
    skipped = report["skipped_uncertain"]
    uncertain_items = [item for item in skipped if item.get("type") == "ambiguous_broken_link"]
    protected_items = [item for item in skipped if item.get("type", "").startswith("protected_")]
    evidence_items = [item for item in skipped if item.get("type") not in {"ambiguous_broken_link"} and not item.get("type", "").startswith("protected_")]
    uncertain_summary = summarize_items(
        uncertain_items,
        lambda item: f"`{item.get('source')}` 中 `[[{item.get('link')}]]` 无唯一匹配",
    )
    evidence_summary = summarize_items(
        [*protected_items, *evidence_items],
        lambda item: f"{item.get('type')}: `{item.get('path') or item.get('source') or item.get('actual') or item.get('link')}`",
    )
    invalid_count = len(report.get("invalid_fingerprints", []))
    invalid_fm_count = len(report.get("invalid_frontmatter", []))
    empty_stub_lines = [
        f"- `{item['stub']}` → 建议目标 `{item['suggested_target']}`（引用源：{', '.join('`' + r['source'] + '`' for r in item['references'])}）"
        for item in report.get("empty_stubs", [])
        if item["status"] == "fixable"
    ]
    unfixable_stub_lines = [
        f"- `{item['stub']}`（{item['status']}）"
        for item in report.get("empty_stubs", [])
        if item["status"] != "fixable"
    ]
    invalid_fm_lines = [
        f"- `{item['path']}`：{item['detail']}"
        for item in report.get("invalid_frontmatter", [])
    ]
    source_fix_lines = [
        f"- `{item['old']}` → `{item['new']}`；note `{item['note']}`"
        for item in report["applied"].get("source_files", [])
    ]
    topic_index_applied_lines = [
        f"- `{item['topic_dir']}` → `{item['readme']}`（{item['status']}）"
        for item in report["applied"].get("topic_indexes", [])
    ]
    profile_applied_lines = [
        f"- `{item['topic_dir']}` → `{item['readme']}`（{item['status']}）"
        for item in report["applied"].get("understanding_profiles", [])
    ]
    topic_relation_applied_lines = [
        f"- `{item['topic_dir']}` → `{item['readme']}`（{item['relation_count']} 个相关主题）"
        for item in report["applied"].get("topic_relations", [])
    ]
    ownership_area_applied_lines = [
        f"- `{item['topic_dir']}` → `{item['target']}`（{item['material_count']} 篇；{', '.join(item.get('concepts', [])[:4])}）"
        for item in report["applied"].get("ownership_areas", [])
    ]
    ownership_relation_applied_lines = [
        f"- `{item['area']}`（{item['relation_count']} 个相关承接）"
        for item in report["applied"].get("ownership_relations", [])
    ]
    ownership_area_profile_applied_lines = [
        f"- `{item['area']}` ← `{item['topic_dir']}`（{item['material_count']} 篇；{item.get('reverse_updates', 0)} 条回链）"
        for item in report["applied"].get("ownership_area_profiles", [])
    ]
    ownership_structure_applied_lines = [
        f"- `{item['source']}` → `{item['target']}`，canonical `{item['canonical']}`（{', '.join(item.get('matched', []))}）"
        for item in report["applied"].get("ownership_structure", [])
    ]
    ownership_split_applied_lines = [
        f"- `{item['parent']}` → `{item['target']}`（{item['concept']}；{item['material_count']} 篇）"
        for item in report["applied"].get("ownership_splits", [])
    ]
    structural_applied = report["applied"].get("structural_moves", [])
    structural_applied_pairs = {(item["source"], item["target"]) for item in structural_applied}
    structural_applied_lines = [
        f"- `{item['source']}` → `{item['target']}`（{item['kind']}；{', '.join(item.get('matched', []))}）"
        for item in structural_applied
    ]
    structural_candidate_lines = [
        f"- `{item['source']}` → `{item.get('target') or item.get('to_topic')}`（{item.get('status')}；{item.get('reason')}）"
        for item in report.get("understanding", {}).get("structure_candidates", [])
        if (item["source"], item.get("target", "")) not in structural_applied_pairs
    ]
    resource_split_decision_lines = [
        f"- `{item['topic_dir']}`：{item['status']}；{item['reason']}"
        + (f"；→ `{item['to_topic']}`（{item['material_count']} / {item['topic_material_count']} 篇）" if item.get("to_topic") else "")
        for item in report.get("understanding", {}).get("resource_topic_split_decisions", [])
    ]
    understanding_applied = report["applied"].get("understanding_links", [])
    understanding_applied_pairs = {(item["source"], item["target"]) for item in understanding_applied}
    understanding_applied_lines = [
        f"- `{item['source']}` → `[[{Path(item['target']).stem}]]`（{item['kind']}；{item['matched']}）"
        for item in understanding_applied
    ]
    understanding_candidate_lines = [
        f"- `{item['source']}` → `[[{item['target_stem']}]]`（{item['kind']}；{item['reason']}）"
        for item in report.get("understanding", {}).get("link_candidates", [])
        if (item["source"], item["target"]) not in understanding_applied_pairs
    ]
    metadata_pending_lines = [
        f"- `{item['path']}`：{', '.join(item['fields'])}"
        for item in report.get("metadata_missing", [])
        if item["path"] not in {applied["path"] for applied in report["applied"].get("metadata", [])}
    ]
    source_pending_lines = [
        f"- `{item.get('actual')}`（{item.get('status')}）：{item.get('reason')}"
        for item in report.get("source_file_anomalies", [])
        if item.get("status") != "fixable"
    ]
    topic_index_lines = [
        f"- `{item['topic_dir']}`：{item['status']}，{item['reference_count']} 篇 reference，目标 `{item['readme']}`"
        for item in report.get("topic_index_gaps", [])
        if not item.get("applied_status")
    ]
    profile_pending_lines = [
        f"- `{item['topic_dir']}`：{item['status']}，目标 `{item['readme']}`"
        for item in report.get("understanding_profile_gaps", [])
        if not item.get("applied_status")
    ]
    ownership_area_candidate_lines = [
        f"- `{item['topic_dir']}` → `{item['target']}`（{item['status']}；{item['reason']}；{', '.join(item.get('concepts', [])[:4])}）"
        for item in report.get("understanding", {}).get("ownership_area_candidates", [])
        if item["target"] not in {applied["target"] for applied in report["applied"].get("ownership_areas", [])}
    ]
    ownership_area_profile_gap_lines = [
        f"- `{item['area']}` ← `{item['topic_dir']}`（{item['status']}；{item['reason']}；{item['material_count']} 篇）"
        for item in report.get("understanding", {}).get("ownership_area_profile_gaps", [])
        if not item.get("applied_status")
    ]
    ownership_structure_candidate_lines = [
        f"- `{item['source']}` → `{item['target']}`，canonical `{item['canonical']}`（{item['status']}；{item['reason']}）"
        for item in report.get("understanding", {}).get("ownership_structure_candidates", [])
        if (item["source"], item["target"]) not in {
            (applied["source"], applied["target"])
            for applied in report["applied"].get("ownership_structure", [])
        }
    ]
    ownership_split_candidate_lines = [
        f"- `{item['parent']}` → `{item.get('target') or item.get('concept')}`（{item['status']}；{item['reason']}；{item['material_count']} 篇）"
        for item in report.get("understanding", {}).get("ownership_split_candidates", [])
        if item.get("target") not in {applied["target"] for applied in report["applied"].get("ownership_splits", [])}
    ]
    topic_profile_lines = [
        f"- `{item['topic_dir']}`：{', '.join(item.get('concepts', [])[:6]) or '待积累'}"
        for item in report.get("understanding", {}).get("topic_profiles", [])[:8]
    ]
    topic_relation_lines = [
        f"- `{item['source_dir']}` ↔ `{item['target_dir']}`（{', '.join(item.get('concepts', [])[:5])}）"
        for item in report.get("understanding", {}).get("topic_relation_candidates", [])
        if not item.get("applied_status")
    ]
    ownership_profile_lines = [
        f"- `{item['path']}`：{', '.join(item.get('concepts', [])[:6]) or '待积累'}"
        for item in report.get("understanding", {}).get("ownership_profiles", [])[:8]
    ]
    residual_broken_link_lines = [
        f"- `{item['source']}` 中 `[[{item['link']}]]` → {', '.join('`' + path + '`' for path in item.get('matches', [])) or '无候选'}"
        for item in report.get("verification", {}).get("residual_broken_links", [])
    ]
    lines = [
        "## 范围与扫描结果",
        f"- 范围：{', '.join(report['scope'])}",
        f"- 扫描：{coverage_data['markdown_count']} 篇 Markdown；目录分布 {coverage_data['distribution']}；来源 URL 覆盖 {coverage_data['source_url_or_canonical']}；源指纹覆盖 {coverage_data['source_fingerprint']}；指纹不一致 {invalid_count}；frontmatter 值非法 {invalid_fm_count}",
        "",
        "## 已自动处理",
        f"- 重复归档：{len(report['applied']['duplicates']) or '无'}",
        "- 补链：" + ("\n" + "\n".join(understanding_applied_lines) if understanding_applied_lines else "无"),
        f"- 元数据补全：{len(report['applied']['metadata']) or '无'}",
        "- 原文附件规范化：" + ("\n" + "\n".join(source_fix_lines) if source_fix_lines else "无"),
        f"- 失效链接修复：{len(report['applied']['broken_links']) or '无'}",
        "- 空残骸清理：" + ("\n" + "\n".join(empty_stub_lines) if empty_stub_lines else "无"),
        "- 主题索引：" + ("\n" + "\n".join(topic_index_applied_lines) if topic_index_applied_lines else "无"),
        "- 概念画像：" + ("\n" + "\n".join(profile_applied_lines) if profile_applied_lines else "无"),
        "- 主题关联：" + ("\n" + "\n".join(topic_relation_applied_lines) if topic_relation_applied_lines else "无"),
        "- 新建承接 Area：" + ("\n" + "\n".join(ownership_area_applied_lines) if ownership_area_applied_lines else "无"),
        "- 关联承接 Area：" + ("\n" + "\n".join(ownership_relation_applied_lines) if ownership_relation_applied_lines else "无"),
        "- 刷新承接 Area：" + ("\n" + "\n".join(ownership_area_profile_applied_lines) if ownership_area_profile_applied_lines else "无"),
        "- 重构承接 Area：" + ("\n" + "\n".join(ownership_structure_applied_lines) if ownership_structure_applied_lines else "无"),
        "- 分化承接 Area：" + ("\n" + "\n".join(ownership_split_applied_lines) if ownership_split_applied_lines else "无"),
        "- 结构迁移：" + ("\n" + "\n".join(structural_applied_lines) if structural_applied_lines else "无"),
        "",
        "## 只报告，未自动处理",
        "- 完全重复候选：" + ("；".join(duplicate_lines) if duplicate_lines else "无"),
        f"- 疑似重复：{len(suspected) if suspected else '无'}",
        f"- 孤岛笔记：{len(report['orphan_notes']) if report['orphan_notes'] else '无'}",
        "- 重新理解补链候选：" + ("\n" + "\n".join(understanding_candidate_lines) if understanding_candidate_lines else "无"),
        "- 重新理解结构候选：" + ("\n" + "\n".join(structural_candidate_lines) if structural_candidate_lines else "无"),
        "- Resource topic 拆分判断：" + ("\n" + "\n".join(resource_split_decision_lines) if resource_split_decision_lines else "无"),
        "- Resource topic 关联候选：" + ("\n" + "\n".join(topic_relation_lines) if topic_relation_lines else "无"),
        "- 当前主题画像：" + ("\n" + "\n".join(topic_profile_lines) if topic_profile_lines else "无"),
        "- 当前承接画像：" + ("\n" + "\n".join(ownership_profile_lines) if ownership_profile_lines else "无"),
        "- 待补元数据：" + ("\n" + "\n".join(metadata_pending_lines) if metadata_pending_lines else "无"),
        "- 新建 / 更新主题索引：" + ("\n" + "\n".join(topic_index_lines) if topic_index_lines else "无"),
        "- 新建 / 更新概念画像：" + ("\n" + "\n".join(profile_pending_lines) if profile_pending_lines else "无"),
        "- 新建承接 Area 候选：" + ("\n" + "\n".join(ownership_area_candidate_lines) if ownership_area_candidate_lines else "无"),
        "- 刷新承接 Area 候选：" + ("\n" + "\n".join(ownership_area_profile_gap_lines) if ownership_area_profile_gap_lines else "无"),
        "- 重构承接 Area 候选：" + ("\n" + "\n".join(ownership_structure_candidate_lines) if ownership_structure_candidate_lines else "无"),
        "- 分化承接 Area 候选：" + ("\n" + "\n".join(ownership_split_candidate_lines) if ownership_split_candidate_lines else "无"),
        "- 原文附件异常：" + ("\n" + "\n".join(source_pending_lines) if source_pending_lines else "无"),
        "- frontmatter 值非法（Obsidian 属性会失效，需给含 `: ` 的 value 加引号）：" + ("\n" + "\n".join(invalid_fm_lines) if invalid_fm_lines else "无"),
        "",
        "## 跳过 / 不确定",
        "- protected paths：" + (", ".join(f"`{p}`" for p in report["protected_paths"]) if report["protected_paths"] else "无"),
        "- 不确定匹配：" + uncertain_summary,
        "- 证据不足：" + evidence_summary,
        "- 无法修复的空残骸：" + ("\n" + "\n".join(unfixable_stub_lines) if unfixable_stub_lines else "无"),
        "",
        "## 验证结果",
        f"- git status：{report['verification'].get('git_status', '未检查')}",
        f"- 自检：{report['verification'].get('self_check', '未检查')}",
        "- 残留结构断链：" + ("\n" + "\n".join(residual_broken_link_lines) if residual_broken_link_lines else "无"),
        "- commit：无",
        "",
    ]
    return "\n".join(lines)


def safe_self_check(vault: Path, report: dict) -> None:
    status = run_git(vault, ["status", "--short"])
    report["verification"]["git_status"] = status.stdout.strip() or "clean"
    allowed_deleted = {item["stub"] for item in report["applied"].get("empty_stubs", [])}
    bad_delete = False
    for line in status.stdout.splitlines():
        if not (line.startswith(" D") or line.startswith("D ")):
            continue
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        raw = raw.strip('"')
        if raw not in allowed_deleted:
            bad_delete = True
            break
    duplicate_missing = False
    for item in report["applied"]["duplicates"]:
        if not (vault / item["duplicate"]).exists():
            duplicate_missing = True
            break
    stub_not_deleted = False
    for item in report["applied"]["empty_stubs"]:
        if (vault / item["stub"]).exists():
            stub_not_deleted = True
            break
    source_missing = False
    for item in report["applied"].get("source_files", []):
        if not (vault / item["new"]).exists():
            source_missing = True
            break
    topic_index_missing = False
    for item in report["applied"].get("topic_indexes", []):
        if not (vault / item["readme"]).exists():
            topic_index_missing = True
            break
    profile_missing = False
    for item in report["applied"].get("understanding_profiles", []):
        if not (vault / item["readme"]).exists():
            profile_missing = True
            break
    topic_relation_missing = False
    for item in report["applied"].get("topic_relations", []):
        if not (vault / item["readme"]).exists():
            topic_relation_missing = True
            break
    ownership_area_missing = False
    for item in report["applied"].get("ownership_areas", []):
        if not (vault / item["target"]).exists():
            ownership_area_missing = True
            break
    ownership_relation_missing = False
    for item in report["applied"].get("ownership_relations", []):
        if not (vault / item["area"]).exists():
            ownership_relation_missing = True
            break
    ownership_area_profile_missing = False
    for item in report["applied"].get("ownership_area_profiles", []):
        if not (vault / item["area"]).exists():
            ownership_area_profile_missing = True
            break
    ownership_structure_missing = False
    for item in report["applied"].get("ownership_structure", []):
        if not (vault / item["target"]).exists():
            ownership_structure_missing = True
            break
        if (vault / item["source"]).exists():
            ownership_structure_missing = True
            break
    ownership_split_missing = False
    for item in report["applied"].get("ownership_splits", []):
        if not (vault / item["target"]).exists():
            ownership_split_missing = True
            break
    structural_missing = False
    for item in report["applied"].get("structural_moves", []):
        if not (vault / item["target"]).exists():
            structural_missing = True
            break
        for source_move in item.get("source_moves", []):
            if not (vault / source_move["new"]).exists():
                structural_missing = True
                break
        if structural_missing:
            break
    residual_broken_links: list[dict] = []
    structural_old_paths = {
        normalize_relpath(item["source"])
        for item in report["applied"].get("structural_moves", [])
        if item.get("source")
    }
    if structural_old_paths:
        protected = set(report.get("protected_paths", []))
        notes, by_name, file_stems, attachment_targets = build_index(
            vault,
            report.get("scope", DEFAULT_SCOPES),
            protected,
        )
        for item in broken_links(notes, by_name, file_stems, attachment_targets):
            link_paths = set(markdown_link_path_candidates(item["link"]))
            if structural_old_paths & link_paths:
                residual_broken_links.append(item)
    report["verification"]["residual_broken_links"] = residual_broken_links
    report["verification"]["self_check"] = (
        "通过"
        if not bad_delete
        and not duplicate_missing
        and not stub_not_deleted
        and not source_missing
        and not topic_index_missing
        and not profile_missing
        and not topic_relation_missing
        and not ownership_area_missing
        and not ownership_relation_missing
        and not ownership_area_profile_missing
        and not ownership_structure_missing
        and not ownership_split_missing
        and not structural_missing
        and not residual_broken_links
        else "未通过"
    )


def checked_report_path(raw: str, expected: Path, label: str) -> Path:
    out = Path(raw).resolve()
    if out != expected:
        raise ValueError(f"{label} report path must be /tmp/{expected.name}")
    if out.exists() and out.is_symlink():
        raise ValueError(f"{label} report path must not be a symlink")
    return out


def write_report_file(path: Path, content: str) -> None:
    if path.parent != FIXED_REPORT_DIR:
        raise ValueError("report parent must be /tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f"failed to open report path safely: {exc}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(content)


def write_outputs(report: dict, json_path: Path | None, markdown_path: Path | None) -> None:
    if json_path:
        write_report_file(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if markdown_path:
        write_report_file(markdown_path, markdown_report(report))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Scan or safely optimize a brain vault.")
    parser.add_argument("--vault", default=".", help="Vault root, defaults to current directory")
    parser.add_argument("--scope", action="append", help="Scope directory relative to vault; repeatable")
    parser.add_argument("--mode", choices=("scan", "apply-safe", "finalize-log"), default="scan")
    parser.add_argument("--json", dest="json_path", help="Write JSON report to this path")
    parser.add_argument("--markdown", dest="markdown_path", help="Write Markdown report to this path")
    parser.add_argument("--date", default="", help="Date string for markers/logs, e.g. 2026-06-29")
    parser.add_argument("--no-log", action="store_true", help="Do not append .claude/meditate.log in apply-safe mode")
    parser.add_argument("--commit", dest="commit_hash", help="Finalize the latest meditate log entry with this commit hash")
    parser.add_argument("--progress", action="store_true", help="Write apply-safe stage progress to stderr")
    args = parser.parse_args(argv)

    vault = Path(args.vault).resolve()
    cwd = Path.cwd().resolve()
    if vault != cwd:
        return fail("--vault override is not allowed; run from the vault root")
    if not vault.exists() or not vault.is_dir():
        return fail("vault does not exist or is not a directory")
    if args.mode == "finalize-log":
        if not args.commit_hash:
            return fail("--commit is required with --mode finalize-log")
        try:
            finalize_latest_log_commit(vault, args.commit_hash)
        except ValueError as exc:
            return fail(str(exc))
        return 0
    try:
        json_path = checked_report_path(args.json_path, FIXED_JSON_REPORT, "JSON") if args.json_path else None
        markdown_path = checked_report_path(args.markdown_path, FIXED_MARKDOWN_REPORT, "Markdown") if args.markdown_path else None
    except ValueError as exc:
        return fail(str(exc))
    scopes: list[str] = args.scope or DEFAULT_SCOPES
    for scope in scopes:
        scope_path = (vault / scope).resolve()
        if not is_relative_inside(scope_path, vault):
            return fail(f"scope escapes vault: {scope}")

    progress(args.progress, "build report")
    report = build_report(vault, scopes)
    if args.mode == "apply-safe":
        protected = set(report["protected_paths"])
        notes, _by_name, _file_stems, _attachment_targets = build_index(vault, scopes, protected)
        date = args.date or "未注明日期"
        progress(args.progress, "apply source file policy")
        apply_source_file_policy(vault, report)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        for _ in range(5):
            progress(args.progress, "apply structural reorganization")
            before = len(report["applied"].get("structural_moves", []))
            apply_structural_reorganization(vault, report)
            notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
            after = len(report["applied"].get("structural_moves", []))
            if after == before:
                break
        progress(args.progress, "apply topic indexes")
        apply_topic_indexes(vault, report)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        progress(args.progress, "apply understanding profiles")
        apply_understanding_profiles(vault, report)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        progress(args.progress, "apply ownership area creations")
        apply_ownership_area_creations(vault, report, date)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        progress(args.progress, "apply ownership area profiles")
        apply_ownership_area_profile_updates(vault, report)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        progress(args.progress, "apply ownership structure")
        apply_ownership_structure(vault, report, date)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        progress(args.progress, "apply ownership splits")
        apply_ownership_splits(vault, report, date)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        progress(args.progress, "apply duplicates")
        apply_duplicates(vault, notes, report, date)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report)
        progress(args.progress, "apply broken links")
        apply_broken_links(vault, notes, report)
        progress(args.progress, "apply empty stubs")
        apply_empty_stubs(vault, report)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report, include_structure=False)
        progress(args.progress, "apply understanding links")
        apply_understanding_links(vault, report)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report, include_structure=False)
        progress(args.progress, "apply metadata")
        apply_metadata(notes, report)
        notes, _by_name, _file_stems, _attachment_targets = refresh_report_findings(vault, report, include_structure=False)
        progress(args.progress, "apply topic relations")
        apply_topic_relations(vault, report)
        progress(args.progress, "apply ownership relations")
        apply_ownership_relations(vault, report)
        if not args.no_log:
            progress(args.progress, "append log")
            append_log(vault, report, date)
        progress(args.progress, "safe self-check")
        safe_self_check(vault, report)
    else:
        report["verification"]["git_status"] = "scan 模式未修改"
        report["verification"]["self_check"] = "通过"

    try:
        progress(args.progress, "write outputs")
        write_outputs(report, json_path, markdown_path)
    except ValueError as exc:
        return fail(str(exc))
    if not json_path and not markdown_path:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
