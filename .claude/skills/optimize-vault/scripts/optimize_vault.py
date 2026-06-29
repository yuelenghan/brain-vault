#!/usr/bin/env python3
"""Deterministic optimizer for a PARA-style brain vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_SCOPES = ("Projects", "Areas", "Resources", "Archive")
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "dclid", "igshid"}
TRACKING_PREFIXES = ("utm_",)
WIKILINK_RE = re.compile(r"!?(?<!\!)\[\[([^\]]+)\]\]")
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")


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
    content_length: int
    has_summary: bool
    inbound_count: int = 0
    outbound_count: int = 0
    duplicate_of: str | None = None
    protected: bool = False


def fail(message: str) -> int:
    print(f"optimize-vault: {message}", file=sys.stderr)
    return 2


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
        ["status", "--short", "--", ".", ":!Inbox/**", ":!.claude/optimize-vault.log"],
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
        if not raw or raw == ".claude/skills/optimize-vault" or raw.startswith(".claude/skills/optimize-vault/"):
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


def normalize_body_for_hash(text: str) -> str:
    _frontmatter, _aliases, body = parse_frontmatter(text)
    out: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("> 整理自 Inbox"):
            continue
        if "内容指纹" in stripped or stripped.startswith("content_fingerprint:"):
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


def read_note(vault: Path, path: Path, protected: set[str]) -> Note:
    rel = path.relative_to(vault).as_posix()
    text = path.read_text(encoding="utf-8")
    frontmatter, aliases, body = parse_frontmatter(text)
    title = frontmatter.get("title") or heading_title(body) or path.stem
    links = [wikilink_target(raw) for raw in WIKILINK_RE.findall(text)]
    fingerprint = frontmatter.get("content_fingerprint") or content_fingerprint(text)
    urls = extract_urls(frontmatter, text)
    return Note(
        path=rel,
        abs_path=path,
        title=title,
        aliases=aliases,
        frontmatter=frontmatter,
        wikilinks=links,
        normalized_urls=urls,
        fingerprint=fingerprint,
        content_length=len(normalize_body_for_hash(text)),
        has_summary="## 提炼" in text or "## 摘要" in text,
        outbound_count=len(links),
        protected=is_protected(rel, protected),
    )


def build_index(vault: Path, scopes: list[str], protected: set[str]) -> tuple[list[Note], dict[str, list[Note]]]:
    notes = [read_note(vault, path, protected) for path in iter_markdown(vault, scopes)]
    by_name: dict[str, list[Note]] = defaultdict(list)
    for note in notes:
        names = {note.title, Path(note.path).stem, *note.aliases}
        for name in names:
            if name:
                by_name[normalize_name(name)].append(note)
    for note in notes:
        for link in note.wikilinks:
            matches = by_name.get(normalize_name(link), [])
            for match in matches:
                match.inbound_count += 1
    return notes, by_name


def canonical_score(note: Note) -> tuple[int, int, int, int, int, str]:
    return (
        0 if note.path.startswith("Archive/Duplicates/") else 1,
        1 if note.path.startswith("Resources/") else 0,
        1 if note.has_summary else 0,
        note.inbound_count,
        note.content_length,
        note.path,
    )


def duplicate_groups(notes: list[Note]) -> list[dict]:
    candidates: dict[tuple[str, str], list[Note]] = defaultdict(list)
    for note in notes:
        for url in note.normalized_urls:
            candidates[("url", url)].append(note)
        if note.fingerprint:
            candidates[("fingerprint", note.fingerprint)].append(note)
        source_file = note.frontmatter.get("source_file")
        if source_file:
            candidates[("source_file", source_file)].append(note)

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


def broken_links(notes: list[Note], by_name: dict[str, list[Note]]) -> list[dict]:
    findings: list[dict] = []
    for note in notes:
        for link in sorted(set(note.wikilinks)):
            key = normalize_name(link)
            matches = [match.path for match in by_name.get(key, [])]
            if not matches:
                # Looser title contains fallback, report only unless unique.
                loose = [n.path for n in notes if key and key in normalize_name(n.title)]
                finding = {"source": note.path, "link": link, "matches": sorted(set(loose))}
                finding["status"] = "unique" if len(set(loose)) == 1 else "ambiguous"
                findings.append(finding)
    return findings


def metadata_missing(notes: list[Note]) -> list[dict]:
    missing: list[dict] = []
    for note in notes:
        if not (note.path.startswith("Resources/") or note.path.startswith("Archive/")):
            continue
        fields: list[str] = []
        if not note.frontmatter.get("content_fingerprint"):
            fields.append("content_fingerprint")
        if note.normalized_urls and not note.frontmatter.get("source_url"):
            fields.append("source_url")
        if fields:
            missing.append({"path": note.path, "fields": fields})
    return missing


def orphan_notes(notes: list[Note]) -> list[str]:
    return sorted(note.path for note in notes if note.inbound_count == 0 and note.outbound_count == 0 and note.path.startswith("Resources/"))


def coverage(notes: list[Note]) -> dict:
    distribution = Counter(note.path.split("/", 1)[0] for note in notes)
    return {
        "markdown_count": len(notes),
        "distribution": dict(sorted(distribution.items())),
        "source_url_or_canonical": sum(1 for note in notes if note.normalized_urls),
        "content_fingerprint": sum(1 for note in notes if note.frontmatter.get("content_fingerprint")),
    }


def quote_yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def insert_frontmatter_fields(text: str, fields: dict[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    start = None
    for idx, line in enumerate(lines[:5]):
        if line.strip() == "---":
            start = idx
            break
        if line.strip() and not line.startswith("> 整理自 Inbox"):
            break
    if start is None:
        block = ["---\n", *[f"{key}: {quote_yaml(value)}\n" for key, value in fields.items()], "---\n", "\n"]
        return "".join(block + lines)
    end = None
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
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


def replace_wikilink(text: str, old: str, new: str) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        target, *rest = raw.split("|", 1)
        target_base, *anchor = target.split("#", 1)
        if normalize_name(target_base) != normalize_name(old):
            return match.group(0)
        suffix = "#" + anchor[0] if anchor else ""
        alias = "|" + rest[0] if rest else ""
        return f"[[{new}{suffix}{alias}]]"

    return WIKILINK_RE.sub(repl, text)


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
        if "content_fingerprint" in item["fields"]:
            fields["content_fingerprint"] = content_fingerprint(text)
        if "source_url" in item["fields"] and note.normalized_urls:
            fields["source_url"] = note.normalized_urls[0]
        new_text = insert_frontmatter_fields(text, fields)
        if new_text != text:
            note.abs_path.write_text(new_text, encoding="utf-8")
            report["applied"]["metadata"].append({"path": note.path, "fields": sorted(fields)})


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
        target_title = by_path[target_path].title if target_path in by_path else Path(target_path).stem
        text = note.abs_path.read_text(encoding="utf-8")
        new_text = replace_wikilink(text, item["link"], target_title)
        if new_text != text:
            note.abs_path.write_text(new_text, encoding="utf-8")
            report["applied"]["broken_links"].append({"source": note.path, "old": item["link"], "new": target_title})


def append_log(vault: Path, report: dict, date: str) -> None:
    log_path = vault / ".claude" / "optimize-vault.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"## {date} manual\n"
        f"- 范围：{', '.join(report['scope'])}\n"
        f"- 完全重复：{len(report['duplicates'])}\n"
        f"- 疑似重复：0\n"
        f"- 补链：0\n"
        f"- 修复失效链接：{len(report['applied']['broken_links'])}\n"
        f"- 元数据补全：{len(report['applied']['metadata'])}\n"
        f"- 结构建议：{len(report['orphan_notes'])}\n"
        "commit: 无\n"
    )
    old = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    log_path.write_text(old + ("\n" if old and not old.endswith("\n") else "") + entry, encoding="utf-8")


def build_report(vault: Path, scopes: list[str]) -> dict:
    protected = protected_paths(vault)
    notes, by_name = build_index(vault, scopes, protected)
    report = {
        "scope": scopes,
        "coverage": coverage(notes),
        "protected_paths": sorted(protected),
        "duplicates": duplicate_groups(notes),
        "broken_links": broken_links(notes, by_name),
        "metadata_missing": metadata_missing(notes),
        "orphan_notes": orphan_notes(notes),
        "applied": {"duplicates": [], "metadata": [], "broken_links": []},
        "report_only": {"suspected_duplicates": [], "structure_suggestions": []},
        "skipped_uncertain": [],
        "verification": {},
    }
    for item in report["broken_links"]:
        if item["status"] != "unique":
            report["skipped_uncertain"].append({"type": "ambiguous_broken_link", **item})
    return report


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
        lambda item: f"{item.get('type')}: `{item.get('path') or item.get('source') or item.get('link')}`",
    )
    lines = [
        "## 范围与扫描结果",
        f"- 范围：{', '.join(report['scope'])}",
        f"- 扫描：{coverage_data['markdown_count']} 篇 Markdown；目录分布 {coverage_data['distribution']}；来源 URL 覆盖 {coverage_data['source_url_or_canonical']}；指纹覆盖 {coverage_data['content_fingerprint']}",
        "",
        "## 已自动处理",
        f"- 重复归档：{len(report['applied']['duplicates']) or '无'}",
        f"- 补链：无（语义补链仅由模型基于脚本报告建议处理）",
        f"- 元数据补全：{len(report['applied']['metadata']) or '无'}",
        f"- 失效链接修复：{len(report['applied']['broken_links']) or '无'}",
        "",
        "## 只报告，未自动处理",
        "- 完全重复候选：" + ("；".join(duplicate_lines) if duplicate_lines else "无"),
        f"- 疑似重复：{len(suspected) if suspected else '无'}",
        f"- 孤岛笔记：{len(report['orphan_notes']) if report['orphan_notes'] else '无'}",
        "",
        "## 跳过 / 不确定",
        "- protected paths：" + (", ".join(f"`{p}`" for p in report["protected_paths"]) if report["protected_paths"] else "无"),
        "- 不确定匹配：" + uncertain_summary,
        "- 证据不足：" + evidence_summary,
        "",
        "## 验证结果",
        f"- git status：{report['verification'].get('git_status', '未检查')}",
        f"- 自检：{report['verification'].get('self_check', '未检查')}",
        "- commit：无",
        "",
    ]
    return "\n".join(lines)


def safe_self_check(vault: Path, report: dict) -> None:
    status = run_git(vault, ["status", "--short"])
    report["verification"]["git_status"] = status.stdout.strip() or "clean"
    bad_delete = any(line.startswith(" D") or line.startswith("D ") for line in status.stdout.splitlines())
    duplicate_missing = False
    for item in report["applied"]["duplicates"]:
        if not (vault / item["duplicate"]).exists():
            duplicate_missing = True
            break
    report["verification"]["self_check"] = "通过" if not bad_delete and not duplicate_missing else "未通过"


def write_outputs(report: dict, json_path: Path | None, markdown_path: Path | None) -> None:
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_report(report), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Scan or safely optimize a brain vault.")
    parser.add_argument("--vault", default=".", help="Vault root, defaults to current directory")
    parser.add_argument("--scope", action="append", help="Scope directory relative to vault; repeatable")
    parser.add_argument("--mode", choices=("scan", "apply-safe"), default="scan")
    parser.add_argument("--json", dest="json_path", help="Write JSON report to this path")
    parser.add_argument("--markdown", dest="markdown_path", help="Write Markdown report to this path")
    parser.add_argument("--date", default="", help="Date string for markers/logs, e.g. 2026-06-29")
    parser.add_argument("--no-log", action="store_true", help="Do not append .claude/optimize-vault.log in apply-safe mode")
    args = parser.parse_args(argv)

    vault = Path(args.vault).resolve()
    if not vault.exists() or not vault.is_dir():
        return fail("vault does not exist or is not a directory")
    scopes = args.scope or list(DEFAULT_SCOPES)
    for scope in scopes:
        scope_path = (vault / scope).resolve()
        if not is_relative_inside(scope_path, vault):
            return fail(f"scope escapes vault: {scope}")

    report = build_report(vault, scopes)
    if args.mode == "apply-safe":
        protected = set(report["protected_paths"])
        notes, _by_name = build_index(vault, scopes, protected)
        date = args.date or "未注明日期"
        apply_metadata(notes, report)
        notes, _by_name = build_index(vault, scopes, protected)
        apply_duplicates(vault, notes, report, date)
        notes, by_name = build_index(vault, scopes, protected)
        apply_broken_links(vault, notes, report)
        if not args.no_log:
            append_log(vault, report, date)
        safe_self_check(vault, report)
    else:
        report["verification"]["git_status"] = "scan 模式未修改"
        report["verification"]["self_check"] = "通过"

    write_outputs(
        report,
        Path(args.json_path).resolve() if args.json_path else None,
        Path(args.markdown_path).resolve() if args.markdown_path else None,
    )
    if not args.json_path and not args.markdown_path:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
