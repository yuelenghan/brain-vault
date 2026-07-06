#!/usr/bin/env python3
"""Deterministic recall for the brain-vault."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SCOPES = ("Projects", "Areas", "Resources", "Archive")
TEST_REPORT_DIR_ENV = "RECALL_TEST_REPORT_DIR"
WIKILINK_RE = re.compile(r"!?(?<!\!)\[\[([^\]]+)\]\]")
LATIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{3,}$")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
MAX_SPREAD_ACTIVATIONS = 30
MAX_SUGGESTED_READING_ORDER = 20
FIXED_REPORT_DIR = Path(os.environ.get(TEST_REPORT_DIR_ENV) or tempfile.gettempdir()).resolve()
FIXED_JSON_REPORT = FIXED_REPORT_DIR / "recall.json"
FIXED_MARKDOWN_REPORT = FIXED_REPORT_DIR / "recall.md"


def load_cross_skill_module(module_name: str, relative_path: Path):
    module_path = relative_path.resolve()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


knowledge_model = load_cross_skill_module(
    "recall_knowledge_model",
    Path(__file__).resolve().parents[2] / "meditate" / "scripts" / "knowledge_model.py",
)


@dataclass
class NoteRecord:
    path: str
    title: str
    aliases: list[str]
    kind: str
    body: str
    wikilinks: list[str]
    concepts: Counter[str]
    topic: str | None
    ownership: list[str]


def fail(message: str) -> int:
    print(f"recall: {message}", file=sys.stderr)
    return 2


def is_relative_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, [], text
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, [], text
    frontmatter: dict[str, str] = {}
    aliases: list[str] = []
    current_key: str | None = None
    for line in lines[1:end]:
        if re.match(r"^[A-Za-z0-9_-]+:\s*", line):
            key, raw = line.split(":", 1)
            key = key.strip()
            current_key = key
            value = strip_quotes(raw.strip())
            frontmatter[key] = value
            if key == "aliases" and value.startswith("[") and value.endswith("]"):
                aliases.extend(strip_quotes(item.strip()) for item in value.strip("[]").split(",") if item.strip())
            elif key == "aliases" and value:
                aliases.append(value)
            continue
        if current_key == "aliases" and line.lstrip().startswith("-"):
            aliases.append(strip_quotes(line.split("-", 1)[1].strip()))
    body = "\n".join(lines[end + 1 :])
    return frontmatter, list(dict.fromkeys(alias for alias in aliases if alias)), body


def heading_title(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def wikilink_target(raw: str) -> str:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return target


def normalize_relpath(path: Path | str) -> str:
    return Path(path).as_posix().lstrip("./")


def tokenize_name(name: str) -> set[str]:
    counts = knowledge_model.concept_counts_for_text(name)
    return {
        term
        for term in counts
        if " " not in term and knowledge_model.meaningful_concept_token(term)
    } | {
        term
        for term in counts
        if " " in term
    }


def build_query_terms(query_counts: Counter[str], query_concepts: set[str]) -> set[str]:
    return {
        term
        for term in query_counts
        if (
            (" " not in term and knowledge_model.meaningful_concept_token(term))
            or (" " not in term and LATIN_TOKEN_RE.fullmatch(term))
        )
    } | {term for term in query_concepts if " " in term}


def query_supports_reverse_match(query: str) -> bool:
    compact = re.sub(r"\s+", "", query)
    latin_len = len(re.sub(r"[^A-Za-z0-9]", "", compact))
    return len(CJK_RE.findall(compact)) >= 2 or latin_len >= 3


def overlap_threshold(terms: set[str]) -> int:
    return min(2, max(1, len(terms)))


def note_name_terms(note: NoteRecord) -> set[str]:
    terms: set[str] = set()
    for name in {Path(note.path).stem, note.title, *note.aliases}:
        if name:
            terms.update(tokenize_name(name))
    return terms


def read_note(vault: Path, path: Path, by_name: dict[str, list[str]] | None = None) -> NoteRecord:
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, aliases, body = parse_frontmatter(text)
    title = frontmatter.get("title") or heading_title(body) or path.stem
    kind = strip_quotes(frontmatter.get("type", "")).strip().lower()
    wikilinks = [wikilink_target(item) for item in WIKILINK_RE.findall(text)]
    concepts = knowledge_model.concept_counts_for_text(f"{path.stem}\n{title}\n{body}")
    rel = path.relative_to(vault).as_posix()
    topic = None
    if rel.startswith("Resources/"):
        parts = Path(rel).parts
        if len(parts) >= 2:
            topic = parts[1]
    ownership: list[str] = []
    if rel.startswith(("Areas/", "Projects/")):
        ownership = [rel]
    elif by_name:
        for link in wikilinks:
            for match in by_name.get(knowledge_model.normalize_name(link), []):
                if match.startswith(("Areas/", "Projects/")) and match not in ownership:
                    ownership.append(match)
    return NoteRecord(
        path=rel,
        title=title,
        aliases=aliases,
        kind=kind,
        body=body,
        wikilinks=wikilinks,
        concepts=concepts,
        topic=topic,
        ownership=ownership,
    )


def build_index(vault: Path) -> tuple[list[NoteRecord], dict[str, list[NoteRecord]], dict[str, NoteRecord], dict[str, list[str]]]:
    raw_paths: list[Path] = []
    for scope in SCOPES:
        root = vault / scope
        if not root.exists():
            continue
        raw_paths.extend(
            path
            for path in sorted(root.rglob("*.md"))
            if path.is_file() and not path.is_symlink()
        )
    name_index: dict[str, list[str]] = defaultdict(list)
    for path in raw_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        frontmatter, aliases, body = parse_frontmatter(text)
        title = frontmatter.get("title") or heading_title(body) or path.stem
        rel = path.relative_to(vault).as_posix()
        for name in {path.stem, title, *aliases}:
            if name:
                name_index[knowledge_model.normalize_name(name)].append(rel)
    notes = [read_note(vault, path, name_index) for path in raw_paths]
    by_path = {note.path: note for note in notes}
    by_name: dict[str, list[NoteRecord]] = defaultdict(list)
    for note in notes:
        for name in {Path(note.path).stem, note.title, *note.aliases}:
            if name:
                by_name[knowledge_model.normalize_name(name)].append(note)
    for note in notes:
        if note.ownership:
            continue
        owners: list[str] = []
        for link in note.wikilinks:
            for match in by_name.get(knowledge_model.normalize_name(link), []):
                if match.path.startswith(("Areas/", "Projects/")) and match.path not in owners:
                    owners.append(match.path)
        note.ownership = owners
    incoming_by_path: dict[str, list[str]] = defaultdict(list)
    for note in notes:
        for link in note.wikilinks:
            target = resolve_link_target(link, by_name, by_path, note.path)
            if target is None or target.path == note.path:
                continue
            if note.path not in incoming_by_path[target.path]:
                incoming_by_path[target.path].append(note.path)
    return notes, by_name, by_path, {path: sorted(sources) for path, sources in incoming_by_path.items()}


def direct_match_terms(query: str, query_terms: set[str], note: NoteRecord) -> list[str]:
    matched: list[str] = []
    threshold = overlap_threshold(query_terms) if query_terms else 1
    reverse_allowed = query_supports_reverse_match(query)
    names = [Path(note.path).stem, note.title, *note.aliases]
    for name in names:
        if not name:
            continue
        if knowledge_model.text_mentions_name(query, name):
            matched.append(f"matched title/alias/stem: {name}")
            continue
        if reverse_allowed and knowledge_model.text_mentions_name(name, query):
            matched.append(f"query matched inside title/alias/stem: {name}")
            continue
        overlap = sorted(query_terms & tokenize_name(name))
        if len(overlap) >= threshold:
            matched.append(f"matched title/alias/stem tokens: {name} ({', '.join(overlap[:5])})")
    return list(dict.fromkeys(matched))


def concept_overlap(query_concepts: set[str], note: NoteRecord) -> tuple[list[str], list[str]]:
    top_concepts = knowledge_model.top_concepts_from_counts(note.concepts, limit=24)
    note_concepts = set(top_concepts)
    overlap = [
        term
        for term in sorted(query_concepts & note_concepts)
        if term and term != knowledge_model.normalize_name(note.topic or "")
    ]
    return overlap, top_concepts


def concept_overlap_allowed(query_concepts: set[str], overlap: list[str], note: NoteRecord, top_concepts: list[str]) -> bool:
    if not overlap:
        return False
    threshold = overlap_threshold(query_concepts)
    if len(overlap) < threshold:
        return False
    if len(overlap) == 1 and threshold == 1:
        term = overlap[0]
        return term in set(top_concepts[:12]) or term in note_name_terms(note)
    return True


def validate_activated_path(vault: Path, raw_path: str) -> str | None:
    candidate = raw_path.strip()
    if not candidate:
        return None
    raw = Path(candidate)
    if raw.is_absolute():
        return None
    rel = normalize_relpath(raw)
    if not rel.endswith(".md"):
        return None
    if not any(rel.startswith(scope + "/") for scope in SCOPES):
        return None
    abs_path = (vault / rel).resolve()
    if not is_relative_inside(abs_path, vault) or not abs_path.is_file():
        return None
    return rel


def resolve_link_target(link: str, by_name: dict[str, list[NoteRecord]], by_path: dict[str, NoteRecord], current_path: str) -> NoteRecord | None:
    target = wikilink_target(link)
    if not target:
        return None
    if "/" in target:
        candidates = [normalize_relpath(target), normalize_relpath(Path(current_path).parent / target)]
        for candidate in candidates:
            note = by_path.get(candidate if candidate.endswith(".md") else candidate + ".md")
            if note:
                return note
        return None
    matches = by_name.get(knowledge_model.normalize_name(target), [])
    if len(matches) == 1:
        return matches[0]
    file_stem_matches = [note for note in matches if Path(note.path).stem == target]
    if len(file_stem_matches) == 1:
        return file_stem_matches[0]
    return None


def build_query_report(vault: Path, query: str) -> dict:
    notes, by_name, by_path, incoming_by_path = build_index(vault)
    query_counts = knowledge_model.concept_counts_for_text(query)
    query_concepts = set(knowledge_model.top_concepts_from_counts(query_counts, limit=24))
    query_terms = build_query_terms(query_counts, query_concepts)
    activations: dict[str, dict] = {}

    for note in notes:
        if note.kind == "index" and Path(note.path).name == "README.md":
            continue
        evidence = direct_match_terms(query, query_terms, note)
        if not evidence:
            continue
        activations[note.path] = {
            "path": note.path,
            "title": note.title,
            "strength": "direct",
            "score": 3.0 + len(evidence) * 0.25,
            "evidence": evidence,
            "topic": note.topic,
            "ownership": note.ownership,
            "related_from": [],
        }

    for note in notes:
        if note.kind == "index" and Path(note.path).name == "README.md":
            continue
        overlap, top_concepts = concept_overlap(query_concepts, note)
        if not concept_overlap_allowed(query_concepts, overlap, note, top_concepts):
            continue
        item = activations.get(note.path)
        score = 2.0 + len(overlap) * 0.25
        evidence = ["matched concepts: " + ", ".join(overlap[:5])]
        if item is None:
            activations[note.path] = {
                "path": note.path,
                "title": note.title,
                "strength": "concept",
                "score": score,
                "evidence": evidence,
                "topic": note.topic,
                "ownership": note.ownership,
                "related_from": [],
            }
            continue
        item["score"] = max(item["score"], score)
        item["evidence"].extend(evidence)

    seed_paths = [
        item["path"]
        for item in sorted(
            activations.values(),
            key=lambda item: (item["score"], item["strength"] == "direct", item["path"]),
            reverse=True,
        )
    ]
    spread_count = 0
    for path in seed_paths:
        note = by_path[path]
        spread_candidates: list[tuple[NoteRecord, str]] = []
        for raw_link in note.wikilinks:
            target = resolve_link_target(raw_link, by_name, by_path, note.path)
            if target is None or target.path == path:
                continue
            spread_candidates.append((target, f"linked from {note.path}"))
        for incoming_path in incoming_by_path.get(path, []):
            target = by_path.get(incoming_path)
            if target is None or target.path == path:
                continue
            spread_candidates.append((target, f"links to {path}"))
        for target, evidence in spread_candidates:
            existing = activations.get(target.path)
            if existing is not None:
                if existing["strength"] == "spread":
                    existing["evidence"].append(evidence)
                    existing["related_from"].append(path)
                continue
            if spread_count >= MAX_SPREAD_ACTIVATIONS:
                break
            activations[target.path] = {
                "path": target.path,
                "title": target.title,
                "strength": "spread",
                "score": 1.0,
                "evidence": [evidence],
                "topic": target.topic,
                "ownership": target.ownership,
                "related_from": [path],
            }
            spread_count += 1

    ordered = sorted(
        activations.values(),
        key=lambda item: (item["score"], item["strength"] == "direct", item["path"]),
        reverse=True,
    )
    suggested_reading_order = ordered[:MAX_SUGGESTED_READING_ORDER]
    for item in ordered:
        item["ownership"] = sorted(set(item.get("ownership") or []))
        item["evidence"] = list(dict.fromkeys(item.get("evidence") or []))
        item["related_from"] = list(dict.fromkeys(item.get("related_from") or []))

    return {
        "query": query,
        "query_concepts": sorted(query_concepts),
        "activations": ordered,
        "suggested_reading_order_total": len(ordered),
        "suggested_reading_order": [
            {
                "path": item["path"],
                "strength": item["strength"],
                "reason": item["evidence"][0] if item["evidence"] else item["strength"],
            }
            for item in suggested_reading_order
        ],
    }


def markdown_report(report: dict) -> str:
    lines = [
        f"# Recall Report: {report['query']}",
        "",
        "## Query Concepts",
        "- " + ("、".join(report.get("query_concepts") or []) if report.get("query_concepts") else "无"),
        "",
        "## Activations",
    ]
    if not report.get("activations"):
        lines.extend(["- 无命中", ""])
        return "\n".join(lines)
    for item in report["activations"]:
        ownership = "、".join(item.get("ownership") or []) or "无"
        topic = item.get("topic") or "无"
        evidence = "；".join(item.get("evidence") or []) or item["strength"]
        lines.append(
            f"- `{item['path']}`（{item['strength']}；topic={topic}；ownership={ownership}；evidence={evidence}）"
        )
    reading_order = report.get("suggested_reading_order") or []
    reading_total = int(report.get("suggested_reading_order_total") or len(reading_order))
    reading_header = "## Suggested Reading Order"
    if reading_total > len(reading_order):
        reading_header += f" (top {len(reading_order)} of {reading_total})"
    lines.extend(["", reading_header])
    for index, item in enumerate(reading_order, start=1):
        lines.append(f"{index}. `{item['path']}`（{item['strength']}；{item['reason']}）")
    lines.append("")
    return "\n".join(lines)


def checked_report_path(raw: str, expected: Path, label: str) -> Path:
    out = Path(raw).resolve()
    if out != expected:
        raise ValueError(f"{label} report path must be {expected}")
    if out.exists() and out.is_symlink():
        raise ValueError(f"{label} report path must not be a symlink")
    return out


def write_report_file(path: Path, content: str) -> None:
    if path.parent != FIXED_REPORT_DIR:
        raise ValueError(f"report parent must be {FIXED_REPORT_DIR}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def write_outputs(report: dict, json_path: Path | None, markdown_path: Path | None) -> None:
    if json_path:
        write_report_file(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if markdown_path:
        write_report_file(markdown_path, markdown_report(report))


def load_latest_activation_strengths() -> dict[str, str]:
    if not FIXED_JSON_REPORT.exists():
        return {}
    try:
        report = json.loads(FIXED_JSON_REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        item["path"]: item.get("strength", "unknown")
        for item in report.get("activations") or []
        if item.get("path")
    }


def append_log_event(
    vault: Path,
    query: str,
    result: str,
    activated_paths: list[str],
    gap_topic: str | None,
) -> None:
    strengths = load_latest_activation_strengths()
    log_path = vault / ".claude" / "recall.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"## {timestamp} recall", f"- 查询：{query}"]
    seen_paths: set[str] = set()
    for path in activated_paths:
        validated = validate_activated_path(vault, path)
        if validated is None:
            print(f"recall: skip invalid activated path: {path}", file=sys.stderr)
            continue
        if validated in seen_paths:
            continue
        seen_paths.add(validated)
        strength = strengths.get(validated, "unknown")
        lines.append(f"- 激活：{validated} ({strength})")
    lines.append(f"- 结果：{result}")
    lines.append(f"- 缺口：{gap_topic or '无'}")
    old = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    log_path.write_text(old + ("\n" if old and not old.endswith("\n") else "") + "\n".join(lines) + "\n", encoding="utf-8")


def sanitize_gap_topic(topic: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", topic).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "未命名缺口"


def create_gap_note(vault: Path, query: str, gap_topic: str, description: str | None) -> Path:
    raw_topic = gap_topic.strip()
    safe_topic = sanitize_gap_topic(raw_topic)
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    note_path = inbox / f"知识缺口 - {safe_topic}.md"
    if note_path.exists():
        raise FileExistsError(f"gap note already exists: {note_path.relative_to(vault).as_posix()}")
    date_text = datetime.now().strftime("%Y-%m-%d")
    note_text = "\n".join(
        [
            "---",
            f'title: "知识缺口 - {safe_topic}"',
            "type: gap",
            f"created: {date_text}",
            "tags:",
            "  - gap",
            "  - recall",
            "---",
            "",
            f"# 知识缺口 - {safe_topic}",
            "",
            "## 背景",
            f"- 原始查询：{query}",
            f"- 缺口主题：{raw_topic or safe_topic}",
            "",
            "## 缺口描述",
            description.strip() if description and description.strip() else "待补充",
            "",
            "## 下一步",
            "- 补充资料后走 ingest 正常整理。",
            "",
        ]
    )
    note_path.write_text(note_text, encoding="utf-8")
    return note_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Deterministic recall for the brain-vault.")
    parser.add_argument("--mode", choices=("query", "log-event", "create-gap"), required=True)
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--markdown", dest="markdown_path")
    parser.add_argument("--query", default="")
    parser.add_argument("--result", choices=("answered", "partial", "miss"))
    parser.add_argument("--activated", action="append", default=[])
    parser.add_argument("--gap-topic", default="")
    parser.add_argument("--description", default="")
    args = parser.parse_args(argv)

    vault = Path.cwd().resolve()
    for scope in SCOPES:
        scope_path = (vault / scope).resolve()
        if scope_path.exists() and not is_relative_inside(scope_path, vault):
            return fail(f"scope escapes vault: {scope}")
    try:
        json_path = checked_report_path(args.json_path, FIXED_JSON_REPORT, "JSON") if args.json_path else None
        markdown_path = checked_report_path(args.markdown_path, FIXED_MARKDOWN_REPORT, "Markdown") if args.markdown_path else None
    except ValueError as exc:
        return fail(str(exc))

    if args.mode == "query":
        if not args.query.strip():
            return fail("--query is required with --mode query")
        report = build_query_report(vault, args.query.strip())
        write_outputs(report, json_path, markdown_path)
        return 0

    if args.mode == "create-gap":
        if not args.query.strip():
            return fail("--query is required with --mode create-gap")
        if not args.gap_topic.strip():
            return fail("--gap-topic is required with --mode create-gap")
        try:
            note_path = create_gap_note(
                vault,
                query=args.query.strip(),
                gap_topic=args.gap_topic.strip(),
                description=args.description.strip() or None,
            )
        except FileExistsError as exc:
            return fail(str(exc))
        print(note_path.relative_to(vault).as_posix())
        return 0

    if not args.query.strip():
        return fail("--query is required with --mode log-event")
    if not args.result:
        return fail("--result is required with --mode log-event")
    append_log_event(
        vault,
        query=args.query.strip(),
        result=args.result,
        activated_paths=args.activated,
        gap_topic=args.gap_topic.strip() or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
