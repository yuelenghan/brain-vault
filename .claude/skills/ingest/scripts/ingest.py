#!/usr/bin/env python3
"""Deterministic preprocessor for organizing Inbox notes in a brain vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DOCUMENT_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf"}
TEXT_EXTENSIONS = {".txt", ".text", ".markdown", ".csv", ".json", ".jsonl"}
WEB_EXTENSIONS = {".html", ".htm", ".epub", ".ipynb"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".mov", ".aac", ".aiff", ".flac", ".ogg", ".opus", ".webm"}
SUPPORTED_CONVERT_EXTENSIONS = DOCUMENT_EXTENSIONS | TEXT_EXTENSIONS | WEB_EXTENSIONS | IMAGE_EXTENSIONS | AUDIO_EXTENSIONS
SCOPES = ("Projects", "Areas", "Resources", "Archive")
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "dclid", "igshid", "spm"}
TRACKING_PREFIXES = ("utm_",)
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")
CONVERSION_ERROR_RE = re.compile(
    r"(?im)(^|\n)\s*(error|exception|failed|failure)\s*:"
    r"|traceback \(most recent call last\)"
    r"|(markitdown|whisper).{0,80}(failed|error)"
    r"|(conversion|transcription)\s+failed"
    r"|could not convert"
    r"|unable to convert"
)
RESOURCE_INDEX_BEGIN = "<!-- BEGIN: resource-index -->"
RESOURCE_INDEX_END = "<!-- END: resource-index -->"
TEST_REPORT_DIR_ENV = "INGEST_TEST_REPORT_DIR"


def fixed_report_dir() -> Path:
    # Test-only escape hatch so subprocess CLI tests do not race on production /tmp reports.
    return Path(os.environ.get(TEST_REPORT_DIR_ENV, "/tmp")).resolve()


FIXED_REPORT_DIR = fixed_report_dir()
FIXED_JSON_REPORT = FIXED_REPORT_DIR / "ingest.json"
FIXED_MARKDOWN_REPORT = FIXED_REPORT_DIR / "ingest.md"
MEDITATE_FEEDBACK_KEYWORDS = (
    "补链",
    "missing link",
    "link attention",
    "prefer link",
    "backlink",
    "承接",
    "结构",
    "失效链接",
    "元数据",
    "概念画像",
    "ownership",
    "source_file",
    "topic",
)
UNDERSTANDING_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "agent",
    "agents",
    "are",
    "because",
    "before",
    "between",
    "build",
    "code",
    "each",
    "error",
    "every",
    "file",
    "from",
    "into",
    "material",
    "model",
    "more",
    "note",
    "notes",
    "only",
    "output",
    "patterns",
    "people",
    "prompt",
    "reference",
    "review",
    "session",
    "shared",
    "step",
    "system",
    "task",
    "that",
    "the",
    "they",
    "this",
    "time",
    "turns",
    "user",
    "uses",
    "what",
    "when",
    "with",
    "work",
    "your",
}


@dataclass
class Candidate:
    path: str
    kind: str
    status: str
    markdown_path: str | None = None
    reason: str | None = None
    title: str | None = None
    source_urls: list[str] | None = None
    source_fingerprint: str | None = None
    content_fingerprint: str | None = None
    source_frontmatter: dict[str, object] | None = None


def fail(message: str) -> int:
    print(f"ingest: {message}", file=sys.stderr)
    return 2


def run(vault: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=vault, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def git(vault: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return run(vault, ["git", *args])


def protected_paths(vault: Path) -> set[str]:
    completed = git(vault, ["status", "--short", "--", ".", ":!Inbox/**", ":!.claude/ingest.log"])
    if completed.returncode != 0:
        return set()
    paths: set[str] = set()
    for line in completed.stdout.splitlines():
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        raw = raw.strip('"')
        if (
            raw == ".agents"
            or raw.startswith(".agents/")
            or raw == ".codex"
            or raw.startswith(".codex/")
            or raw == ".copilot"
            or raw.startswith(".copilot/")
            or raw == ".github"
            or raw.startswith(".github/")
        ):
            continue
        if raw:
            paths.add(raw)
    return paths


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", Path(name).stem.strip()).lower()


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines[:5]):
        if line.strip() == "---":
            start = idx
            break
        if line.strip() and not line.startswith("> 整理自 Inbox"):
            break
    if start is None:
        return {}, text
    end = None
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text
    frontmatter: dict[str, object] = {}
    current_list_key: str | None = None
    for line in lines[start + 1 : end]:
        if re.match(r"^[A-Za-z0-9_-]+:\s*", line):
            key, raw = line.split(":", 1)
            current_list_key = None
            key = key.strip()
            raw = raw.strip()
            if not raw:
                frontmatter[key] = []
                current_list_key = key
                continue
            frontmatter[key] = strip_quotes(raw)
            continue
        if current_list_key and line.startswith((" ", "\t")) and line.lstrip().startswith("-"):
            item = strip_quotes(line.lstrip().split("-", 1)[1].strip())
            if item:
                current = frontmatter.get(current_list_key)
                if not isinstance(current, list):
                    current = []
                    frontmatter[current_list_key] = current
                current.append(item)
            continue
        if line.strip():
            current_list_key = None
    body = "\n".join(lines[:start] + lines[end + 1 :])
    return frontmatter, body


def parse_aliases(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    aliases: list[str] = []
    in_aliases = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if re.match(r"^[A-Za-z0-9_-]+:\s*", line):
            key, raw = line.split(":", 1)
            in_aliases = key.strip() == "aliases"
            value = strip_quotes(raw.strip())
            if in_aliases and value:
                if value.startswith("[") and value.endswith("]"):
                    aliases.extend(strip_quotes(item.strip()) for item in value.strip("[]").split(",") if item.strip())
                else:
                    aliases.append(value)
            continue
        if in_aliases and line.lstrip().startswith("-"):
            aliases.append(strip_quotes(line.split("-", 1)[1].strip()))
    return list(dict.fromkeys(alias for alias in aliases if alias))


def heading_title(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


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


def frontmatter_string(frontmatter: dict[str, object], key: str) -> str:
    value = frontmatter.get(key)
    return value if isinstance(value, str) else ""


def normalized_url_value(value: str) -> str:
    if value.startswith(("http://", "https://")):
        return normalize_url(value)
    return value


def extract_urls(frontmatter: dict[str, object], text: str) -> list[str]:
    urls: list[str] = []
    for key in ("source_url", "canonical_url", "source"):
        value = frontmatter_string(frontmatter, key)
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(normalize_url(value))
    for line in text.splitlines():
        if any(marker in line for marker in ("来源 URL", "来源：", "来源:", "Source:", "source:")):
            urls.extend(normalize_url(match) for match in URL_RE.findall(line))
    return list(dict.fromkeys(urls))


def parse_inline_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text or text == "[]":
        return []
    if text.startswith("[") and text.endswith("]"):
        return [strip_quotes(item.strip()) for item in text[1:-1].split(",") if item.strip()]
    return [strip_quotes(text)]


DISTILLATION_HEADING_RE = re.compile(r"^##\s*(提炼|摘要|总结|TL;DR)\s*$", re.IGNORECASE)
SOURCE_HEADING_RE = re.compile(r"^##\s*(原文|原文\s*/\s*摘录|摘录|原始内容|正文|Transcript)\s*$", re.IGNORECASE)
CURATED_TRAILING_HEADING_RE = re.compile(
    r"^##\s*(关联|可能相关|相关资料|相关项目|资料索引|重复归档|后续行动|下一步)\s*$"
)


def source_body_for_hash(text: str) -> str:
    _frontmatter, body = parse_frontmatter(text)
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == RESOURCE_INDEX_BEGIN:
            i += 1
            while i < len(lines) and lines[i].strip() != RESOURCE_INDEX_END:
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


def fingerprint(text: str) -> str:
    return "sha256:" + hashlib.sha256(normalize_body_for_hash(text).encode("utf-8")).hexdigest()


def text_mentions_name(text: str, name: str) -> bool:
    if not name:
        return False
    if re.fullmatch(r"[A-Za-z0-9 _.-]+", name):
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return name.lower() in text.lower()


def normalize_concept_token(token: str) -> str:
    token = token.lower().strip("-_")
    if token.endswith("ies") and len(token) > 5:
        token = token[:-3] + "y"
    elif token.endswith(("ches", "shes", "sses", "xes", "zes")) and len(token) > 4:
        token = token[:-2]
    elif token.endswith("es") and len(token) > 5 and not token.endswith(("ses", "xes")):
        token = token[:-2]
    elif token.endswith("s") and len(token) > 4 and not token.endswith(("sis", "ss", "us", "ys")):
        token = token[:-1]
    return token


def meaningful_concept_token(token: str) -> bool:
    return len(token) >= 4 and token not in UNDERSTANDING_STOPWORDS and not token.isdigit()


def concept_counts_for_text(text: str) -> Counter[str]:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]*\)", " ", text)
    counts: Counter[str] = Counter()
    chunks = re.findall(r"[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[A-Za-z][A-Za-z0-9-]*)*", text)
    for chunk in chunks:
        segment: list[str] = []
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9-]*", chunk):
            token = normalize_concept_token(raw)
            if not meaningful_concept_token(token):
                for first, second in zip(segment, segment[1:]):
                    if first != second:
                        counts[f"{first} {second}"] += 2
                segment = []
                continue
            counts[token] += 1
            segment.append(token)
        for first, second in zip(segment, segment[1:]):
            if first != second:
                counts[f"{first} {second}"] += 2
    for cjk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        counts[cjk] += 1
    return counts


def top_concepts(counts: Counter[str], limit: int = 12) -> list[str]:
    items = [(term, count) for term, count in counts.items() if count > 0]
    items.sort(key=lambda item: (-item[1], -len(item[0].split()), item[0]))
    return [term for term, _count in items[:limit]]


def inbox_files(vault: Path) -> list[Path]:
    inbox = vault / "Inbox"
    if not inbox.exists():
        return []
    return sorted(p for p in inbox.iterdir() if p.is_file() and not p.name.startswith("."))


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in SUPPORTED_CONVERT_EXTENSIONS:
        return "convertible"
    return "unsupported"


def source_modality(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    if suffix in TEXT_EXTENSIONS:
        return "data_or_text"
    if suffix in WEB_EXTENSIONS:
        return "web_or_notebook"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio_video"
    return "unsupported"


def converter_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return None
    if suffix in AUDIO_EXTENSIONS:
        # Prefer the dedicated brain-vault audio/video wrapper; fall back for older vaults.
        if (Path.cwd() / ".claude/bin/safe-whisper").exists():
            return ".claude/bin/safe-whisper"
        return ".claude/bin/safe-markitdown"
    if suffix in SUPPORTED_CONVERT_EXTENSIONS:
        return ".claude/bin/safe-markitdown"
    return None


def safe_relative_inbox(path: Path) -> str:
    return "Inbox/" + path.name


def run_conversion(vault: Path, path: Path) -> tuple[bool, str | None]:
    converter = converter_for(path)
    if not converter:
        return True, None
    rel = safe_relative_inbox(path)
    completed = run(vault, [converter, rel])
    if completed.returncode != 0:
        reason = (completed.stderr or completed.stdout or f"converter exited {completed.returncode}").strip()
        return False, reason
    output = (vault / rel).with_suffix(".md")
    if not output.exists() or output.stat().st_size == 0:
        return False, "conversion output is empty or missing"
    try:
        converted_text = output.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, "conversion output is not valid UTF-8 markdown"
    if CONVERSION_ERROR_RE.search(converted_text.strip()):
        return False, "conversion output looks like an error message"
    return True, None


def read_markdown_info(vault: Path, markdown_rel: str) -> tuple[str | None, list[str], str | None, dict[str, object]]:
    path = vault / markdown_rel
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, [], None, {}
    frontmatter, body = parse_frontmatter(text)
    title = frontmatter_string(frontmatter, "title") or heading_title(body) or path.stem
    return title, extract_urls(frontmatter, text), fingerprint(text), frontmatter


def can_pair_existing_conversion_markdown(vault: Path, markdown_rel: str, source_rel: str) -> bool:
    path = vault / markdown_rel
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    if CONVERSION_ERROR_RE.search(text.strip()):
        return False
    frontmatter, _body = parse_frontmatter(text)
    source_name = Path(source_rel).name
    source_markers = {
        source_rel,
        f"`{source_rel}`",
        source_name,
        f"`{source_name}`",
        f"[[{source_name}]]",
    }
    for key in ("source_file", "original_file", "source"):
        value = frontmatter_string(frontmatter, key)
        if value and any(marker in value for marker in source_markers):
            return True
    explicit_text_markers = {source_rel, f"`{source_rel}`", f"`{source_name}`", f"[[{source_name}]]"}
    return any(marker in text for marker in explicit_text_markers)


def existing_notes(vault: Path) -> tuple[list[dict], list[dict]]:
    notes: list[dict] = []
    invalid_fingerprints: list[dict] = []
    for scope in SCOPES:
        root = vault / scope
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(vault).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            frontmatter, body = parse_frontmatter(text)
            title = frontmatter_string(frontmatter, "title") or heading_title(body) or path.stem
            computed_fingerprint = fingerprint(text)
            stored_fingerprint_field = None
            stored_fingerprint = None
            for field_name in ("source_fingerprint", "content_fingerprint"):
                if frontmatter_string(frontmatter, field_name):
                    stored_fingerprint_field = field_name
                    stored_fingerprint = frontmatter_string(frontmatter, field_name)
                    break
            fingerprint_valid = (
                not stored_fingerprint
                or stored_fingerprint_field == "content_fingerprint"
                or stored_fingerprint == computed_fingerprint
            )
            if not fingerprint_valid:
                invalid_fingerprints.append({
                    "path": rel,
                    "field": stored_fingerprint_field,
                    "stored": stored_fingerprint,
                    "computed": computed_fingerprint,
                })
            notes.append({
                "path": rel,
                "title": title,
                "urls": extract_urls(frontmatter, text),
                "fingerprint": computed_fingerprint if fingerprint_valid else None,
            })
    return notes, invalid_fingerprints


def read_note_record(vault: Path, path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    rel = path.relative_to(vault).as_posix()
    frontmatter, body = parse_frontmatter(text)
    title = frontmatter_string(frontmatter, "title") or heading_title(body) or path.stem
    aliases = parse_aliases(text)
    kind = strip_quotes(frontmatter_string(frontmatter, "type")).strip().lower()
    source_text = source_body_for_hash(text)
    concepts = concept_counts_for_text(f"{path.stem}\n{title}\n{source_text}")
    return {
        "path": rel,
        "stem": path.stem,
        "title": title,
        "aliases": aliases,
        "kind": kind,
        "body": source_text,
        "concepts": concepts,
    }


def build_knowledge_index(vault: Path) -> dict:
    topics: dict[str, dict] = {}
    owners: list[dict] = []
    notes: list[dict] = []
    for scope in SCOPES:
        root = vault / scope
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            record = read_note_record(vault, path)
            if record is None:
                continue
            notes.append(record)
            parts = Path(record["path"]).parts
            if scope == "Resources" and len(parts) >= 2:
                topic = parts[1]
                profile = topics.setdefault(
                    topic,
                    {
                        "topic": topic,
                        "dir": f"Resources/{topic}",
                        "names": [topic],
                        "concepts": Counter(),
                        "material_count": 0,
                    },
                )
                for name in [record["title"], record["stem"], *record["aliases"]]:
                    if name and name not in profile["names"]:
                        profile["names"].append(name)
                profile["concepts"].update(record["concepts"])
                if record["kind"] not in {"index", "area", "project"} and record["stem"] != "README":
                    profile["material_count"] += 1
            if scope in {"Projects", "Areas"}:
                owners.append(record)
    return {"topics": topics, "owners": owners, "notes": notes}


def candidate_text(vault: Path, candidate: Candidate) -> tuple[str, Counter[str]]:
    if not candidate.markdown_path:
        return "", Counter()
    path = vault / candidate.markdown_path
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return candidate.title or "", Counter()
    frontmatter, body = parse_frontmatter(text)
    title = frontmatter_string(frontmatter, "title") or heading_title(body) or path.stem
    source_text = source_body_for_hash(text)
    combined = f"{path.stem}\n{title}\n{source_text}"
    return combined, concept_counts_for_text(combined)


def candidate_source_text(vault: Path, candidate: Candidate) -> str:
    if not candidate.markdown_path:
        return ""
    path = vault / candidate.markdown_path
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
    return source_body_for_hash(text)


def looks_like_image_placeholder(text: str) -> bool:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    lowered = normalized.lower()
    chinese_metadata_hits = sum(
        1
        for marker in ("截图笔记占位", "## 图片信息", "- 文件：", "- 格式：", "- 尺寸：", "## 待整理")
        if marker in normalized
    )
    if chinese_metadata_hits >= 4 and "## 自动识别文本" not in normalized:
        return True
    metadata_hits = sum(1 for marker in ("filename:", "format:", "size:", "dimensions:") if marker in lowered)
    word_count = len(re.findall(r"[A-Za-z\u4e00-\u9fff]{2,}", normalized))
    return metadata_hits >= 2 and word_count <= 16


def source_understanding_status(candidate: Candidate, source_text: str) -> dict:
    modality = source_modality(candidate.path)
    stripped = source_text.strip()
    base = {
        "modality": modality,
        "status": "pass",
        "reason": "source material has enough converted text for first-pass understanding",
        "required_action": None,
    }
    if modality == "image" and looks_like_image_placeholder(stripped):
        return {
            **base,
            "status": "blocked",
            "reason": "image conversion output is only metadata placeholder",
            "required_action": "manual visual inspection before organization",
        }
    if modality == "audio_video" and len(stripped) < 120:
        return {
            **base,
            "status": "blocked",
            "reason": f"transcript too short for first-pass understanding ({len(stripped)} characters)",
            "required_action": "rerun or manually inspect/transcribe original media before organization",
        }
    if modality != "markdown" and not stripped:
        return {
            **base,
            "status": "blocked",
            "reason": "converted source text is empty",
            "required_action": "rerun conversion or inspect original source before organization",
        }
    if modality in {"image", "audio_video"}:
        return {
            **base,
            "reason": "converted source contains substantive media-derived text",
        }
    return base


def encoding_plan(vault: Path, candidates: list[Candidate]) -> dict:
    plans: dict[str, dict] = {}
    for candidate in candidates:
        if candidate.status != "ready" or not candidate.markdown_path:
            continue
        source_text = candidate_source_text(vault, candidate)
        source_characters = len(source_text.strip())
        converted = candidate.kind != "markdown"
        distillation_required = converted or source_characters > 3000
        distillation_reason = "converted source material" if converted else f"source body has {source_characters} characters"
        source_frontmatter = candidate.source_frontmatter or {}
        tags = parse_inline_list(source_frontmatter.get("tags"))
        recommended_frontmatter: dict[str, object] = {
            "title": candidate.title or Path(candidate.markdown_path).stem,
            "type": "reference",
            "created": "<YYYY-MM-DD>",
            "tags": tags,
        }
        source_url = frontmatter_string(source_frontmatter, "source_url")
        canonical_url = frontmatter_string(source_frontmatter, "canonical_url")
        source = frontmatter_string(source_frontmatter, "source")
        if source_url:
            recommended_frontmatter["source_url"] = normalized_url_value(source_url)
        elif source and source.startswith(("http://", "https://")) and candidate.source_urls:
            recommended_frontmatter["source_url"] = candidate.source_urls[0]
        elif not canonical_url and candidate.source_urls:
            recommended_frontmatter["source_url"] = candidate.source_urls[0]
        if canonical_url:
            recommended_frontmatter["canonical_url"] = normalized_url_value(canonical_url)
        if source:
            recommended_frontmatter["source"] = normalized_url_value(source)
        if candidate.source_fingerprint:
            recommended_frontmatter["source_fingerprint"] = candidate.source_fingerprint
        for key in ("author", "published", "description"):
            value = frontmatter_string(source_frontmatter, key)
            if value:
                recommended_frontmatter[key] = value

        source_file = {"required": False}
        if converted:
            expected = f"source/{Path(candidate.markdown_path).stem}{Path(candidate.path).suffix}"
            source_file = {
                "required": True,
                "expected": expected,
                "visible_link": f"原始文件：[[{expected}]]",
                "reason": "converted source must be moved beside the organized Markdown note under lowercase source/",
            }

        plans[candidate.path] = {
            "markdown_path": candidate.markdown_path,
            "title": recommended_frontmatter["title"],
            "source_kind": candidate.kind,
            "source_characters": source_characters,
            "frontmatter": {
                "required_fields": ["title", "type", "created", "tags", "source_fingerprint"],
                "recommended": recommended_frontmatter,
            },
            "distillation": {
                "required": distillation_required,
                "reason": distillation_reason,
                "sections": ["## 提炼", "## 原文 / 摘录"] if distillation_required else [],
                "checks": [
                    "one-sentence judgment",
                    "3-7 key points",
                    "Area/Project use and next step",
                    "keep source evidence under original/excerpt section when distilling",
                ],
            },
            "source_file": source_file,
            "source_understanding": source_understanding_status(candidate, source_text),
            "organize_marker": "> 整理自 Inbox，<YYYY-MM-DD>",
            "wikilink_policy": "use existing filename stems only; never use Inbox/ prefixes or frontmatter titles",
            "notes": ["report-only; model must verify and execute during first-pass organization"],
        }
    return plans


def topic_concept_frequency(topics: dict[str, dict]) -> Counter[str]:
    frequency: Counter[str] = Counter()
    for profile in topics.values():
        for term in set(profile["concepts"]):
            frequency[term] += 1
    return frequency


def score_topic_candidate(
    text: str,
    concepts: Counter[str],
    profile: dict,
    topic_term_frequency: Counter[str],
) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    for name in profile["names"]:
        if text_mentions_name(text, name):
            score += 8
            evidence.append(f"matched topic name: {name}")
            break
    candidate_terms = set(top_concepts(concepts, limit=40))
    matched_terms = sorted(
        term
        for term in candidate_terms
        if profile["concepts"].get(term, 0) > 0 and topic_term_frequency.get(term, 0) <= 2
    )
    if matched_terms:
        score += min(10, len(matched_terms) * 2)
        evidence.append("matched concepts: " + ", ".join(matched_terms[:5]))
    return score, evidence


def score_owner_candidate(text: str, concepts: Counter[str], owner: dict, owner_term_frequency: Counter[str]) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    for name in [owner["stem"], owner["title"], *owner["aliases"]]:
        if text_mentions_name(text, name):
            score += 8
            evidence.append(f"matched ownership name: {name}")
            break
    candidate_terms = set(top_concepts(concepts, limit=24))
    owner_terms = {
        term
        for term in top_concepts(owner["concepts"], limit=24)
        if owner_term_frequency.get(term, 0) == 1
    }
    matched_terms = sorted(candidate_terms & owner_terms)
    if len(matched_terms) >= 2:
        score += min(6, len(matched_terms) * 2)
        evidence.append("matched concepts: " + ", ".join(matched_terms[:5]))
    return score, evidence


def owner_concept_frequency(owners: list[dict]) -> Counter[str]:
    frequency: Counter[str] = Counter()
    for owner in owners:
        for term in set(top_concepts(owner["concepts"], limit=24)):
            frequency[term] += 1
    return frequency


def owner_matches_topic(owner: dict, topic: str) -> bool:
    topic_key = normalize_name(topic)
    return any(
        normalize_name(name) == topic_key
        for name in [owner["stem"], owner["title"], *owner["aliases"]]
        if name
    )


def clean_feedback_link_term(term: str) -> str:
    term = strip_quotes(term.strip(" `，。；:："))
    term = re.sub(r"^(?:Projects|Areas|Resources|Archive)/", "", term)
    term = re.sub(r"\.md$", "", term, flags=re.IGNORECASE)
    term = re.sub(r"\s*(?:的)?(?:显式)?(?:关系|关联)$", "", term)
    term = re.sub(r"\s*(?:explicit\s+)?(?:relationship|relation)$", "", term, flags=re.IGNORECASE)
    return term.strip(" `，。；:：")


def parse_link_feedback_terms(item: str) -> list[str]:
    if not re.search(r"补链|link attention|prefer link|missing link|add link", item, flags=re.IGNORECASE):
        return []
    body = re.sub(r"^[^:：]+[:：]\s*", "", item, count=1)
    fragments = re.split(r"优先识别|识别|连接|建立|between|link(?:ing)?", body, flags=re.IGNORECASE)
    search_area = fragments[-1] if len(fragments) > 1 else body
    match = re.search(
        r"(.+?)\s*(?:与|和|及|and|&)\s*(.+?)(?:的(?:显式)?关系|之间(?:的)?关系|关系|relationship|relation|$)",
        search_area,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    terms = [clean_feedback_link_term(match.group(1)), clean_feedback_link_term(match.group(2))]
    terms = [term for term in terms if term]
    if len(terms) != 2 or normalize_name(terms[0]) == normalize_name(terms[1]):
        return []
    return terms


def resources_topic_exists(index: dict | None, topic: str) -> bool:
    if index is None:
        return True
    return topic in (index.get("topics") or {})


def intake_rules_from_meditate_feedback(feedback: dict, index: dict | None = None) -> list[dict]:
    rules: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in feedback.get("items") or []:
        link_terms = parse_link_feedback_terms(item)
        if link_terms:
            key = ("prefer_link", "|".join(normalize_name(term) for term in link_terms))
            if key not in seen:
                seen.add(key)
                rules.append({
                    "action": "prefer_link",
                    "terms": link_terms,
                    "source": "meditate_feedback",
                    "evidence": item,
                    "notes": "apply only to new Inbox material that explicitly mentions both sides; do not reorganize existing notes",
                })

        structure_match = re.search(
            r"Resources/([^，。；\n]+?)\s+(?:中|中的|under|inside).{0,80}?(?:归入|迁入|移入|re-?home(?:d)? to|move(?:d)? to)\s+(?:Resources/)?([^，。；\n]+)",
            item,
            flags=re.IGNORECASE,
        )
        if structure_match:
            from_topic = structure_match.group(1).strip(" `。；，")
            suggested_topic = structure_match.group(2).strip(" `。；，")
            if from_topic and suggested_topic:
                if not resources_topic_exists(index, suggested_topic):
                    continue
                from_topic_path = f"Resources/{from_topic}"
                topic_path = f"Resources/{suggested_topic}"
                key = ("prefer_topic", f"{from_topic_path}->{topic_path}")
                if key not in seen:
                    seen.add(key)
                    rules.append({
                        "action": "prefer_topic",
                        "from_topic_path": from_topic_path,
                        "topic_path": topic_path,
                        "source": "meditate_feedback",
                        "evidence": item,
                        "notes": "apply only to new Inbox material; do not reorganize existing notes",
                    })

        if re.search(r"承接|ownership|owner", item, flags=re.IGNORECASE):
            match = re.search(r"Resources/([^，。；\n]+?)(?:\s+(?:缺少|missing|needs?|缺失)|$)", item, flags=re.IGNORECASE)
            if not match:
                continue
            topic = match.group(1).strip(" `。；，")
            if not topic:
                continue
            topic_path = f"Resources/{topic}"
            key = ("ensure_ownership", topic_path)
            if key in seen:
                continue
            seen.add(key)
            rules.append({
                "action": "ensure_ownership",
                "topic_path": topic_path,
                "suggested_owner": (Path("Areas") / f"{topic}.md").as_posix(),
                "source": "meditate_feedback",
                "evidence": item,
                "notes": "apply only to new Inbox material; do not reorganize existing notes",
            })
    return rules


def owner_for_wikilink(index: dict, wikilink: str) -> dict | None:
    link_key = normalize_name(wikilink)
    for owner in index["owners"]:
        names = [owner["stem"], owner["title"], *owner["aliases"]]
        if any(normalize_name(name) == link_key for name in names if name):
            return owner
    return None


def log_entry_is_committed(entry: list[str]) -> bool:
    for line in entry:
        stripped = line.strip()
        if not stripped.startswith("commit:"):
            continue
        value = stripped.split(":", 1)[1].strip().lower()
        return bool(value and value not in {"无", "none", "null", "no"})
    return False


def committed_ingest_log_entries(lines: list[str]) -> list[list[str]]:
    entries: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current and log_entry_is_committed(current):
                entries.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
    if current and log_entry_is_committed(current):
        entries.append(current)
    return entries


def intake_rules_from_ingest_history(vault: Path, index: dict, limit: int = 12) -> list[dict]:
    rel = ".claude/ingest.log"
    path = vault / rel
    if not path.exists() or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []
    rules: list[dict] = []
    seen: set[tuple[str, str]] = set()
    current_topic_paths: list[str] = []
    recent_lines = [line for entry in committed_ingest_log_entries(lines) for line in entry][-400:]
    for line in recent_lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current_topic_paths = []
            continue
        move_match = re.match(r"-\s+.+?\s+→\s+(Resources/([^/\n]+)/[^\n（]+)", stripped)
        if move_match:
            topic_path = f"Resources/{move_match.group(2).strip()}"
            if topic_path not in current_topic_paths:
                current_topic_paths.append(topic_path)
            continue
        if "承接笔记" not in stripped or not current_topic_paths:
            continue
        for link in re.findall(r"\[\[([^\]]+)\]\]", stripped):
            owner = owner_for_wikilink(index, link)
            if not owner:
                continue
            for topic_path in current_topic_paths:
                key = (topic_path, owner["path"])
                if key in seen:
                    continue
                seen.add(key)
                rules.append({
                    "action": "prefer_ownership",
                    "topic_path": topic_path,
                    "suggested_owner": owner["path"],
                    "source": "ingest_history",
                    "evidence": f"{topic_path} was previously organized with [[{link}]]",
                    "notes": "learned from prior ingest results; apply only to new Inbox material",
                })
                if len(rules) >= limit:
                    return rules
    return rules


def matching_intake_rule_for_target(target: dict, intake_rules: list[dict], actions: set[str] | None = None) -> dict | None:
    topic_path = f"Resources/{target['topic']}"
    for rule in intake_rules:
        if actions is not None and rule.get("action") not in actions:
            continue
        if rule.get("topic_path") == topic_path:
            return rule
    return None


def apply_topic_preference_rules(
    scored_topics: list[tuple[int, str, list[str], dict]],
    text: str,
    intake_rules: list[dict],
) -> list[tuple[int, str, list[str], dict]]:
    if not scored_topics:
        return scored_topics
    score_by_topic = {topic: score for score, topic, _evidence, _profile in scored_topics}
    best_score = max(score_by_topic.values())
    adjusted: list[tuple[int, str, list[str], dict]] = []
    for score, topic, evidence, profile in scored_topics:
        new_score = score
        new_evidence = list(evidence)
        for rule in intake_rules:
            if rule.get("action") != "prefer_topic":
                continue
            suggested_topic = Path(rule.get("topic_path", "")).name
            from_topic = Path(rule.get("from_topic_path", "")).name
            if topic != suggested_topic:
                continue
            source_topic_matched = from_topic in score_by_topic or text_mentions_name(text, from_topic)
            suggested_topic_matched = topic in score_by_topic or text_mentions_name(text, suggested_topic)
            if not source_topic_matched or not suggested_topic_matched:
                continue
            new_score = max(new_score, best_score + 3)
            new_evidence.append(f"meditate feedback topic preference: {rule.get('evidence')}")
        adjusted.append((new_score, topic, new_evidence, profile))
    return adjusted


def ownership_actions_for_targets(target_candidates: list[dict], owner_candidates: list[dict], intake_rules: list[dict]) -> list[dict]:
    if not target_candidates or owner_candidates:
        return []
    best_target = target_candidates[0]
    if best_target.get("scope") != "Resources":
        return []
    topic = best_target["topic"]
    rule = matching_intake_rule_for_target(best_target, intake_rules, {"ensure_ownership"})
    evidence = [
        "best Resources target has no Project/Area ownership candidate",
        "Resources material normally needs an Area or Project owner",
    ]
    source = "deterministic_hint"
    if rule:
        evidence.append(f"meditate feedback: {rule['evidence']}")
        source = "meditate_feedback"
    return [{
        "action": "create_area",
        "path": (Path("Areas") / f"{topic}.md").as_posix(),
        "target": best_target["target"],
        "topic": topic,
        "score": max(1, best_target["score"] - 2),
        "source": source,
        "evidence": evidence,
    }]


def note_in_target_topics(note_path: str, target_candidates: list[dict]) -> bool:
    if not target_candidates:
        return False
    if target_candidates[0].get("scope") != "Resources":
        return False
    note_parts = Path(note_path).parts
    if len(note_parts) < 3 or note_parts[0] != "Resources":
        return False
    best_score = target_candidates[0]["score"]
    target_topics = {target["topic"] for target in target_candidates if target["score"] == best_score}
    return note_parts[1] in target_topics


def concept_overlap_link_score(candidate_concepts: Counter[str], note: dict) -> tuple[int, list[str]]:
    candidate_terms = set(top_concepts(candidate_concepts, limit=36))
    note_terms = set(top_concepts(note["concepts"], limit=36))
    matched = sorted(candidate_terms & note_terms)
    matched_phrases = [term for term in matched if " " in term]
    if len(matched_phrases) < 2 and len(matched) < 5:
        return 0, []
    score = min(7, 2 + len(matched_phrases) * 2 + max(0, len(matched) - len(matched_phrases)))
    return score, ["matched concepts: " + ", ".join(matched[:6])]


def note_matches_term(note: dict, term: str) -> bool:
    term_key = normalize_name(term)
    return any(normalize_name(name) == term_key for name in [note["stem"], note["title"], *note["aliases"]] if name)


def resolve_link_attention_note(index: dict, term: str, candidate_path: str) -> dict | None:
    matches: list[tuple[int, str, dict]] = []
    for note in index["notes"]:
        if note["path"] == candidate_path or note["stem"] == "README":
            continue
        if not note_matches_term(note, term):
            continue
        priority = 0 if note["kind"] in {"area", "project"} else 1
        matches.append((priority, note["path"], note))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]))
    return matches[0][2]


def link_attention_candidates(text: str, index: dict, candidate_path: str, intake_rules: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen_paths: set[str] = set()
    for rule in intake_rules:
        if rule.get("action") != "prefer_link":
            continue
        terms = list(rule.get("terms") or [])
        if len(terms) < 2 or not all(text_mentions_name(text, term) for term in terms):
            continue
        resolved = [resolve_link_attention_note(index, term, candidate_path) for term in terms]
        if any(note is None for note in resolved):
            continue
        for note in resolved:
            assert note is not None
            wikilink = Path(note["path"]).stem
            if note["path"] in seen_paths or not wikilink_is_safe_stem(wikilink):
                continue
            seen_paths.add(note["path"])
            items.append({
                "path": note["path"],
                "wikilink": wikilink,
                "score": 9,
                "evidence": [
                    f"meditate feedback link attention: {rule.get('evidence')}",
                    "candidate mentions both terms: " + ", ".join(terms),
                ],
            })
    return items


def merge_scored_link(scored: list[tuple[int, str, dict]], item: dict) -> None:
    path = item["path"]
    for idx, (score, existing_path, existing_item) in enumerate(scored):
        if existing_path != path:
            continue
        merged = dict(existing_item)
        merged["score"] = max(score, item.get("score", 0))
        merged["evidence"] = list(dict.fromkeys([*(existing_item.get("evidence") or []), *(item.get("evidence") or [])]))
        scored[idx] = (merged["score"], path, merged)
        return
    scored.append((item.get("score", 0), path, item))


def link_candidates(
    text: str,
    concepts: Counter[str],
    index: dict,
    candidate_path: str,
    target_candidates: list[dict],
    intake_rules: list[dict],
) -> list[dict]:
    scored: list[tuple[int, str, dict]] = []
    for note in index["notes"]:
        if note["path"] == candidate_path:
            continue
        if note["kind"] in {"index", "area", "project"} or note["stem"] == "README":
            continue
        evidence: list[str] = []
        score = 0
        for name in [note["title"], note["stem"], *note["aliases"]]:
            if text_mentions_name(text, name):
                score += 8 if name == note["title"] else 6
                evidence.append(f"matched existing note name: {name}")
                break
        if not score and note_in_target_topics(note["path"], target_candidates):
            score, evidence = concept_overlap_link_score(concepts, note)
        if score:
            scored.append((score, note["path"], {
                "path": note["path"],
                "wikilink": Path(note["path"]).stem,
                "score": score,
                "evidence": evidence,
            }))
    for item in link_attention_candidates(text, index, candidate_path, intake_rules):
        merge_scored_link(scored, item)
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item for _score, _path, item in scored[:3]]


def wikilink_is_safe_stem(wikilink: str) -> bool:
    return bool(wikilink) and not wikilink.startswith("Inbox/") and "/" not in wikilink and ":" not in wikilink


def link_verification_plan(report: dict, vault: Path) -> dict:
    plans: dict[str, dict] = {}
    hints = report.get("understanding_hints") or {}
    for candidate in report.get("candidates") or []:
        path = candidate["path"]
        if candidate.get("status") != "ready":
            continue
        hint = hints.get(path) or {}
        link_items = hint.get("link_candidates") or []
        links: list[dict] = []
        blocked_by: list[str] = []
        for item in link_items:
            wikilink = item.get("wikilink") or ""
            target_path = item.get("path") or ""
            safe = wikilink_is_safe_stem(wikilink)
            exists = bool(target_path) and (vault / target_path).is_file()
            stem_matches = bool(target_path) and Path(target_path).stem == wikilink
            if not safe:
                blocked_by.append(f"unsafe wikilink candidate: {wikilink}")
            if target_path and not exists:
                blocked_by.append(f"missing wikilink target: {target_path}")
            if target_path and exists and not stem_matches:
                blocked_by.append(f"wikilink does not match filename stem: {wikilink} -> {target_path}")
            links.append({
                "wikilink": wikilink,
                "target_path": target_path,
                "exists": exists,
                "stem_matches": stem_matches,
                "safe": safe,
                "status": "pass" if safe and exists and stem_matches else "blocked",
                "evidence": item.get("evidence") or [],
            })
        if not links:
            status = "none"
        elif blocked_by:
            status = "blocked"
        else:
            status = "pass"
        plans[path] = {
            "status": status,
            "links": links,
            "verified_wikilinks": [link["wikilink"] for link in links if link["status"] == "pass"],
            "blocked_by": list(dict.fromkeys(blocked_by)),
            "notes": [
                "report-only; verifies wikilinks resolve by actual filename stem",
                "do not emit Inbox/ prefixes, path links, or frontmatter-title-only links",
            ],
        }
    return plans


def verified_wikilinks_for_path(report: dict, path: str) -> list[str]:
    plan = (report.get("link_verification_plan") or {}).get(path) or {}
    if plan.get("status") == "pass":
        return list(plan.get("verified_wikilinks") or [])
    if plan.get("status") in {"blocked", "none"}:
        return []
    hint = (report.get("understanding_hints") or {}).get(path) or {}
    return [
        item["wikilink"]
        for item in hint.get("link_candidates") or []
        if item.get("wikilink") and wikilink_is_safe_stem(item["wikilink"])
    ]


def understanding_hints(vault: Path, candidates: list[Candidate], index: dict, intake_rules: list[dict]) -> dict:
    hints: dict[str, dict] = {}
    owner_frequency = owner_concept_frequency(index["owners"])
    topic_frequency = topic_concept_frequency(index["topics"])
    owners_by_path = {owner["path"]: owner for owner in index["owners"]}
    for candidate in candidates:
        if candidate.status != "ready" or not candidate.markdown_path:
            continue
        text, concepts = candidate_text(vault, candidate)
        target_candidates: list[dict] = []
        notes: list[str] = ["report-only; model must verify before moving or editing"]
        scored_topics: list[tuple[int, str, list[str], dict]] = []
        for topic, profile in sorted(index["topics"].items()):
            score, evidence = score_topic_candidate(text, concepts, profile, topic_frequency)
            if score > 0:
                scored_topics.append((score, topic, evidence, profile))
        scored_topics = apply_topic_preference_rules(scored_topics, text, intake_rules)
        scored_topics.sort(key=lambda item: (-item[0], item[1]))
        if scored_topics:
            best_score = scored_topics[0][0]
            tied_best = [item for item in scored_topics if item[0] == best_score]
            if len(tied_best) > 1:
                names = ", ".join(topic for _score, topic, _evidence, _profile in tied_best)
                notes.append(f"ambiguous target topic candidates: {names}")
            else:
                for score, topic, evidence, _profile in scored_topics[:3]:
                    target_candidates.append({
                        "target": (Path("Resources") / topic / Path(candidate.markdown_path).name).as_posix(),
                        "scope": "Resources",
                        "topic": topic,
                        "score": score,
                        "evidence": evidence,
                    })

        for owner in index["owners"]:
            if Path(owner["path"]).parts[0] != "Projects":
                continue
            score, evidence = score_owner_candidate(text, concepts, owner, owner_frequency)
            if score <= 0:
                continue
            target_candidates.append({
                "target": (Path("Projects") / owner["stem"] / Path(candidate.markdown_path).name).as_posix(),
                "scope": "Projects",
                "project": owner["stem"],
                "owner_path": owner["path"],
                "score": score + 2,
                "evidence": [*evidence, "matched existing Project owner"],
            })
        target_candidates.sort(key=lambda item: (-item["score"], item["target"]))

        owner_candidates: list[dict] = []
        for owner in index["owners"]:
            score, evidence = score_owner_candidate(text, concepts, owner, owner_frequency)
            if score > 0:
                owner_candidates.append({
                    "path": owner["path"],
                    "scope": Path(owner["path"]).parts[0],
                    "score": score,
                    "evidence": evidence,
                })
        existing_owner_paths = {item["path"] for item in owner_candidates}
        best_target_score = target_candidates[0]["score"] if target_candidates else 0
        for target in [item for item in target_candidates if item["score"] == best_target_score]:
            if target.get("scope") != "Resources":
                continue
            for owner in index["owners"]:
                if owner["path"] in existing_owner_paths or not owner_matches_topic(owner, target["topic"]):
                    continue
                owner_candidates.append({
                    "path": owner["path"],
                    "scope": Path(owner["path"]).parts[0],
                    "score": max(1, target["score"] - 1),
                    "evidence": ["matched target topic owner"],
                })
                existing_owner_paths.add(owner["path"])
        for target in [item for item in target_candidates if item["score"] == best_target_score]:
            if target.get("scope") != "Resources":
                continue
            topic_path = f"Resources/{target['topic']}"
            for rule in intake_rules:
                if rule.get("action") not in {"prefer_ownership", "ensure_ownership"}:
                    continue
                if rule.get("topic_path") != topic_path:
                    continue
                owner_path = rule.get("suggested_owner")
                owner = owners_by_path.get(owner_path)
                if not owner or owner_path in existing_owner_paths:
                    continue
                source = "ingest history" if rule.get("source") == "ingest_history" else "meditate feedback"
                owner_candidates.append({
                    "path": owner_path,
                    "scope": Path(owner_path).parts[0],
                    "score": max(1, target["score"] - 1),
                    "evidence": [f"matched {source} ownership rule: {rule.get('evidence')}"],
                })
                existing_owner_paths.add(owner_path)
        owner_candidates.sort(key=lambda item: (-item["score"], item["path"]))

        hints[candidate.path] = {
            "target_candidates": target_candidates,
            "ownership_candidates": owner_candidates[:3],
            "ownership_actions": ownership_actions_for_targets(target_candidates, owner_candidates, intake_rules),
            "link_candidates": link_candidates(text, concepts, index, candidate.markdown_path, target_candidates, intake_rules),
            "notes": notes,
        }
    return hints


def intake_learning_audit(report: dict) -> dict:
    rules = report.get("intake_rules") or []
    hints = report.get("understanding_hints") or {}
    by_action: dict[str, int] = {}
    for rule in rules:
        action = rule.get("action", "unknown")
        by_action[action] = by_action.get(action, 0) + 1

    applied: list[dict] = []
    applied_rule_indexes: set[int] = set()
    for candidate_path, hint in sorted(hints.items()):
        for index, rule in enumerate(rules):
            action = rule.get("action")
            if action == "prefer_topic":
                topic = Path(rule.get("topic_path", "")).name
                for target in hint.get("target_candidates") or []:
                    if target.get("topic") != topic:
                        continue
                    if not any("meditate feedback topic preference" in evidence for evidence in target.get("evidence") or []):
                        continue
                    applied.append({
                        "candidate": candidate_path,
                        "action": action,
                        "source": rule.get("source"),
                        "effect": "target candidate boosted",
                        "target": target.get("target"),
                        "rule_evidence": rule.get("evidence"),
                    })
                    applied_rule_indexes.add(index)
                    break
            elif action in {"prefer_ownership", "ensure_ownership"}:
                owner_path = rule.get("suggested_owner")
                for owner in hint.get("ownership_candidates") or []:
                    if owner.get("path") != owner_path:
                        continue
                    source_label = "ingest history" if rule.get("source") == "ingest_history" else "meditate feedback"
                    if not any(source_label in evidence for evidence in owner.get("evidence") or []):
                        continue
                    applied.append({
                        "candidate": candidate_path,
                        "action": action,
                        "source": rule.get("source"),
                        "effect": "ownership candidate preferred",
                        "target": owner_path,
                        "rule_evidence": rule.get("evidence"),
                    })
                    applied_rule_indexes.add(index)
                    break
                for ownership_action in hint.get("ownership_actions") or []:
                    if ownership_action.get("source") != "meditate_feedback":
                        continue
                    if action != "ensure_ownership":
                        continue
                    applied.append({
                        "candidate": candidate_path,
                        "action": action,
                        "source": rule.get("source"),
                        "effect": "ownership action required",
                        "target": ownership_action.get("path"),
                        "rule_evidence": rule.get("evidence"),
                    })
                    applied_rule_indexes.add(index)
                    break
            elif action == "prefer_link":
                matched_links = [
                    link.get("wikilink")
                    for link in hint.get("link_candidates") or []
                    if any("meditate feedback link attention" in evidence for evidence in link.get("evidence") or [])
                ]
                if matched_links:
                    applied.append({
                        "candidate": candidate_path,
                        "action": action,
                        "source": rule.get("source"),
                        "effect": "link candidates preferred",
                        "target": ", ".join(f"[[{link}]]" for link in matched_links if link),
                        "rule_evidence": rule.get("evidence"),
                    })
                    applied_rule_indexes.add(index)

    return {
        "rules_total": len(rules),
        "by_action": by_action,
        "applied": applied,
        "unapplied_rules": [
            {
                "action": rule.get("action"),
                "source": rule.get("source"),
                "evidence": rule.get("evidence"),
            }
            for index, rule in enumerate(rules)
            if index not in applied_rule_indexes
        ],
        "notes": [
            "audit applies learned rules only to current Inbox candidates",
            "absence from applied means the rule was retained but did not match this scan",
        ],
    }


def intake_quality_metrics(report: dict) -> dict:
    raw_candidates = report.get("candidates") or []
    candidates = [
        candidate
        for candidate in raw_candidates
        if candidate.get("reason") != "not selected for apply-ready"
    ]
    excluded_by_selection = len(raw_candidates) - len(candidates)
    organization = report.get("organization_plan") or {}
    handoff = report.get("meditate_handoff") or {}
    readiness = report.get("placement_readiness") or {}
    encoding = report.get("encoding_plan") or {}
    audit = report.get("intake_learning_audit") or {}

    ready_for_apply = 0
    handoff_ready = 0
    handoff_blocked = 0
    source_understanding_blocked = 0
    blocked_by_reason: dict[str, int] = {}

    for candidate in candidates:
        path = candidate.get("path")
        plan = organization.get(path) or {}
        if plan.get("status") == "ready":
            ready_for_apply += 1
        ready = readiness.get(path) or {}
        reasons = ready.get("reasons") or []
        if not reasons and candidate.get("status") != "ready" and candidate.get("reason"):
            reasons = [candidate["reason"]]
        for reason in reasons:
            blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1

        handoff_item = handoff.get(path) or {}
        if handoff_item.get("status") == "ready":
            handoff_ready += 1
        elif handoff_item.get("status") == "blocked":
            handoff_blocked += 1

        source_understanding = (encoding.get(path) or {}).get("source_understanding") or {}
        if source_understanding.get("status") == "blocked":
            source_understanding_blocked += 1

    total = len(candidates)
    blocked = max(0, total - ready_for_apply)
    return {
        "candidates_total": total,
        "ready_for_apply": ready_for_apply,
        "blocked": blocked,
        "ready_rate": round(ready_for_apply / total, 3) if total else 1.0,
        "handoff_ready": handoff_ready,
        "handoff_blocked": handoff_blocked,
        "blocked_by_reason": dict(sorted(blocked_by_reason.items())),
        "source_understanding_blocked": source_understanding_blocked,
        "excluded_by_selection": excluded_by_selection,
        "learning_rules_total": audit.get("rules_total", 0),
        "learning_rules_applied": len(audit.get("applied") or []),
        "notes": [
            "ready_for_apply counts candidates the script can move/edit/stage now",
            "handoff_ready counts candidates whose first-pass encoding is ready for meditate after organization",
            "blocked_by_reason is a source-side rework reduction signal for future ingest improvements",
            "not selected for apply-ready is tracked in apply_selection_audit and excluded from quality rates",
        ],
    }


def parse_metric_pairs(text: str) -> dict[str, float | int]:
    values: dict[str, float | int] = {}
    for part in text.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            values[key] = float(value) if "." in value else int(value)
        except ValueError:
            continue
    return values


def parse_blocker_pairs(text: str) -> dict[str, int]:
    if text.strip() == "无":
        return {}
    blockers: dict[str, int] = {}
    for key, value in parse_metric_pairs(text).items():
        blockers[key] = int(value)
    return blockers


def read_ingest_quality_history(vault: Path, limit: int = 12) -> list[dict]:
    path = vault / ".claude" / "ingest.log"
    if not path.exists() or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []
    history: list[dict] = []
    for line in [line for entry in committed_ingest_log_entries(lines) for line in entry]:
        stripped = line.strip()
        if stripped.startswith("- 摄入质量："):
            history.append({
                "metrics": parse_metric_pairs(stripped.split("：", 1)[1]),
                "blockers": {},
            })
            continue
        if stripped.startswith("- 阻断原因：") and history:
            history[-1]["blockers"] = parse_blocker_pairs(stripped.split("：", 1)[1])
    return history[-limit:]


def intake_quality_trends(vault: Path, current_metrics: dict) -> dict:
    history = read_ingest_quality_history(vault)
    ready_rates = [
        float(item.get("metrics", {}).get("ready_rate"))
        for item in history
        if item.get("metrics", {}).get("ready_rate") is not None
    ]
    recurring_blockers: dict[str, int] = {}
    for item in history:
        for reason, count in (item.get("blockers") or {}).items():
            recurring_blockers[reason] = recurring_blockers.get(reason, 0) + int(count)

    current_ready_rate = float(current_metrics.get("ready_rate", 0))
    latest = ready_rates[-1] if ready_rates else None
    if latest is None:
        trend = "insufficient_history"
    elif current_ready_rate > latest:
        trend = "improving"
    elif current_ready_rate < latest:
        trend = "declining"
    else:
        trend = "stable"

    return {
        "history_runs": len(history),
        "historical_average_ready_rate": round(sum(ready_rates) / len(ready_rates), 3) if ready_rates else None,
        "historical_latest_ready_rate": latest,
        "current_ready_rate": current_ready_rate,
        "ready_rate_trend": trend,
        "recurring_blockers": dict(sorted(recurring_blockers.items())),
        "notes": [
            "history is parsed from prior .claude/ingest.log quality metric lines",
            "trend compares the current scan against the most recent logged ingest run",
        ],
    }


def duplicate_lookup(report: dict) -> dict[str, dict]:
    duplicates: dict[str, dict] = {}
    for item in report.get("duplicates") or []:
        for key in ("inbox_path", "markdown_path"):
            path = item.get(key)
            if path:
                duplicates[path] = item
    return duplicates


def placement_readiness(report: dict, vault: Path | None = None) -> dict:
    readiness: dict[str, dict] = {}
    protected = set(report.get("protected_paths") or [])
    hints = report.get("understanding_hints") or {}
    plans = report.get("encoding_plan") or {}
    duplicates = duplicate_lookup(report)
    for candidate in report.get("candidates") or []:
        path = candidate["path"]
        duplicate = duplicates.get(path) or duplicates.get(candidate.get("markdown_path"))
        if duplicate:
            canonical = duplicate.get("canonical") or {}
            readiness[path] = {
                "status": "blocked",
                "target": canonical.get("path"),
                "ownership": [],
                "required_actions": ["run apply-duplicates for exact duplicate"],
                "reasons": ["exact duplicate"],
                "duplicate": duplicate,
            }
            continue
        if candidate["status"] != "ready":
            readiness[path] = {
                "status": "blocked",
                "target": None,
                "ownership": [],
                "required_actions": [],
                "reasons": [candidate.get("reason") or candidate["status"]],
            }
            continue
        hint = hints.get(path, {})
        targets = hint.get("target_candidates") or []
        owners = hint.get("ownership_candidates") or []
        actions = hint.get("ownership_actions") or []
        reasons: list[str] = []
        required_actions: list[str] = []
        target = targets[0]["target"] if targets else None
        if not targets:
            reasons.append("no target candidate")
        notes = hint.get("notes") or []
        if any("ambiguous target topic candidates" in note for note in notes):
            reasons.append("ambiguous target")
        action_owners = [
            action["path"]
            for action in actions
            if action.get("action") == "create_area" and action.get("path")
        ]
        blocking_actions = [
            action
            for action in actions
            if action.get("action") != "create_area" or not action.get("path")
        ]
        if blocking_actions:
            reasons.append("ownership action required")
            required_actions.extend(action["path"] for action in blocking_actions if action.get("path"))
        ownership = [owner["path"] for owner in owners] + action_owners
        protected_owners = sorted(owner for owner in ownership if owner in protected)
        if protected_owners:
            reasons.append("ownership path protected")
            required_actions.extend(protected_owners)
        if target and vault is not None and (vault / target).exists():
            reasons.append("target path conflict")
            required_actions.append(target)
        plan = plans.get(path) or {}
        source_file = plan.get("source_file") or {}
        if target and source_file.get("required") and source_file.get("expected") and vault is not None:
            source_target = (Path(target).parent / source_file["expected"]).as_posix()
            if (vault / source_target).exists():
                reasons.append("source path conflict")
                required_actions.append(source_target)
        source_understanding = plan.get("source_understanding") or {}
        if source_understanding.get("status") == "blocked":
            reasons.append("source understanding required")
            required_actions.append(f"inspect original source: {path}")
        status = "ready" if target and ownership and not reasons else "blocked"
        readiness[path] = {
            "status": status,
            "target": target,
            "ownership": ownership,
            "required_actions": list(dict.fromkeys(required_actions)),
            "reasons": reasons,
        }
    return readiness


def handoff_next_action(action_or_path: str) -> str:
    if action_or_path.startswith(("Areas/", "Projects/")):
        return f"create/update ownership note: {action_or_path}"
    return f"resolve: {action_or_path}"


def meditate_handoff(report: dict) -> dict:
    handoff: dict[str, dict] = {}
    readiness = report.get("placement_readiness") or {}
    plans = report.get("encoding_plan") or {}
    hints = report.get("understanding_hints") or {}
    link_plans = report.get("link_verification_plan") or {}
    for candidate in report.get("candidates") or []:
        path = candidate["path"]
        ready = readiness.get(path, {})
        plan = plans.get(path, {})
        hint = hints.get(path, {})
        link_plan = link_plans.get(path) or {}
        blocked_by = list(ready.get("reasons") or [])
        next_actions = [handoff_next_action(item) for item in ready.get("required_actions") or []]
        target = ready.get("target")
        ownership = ready.get("ownership") or []

        checks: list[dict] = []
        placement_status = "pass" if ready.get("status") == "ready" else "blocked"
        checks.append({
            "name": "placement",
            "status": placement_status,
            "target": target,
            "ownership": ownership,
            "reasons": ready.get("reasons") or [],
        })

        fingerprint = candidate.get("source_fingerprint") or candidate.get("content_fingerprint")
        if candidate.get("status") == "ready" and fingerprint:
            checks.append({"name": "source_fingerprint", "status": "pass", "value": fingerprint})
        else:
            checks.append({"name": "source_fingerprint", "status": "blocked", "value": fingerprint})
            if "source_fingerprint missing" not in blocked_by:
                blocked_by.append("source_fingerprint missing")
            next_actions.append("record source_fingerprint from preprocessor")

        source_understanding = plan.get("source_understanding") or {}
        if source_understanding:
            checks.append({
                "name": "source_understanding",
                "status": source_understanding.get("status", "pass"),
                "modality": source_understanding.get("modality"),
                "reason": source_understanding.get("reason"),
                "required_action": source_understanding.get("required_action"),
            })
            if source_understanding.get("status") == "blocked":
                if "source understanding required" not in blocked_by:
                    blocked_by.append("source understanding required")
                next_actions.append(f"inspect original source: {path}")

        distillation = plan.get("distillation") or {}
        distillation_required = bool(distillation.get("required"))
        checks.append({
            "name": "distillation",
            "status": "required" if distillation_required else "optional",
            "reason": distillation.get("reason"),
            "sections": distillation.get("sections") or [],
        })

        source_file = plan.get("source_file") or {}
        checks.append({
            "name": "source_file",
            "status": "required" if source_file.get("required") else "not_required",
            "expected": source_file.get("expected"),
            "visible_link": source_file.get("visible_link"),
        })

        wikilinks = verified_wikilinks_for_path(report, path)
        unsafe_links = [
            link.get("wikilink")
            for link in link_plan.get("links") or []
            if link.get("status") == "blocked"
        ]
        link_status = "none" if link_plan.get("status") == "none" else "stem_safe" if link_plan.get("status") == "pass" else "blocked" if link_plan.get("status") == "blocked" else ("none" if not wikilinks else "stem_safe")
        if link_plan.get("status") == "blocked":
            link_status = "blocked"
            blocked_by.extend(link_plan.get("blocked_by") or ["unsafe wikilink candidate"])
            next_actions.append("remove or fix unsafe/missing wikilink candidates")
        checks.append({
            "name": "wikilinks",
            "status": link_status,
            "wikilinks": wikilinks,
            "unsafe": unsafe_links,
        })

        source_understanding_ok = not source_understanding or source_understanding.get("status") != "blocked"
        links_ok = link_plan.get("status") != "blocked"
        status = "ready" if placement_status == "pass" and source_understanding_ok and links_ok and fingerprint else "blocked"
        handoff[path] = {
            "status": status,
            "target": target,
            "ownership": ownership,
            "checks": checks,
            "blocked_by": list(dict.fromkeys(blocked_by)),
            "next_actions": list(dict.fromkeys(next_actions)),
            "notes": [
                "report-only; this describes whether first-pass organization has enough information for meditate to consume later",
                "ingest still must not reorganize already-ingested notes",
            ],
        }
    return handoff


def resource_index_plan(target: str) -> dict:
    parts = Path(target).parts
    if len(parts) < 3 or parts[0] != "Resources":
        return {"required": False}
    topic_dir = (Path("Resources") / parts[1]).as_posix()
    return {
        "required": True,
        "topic_dir": topic_dir,
        "readme": (Path(topic_dir) / "README.md").as_posix(),
        "command": f'python3 .claude/skills/meditate/scripts/generate_resource_index.py --dir "{topic_dir}"',
        "notes": "stage README only if the resource-index script updates it",
    }


def organization_plan(report: dict) -> dict:
    plans: dict[str, dict] = {}
    readiness = report.get("placement_readiness") or {}
    encoding_plans = report.get("encoding_plan") or {}
    hints = report.get("understanding_hints") or {}
    handoffs = report.get("meditate_handoff") or {}
    for candidate in report.get("candidates") or []:
        path = candidate["path"]
        ready = readiness.get(path, {})
        encoding = encoding_plans.get(path) or {}
        hint = hints.get(path) or {}
        handoff = handoffs.get(path) or {}
        target = ready.get("target")
        blocked_by = list(handoff.get("blocked_by") or ready.get("reasons") or [])
        next_actions = list(handoff.get("next_actions") or [])
        if ready.get("status") != "ready" or handoff.get("status") != "ready" or not target:
            if not next_actions:
                next_actions = [handoff_next_action(item) for item in ready.get("required_actions") or []]
            plans[path] = {
                "status": "blocked",
                "target": target,
                "markdown_move": None,
                "source_moves": [],
                "ownership_updates": ready.get("ownership") or [],
                "distillation": (encoding.get("distillation") or {}),
                "source_understanding": encoding.get("source_understanding") or {},
                "wikilinks": verified_wikilinks_for_path(report, path),
                "resource_index": resource_index_plan(target) if target else {"required": False},
                "commit_scope": [],
                "blocked_by": blocked_by,
                "next_actions": list(dict.fromkeys(next_actions)),
                "notes": ["resolve blockers before moving Inbox material"],
            }
            continue

        markdown_from = candidate.get("markdown_path") or path
        markdown_move = {"from": markdown_from, "to": target}
        source_moves: list[dict[str, str]] = []
        source_file = encoding.get("source_file") or {}
        if source_file.get("required") and source_file.get("expected"):
            source_moves.append({
                "from": path,
                "to": (Path(target).parent / source_file["expected"]).as_posix(),
            })
        ownership_updates = ready.get("ownership") or []
        wikilinks = verified_wikilinks_for_path(report, path)
        resource_index = resource_index_plan(target)
        commit_scope = [target, *[move["to"] for move in source_moves], *ownership_updates]
        if resource_index.get("required"):
            commit_scope.append(resource_index["readme"])
        actions = [
            f"git add {markdown_from}",
            f"git mv {markdown_from} {target}",
        ]
        for move in source_moves:
            actions.append(f"git add {move['from']}")
            actions.append(f"git mv {move['from']} {move['to']}")
        actions.extend([
            "add/update frontmatter from encoding_plan",
            f"add organize marker: {encoding.get('organize_marker', '> 整理自 Inbox，<YYYY-MM-DD>')}",
        ])
        if (encoding.get("distillation") or {}).get("required"):
            actions.append("prepend ## 提炼 and preserve evidence under ## 原文 / 摘录")
        if wikilinks:
            actions.append("add verified stem-safe wikilinks: " + ", ".join(f"[[{link}]]" for link in wikilinks))
        if ownership_updates:
            actions.append("update ownership notes: " + ", ".join(ownership_updates))
        if resource_index.get("required"):
            actions.append(resource_index["command"])
        actions.append("stage only commit_scope paths")
        plans[path] = {
            "status": "ready",
            "target": target,
            "markdown_move": markdown_move,
            "source_moves": source_moves,
            "ownership_updates": ownership_updates,
            "frontmatter": encoding.get("frontmatter") or {},
            "distillation": encoding.get("distillation") or {},
            "source_understanding": encoding.get("source_understanding") or {},
            "source_file": source_file,
            "organize_marker": encoding.get("organize_marker"),
            "wikilinks": wikilinks,
            "resource_index": resource_index,
            "commit_scope": list(dict.fromkeys(commit_scope)),
            "actions": actions,
            "blocked_by": [],
            "next_actions": [],
            "notes": ["report-only; model must verify content and execute with precise staging"],
        }
    return plans


def resource_scope_for_target(target: str | None) -> str | None:
    if not target:
        return None
    parts = Path(target).parts
    if len(parts) >= 2 and parts[0] == "Resources":
        return (Path("Resources") / parts[1]).as_posix()
    return None


def meditate_scope_suggestions(report: dict) -> dict:
    readiness = report.get("placement_readiness") or {}
    hints = report.get("understanding_hints") or {}
    scopes: list[str] = []
    reasons: list[dict] = []
    for candidate_path, ready in sorted(readiness.items()):
        if ready.get("status") != "ready":
            continue
        primary_scope = resource_scope_for_target(ready.get("target"))
        if not primary_scope:
            continue
        related_scopes: list[str] = []
        for target_candidate in (hints.get(candidate_path) or {}).get("target_candidates") or []:
            scope = resource_scope_for_target(target_candidate.get("target"))
            if not scope or scope == primary_scope or scope in related_scopes:
                continue
            related_scopes.append(scope)
            if len(related_scopes) >= 2:
                break
        for scope in [primary_scope, *related_scopes]:
            if scope not in scopes:
                scopes.append(scope)
        reasons.append({
            "candidate": candidate_path,
            "primary_scope": primary_scope,
            "related_scopes": related_scopes,
        })
    command = ""
    if scopes:
        scope_args = " ".join(f'--scope "{scope}"' for scope in scopes)
        command = (
            "python3 .claude/skills/meditate/scripts/optimize_vault.py "
            "--mode apply-safe --json /tmp/meditate.json --markdown /tmp/meditate.md "
            "--date <YYYY-MM-DD> --progress "
            f"{scope_args}"
        )
    return {
        "scopes": scopes,
        "command": command,
        "reasons": reasons,
        "notes": [
            "run after reviewed ingest apply-ready when new Resource material may change nearby topic structure",
            "includes ready Resource target topics plus up to two adjacent Resource candidate topics",
        ],
    }


def excerpt_candidates(source_text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", source_text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s+|\n+", source_text)
    excerpts: list[str] = []
    for part in parts:
        text = re.sub(r"\s+", " ", part).strip()
        if len(text) < 30:
            continue
        if re.fullmatch(r"!\[[^\]]*]\([^)]*\)", text) or re.fullmatch(r"\[[^\]]+]\([^)]*\)", text):
            continue
        if len(text) > 280:
            text = text[:277].rstrip() + "..."
        if text not in excerpts:
            excerpts.append(text)
    if excerpts:
        return excerpts
    chunks = [normalized[i : i + 240].strip() for i in range(0, min(len(normalized), 1200), 240)]
    return [chunk for chunk in chunks if chunk]


def evidence_excerpts(source_text: str, key_concepts: list[str], limit: int = 5) -> list[dict]:
    candidates = excerpt_candidates(source_text)
    scored: list[tuple[int, int, str, list[str]]] = []
    for idx, excerpt in enumerate(candidates):
        lowered = excerpt.lower()
        matched = [concept for concept in key_concepts if concept.lower() in lowered]
        score = len(matched)
        if score:
            scored.append((score, idx, excerpt, matched[:5]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict] = []
    seen: set[str] = set()
    for _score, _idx, excerpt, matched in scored:
        if excerpt in seen:
            continue
        seen.add(excerpt)
        selected.append({"text": excerpt, "matched_concepts": matched})
        if len(selected) >= limit:
            break
    for excerpt in candidates:
        if len(selected) >= min(3, limit):
            break
        if excerpt in seen:
            continue
        seen.add(excerpt)
        selected.append({"text": excerpt, "matched_concepts": []})
    return selected


def ordered_phrase_concepts(source_text: str, counts: Counter[str], limit: int = 7) -> list[str]:
    concepts: list[str] = []
    for excerpt in excerpt_candidates(source_text):
        sentence_phrases = 0
        for raw_first, raw_second in re.findall(r"\b([A-Za-z][A-Za-z0-9-]*)\s+([A-Za-z][A-Za-z0-9-]*)\b", excerpt):
            first = normalize_concept_token(raw_first)
            second = normalize_concept_token(raw_second)
            if not meaningful_concept_token(first) or not meaningful_concept_token(second) or first == second:
                continue
            phrase = f"{first} {second}"
            if counts.get(phrase, 0) <= 0 or phrase in concepts:
                continue
            concepts.append(phrase)
            sentence_phrases += 1
            if len(concepts) >= limit or sentence_phrases >= 2:
                break
        if len(concepts) >= limit:
            break
    return concepts


def distillation_key_concepts(source_text: str, counts: Counter[str], limit: int = 7) -> list[str]:
    ordered_phrases = ordered_phrase_concepts(source_text, counts, limit=limit)
    ranked = top_concepts(counts, limit=limit * 2)
    concepts: list[str] = []
    for concept in [*ordered_phrases, *ranked]:
        if concept not in concepts:
            concepts.append(concept)
        if len(concepts) >= limit:
            break
    return concepts


def hint_matched_concepts(hint: dict) -> list[str]:
    concepts: list[str] = []
    for group_name in ("target_candidates", "ownership_candidates", "link_candidates"):
        for item in hint.get(group_name) or []:
            for evidence in item.get("evidence") or []:
                if "matched concepts:" not in evidence:
                    continue
                raw = evidence.split("matched concepts:", 1)[1]
                for concept in [part.strip() for part in raw.split(",")]:
                    if concept and concept not in concepts:
                        concepts.append(concept)
    return concepts


def merge_key_concepts(preferred: list[str], extracted: list[str], limit: int = 7) -> list[str]:
    concepts: list[str] = []
    ordered = [
        *[concept for concept in preferred if " " in concept],
        *[concept for concept in extracted if " " in concept],
        *[concept for concept in preferred if " " not in concept],
        *[concept for concept in extracted if " " not in concept],
    ]
    for concept in ordered:
        if concept not in concepts:
            concepts.append(concept)
        if len(concepts) >= limit:
            break
    return concepts


def distillation_seed(vault: Path, candidates: list[Candidate], report: dict) -> dict:
    seeds: dict[str, dict] = {}
    readiness = report.get("placement_readiness") or {}
    hints = report.get("understanding_hints") or {}
    encoding_plans = report.get("encoding_plan") or {}
    handoffs = report.get("meditate_handoff") or {}
    for candidate in candidates:
        if candidate.status != "ready" or not candidate.markdown_path:
            continue
        path = candidate.path
        ready = readiness.get(path) or {}
        hint = hints.get(path) or {}
        encoding = encoding_plans.get(path) or {}
        handoff = handoffs.get(path) or {}
        source_understanding = encoding.get("source_understanding") or {}
        blocked_by = list(handoff.get("blocked_by") or ready.get("reasons") or [])
        if source_understanding.get("status") == "blocked" and "source understanding required" not in blocked_by:
            blocked_by.append("source understanding required")
        target = ready.get("target")
        topic = None
        targets = hint.get("target_candidates") or []
        if targets:
            topic = targets[0].get("topic")
        source_text = candidate_source_text(vault, candidate)
        source_counts = concept_counts_for_text(source_text)
        key_concepts = merge_key_concepts(
            hint_matched_concepts(hint),
            distillation_key_concepts(source_text, source_counts, limit=7),
            limit=7,
        )
        status = "ready" if handoff.get("status") == "ready" and not blocked_by else "blocked"
        excerpts = [] if status == "blocked" else evidence_excerpts(source_text, key_concepts, limit=5)
        target_dir = Path(target).parent.as_posix() if target else None
        use_context = {
            "target": target,
            "topic": topic,
            "topic_dir": (Path("Resources") / topic).as_posix() if topic else None,
            "target_dir": target_dir,
            "ownership": ready.get("ownership") or [],
            "wikilinks": verified_wikilinks_for_path(report, path),
        }
        seeds[path] = {
            "status": status,
            "target": target,
            "ownership": ready.get("ownership") or [],
            "key_concepts": key_concepts,
            "evidence_excerpts": excerpts,
            "use_context": use_context,
            "blocked_by": list(dict.fromkeys(blocked_by)),
            "draft_outline": [
                "## 提炼",
                "一句话判断：基于 key_concepts、use_context 和 evidence_excerpts 生成，不要凭空补充。",
                "关键点：从 evidence_excerpts 提炼 3-7 条，并保留对应证据。",
                "用途与下一步：说明如何服务承接 Area/Project。",
                "## 原文 / 摘录",
            ],
            "notes": ["report-only; excerpts are copied from converted/source Markdown for auditability"],
        }
    return seeds


def ownership_snippet(target: str | None, wikilink: str, topic: str | None) -> str:
    target_text = f"`{target}`" if target else "待定目标"
    topic_text = f"；主题：{topic}" if topic else ""
    return f"- [[{wikilink}]]：承接 {target_text}{topic_text}；用于后续提炼、补链和复用。"


def ownership_create_template(path: str, wikilink: str, topic: str | None, target: str | None) -> str:
    title = Path(path).stem
    target_text = f"`{target}`" if target else "待定目标"
    topic_text = topic or title
    return "\n".join([
        "---",
        f'title: "{title}"',
        "type: area",
        "status: active",
        "tags: []",
        "---",
        "",
        f"# {title}",
        "",
        "## 定位",
        f"持续承接 `{topic_text}` 相关资料、实践和复用判断。",
        "",
        "## 适用范围",
        f"- 新摄入资料：[[{wikilink}]]（{target_text}）",
        "",
        "## 下一步",
        "- 基于新资料补充关键问题、实践场景和后续连接。",
    ])


def ownership_update_plan(report: dict) -> dict:
    plans: dict[str, dict] = {}
    readiness = report.get("placement_readiness") or {}
    hints = report.get("understanding_hints") or {}
    for candidate in report.get("candidates") or []:
        if candidate.get("status") != "ready":
            continue
        path = candidate["path"]
        ready = readiness.get(path) or {}
        hint = hints.get(path) or {}
        targets = hint.get("target_candidates") or []
        target = ready.get("target") or (targets[0].get("target") if targets else None)
        topic = targets[0].get("topic") if targets else None
        wikilink = Path(target).stem if target else Path(candidate.get("markdown_path") or path).stem
        updates: list[dict] = []
        create_area_paths = {
            action.get("path")
            for action in hint.get("ownership_actions") or []
            if action.get("action") == "create_area" and action.get("path")
        }
        for owner_path in ready.get("ownership") or []:
            if owner_path in create_area_paths:
                continue
            updates.append({
                "action": "update_existing",
                "path": owner_path,
                "wikilink": wikilink,
                "target": target,
                "snippet": ownership_snippet(target, wikilink, topic),
                "notes": "append or merge into the ownership note after verifying the relationship",
            })
        for action in hint.get("ownership_actions") or []:
            if action.get("action") != "create_area":
                continue
            owner_path = action.get("path")
            action_target = action.get("target") or target
            action_topic = action.get("topic") or topic
            updates.append({
                "action": "create_area",
                "path": owner_path,
                "wikilink": Path(action_target).stem if action_target else wikilink,
                "target": action_target,
                "snippet": ownership_snippet(action_target, Path(action_target).stem if action_target else wikilink, action_topic),
                "template": ownership_create_template(owner_path, Path(action_target).stem if action_target else wikilink, action_topic, action_target),
                "notes": "create this owner before moving the Inbox material into Resources/Archive",
            })
        plans[path] = {
            "status": "ready" if ready.get("status") == "ready" and updates else "blocked",
            "target": target,
            "wikilink": wikilink,
            "updates": updates,
            "blocked_by": [] if ready.get("status") == "ready" and updates else ready.get("reasons") or ["ownership update required"],
            "notes": [
                "report-only; wikilinks must stay as bare filename stems",
                "do not include Inbox/ prefixes in ownership backlinks",
            ],
        }
    return plans


def yaml_scalar(value: object) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if not text:
        return '""'
    if re.search(r"[:#\[\]{}&*?|>%@`'\"]|\s$", text) or text.strip() != text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def quoted_yaml_string(value: object) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_field_value(key: str, value: object) -> str:
    if key == "source_fingerprint" and isinstance(value, str) and value.startswith("sha256:"):
        return value
    if key == "source_file":
        return quoted_yaml_string(value)
    if key in {"title", "created", "source", "source_url", "canonical_url", "description", "author", "published"}:
        return quoted_yaml_string(value)
    return yaml_scalar(value)


def target_frontmatter_type_and_status(target: str | None) -> tuple[str, str | None]:
    if not target:
        return "reference", None
    parts = Path(target).parts
    scope = parts[0] if parts else ""
    if scope == "Projects":
        return "project", "active"
    if scope == "Areas":
        return "area", "active"
    if scope == "Archive":
        return "archive", "archived"
    return "reference", None


def render_frontmatter(fields: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {yaml_scalar(item)}")
            continue
        lines.append(f"{key}: {yaml_field_value(key, value)}")
    lines.append("---")
    return "\n".join(lines)


def frontmatter_patch_plan(report: dict) -> dict:
    plans: dict[str, dict] = {}
    readiness = report.get("placement_readiness") or {}
    encoding_plans = report.get("encoding_plan") or {}
    handoffs = report.get("meditate_handoff") or {}
    for candidate in report.get("candidates") or []:
        if candidate.get("status") != "ready":
            continue
        path = candidate["path"]
        ready = readiness.get(path) or {}
        encoding = encoding_plans.get(path) or {}
        handoff = handoffs.get(path) or {}
        target = ready.get("target")
        recommended = dict((encoding.get("frontmatter") or {}).get("recommended") or {})
        note_type, status = target_frontmatter_type_and_status(target)
        fields: dict[str, object] = {
            "title": recommended.get("title") or Path(candidate.get("markdown_path") or path).stem,
            "type": note_type,
            "created": "<YYYY-MM-DD>",
        }
        if status:
            fields["status"] = status
        fields["tags"] = parse_inline_list(recommended.get("tags"))
        for key in ("source_url", "canonical_url", "source"):
            if recommended.get(key):
                fields[key] = recommended[key]
        source_file = encoding.get("source_file") or {}
        if source_file.get("required") and source_file.get("expected"):
            fields["source_file"] = source_file["expected"]
        if recommended.get("source_fingerprint"):
            fields["source_fingerprint"] = recommended["source_fingerprint"]
        for key in ("author", "published", "description"):
            if recommended.get(key):
                fields[key] = recommended[key]
        status_value = "ready" if handoff.get("status") == "ready" else "blocked"
        plans[path] = {
            "status": status_value,
            "target": target,
            "fields": fields,
            "yaml": render_frontmatter(fields),
            "insert_after": "line 1; replace existing frontmatter or insert before any body text",
            "blocked_by": [] if status_value == "ready" else handoff.get("blocked_by") or ready.get("reasons") or [],
            "notes": [
                "quote free-text YAML values so Obsidian properties parse reliably",
                "Resources notes use type: reference and must not use status: resource",
            ],
        }
    return plans


def safe_wikilink_stems(wikilinks: list[str]) -> list[str]:
    safe: list[str] = []
    for link in wikilinks:
        if link.startswith("Inbox/") or "/" in link or ":" in link:
            continue
        if link not in safe:
            safe.append(link)
    return safe


def render_content_body_patch(seed: dict, encoding: dict, visible_source_line: str | None) -> str:
    target = seed.get("target") or "待定目标"
    use_context = seed.get("use_context") or {}
    context_dir = use_context.get("topic_dir") or use_context.get("target_dir") or "待定归属"
    ownership = seed.get("ownership") or use_context.get("ownership") or []
    ownership_text = ", ".join(f"`{owner}`" for owner in ownership) if ownership else "无"
    wikilinks = safe_wikilink_stems(use_context.get("wikilinks") or [])
    excerpts = seed.get("evidence_excerpts") or []

    lines = [encoding.get("organize_marker") or "> 整理自 Inbox，<YYYY-MM-DD>"]
    if visible_source_line:
        lines.append(visible_source_line)
    lines.extend([
        "",
        "## 提炼",
        f"一句话判断：本资料归位到 `{target}`，由 {ownership_text} 承接，用于 `{context_dir}` 的后续提炼、补链和复用。",
        "",
        "关键点（基于原文摘录）：",
    ])
    copied_excerpt = False
    if excerpts:
        for item in excerpts[:5]:
            text = item.get("text")
            if text:
                lines.append(f"- {text}")
                copied_excerpt = True
    if not copied_excerpt:
        lines.append("- 原文信息不足，需保留原始正文供后续核验。")

    lines.extend([
        "",
        "用途与下一步：",
        f"- 归位：`{target}`",
        f"- 承接：{ownership_text}",
    ])
    if wikilinks:
        lines.append("- 连链：" + "、".join(f"[[{link}]]" for link in wikilinks))
    lines.extend([
        "",
        "## 原文 / 摘录",
        "- 以下保留原始正文或转换文本，不删除原文证据。",
    ])
    return "\n".join(lines)


def content_patch_plan(report: dict) -> dict:
    plans: dict[str, dict] = {}
    readiness = report.get("placement_readiness") or {}
    encoding_plans = report.get("encoding_plan") or {}
    handoffs = report.get("meditate_handoff") or {}
    seeds = report.get("distillation_seed") or {}
    for candidate in report.get("candidates") or []:
        if candidate.get("status") != "ready":
            continue
        path = candidate["path"]
        ready = readiness.get(path) or {}
        encoding = encoding_plans.get(path) or {}
        handoff = handoffs.get(path) or {}
        seed = seeds.get(path) or {}
        blocked_by = handoff.get("blocked_by") or ready.get("reasons") or seed.get("blocked_by") or []
        status = "ready" if ready.get("status") == "ready" and handoff.get("status") == "ready" and seed.get("status") == "ready" else "blocked"
        source_file = encoding.get("source_file") or {}
        visible_source_line = source_file.get("visible_link") if source_file.get("required") else None
        body_markdown = "" if status != "ready" else render_content_body_patch(seed, encoding, visible_source_line)
        use_context = seed.get("use_context") or {}
        plans[path] = {
            "status": status,
            "target": ready.get("target"),
            "insert_after": "frontmatter closing ---; before existing body",
            "visible_source_line": visible_source_line,
            "body_markdown": body_markdown,
            "wikilinks": safe_wikilink_stems(use_context.get("wikilinks") or []),
            "blocked_by": [] if status == "ready" else list(dict.fromkeys(blocked_by)),
            "notes": [
                "deterministic first-pass; key points are copied from source excerpts for auditability",
                "keep existing source text under ## 原文 / 摘录 when distilling",
            ],
        }
    return plans


def meditate_feedback(vault: Path, limit: int = 8) -> dict:
    rel = ".claude/meditate.log"
    path = vault / rel
    if not path.exists() or not path.is_file():
        return {"source": rel, "items": []}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return {"source": rel, "items": []}
    items: list[str] = []
    for line in reversed(lines[-240:]):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:].strip()
        if any(keyword.lower() in body.lower() for keyword in MEDITATE_FEEDBACK_KEYWORDS):
            items.append(body)
        if len(items) >= limit:
            break
    items.reverse()
    return {"source": rel, "items": items}


def find_duplicates(candidates: list[Candidate], notes: list[dict]) -> list[dict]:
    by_url: dict[str, list[dict]] = defaultdict(list)
    by_fp: dict[str, list[dict]] = defaultdict(list)
    for note in notes:
        for url in note["urls"]:
            by_url[url].append(note)
        if note["fingerprint"]:
            by_fp[note["fingerprint"]].append(note)
    duplicates: list[dict] = []
    for candidate in candidates:
        if candidate.status != "ready" or not candidate.markdown_path:
            continue
        evidence = []
        matches: dict[str, dict] = {}
        for url in candidate.source_urls or []:
            for note in by_url.get(url, []):
                matches[note["path"]] = note
                evidence.append({"type": "url", "value": url})
        candidate_fingerprint = candidate.source_fingerprint or candidate.content_fingerprint
        if candidate_fingerprint:
            for note in by_fp.get(candidate_fingerprint, []):
                matches[note["path"]] = note
                evidence.append({"type": "source_fingerprint", "value": candidate_fingerprint})
        if matches:
            canonical = sorted(matches.values(), key=lambda n: (not n["path"].startswith("Archive/"), n["path"]), reverse=True)[0]
            duplicates.append({
                "inbox_path": candidate.path,
                "markdown_path": candidate.markdown_path,
                "canonical": canonical,
                "evidence": evidence,
            })
    return duplicates


def selectable_only_paths(vault: Path) -> set[str]:
    selectable: set[str] = set()
    for path in inbox_files(vault):
        rel = safe_relative_inbox(path)
        selectable.add(rel)
        kind = classify(path)
        if kind not in {"markdown", "unsupported"}:
            selectable.add(safe_relative_inbox(path.with_suffix(".md")))
    return selectable


def make_report(vault: Path, convert: bool, only_paths: set[str] | None = None) -> dict:
    protected = sorted(protected_paths(vault))
    candidates: list[Candidate] = []
    paired_markdown_paths: set[str] = set()
    paths = sorted(inbox_files(vault), key=lambda item: (classify(item) == "markdown", item.name))
    markdown_reserved_by_source = {
        safe_relative_inbox(path.with_suffix(".md")): safe_relative_inbox(path)
        for path in paths
        if classify(path) not in {"markdown", "unsupported"}
    }
    for path in paths:
        inbox_rel = safe_relative_inbox(path)
        if inbox_rel in paired_markdown_paths:
            continue
        kind = classify(path)
        candidate = Candidate(path=inbox_rel, kind=kind, status="pending")
        if kind == "markdown" and inbox_rel in markdown_reserved_by_source:
            candidate.status = "left_in_inbox"
            candidate.reason = "same-name markdown conflict"
            candidates.append(candidate)
            continue
        if kind == "unsupported":
            candidate.status = "left_in_inbox"
            candidate.reason = "unsupported file type"
            candidates.append(candidate)
            continue
        markdown_rel = safe_relative_inbox(path if path.suffix.lower() == ".md" else path.with_suffix(".md"))
        if only_paths is not None and inbox_rel not in only_paths and markdown_rel not in only_paths:
            candidate.status = "left_in_inbox"
            candidate.reason = "not selected for apply-ready"
            candidates.append(candidate)
            continue
        if kind != "markdown" and (vault / markdown_rel).exists():
            if convert and can_pair_existing_conversion_markdown(vault, markdown_rel, inbox_rel):
                candidate.status = "ready"
                candidate.markdown_path = markdown_rel
                title, urls, fp, frontmatter = read_markdown_info(vault, candidate.markdown_path)
                candidate.title = title
                candidate.source_urls = urls
                candidate.source_fingerprint = fp
                candidate.content_fingerprint = fp
                candidate.source_frontmatter = frontmatter
                paired_markdown_paths.add(markdown_rel)
            else:
                candidate.status = "left_in_inbox"
                candidate.reason = "same-name markdown conflict"
            candidates.append(candidate)
            continue
        if convert and kind != "markdown":
            ok, reason = run_conversion(vault, path)
            if not ok:
                candidate.status = "left_in_inbox"
                candidate.reason = reason or "conversion failed"
                candidates.append(candidate)
                continue
        if kind == "markdown" or (vault / markdown_rel).exists():
            candidate.status = "ready"
            candidate.markdown_path = safe_relative_inbox(path) if kind == "markdown" else markdown_rel
            title, urls, fp, frontmatter = read_markdown_info(vault, candidate.markdown_path)
            candidate.title = title
            candidate.source_urls = urls
            candidate.source_fingerprint = fp
            candidate.content_fingerprint = fp
            candidate.source_frontmatter = frontmatter
        else:
            candidate.status = "needs_conversion"
            candidate.markdown_path = markdown_rel
        candidates.append(candidate)

    notes, invalid_fingerprints = existing_notes(vault)
    duplicates = find_duplicates(candidates, notes)
    knowledge_index = build_knowledge_index(vault)
    feedback = meditate_feedback(vault)
    intake_rules = [
        *intake_rules_from_meditate_feedback(feedback, knowledge_index),
        *intake_rules_from_ingest_history(vault, knowledge_index),
    ]
    report = {
        "protected_paths": protected,
        "inbox_count": len(candidates),
        "candidates": [candidate.__dict__ for candidate in candidates],
        "existing_note_count": len(notes),
        "invalid_fingerprints": invalid_fingerprints,
        "duplicates": duplicates,
        "encoding_plan": encoding_plan(vault, candidates),
        "intake_rules": intake_rules,
        "understanding_hints": understanding_hints(vault, candidates, knowledge_index, intake_rules),
        "meditate_feedback": feedback,
        "applied": {"duplicates": []},
        "skipped": [],
    }
    report["intake_learning_audit"] = intake_learning_audit(report)
    report["link_verification_plan"] = link_verification_plan(report, vault)
    report["placement_readiness"] = placement_readiness(report, vault)
    report["meditate_handoff"] = meditate_handoff(report)
    report["organization_plan"] = organization_plan(report)
    report["meditate_scope_suggestions"] = meditate_scope_suggestions(report)
    report["distillation_seed"] = distillation_seed(vault, candidates, report)
    report["ownership_update_plan"] = ownership_update_plan(report)
    report["frontmatter_patch_plan"] = frontmatter_patch_plan(report)
    report["content_patch_plan"] = content_patch_plan(report)
    report["intake_quality_metrics"] = intake_quality_metrics(report)
    report["intake_quality_trends"] = intake_quality_trends(vault, report["intake_quality_metrics"])
    return report


def duplicate_marker(text: str, canonical_wikilink: str, evidence: list[dict], date: str) -> str:
    if "重复内容，canonical" in text:
        return text
    ev = ", ".join(f"{item['type']}={item['value']}" for item in evidence)
    marker_lines = [
        f"> 重复内容，canonical：[[{canonical_wikilink}]]",
        f"> 重复依据：{ev}",
        f"> 整理自 Inbox，{date}",
    ]
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                merged = [*lines[: idx + 1], "", *marker_lines, "", *lines[idx + 1 :]]
                return "\n".join(merged).rstrip() + "\n"
    return "\n".join([*marker_lines, "", text]).rstrip() + "\n"


def canonical_wikilink_for_duplicate(canonical: dict) -> str:
    path = canonical.get("path")
    if path:
        return Path(path).stem
    return canonical.get("title") or "canonical"


def rewrite_source_file_frontmatter(text: str, source_file: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return text
    replacement = f'source_file: "{source_file}"'
    for idx in range(1, end):
        if re.match(r"^source_file:\s*", lines[idx]):
            lines[idx] = replacement
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    lines.insert(end, replacement)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def ensure_archive_frontmatter(text: str, target_rel: str, source_file: str | None = None) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        if source_file:
            return rewrite_source_file_frontmatter(text, source_file)
        return text
    fields: dict[str, object] = {
        "title": heading_title(text) or Path(target_rel).stem,
        "type": "archive",
        "status": "archived",
        "tags": [],
    }
    if source_file:
        fields["source_file"] = source_file
    return render_frontmatter(fields) + "\n\n" + text.lstrip()


def strip_stale_source_reference_lines(text: str, source_names: set[str]) -> str:
    if not source_names:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("原始文件：") and "source/" not in stripped and any(name in stripped for name in source_names):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def duplicate_archive_target(vault: Path, src: str, protected: set[str] | None = None) -> str:
    protected = protected or set()
    target_rel = f"Archive/Duplicates/{Path(src).name}"
    counter = 2
    while (vault / target_rel).exists() or target_rel in protected:
        target_rel = f"Archive/Duplicates/{Path(src).stem}-{counter}{Path(src).suffix}"
        counter += 1
    return target_rel


def duplicate_source_target(vault: Path, markdown_target: str, source_src: str, protected: set[str] | None = None) -> str:
    protected = protected or set()
    target_rel = (Path(markdown_target).parent / "source" / f"{Path(markdown_target).stem}{Path(source_src).suffix}").as_posix()
    counter = 2
    while (vault / target_rel).exists() or target_rel in protected:
        target_rel = (Path(markdown_target).parent / "source" / f"{Path(markdown_target).stem}-{counter}{Path(source_src).suffix}").as_posix()
        counter += 1
    return target_rel


def add_visible_source_link_once(text: str, visible_link: str) -> str:
    if visible_link in text:
        return text
    lines = text.splitlines()
    insert_at = 0
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                insert_at = idx + 1
                break
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    while insert_at < len(lines) and lines[insert_at].startswith("> "):
        insert_at += 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    lines.insert(insert_at, visible_link)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def apply_duplicates(vault: Path, report: dict, date: str) -> None:
    current_protected = protected_paths(vault)
    for item in report["duplicates"]:
        src = item["markdown_path"]
        src_path = vault / src
        if not src_path.exists():
            report["skipped"].append({"path": src, "reason": "markdown missing"})
            continue
        target_rel = duplicate_archive_target(vault, src, current_protected)
        source_moves: list[dict[str, str]] = []
        original_src = item.get("inbox_path")
        if original_src and original_src != src:
            original_path = vault / original_src
            if not original_path.exists():
                report["skipped"].append({"path": original_src, "reason": "source file missing"})
                continue
            source_target = duplicate_source_target(vault, target_rel, original_src, current_protected)
            source_moves.append({"from": original_src, "to": source_target})
        (vault / target_rel).parent.mkdir(parents=True, exist_ok=True)
        try:
            git_checked(vault, ["add", src])
            git_checked(vault, ["mv", src, target_rel])
            for move in source_moves:
                (vault / move["to"]).parent.mkdir(parents=True, exist_ok=True)
                git_checked(vault, ["add", move["from"]])
                git_checked(vault, ["mv", move["from"], move["to"]])
        except RuntimeError as exc:
            report["skipped"].append({"path": src, "reason": str(exc)})
            continue
        target_path = vault / target_rel
        text = target_path.read_text(encoding="utf-8")
        text = ensure_archive_frontmatter(
            text,
            target_rel,
            f"source/{Path(source_moves[0]['to']).name}" if source_moves else None,
        )
        text = duplicate_marker(text, canonical_wikilink_for_duplicate(item["canonical"]), item["evidence"], date)
        if source_moves:
            visible_link = f"原始文件：[[source/{Path(source_moves[0]['to']).name}]]"
            text = add_visible_source_link_once(text, visible_link)
        target_path.write_text(text, encoding="utf-8")
        git_checked(vault, ["add", target_rel])
        for move in source_moves:
            git_checked(vault, ["add", move["to"]])
        applied_duplicate = {
            "from": src,
            "to": target_rel,
            "canonical": item["canonical"],
            "evidence": item["evidence"],
        }
        if source_moves:
            applied_duplicate["source_moves"] = source_moves
        report["applied"]["duplicates"].append(applied_duplicate)


def git_checked(vault: Path, args: list[str]) -> None:
    completed = git(vault, args)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"git {' '.join(args)} failed").strip()
        raise RuntimeError(detail)


def wikilink_stems(text: str) -> set[str]:
    stems: set[str] = set()
    for raw in re.findall(r"\[\[([^\]]+)\]\]", text):
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            stems.add(normalize_name(target))
    return stems


def append_snippet_once(path: Path, snippet: str) -> None:
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if snippet in old:
        return
    snippet_links = wikilink_stems(snippet)
    if snippet_links and snippet_links & wikilink_stems(old):
        return
    separator = "\n" if old.endswith("\n") or not old else "\n\n"
    path.write_text(old + separator + snippet + "\n", encoding="utf-8")


def replace_frontmatter_scalar(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return text
    rendered = f"{key}: {value}"
    for idx in range(1, end):
        if re.match(rf"^{re.escape(key)}\s*:", lines[idx]):
            lines[idx] = rendered
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    lines.insert(end, rendered)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def refresh_final_source_fingerprint(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    frontmatter, _body = parse_frontmatter(text)
    existing = frontmatter_string(frontmatter, "source_fingerprint")
    if not existing:
        return
    final = fingerprint(text)
    if final == existing:
        return
    path.write_text(replace_frontmatter_scalar(text, "source_fingerprint", final), encoding="utf-8")


def original_body_for_apply(text: str) -> str:
    _frontmatter, body = parse_frontmatter(text)
    return body.strip()


def protected_apply_scope(plan: dict, current_protected: set[str]) -> list[str]:
    scope = set(plan.get("commit_scope") or [])
    for move in plan.get("source_moves") or []:
        if move.get("to"):
            scope.add(move["to"])
    markdown_move = plan.get("markdown_move") or {}
    if markdown_move.get("to"):
        scope.add(markdown_move["to"])
    return sorted(path for path in scope if path in current_protected)


def refresh_resource_index(vault: Path, plan: dict, report: dict, path: str) -> None:
    resource_index = plan.get("resource_index") or {}
    if not resource_index.get("required") or not resource_index.get("topic_dir"):
        return
    generator = vault / ".claude" / "skills" / "meditate" / "scripts" / "generate_resource_index.py"
    if not generator.exists():
        report.setdefault("warnings", []).append({
            "path": path,
            "reason": "resource index generator missing",
            "generator": generator.relative_to(vault).as_posix(),
        })
        return
    completed = run(vault, [sys.executable, generator.relative_to(vault).as_posix(), "--dir", resource_index["topic_dir"]])
    if completed.returncode != 0:
        report.setdefault("warnings", []).append({
            "path": path,
            "reason": "resource index refresh failed",
            "stderr": completed.stderr.strip(),
        })


def ready_candidate_paths(report: dict) -> set[str]:
    paths: set[str] = set()
    organization = report.get("organization_plan") or {}
    for candidate in report.get("candidates") or []:
        path = candidate.get("path")
        plan = organization.get(path) or {}
        if plan.get("status") != "ready":
            continue
        if path:
            paths.add(path)
        markdown_move = plan.get("markdown_move") or {}
        if markdown_move.get("from"):
            paths.add(markdown_move["from"])
    return paths


def validate_only_paths(report: dict, only_paths: set[str]) -> list[str]:
    ready_paths = ready_candidate_paths(report)
    return sorted(path for path in only_paths if path not in ready_paths)


def apply_ready(vault: Path, report: dict, date: str, only_paths: set[str] | None = None) -> None:
    report.setdefault("applied", {}).setdefault("ready", [])
    audit = report.setdefault("apply_selection_audit", {})
    audit["selected_only"] = sorted(only_paths) if only_paths is not None else []
    audit["applied_ready"] = []
    audit["skipped_ready_not_selected"] = [
        candidate.get("path")
        for candidate in report.get("candidates", [])
        if candidate.get("reason") == "not selected for apply-ready" and candidate.get("path")
    ]
    audit["unmatched_only"] = validate_only_paths(report, only_paths) if only_paths is not None else []
    if audit["unmatched_only"]:
        raise RuntimeError("unmatched --only path: " + ", ".join(audit["unmatched_only"]))
    organization = report.get("organization_plan") or {}
    frontmatter_plans = report.get("frontmatter_patch_plan") or {}
    content_plans = report.get("content_patch_plan") or {}
    ownership_plans = report.get("ownership_update_plan") or {}
    for candidate in report.get("candidates") or []:
        path = candidate.get("path")
        plan = organization.get(path) or {}
        if plan.get("status") != "ready":
            continue
        markdown_move = plan.get("markdown_move") or {}
        markdown_from = markdown_move.get("from")
        target = markdown_move.get("to")
        if not markdown_from or not target:
            report.setdefault("skipped", []).append({"path": path, "reason": "missing markdown move"})
            continue
        if only_paths is not None and path not in only_paths and markdown_from not in only_paths:
            report.setdefault("skipped", []).append({"path": path, "reason": "not selected for apply-ready"})
            audit["skipped_ready_not_selected"].append(path)
            continue
        source_path = vault / markdown_from
        target_path = vault / target
        protected_scope = protected_apply_scope(plan, protected_paths(vault))
        if protected_scope:
            report.setdefault("skipped", []).append({
                "path": path,
                "reason": "protected paths changed after report",
                "paths": protected_scope,
            })
            continue
        if not source_path.exists():
            report.setdefault("skipped", []).append({"path": path, "reason": "markdown missing"})
            continue
        if target_path.exists():
            report.setdefault("skipped", []).append({"path": path, "reason": "target already exists"})
            continue
        source_move_conflicts: list[str] = []
        source_move_missing: list[str] = []
        for move in plan.get("source_moves") or []:
            move_from = move.get("from")
            move_to = move.get("to")
            if not move_from or not move_to:
                continue
            if not (vault / move_from).exists():
                source_move_missing.append(move_from)
            if (vault / move_to).exists():
                source_move_conflicts.append(move_to)
        if source_move_missing:
            report.setdefault("skipped", []).append({
                "path": path,
                "reason": "source file missing",
                "paths": sorted(source_move_missing),
            })
            continue
        if source_move_conflicts:
            report.setdefault("skipped", []).append({
                "path": path,
                "reason": "source target already exists",
                "paths": sorted(source_move_conflicts),
            })
            continue

        original_text = source_path.read_text(encoding="utf-8")
        original_body = original_body_for_apply(original_text)
        source_names_to_strip = {
            Path(move.get("from", "")).name
            for move in plan.get("source_moves") or []
            if move.get("from")
        }
        original_body = strip_stale_source_reference_lines(original_body, source_names_to_strip)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        git_checked(vault, ["add", markdown_from])
        git_checked(vault, ["mv", markdown_from, target])

        for move in plan.get("source_moves") or []:
            move_from = move.get("from")
            move_to = move.get("to")
            if not move_from or not move_to:
                continue
            (vault / move_to).parent.mkdir(parents=True, exist_ok=True)
            git_checked(vault, ["add", move_from])
            git_checked(vault, ["mv", move_from, move_to])

        yaml = ((frontmatter_plans.get(path) or {}).get("yaml") or render_frontmatter({})).replace("<YYYY-MM-DD>", date)
        body_markdown = ((content_plans.get(path) or {}).get("body_markdown") or "").replace("<YYYY-MM-DD>", date)
        pieces = [yaml.strip(), body_markdown.strip(), original_body]
        target_path.write_text("\n\n".join(piece for piece in pieces if piece).rstrip() + "\n", encoding="utf-8")
        refresh_final_source_fingerprint(target_path)

        for update in (ownership_plans.get(path) or {}).get("updates") or []:
            update_path = update.get("path")
            snippet = update.get("snippet")
            if not update_path or not snippet:
                continue
            owner_path = vault / update_path
            if update.get("action") == "create_area" and not owner_path.exists():
                owner_path.parent.mkdir(parents=True, exist_ok=True)
                owner_path.write_text((update.get("template") or snippet).rstrip() + "\n", encoding="utf-8")
            elif owner_path.exists():
                append_snippet_once(owner_path, snippet)

        refresh_resource_index(vault, plan, report, path)

        for scope_path in plan.get("commit_scope") or []:
            if (vault / scope_path).exists():
                git_checked(vault, ["add", scope_path])
        applied_ready = {"from": markdown_from, "to": target}
        if plan.get("source_moves"):
            applied_ready["source_moves"] = plan.get("source_moves") or []
        report["applied"]["ready"].append(applied_ready)
        audit["applied_ready"].append(path)
    audit["skipped_ready_not_selected"] = sorted(dict.fromkeys(audit["skipped_ready_not_selected"]))


def applied_ready_plans(report: dict) -> list[tuple[dict, dict]]:
    applied = {(item.get("from"), item.get("to")) for item in (report.get("applied", {}).get("ready") or [])}
    if not applied:
        return []
    plans: list[tuple[dict, dict]] = []
    organization = report.get("organization_plan") or {}
    for candidate in report.get("candidates") or []:
        plan = organization.get(candidate.get("path")) or {}
        move = plan.get("markdown_move") or {}
        if (move.get("from"), move.get("to")) in applied:
            plans.append((candidate, plan))
    return plans


def applied_ready_commit_paths(report: dict) -> list[str]:
    paths: list[str] = []
    for _candidate, plan in applied_ready_plans(report):
        move = plan.get("markdown_move") or {}
        paths.extend(path for path in (move.get("from"), move.get("to")) if path)
        for source_move in plan.get("source_moves") or []:
            paths.extend(path for path in (source_move.get("from"), source_move.get("to")) if path)
        paths.extend(plan.get("commit_scope") or [])
    return list(dict.fromkeys(paths))


def git_knows_path(vault: Path, path: str) -> bool:
    if (vault / path).exists():
        return True
    completed = git(vault, ["status", "--short", "--", path])
    return completed.returncode == 0 and bool(completed.stdout.strip())


def applied_ready_commit_summary(report: dict) -> str:
    targets = [Path(item["to"]).stem for item in (report.get("applied", {}).get("ready") or []) if item.get("to")]
    if not targets:
        return "no ready items"
    if len(targets) == 1:
        return targets[0]
    return f"{len(targets)} ready items"


def commit_applied_ready(vault: Path, report: dict) -> str | None:
    paths = [path for path in applied_ready_commit_paths(report) if git_knows_path(vault, path)]
    if not paths:
        return None
    message = f"ingest: {applied_ready_commit_summary(report)}"
    git_checked(vault, ["commit", "-m", message, "--", *paths])
    completed = git(vault, ["log", "-1", "--format=%H"])
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git log -1 failed").strip()
        raise RuntimeError(detail)
    commit_hash = completed.stdout.strip()
    report.setdefault("applied", {})["commit"] = commit_hash
    return commit_hash


def applied_ready_ownership_notes(report: dict) -> list[str]:
    owners: list[str] = []
    for _candidate, plan in applied_ready_plans(report):
        owners.extend(plan.get("ownership_updates") or [])
    return list(dict.fromkeys(owners))


def log_quality_metric_line(report: dict) -> str:
    metrics = report.get("intake_quality_metrics") or {}
    return (
        "- 摄入质量："
        f"ready_rate={metrics.get('ready_rate', 0)}, "
        f"ready_for_apply={metrics.get('ready_for_apply', 0)}, "
        f"blocked={metrics.get('blocked', 0)}, "
        f"handoff_ready={metrics.get('handoff_ready', 0)}, "
        f"handoff_blocked={metrics.get('handoff_blocked', 0)}, "
        f"learning_rules_applied={metrics.get('learning_rules_applied', 0)}"
    )


def log_blocker_metric_line(report: dict) -> str:
    blockers = (report.get("intake_quality_metrics") or {}).get("blocked_by_reason") or {}
    if not blockers:
        return "- 阻断原因：无"
    return "- 阻断原因：" + ", ".join(f"{reason}={count}" for reason, count in blockers.items())


def left_inbox_reason(report: dict, candidate: dict) -> str:
    path = candidate.get("path") or candidate.get("markdown_path") or "unknown"
    skipped_reasons = [
        item.get("reason")
        for item in report.get("skipped", [])
        if item.get("path") == path and item.get("reason")
    ]
    if skipped_reasons:
        return ", ".join(dict.fromkeys(skipped_reasons))
    if candidate.get("reason"):
        return candidate["reason"]
    plan = (report.get("organization_plan") or {}).get(path) or {}
    blocked_by = plan.get("blocked_by") or []
    if blocked_by:
        return ", ".join(blocked_by)
    handoff = (report.get("meditate_handoff") or {}).get(path) or {}
    blocked_by = handoff.get("blocked_by") or []
    if blocked_by:
        return ", ".join(blocked_by)
    readiness = (report.get("placement_readiness") or {}).get(path) or {}
    reasons = readiness.get("reasons") or []
    if reasons:
        return ", ".join(reasons)
    return candidate.get("reason") or candidate.get("status") or "unknown"


def log_left_inbox_lines(report: dict, left: list[dict]) -> list[str]:
    if not left:
        return ["- 留在 Inbox：无"]
    return [
        f"- 留在 Inbox：{candidate.get('path') or candidate.get('markdown_path')}（{left_inbox_reason(report, candidate)}）"
        for candidate in left
    ]


def applied_duplicate_moves(report: dict) -> list[dict]:
    moves: list[dict] = []
    for item in (report.get("applied") or {}).get("duplicates") or []:
        if item.get("from") and item.get("to"):
            moves.append({"from": item["from"], "to": item["to"]})
        for move in item.get("source_moves") or []:
            if move.get("from") and move.get("to"):
                moves.append({"from": move["from"], "to": move["to"]})
    return moves


def applied_ready_moves(report: dict) -> list[dict]:
    moves: list[dict] = []
    for item in (report.get("applied") or {}).get("ready") or []:
        if item.get("from") and item.get("to"):
            moves.append({"from": item["from"], "to": item["to"]})
        for move in item.get("source_moves") or []:
            if move.get("from") and move.get("to"):
                moves.append({"from": move["from"], "to": move["to"]})
    return moves


def append_log(vault: Path, report: dict, date: str, mode: str) -> None:
    path = vault / ".claude" / "ingest.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    ready_moves = applied_ready_moves(report)
    duplicate_moves = applied_duplicate_moves(report)
    applied_from = {item.get("from") for item in [*ready_moves, *duplicate_moves]}
    left = [c for c in report["candidates"] if c.get("path") not in applied_from and c.get("markdown_path") not in applied_from]
    moved = [f"- {item['from']} → {item['to']}" for item in [*ready_moves, *duplicate_moves]]
    owners = [f"[[{Path(owner).stem}]]" for owner in applied_ready_ownership_notes(report)]
    commit_hash = report.get("applied", {}).get("commit") or "无"
    entry = [
        f"## {date} manual",
        f"- 脚本模式：{mode}",
        f"- Inbox 候选：{report['inbox_count']}",
        f"- 完全重复：{len(report['duplicates'])}",
        f"- 已归档重复：{len(report['applied']['duplicates'])}",
        *(moved or ["- 无移动"]),
        f"- 承接笔记：{', '.join(owners) if owners else '无'}",
        *log_left_inbox_lines(report, left),
        log_quality_metric_line(report),
        log_blocker_metric_line(report),
        f"commit: {commit_hash}",
        "",
    ]
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(old + ("\n" if old and not old.endswith("\n") else "") + "\n".join(entry), encoding="utf-8")


def summarize_hint_item(item: dict) -> str:
    evidence = "; ".join(item.get("evidence") or [])
    if evidence:
        return f"score {item.get('score', 0)}; {evidence}"
    return f"score {item.get('score', 0)}"


def append_understanding_hints(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 摄入理解提示"])
    hints = report.get("understanding_hints") or {}
    if not hints:
        lines.append("- 无")
        return
    for path, hint in sorted(hints.items()):
        lines.append(f"- `{path}`")
        targets = hint.get("target_candidates") or []
        owners = hint.get("ownership_candidates") or []
        actions = hint.get("ownership_actions") or []
        links = hint.get("link_candidates") or []
        notes = hint.get("notes") or []
        if targets:
            for item in targets:
                lines.append(f"  - 目标候选：{item['target']}（{summarize_hint_item(item)}）")
        else:
            lines.append("  - 目标候选：无")
        if owners:
            for item in owners:
                lines.append(f"  - 承接候选：{item['path']}（{summarize_hint_item(item)}）")
        else:
            lines.append("  - 承接候选：无")
        for item in actions:
            if item.get("action") == "create_area":
                lines.append(f"  - 承接动作：新建 Area `{item['path']}` 承接 `{item['target']}`（{summarize_hint_item(item)}）")
        if links:
            for item in links:
                lines.append(f"  - 补链候选：[[{item['wikilink']}]]（{summarize_hint_item(item)}）")
        else:
            lines.append("  - 补链候选：无")
        for note in notes:
            lines.append(f"  - 备注：{note}")


def append_encoding_plan(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 首次编码计划"])
    plans = report.get("encoding_plan") or {}
    if not plans:
        lines.append("- 无")
        return
    for path, plan in sorted(plans.items()):
        frontmatter = plan.get("frontmatter", {}).get("recommended", {})
        distillation = plan.get("distillation", {})
        source_file = plan.get("source_file", {})
        source_understanding = plan.get("source_understanding", {})
        lines.append(f"- `{path}`")
        lines.append(f"  - Markdown：`{plan.get('markdown_path')}`")
        lines.append(f"  - frontmatter：title/type/created/tags/source_fingerprint；source_fingerprint=`{frontmatter.get('source_fingerprint', '待确认')}`")
        if frontmatter.get("source_url"):
            lines.append(f"  - source_url：`{frontmatter['source_url']}`")
        if source_understanding:
            action = source_understanding.get("required_action")
            suffix = f"；需处理：{action}" if action else ""
            lines.append(
                f"  - 源素材理解：{source_understanding.get('status')}（{source_understanding.get('modality')}；"
                f"{source_understanding.get('reason')}）{suffix}"
            )
        if distillation.get("required"):
            sections = "、".join(distillation.get("sections") or [])
            lines.append(f"  - 提炼：必须（{distillation.get('reason')}；保留 {sections}）")
        else:
            lines.append(f"  - 提炼：按内容判断（{distillation.get('reason')}）")
        if source_file.get("required"):
            lines.append(f"  - 原始文件：`{source_file.get('expected')}`；可见链接 `{source_file.get('visible_link')}`")
        lines.append(f"  - 备注：{'; '.join(plan.get('notes') or [])}")


def append_intake_rules(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 摄入学习规则"])
    rules = report.get("intake_rules") or []
    if not rules:
        lines.append("- 无")
        return
    for rule in rules:
        if rule.get("action") == "ensure_ownership":
            lines.append(
                f"- `{rule['topic_path']}`：摄入新资料时确保承接到 `{rule['suggested_owner']}`"
                f"（来源：{rule['source']}；{rule['evidence']}）"
            )
        elif rule.get("action") == "prefer_ownership":
            lines.append(
                f"- `{rule['topic_path']}`：历史摄入优先承接到 `{rule['suggested_owner']}`"
                f"（来源：{rule['source']}；{rule['evidence']}）"
            )
        elif rule.get("action") == "prefer_topic":
            lines.append(
                f"- `{rule['from_topic_path']}`：结构反馈优先归入 `{rule['topic_path']}`"
                f"（来源：{rule['source']}；{rule['evidence']}）"
            )
        elif rule.get("action") == "prefer_link":
            terms = " ↔ ".join(rule.get("terms") or [])
            lines.append(
                f"- `{terms}`：补链反馈优先连链"
                f"（来源：{rule['source']}；{rule['evidence']}）"
            )
        else:
            lines.append(f"- {rule}")


def summarize_applied_learning_rules(applied: list[dict]) -> list[dict]:
    grouped: dict[tuple[object, ...], dict] = {}
    for item in applied:
        key = (
            item.get("candidate"),
            item.get("action"),
            item.get("source"),
            item.get("effect"),
            item.get("target"),
        )
        if key not in grouped:
            grouped[key] = {**item, "count": 0, "evidence_samples": []}
        grouped_item = grouped[key]
        grouped_item["count"] += 1
        evidence = item.get("rule_evidence")
        if evidence and evidence not in grouped_item["evidence_samples"]:
            grouped_item["evidence_samples"].append(evidence)
    return list(grouped.values())


def append_intake_learning_audit(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 摄入学习审计"])
    audit = report.get("intake_learning_audit") or {}
    if not audit:
        lines.append("- 无")
        return
    lines.append(f"- 规则总数：{audit.get('rules_total', 0)}")
    by_action = audit.get("by_action") or {}
    if by_action:
        lines.append("- 按动作：" + ", ".join(f"{action}={count}" for action, count in sorted(by_action.items())))
    applied = audit.get("applied") or []
    if applied:
        lines.append("- 本次命中：")
        for item in summarize_applied_learning_rules(applied):
            count = item.get("count", 1)
            samples = item.get("evidence_samples") or []
            evidence = samples[0] if samples else item.get("rule_evidence")
            evidence_text = f"{count} 条规则；例：{evidence}" if count > 1 else str(evidence or "")
            lines.append(
                f"  - `{item.get('candidate')}`：{item.get('action')} / {item.get('source')} "
                f"→ {item.get('effect')} `{item.get('target')}`（{evidence_text}）"
            )
    else:
        lines.append("- 本次命中：无")
    unapplied = audit.get("unapplied_rules") or []
    if unapplied:
        lines.append(f"- 未命中规则：{len(unapplied)}")
    for note in audit.get("notes") or []:
        lines.append(f"- 备注：{note}")


def append_intake_quality_metrics(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 摄入质量指标"])
    metrics = report.get("intake_quality_metrics") or {}
    if not metrics:
        lines.append("- 无")
        return
    lines.append(
        "- "
        f"candidates_total={metrics.get('candidates_total', 0)}, "
        f"ready_for_apply={metrics.get('ready_for_apply', 0)}, "
        f"blocked={metrics.get('blocked', 0)}, "
        f"ready_rate={metrics.get('ready_rate', 0)}"
    )
    lines.append(
        "- "
        f"handoff_ready={metrics.get('handoff_ready', 0)}, "
        f"handoff_blocked={metrics.get('handoff_blocked', 0)}, "
        f"source_understanding_blocked={metrics.get('source_understanding_blocked', 0)}"
    )
    lines.append(
        "- "
        f"learning_rules_total={metrics.get('learning_rules_total', 0)}, "
        f"learning_rules_applied={metrics.get('learning_rules_applied', 0)}"
    )
    if metrics.get("excluded_by_selection"):
        lines.append(f"- excluded_by_selection={metrics.get('excluded_by_selection', 0)}")
    blocked = metrics.get("blocked_by_reason") or {}
    if blocked:
        lines.append("- 阻断原因：" + ", ".join(f"{reason}={count}" for reason, count in blocked.items()))
    else:
        lines.append("- 阻断原因：无")
    for note in metrics.get("notes") or []:
        lines.append(f"- 备注：{note}")


def append_intake_quality_trends(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 摄入质量趋势"])
    trends = report.get("intake_quality_trends") or {}
    if not trends:
        lines.append("- 无")
        return
    lines.append(
        "- "
        f"history_runs={trends.get('history_runs', 0)}, "
        f"historical_average_ready_rate={trends.get('historical_average_ready_rate')}, "
        f"historical_latest_ready_rate={trends.get('historical_latest_ready_rate')}, "
        f"current_ready_rate={trends.get('current_ready_rate')}, "
        f"ready_rate_trend={trends.get('ready_rate_trend')}"
    )
    blockers = trends.get("recurring_blockers") or {}
    if blockers:
        lines.append("- 历史阻断原因：" + ", ".join(f"{reason}={count}" for reason, count in blockers.items()))
    else:
        lines.append("- 历史阻断原因：无")
    for note in trends.get("notes") or []:
        lines.append(f"- 备注：{note}")


def append_frontmatter_patch_plan(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 元数据写入计划"])
    plans = report.get("frontmatter_patch_plan") or {}
    if not plans:
        lines.append("- 无")
        return
    for path, plan in sorted(plans.items()):
        if plan.get("status") != "ready":
            blocked_by = ", ".join(plan.get("blocked_by") or [])
            lines.append(f"- `{path}`：blocked（{blocked_by or 'unknown'}）")
            continue
        lines.append(f"- `{path}`：ready → `{plan.get('target')}`")
        lines.append("  - YAML：")
        for line in (plan.get("yaml") or "").splitlines():
            lines.append(f"    {line}")
        for note in plan.get("notes") or []:
            lines.append(f"  - 备注：{note}")


def append_link_verification_plan(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 双链验证计划"])
    plans = report.get("link_verification_plan") or {}
    if not plans:
        lines.append("- 无")
        return
    for path, plan in sorted(plans.items()):
        if plan.get("status") == "none":
            lines.append(f"- `{path}`：none")
        elif plan.get("status") == "pass":
            lines.append(f"- `{path}`：pass")
        else:
            blocked_by = ", ".join(plan.get("blocked_by") or [])
            lines.append(f"- `{path}`：blocked（{blocked_by or 'unknown'}）")
        for link in plan.get("links") or []:
            status = link.get("status")
            lines.append(
                f"  - [[{link.get('wikilink')}]] → `{link.get('target_path')}`"
                f"（{status}; exists={link.get('exists')}; stem={link.get('stem_matches')}; safe={link.get('safe')}）"
            )
        for note in plan.get("notes") or []:
            lines.append(f"  - 备注：{note}")


def append_content_patch_plan(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 正文写入计划"])
    plans = report.get("content_patch_plan") or {}
    if not plans:
        lines.append("- 无")
        return
    for path, plan in sorted(plans.items()):
        if plan.get("status") != "ready":
            blocked_by = ", ".join(plan.get("blocked_by") or [])
            lines.append(f"- `{path}`：blocked（{blocked_by or 'unknown'}）")
            continue
        lines.append(f"- `{path}`：ready → `{plan.get('target')}`")
        if plan.get("visible_source_line"):
            lines.append(f"  - 原始文件行：{plan['visible_source_line']}")
        if plan.get("wikilinks"):
            lines.append("  - 补链：" + ", ".join(f"[[{link}]]" for link in plan["wikilinks"]))
        lines.append("  - 正文草案：")
        for line in (plan.get("body_markdown") or "").splitlines():
            lines.append(f"    {line}")
        for note in plan.get("notes") or []:
            lines.append(f"  - 备注：{note}")


def append_placement_readiness(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 归位就绪度"])
    readiness = report.get("placement_readiness") or {}
    if not readiness:
        lines.append("- 无")
        return
    for path, item in sorted(readiness.items()):
        if item.get("status") == "ready":
            owners = ", ".join(item.get("ownership") or [])
            lines.append(f"- `{path}`：ready → `{item.get('target')}`；承接：{owners}")
            continue
        reasons = ", ".join(item.get("reasons") or [])
        actions = ", ".join(item.get("required_actions") or [])
        suffix = f"；需处理：{actions}" if actions else ""
        lines.append(f"- `{path}`：blocked（{reasons or 'unknown'}）{suffix}")


def summarize_handoff_check(check: dict) -> str:
    name = check.get("name")
    status = check.get("status")
    if name == "placement":
        return f"归位：{status}"
    if name == "source_fingerprint":
        value = check.get("value") or "缺失"
        return f"指纹：{status} `{value}`"
    if name == "source_understanding":
        action = check.get("required_action")
        suffix = f"；需处理：{action}" if action else ""
        return f"源素材理解：{status}（{check.get('modality')}；{check.get('reason')}）{suffix}"
    if name == "distillation":
        sections = "、".join(check.get("sections") or [])
        suffix = f"；{sections}" if sections else ""
        return f"提炼：{status}{suffix}"
    if name == "source_file":
        expected = check.get("expected")
        suffix = f" `{expected}`" if expected else ""
        return f"原始文件：{status}{suffix}"
    if name == "wikilinks":
        links = ", ".join(f"[[{link}]]" for link in check.get("wikilinks") or [])
        return f"补链：{status}" + (f" {links}" if links else "")
    return f"{name}：{status}"


def append_ownership_update_plan(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 承接更新计划"])
    plans = report.get("ownership_update_plan") or {}
    if not plans:
        lines.append("- 无")
        return
    for path, plan in sorted(plans.items()):
        target = plan.get("target") or "待定"
        lines.append(f"- `{path}`：{plan.get('status')} → `{target}`；反链：[[{plan.get('wikilink')}]]")
        updates = plan.get("updates") or []
        if not updates:
            blocked_by = ", ".join(plan.get("blocked_by") or [])
            lines.append(f"  - 阻断：{blocked_by or 'ownership update required'}")
            continue
        for update in updates:
            lines.append(f"  - {update.get('action')} `{update.get('path')}`：{update.get('snippet')}")
            if update.get("template"):
                compact = " / ".join(line for line in update["template"].splitlines() if line.strip())[:260]
                lines.append(f"    - 新建模板：{compact}")
        for note in plan.get("notes") or []:
            lines.append(f"  - 备注：{note}")


def append_meditate_handoff(lines: list[str], report: dict) -> None:
    lines.extend(["", "## meditate 交接清单"])
    handoff = report.get("meditate_handoff") or {}
    if not handoff:
        lines.append("- 无")
        return
    for path, item in sorted(handoff.items()):
        if item.get("status") == "ready":
            owners = ", ".join(item.get("ownership") or [])
            lines.append(f"- `{path}`：ready → `{item.get('target')}`；承接：{owners}")
        else:
            blocked_by = ", ".join(item.get("blocked_by") or [])
            next_actions = ", ".join(item.get("next_actions") or [])
            suffix = f"；下一步：{next_actions}" if next_actions else ""
            lines.append(f"- `{path}`：blocked（{blocked_by or 'unknown'}）{suffix}")
        checks = "；".join(summarize_handoff_check(check) for check in item.get("checks") or [])
        if checks:
            lines.append(f"  - 检查：{checks}")
        for note in item.get("notes") or []:
            lines.append(f"  - 备注：{note}")


def append_organization_plan(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 首次归位执行计划"])
    plans = report.get("organization_plan") or {}
    if not plans:
        lines.append("- 无")
        return
    for path, plan in sorted(plans.items()):
        if plan.get("status") != "ready":
            blocked_by = ", ".join(plan.get("blocked_by") or [])
            next_actions = ", ".join(plan.get("next_actions") or [])
            suffix = f"；下一步：{next_actions}" if next_actions else ""
            lines.append(f"- `{path}`：blocked（{blocked_by or 'unknown'}）{suffix}")
            continue
        lines.append(f"- `{path}`：ready → `{plan.get('target')}`")
        markdown_move = plan.get("markdown_move") or {}
        if markdown_move:
            lines.append(f"  - Markdown：`{markdown_move.get('from')}` → `{markdown_move.get('to')}`")
        for move in plan.get("source_moves") or []:
            lines.append(f"  - 原始文件：`{move.get('from')}` → `{move.get('to')}`")
        if plan.get("ownership_updates"):
            lines.append("  - 承接更新：" + ", ".join(f"`{owner}`" for owner in plan["ownership_updates"]))
        if (plan.get("distillation") or {}).get("required"):
            lines.append("  - 提炼：必须补 `## 提炼` 并保留 `## 原文 / 摘录`")
        elif plan.get("distillation"):
            lines.append("  - 提炼：按内容判断")
        if plan.get("wikilinks"):
            lines.append("  - 补链：" + ", ".join(f"[[{link}]]" for link in plan["wikilinks"]))
        resource_index = plan.get("resource_index") or {}
        if resource_index.get("required"):
            lines.append(f"  - 资源索引：`{resource_index.get('command')}`")
        if plan.get("commit_scope"):
            lines.append("  - 暂存范围：" + ", ".join(f"`{item}`" for item in plan["commit_scope"]))
        for note in plan.get("notes") or []:
            lines.append(f"  - 备注：{note}")


def append_meditate_scope_suggestions(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 后续 meditate scope 建议"])
    suggestion = report.get("meditate_scope_suggestions") or {}
    scopes = suggestion.get("scopes") or []
    if not scopes:
        lines.append("- 无")
        return
    lines.append("- 建议范围：" + ", ".join(f"`{scope}`" for scope in scopes))
    if suggestion.get("command"):
        lines.append(f"- 建议命令：`{suggestion['command']}`")
    for item in suggestion.get("reasons") or []:
        related = ", ".join(f"`{scope}`" for scope in item.get("related_scopes") or []) or "无"
        lines.append(
            f"- `{item.get('candidate')}`：主范围 `{item.get('primary_scope')}`；相邻范围：{related}"
        )
    for note in suggestion.get("notes") or []:
        lines.append(f"- 备注：{note}")


def append_distillation_seed(lines: list[str], report: dict) -> None:
    lines.extend(["", "## 提炼种子"])
    seeds = report.get("distillation_seed") or {}
    if not seeds:
        lines.append("- 无")
        return
    for path, seed in sorted(seeds.items()):
        if seed.get("status") != "ready":
            blocked_by = ", ".join(seed.get("blocked_by") or [])
            lines.append(f"- `{path}`：blocked（{blocked_by or 'unknown'}）")
            continue
        lines.append(f"- `{path}`：ready → `{seed.get('target')}`")
        concepts = ", ".join(seed.get("key_concepts") or [])
        if concepts:
            lines.append(f"  - 关键概念：{concepts}")
        use_context = seed.get("use_context") or {}
        if use_context.get("topic_dir") or use_context.get("target_dir"):
            context_dir = use_context.get("topic_dir") or use_context.get("target_dir")
            lines.append(f"  - 归属用途：`{context_dir}`；承接：{', '.join(use_context.get('ownership') or []) or '无'}")
        if use_context.get("wikilinks"):
            lines.append("  - 可连链：" + ", ".join(f"[[{link}]]" for link in use_context["wikilinks"]))
        excerpts = seed.get("evidence_excerpts") or []
        if excerpts:
            lines.append("  - 原文摘录：")
            for item in excerpts[:5]:
                matched = ", ".join(item.get("matched_concepts") or [])
                suffix = f"（{matched}）" if matched else ""
                lines.append(f"    - {item.get('text')}{suffix}")
        for note in seed.get("notes") or []:
            lines.append(f"  - 备注：{note}")


def append_meditate_feedback(lines: list[str], report: dict) -> None:
    feedback = report.get("meditate_feedback") or {}
    items = feedback.get("items") or []
    lines.extend(["", "## meditate 反馈提醒"])
    if not items:
        lines.append("- 无")
        return
    lines.append(f"- 来源：`{feedback.get('source', '.claude/meditate.log')}`")
    for item in items:
        lines.append(f"- {item}")
    lines.append("- 说明：以上为 report-only 摄入提醒，用于减少后续 meditate 返工；不授权 ingest 重组存量知识。")


def append_apply_selection_audit(lines: list[str], report: dict) -> None:
    audit = report.get("apply_selection_audit") or {}
    if not audit:
        return
    lines.extend(["", "## apply-ready 选择审计"])
    selected = audit.get("selected_only") or []
    applied = audit.get("applied_ready") or []
    skipped = audit.get("skipped_ready_not_selected") or []
    unmatched = audit.get("unmatched_only") or []
    lines.append("- selected_only：" + (", ".join(f"`{path}`" for path in selected) if selected else "未限制"))
    lines.append("- applied_ready：" + (", ".join(f"`{path}`" for path in applied) if applied else "无"))
    lines.append("- skipped_ready_not_selected：" + (", ".join(f"`{path}`" for path in skipped) if skipped else "无"))
    lines.append("- unmatched_only：" + (", ".join(f"`{path}`" for path in unmatched) if unmatched else "无"))


def markdown_report(report: dict) -> str:
    ready = [c for c in report["candidates"] if c["status"] == "ready"]
    skipped_paths = {item.get("path"): item.get("reason") for item in report.get("skipped", []) if item.get("path")}
    left = [c for c in report["candidates"] if c["status"] != "ready" or c.get("path") in skipped_paths]
    invalid = report.get("invalid_fingerprints", [])
    lines = [
        "## 范围与扫描结果",
        f"- Inbox 候选：{report['inbox_count']}",
        f"- 可整理 Markdown：{len(ready)}",
        f"- 已整理库笔记：{report['existing_note_count']}",
        "",
        "## 确定性结果",
        f"- protected paths：{', '.join(report['protected_paths']) if report['protected_paths'] else '无'}",
        f"- 完全重复：{len(report['duplicates']) if report['duplicates'] else '无'}",
        f"- 指纹不一致：{len(invalid) if invalid else '无'}",
        f"- 已归档重复：{len(report['applied']['duplicates']) if report['applied']['duplicates'] else '无'}",
    ]
    append_intake_rules(lines, report)
    append_intake_learning_audit(lines, report)
    append_intake_quality_metrics(lines, report)
    append_intake_quality_trends(lines, report)
    append_placement_readiness(lines, report)
    append_encoding_plan(lines, report)
    append_frontmatter_patch_plan(lines, report)
    append_link_verification_plan(lines, report)
    append_content_patch_plan(lines, report)
    append_understanding_hints(lines, report)
    append_ownership_update_plan(lines, report)
    append_meditate_handoff(lines, report)
    append_organization_plan(lines, report)
    append_meditate_scope_suggestions(lines, report)
    append_distillation_seed(lines, report)
    append_meditate_feedback(lines, report)
    append_apply_selection_audit(lines, report)
    lines.extend([
        "",
        "## 需要模型继续处理",
        "- PARA 分类、提炼、承接、语义补链：由模型基于 ready 候选、摄入学习规则、摄入学习审计、摄入质量指标、摄入质量趋势、归位就绪度、首次编码计划、元数据写入计划、双链验证计划、正文写入计划、摄入理解提示、承接更新计划、meditate 交接清单、首次归位执行计划、后续 meditate scope 建议、提炼种子和 meditate 反馈提醒继续核验并执行。",
        "- 摄入学习规则、摄入学习审计、摄入质量指标、摄入质量趋势、归位就绪度、首次编码计划、元数据写入计划、双链验证计划、正文写入计划、摄入理解提示、承接更新计划、meditate 交接清单、首次归位执行计划、后续 meditate scope 建议、提炼种子和 meditate 反馈提醒是 report-only，不授权脚本重组或改写已入库的存量知识。",
        "- 主题相似但非完全重复：由模型判断并只做低风险补链或报告。",
        "",
        "## 留在 Inbox / 跳过",
    ])
    if left:
        lines.extend(f"- `{c['path']}`：{skipped_paths.get(c.get('path')) or c.get('reason') or c['status']}" for c in left)
    else:
        lines.append("- 无")
    return "\n".join(lines) + "\n"


def checked_report_path(raw: str, expected: Path, label: str) -> Path:
    out = Path(raw).resolve()
    if out != expected:
        raise ValueError(f"{label} report path must be {expected}")
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare Inbox files for model-assisted PARA organization.")
    parser.add_argument("--vault", default=".")
    parser.add_argument("--mode", choices=("scan", "prepare", "apply-ready", "apply-duplicates"), default="scan")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--markdown", dest="markdown_path")
    parser.add_argument("--date", default="未注明日期")
    parser.add_argument("--commit", action="store_true", help="commit applied ready candidates with a precise pathspec")
    parser.add_argument("--only", action="append", default=[], help="apply only this reviewed Inbox path; may be repeated")
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args(argv)

    vault = Path(args.vault).resolve()
    cwd = Path.cwd().resolve()
    if vault != cwd:
        return fail("--vault override is not allowed; run from the vault root")
    if not vault.exists() or not vault.is_dir():
        return fail("vault does not exist or is not a directory")
    try:
        json_path = checked_report_path(args.json_path, FIXED_JSON_REPORT, "JSON") if args.json_path else None
        markdown_path = checked_report_path(args.markdown_path, FIXED_MARKDOWN_REPORT, "Markdown") if args.markdown_path else None
    except ValueError as exc:
        return fail(str(exc))
    convert = args.mode in {"prepare", "apply-ready", "apply-duplicates"}
    only_paths = set(args.only) if args.only else None
    if args.mode == "apply-ready" and only_paths:
        unmatched = sorted(path for path in only_paths if path not in selectable_only_paths(vault))
        if unmatched:
            return fail("unmatched --only path: " + ", ".join(unmatched))
    report = make_report(vault, convert, only_paths if args.mode == "apply-ready" else None)
    if args.mode == "apply-ready":
        try:
            apply_ready(vault, report, args.date, only_paths)
            if args.commit:
                commit_applied_ready(vault, report)
        except RuntimeError as exc:
            return fail(str(exc))
        if args.commit and not args.no_log:
            append_log(vault, report, args.date, args.mode)
    if args.mode == "apply-duplicates":
        apply_duplicates(vault, report, args.date)
        if not args.no_log:
            append_log(vault, report, args.date, args.mode)
    try:
        if json_path:
            write_report_file(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        if markdown_path:
            write_report_file(markdown_path, markdown_report(report))
    except ValueError as exc:
        return fail(str(exc))
    if not json_path and not markdown_path:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
