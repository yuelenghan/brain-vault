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
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "dclid", "igshid"}
TRACKING_PREFIXES = ("utm_",)
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")
FIXED_REPORT_DIR = Path("/tmp").resolve()
FIXED_JSON_REPORT = FIXED_REPORT_DIR / "organize-inbox.json"
FIXED_MARKDOWN_REPORT = FIXED_REPORT_DIR / "organize-inbox.md"


@dataclass
class Candidate:
    path: str
    kind: str
    status: str
    markdown_path: str | None = None
    reason: str | None = None
    title: str | None = None
    source_urls: list[str] | None = None
    content_fingerprint: str | None = None


def fail(message: str) -> int:
    print(f"organize-inbox: {message}", file=sys.stderr)
    return 2


def run(vault: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=vault, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def git(vault: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return run(vault, ["git", *args])


def protected_paths(vault: Path) -> set[str]:
    completed = git(vault, ["status", "--short", "--", ".", ":!Inbox/**", ":!.claude/organize.log"])
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


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines[:5]):
        if line.strip() == "---":
            start = idx
            break
        if line.strip() and not line.startswith("> Organized from Inbox"):
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
    frontmatter: dict[str, str] = {}
    for line in lines[start + 1 : end]:
        if re.match(r"^[A-Za-z0-9_-]+:\s*", line):
            key, raw = line.split(":", 1)
            frontmatter[key.strip()] = strip_quotes(raw.strip())
    body = "\n".join(lines[:start] + lines[end + 1 :])
    return frontmatter, body


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


def extract_urls(frontmatter: dict[str, str], text: str) -> list[str]:
    urls: list[str] = []
    for key in ("source_url", "canonical_url", "source"):
        value = frontmatter.get(key, "")
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(normalize_url(value))
    for line in text.splitlines():
        if any(marker in line for marker in ("Source URL", "Source:", "source:")):
            urls.extend(normalize_url(match) for match in URL_RE.findall(line))
    return list(dict.fromkeys(urls))


def normalize_body_for_hash(text: str) -> str:
    _frontmatter, body = parse_frontmatter(text)
    out: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("> Organized from Inbox"):
            continue
        if "content fingerprint" in stripped or stripped.startswith("content_fingerprint:"):
            continue
        if stripped.startswith("source_url:") or stripped.startswith("canonical_url:"):
            continue
        if re.match(r"^source:\s*https?://", stripped):
            continue
        if re.match(r"^>\s*(Source URL|Source|Duplicate content|Duplication evidence|canonical):?", stripped):
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
    return True, None


def read_markdown_info(vault: Path, markdown_rel: str) -> tuple[str | None, list[str], str | None]:
    path = vault / markdown_rel
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, [], None
    frontmatter, body = parse_frontmatter(text)
    title = frontmatter.get("title") or heading_title(body) or path.stem
    return title, extract_urls(frontmatter, text), fingerprint(text)


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
            title = frontmatter.get("title") or heading_title(body) or path.stem
            computed_fingerprint = fingerprint(text)
            stored_fingerprint = frontmatter.get("content_fingerprint")
            fingerprint_valid = not stored_fingerprint or stored_fingerprint == computed_fingerprint
            if not fingerprint_valid:
                invalid_fingerprints.append({
                    "path": rel,
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
        if candidate.content_fingerprint:
            for note in by_fp.get(candidate.content_fingerprint, []):
                matches[note["path"]] = note
                evidence.append({"type": "fingerprint", "value": candidate.content_fingerprint})
        if matches:
            canonical = sorted(matches.values(), key=lambda n: (not n["path"].startswith("Archive/"), n["path"]), reverse=True)[0]
            duplicates.append({
                "inbox_path": candidate.path,
                "markdown_path": candidate.markdown_path,
                "canonical": canonical,
                "evidence": evidence,
            })
    return duplicates


def make_report(vault: Path, convert: bool) -> dict:
    protected = sorted(protected_paths(vault))
    candidates: list[Candidate] = []
    for path in inbox_files(vault):
        kind = classify(path)
        candidate = Candidate(path=safe_relative_inbox(path), kind=kind, status="pending")
        if kind == "unsupported":
            candidate.status = "left_in_inbox"
            candidate.reason = "unsupported file type"
            candidates.append(candidate)
            continue
        markdown_rel = safe_relative_inbox(path if path.suffix.lower() == ".md" else path.with_suffix(".md"))
        if kind != "markdown" and (vault / markdown_rel).exists():
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
            title, urls, fp = read_markdown_info(vault, candidate.markdown_path)
            candidate.title = title
            candidate.source_urls = urls
            candidate.content_fingerprint = fp
        else:
            candidate.status = "needs_conversion"
            candidate.markdown_path = markdown_rel
        candidates.append(candidate)

    notes, invalid_fingerprints = existing_notes(vault)
    duplicates = find_duplicates(candidates, notes)
    return {
        "protected_paths": protected,
        "inbox_count": len(candidates),
        "candidates": [candidate.__dict__ for candidate in candidates],
        "existing_note_count": len(notes),
        "invalid_fingerprints": invalid_fingerprints,
        "duplicates": duplicates,
        "applied": {"duplicates": []},
        "skipped": [],
    }


def duplicate_marker(text: str, canonical_title: str, evidence: list[dict], date: str) -> str:
    if "Duplicate content, canonical" in text:
        return text
    ev = ", ".join(f"{item['type']}={item['value']}" for item in evidence)
    return f"> Duplicate content, canonical: [[{canonical_title}]]\n> Duplication evidence: {ev}\n> Organized from Inbox, {date}\n\n" + text


def apply_duplicates(vault: Path, report: dict, date: str) -> None:
    for item in report["duplicates"]:
        src = item["markdown_path"]
        src_path = vault / src
        if not src_path.exists():
            report["skipped"].append({"path": src, "reason": "markdown missing"})
            continue
        target_rel = f"Archive/Duplicates/{Path(src).name}"
        counter = 2
        while (vault / target_rel).exists():
            target_rel = f"Archive/Duplicates/{Path(src).stem}-{counter}{Path(src).suffix}"
            counter += 1
        (vault / target_rel).parent.mkdir(parents=True, exist_ok=True)
        completed = git(vault, ["mv", src, target_rel])
        if completed.returncode != 0:
            report["skipped"].append({"path": src, "reason": completed.stderr.strip()})
            continue
        target_path = vault / target_rel
        text = target_path.read_text(encoding="utf-8")
        target_path.write_text(duplicate_marker(text, item["canonical"]["title"], item["evidence"], date), encoding="utf-8")
        report["applied"]["duplicates"].append({"from": src, "to": target_rel, "canonical": item["canonical"], "evidence": item["evidence"]})


def append_log(vault: Path, report: dict, date: str, mode: str) -> None:
    path = vault / ".claude" / "organize.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    left = [c for c in report["candidates"] if c["status"] != "ready"]
    entry = [
        f"## {date} manual",
        f"- Script mode: {mode}",
        f"- Inbox candidates: {report['inbox_count']}",
        f"- Exact duplicates: {len(report['duplicates'])}",
        f"- Archived duplicates: {len(report['applied']['duplicates'])}",
        f"- Left in Inbox: {len(left)}",
        "commit: none",
        "",
    ]
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(old + ("\n" if old and not old.endswith("\n") else "") + "\n".join(entry), encoding="utf-8")


def markdown_report(report: dict) -> str:
    ready = [c for c in report["candidates"] if c["status"] == "ready"]
    left = [c for c in report["candidates"] if c["status"] != "ready"]
    invalid = report.get("invalid_fingerprints", [])
    lines = [
        "## Scope and scan results",
        f"- Inbox candidates: {report['inbox_count']}",
        f"- Organizable Markdown: {len(ready)}",
        f"- Existing library notes: {report['existing_note_count']}",
        "",
        "## Deterministic results",
        f"- protected paths: {', '.join(report['protected_paths']) if report['protected_paths'] else 'none'}",
        f"- Exact duplicates: {len(report['duplicates']) if report['duplicates'] else 'none'}",
        f"- Fingerprint mismatches: {len(invalid) if invalid else 'none'}",
        f"- Archived duplicates: {len(report['applied']['duplicates']) if report['applied']['duplicates'] else 'none'}",
        "",
        "## Needs model follow-up",
        "- PARA classification, distillation, supporting-note creation, and semantic link addition: handled by the model over the ready candidates.",
        "- Topically similar but not exact duplicates: the model judges and only performs low-risk link additions or reports.",
        "",
        "## Left in Inbox / skipped",
    ]
    if left:
        lines.extend(f"- `{c['path']}`：{c.get('reason') or c['status']}" for c in left)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare Inbox files for model-assisted PARA organization.")
    parser.add_argument("--vault", default=".")
    parser.add_argument("--mode", choices=("scan", "prepare", "apply-duplicates"), default="scan")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--markdown", dest="markdown_path")
    parser.add_argument("--date", default="undated")
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
    convert = args.mode in {"prepare", "apply-duplicates"}
    report = make_report(vault, convert)
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
