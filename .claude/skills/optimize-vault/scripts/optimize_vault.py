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

DEFAULT_SCOPES: list[str] = ["Projects", "Areas", "Resources", "Archive"]
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "dclid", "igshid"}
TRACKING_PREFIXES = ("utm_",)
WIKILINK_RE = re.compile(r"!?(?<!\!)\[\[([^\]]+)\]\]")
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")
FIXED_REPORT_DIR = Path("/tmp").resolve()
FIXED_JSON_REPORT = FIXED_REPORT_DIR / "optimize-vault.json"
FIXED_MARKDOWN_REPORT = FIXED_REPORT_DIR / "optimize-vault.md"


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
    fingerprint_valid: bool
    invalid_frontmatter: str | None
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
        if line.strip() and not line.startswith("> Organized from Inbox"):
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
    SMART_QUOTES = {'“', '”', '‘', '’'}  # " " ' '
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
        if any(marker in line for marker in ("Source URL", "Source:", "source:")):
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
    computed_fingerprint = content_fingerprint(text)
    stored_fingerprint = frontmatter.get("content_fingerprint")
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
        fingerprint_valid=not stored_fingerprint or stored_fingerprint == computed_fingerprint,
        invalid_frontmatter=find_invalid_frontmatter(text),
        content_length=len(normalize_body_for_hash(text)),
        has_summary="## Summary" in text or "## Abstract" in text,
        outbound_count=len(links),
        protected=is_protected(rel, protected),
    )


def build_index(vault: Path, scopes: list[str], protected: set[str]) -> tuple[list[Note], dict[str, list[Note]], set[str]]:
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
    return notes, by_name, file_stems


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
    source_file_candidates: dict[str, list[Note]] = defaultdict(list)
    for note in notes:
        for url in note.normalized_urls:
            candidates[("url", url)].append(note)
        if note.fingerprint and note.fingerprint_valid:
            candidates[("fingerprint", note.fingerprint)].append(note)
        source_file = note.frontmatter.get("source_file")
        if source_file:
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


def broken_links(notes: list[Note], by_name: dict[str, list[Note]], file_stems: set[str]) -> list[dict]:
    """Find wikilinks whose target does not match any existing file's filename stem.

    Obsidian resolves [[X]] → X.md by **filename**, not by frontmatter title
    or alias. A wikilink that matches a note's title but not its filename is
    still broken — Obsidian will create a 0-byte stub file when the link is
    clicked. This function checks file_stems first; title/alias matches are
    treated as "soft match" findings that need the wikilink text updated to
    use the actual filename stem.
    """
    findings: list[dict] = []
    for note in notes:
        for link in sorted(set(note.wikilinks)):
            key = normalize_name(link)
            # Primary check: does any FILE have this exact stem?
            if key in file_stems:
                continue  # Valid: Obsidian resolves [[link]] → link.md
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


def empty_stubs(vault: Path, notes: list[Note], by_name: dict[str, list[Note]]) -> list[dict]:
    """Detect 0-byte .md stubs auto-created by Obsidian when a broken wikilink is clicked.

    Obsidian creates a 0-byte file at the path the wikilink expects when the user
    clicks a [[wikilink]] whose target does not exist. For bare [[Note Name]], the
    stub lands at the vault root; for [[Inbox/Note Name]], it lands in Inbox/.

    These stubs are invisible to the script's normal scan (only PARA dirs), and
    their existence causes further issues: the next optimize-vault scan sees the
    stub as an existing file and considers the link "resolved", even though the
    stub is empty and the real note lives elsewhere.

    Returns a list of findings, each with:
      - stub: relative path of the 0-byte stub
      - references: list of {source path, link text} that point to this stub
      - suggested_target: path of the closest-matching real note (or None)
    """
    skip_prefixes = (".claude/", ".git/", ".obsidian/")
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
        for note in notes:
            for link in sorted(set(note.wikilinks)):
                link_key = normalize_name(link)
                if link_key == stub_key:
                    references.append({"source": note.path, "link": link})
        # Find the closest real note: prefer loose title match (stub stem is
        # a prefix/substring of the real note's name)
        suggested_target: str | None = None
        match_candidates: list[str] = []
        for norm_name, paths in all_names.items():
            if stub_key and stub_key in norm_name:
                match_candidates.extend(paths)
        # For Inbox/ stubs, also check if there's a note with the same stem
        # in a PARA directory (common after organize-inbox moves)
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


def invalid_fingerprints(notes: list[Note]) -> list[dict]:
    return [
        {
            "path": note.path,
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
            if line.strip() and not line.startswith("> Organized from Inbox"):
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
    if "Duplicate content, canonical" in text:
        return text
    evidence_text = ", ".join(f"{item['type']}={item['value']}" for item in evidence)
    marker = f"> Duplicate content, canonical: [[{canonical_title}]]\n> Duplication evidence: {evidence_text}\n> Optimization date: {date}\n\n"
    return marker + text


def append_canonical_record(text: str, duplicate_title: str) -> str:
    if duplicate_title in text and "Duplicate archive" in text:
        return text
    return text.rstrip() + f"\n\n## Duplicate archive\n\n- [[{duplicate_title}]]: archived as duplicate content.\n"


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
        if target_path:
            # Find the source notes and fix their wikilinks
            for ref in item["references"]:
                source_note_path = vault / ref["source"]
                if not source_note_path.exists():
                    continue
                # Check if protected
                if ref["source"] in set(report.get("protected_paths", [])):
                    report["skipped_uncertain"].append(
                        {"type": "protected_stub_reference", "stub": item["stub"], "source": ref["source"]}
                    )
                    continue
                text = source_note_path.read_text(encoding="utf-8")
                new_text = replace_wikilink(text, ref["link"], Path(target_path).stem)
                if new_text != text:
                    source_note_path.write_text(new_text, encoding="utf-8")

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
    log_path = vault / ".claude" / "optimize-vault.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"## {date} manual\n"
        f"- Scope: {', '.join(report['scope'])}\n"
        f"- Exact duplicates: {len(report['duplicates'])}\n"
        f"- Suspected duplicates: 0\n"
        f"- Link additions: 0\n"
        f"- Broken links fixed: {len(report['applied']['broken_links'])}\n"
        f"- Empty stubs cleaned: {len(report['applied']['empty_stubs'])}\n"
        f"- Metadata backfilled: {len(report['applied']['metadata'])}\n"
        f"- Invalid frontmatter values: {len(report.get('invalid_frontmatter', []))}\n"
        f"- Structure suggestions: {len(report['orphan_notes'])}\n"
        "commit: none\n"
    )
    old = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    log_path.write_text(old + ("\n" if old and not old.endswith("\n") else "") + entry, encoding="utf-8")


def build_report(vault: Path, scopes: list[str]) -> dict:
    protected = protected_paths(vault)
    notes, by_name, file_stems = build_index(vault, scopes, protected)
    empty_stub_findings = empty_stubs(vault, notes, by_name)
    report = {
        "scope": scopes,
        "coverage": coverage(notes),
        "protected_paths": sorted(protected),
        "duplicates": duplicate_groups(notes),
        "broken_links": broken_links(notes, by_name, file_stems),
        "empty_stubs": empty_stub_findings,
        "metadata_missing": metadata_missing(notes),
        "orphan_notes": orphan_notes(notes),
        "invalid_fingerprints": invalid_fingerprints(notes),
        "invalid_frontmatter": invalid_frontmatter_list(notes),
        "applied": {"duplicates": [], "metadata": [], "broken_links": [], "empty_stubs": []},
        "report_only": {"suspected_duplicates": [], "structure_suggestions": []},
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
    return report


def summarize_items(items: list, formatter, limit: int = 8) -> str:
    if not items:
        return "none"
    rendered = [formatter(item) for item in items[:limit]]
    extra = len(items) - limit
    suffix = f"; {extra} more" if extra > 0 else ""
    return "; ".join(rendered) + suffix


def markdown_report(report: dict) -> str:
    coverage_data = report["coverage"]
    duplicate_lines = [
        f"- canonical `{item['canonical']}`; duplicates: {', '.join('`' + p + '`' for p in item['duplicates'])}"
        for item in report["duplicates"]
    ]
    suspected = report["report_only"].get("suspected_duplicates", [])
    skipped = report["skipped_uncertain"]
    uncertain_items = [item for item in skipped if item.get("type") == "ambiguous_broken_link"]
    protected_items = [item for item in skipped if item.get("type", "").startswith("protected_")]
    evidence_items = [item for item in skipped if item.get("type") not in {"ambiguous_broken_link"} and not item.get("type", "").startswith("protected_")]
    uncertain_summary = summarize_items(
        uncertain_items,
        lambda item: f"`[[{item.get('link')}]]` in `{item.get('source')}` has no unique match",
    )
    evidence_summary = summarize_items(
        [*protected_items, *evidence_items],
        lambda item: f"{item.get('type')}: `{item.get('path') or item.get('source') or item.get('link')}`",
    )
    invalid_count = len(report.get("invalid_fingerprints", []))
    invalid_fm_count = len(report.get("invalid_frontmatter", []))
    invalid_fm_lines = [
        f"- `{item['path']}`: {item['detail']}"
        for item in report.get("invalid_frontmatter", [])
    ]
    empty_stub_lines = [
        f"- `{item['stub']}` -> suggested target `{item['suggested_target']}` (referenced by: {', '.join('`' + r['source'] + '`' for r in item['references'])})"
        for item in report.get("empty_stubs", [])
        if item["status"] == "fixable"
    ]
    unfixable_stub_lines = [
        f"- `{item['stub']}` ({item['status']})"
        for item in report.get("empty_stubs", [])
        if item["status"] != "fixable"
    ]
    lines = [
        "## Scope and scan results",
        f"- Scope: {', '.join(report['scope'])}",
        f"- Scan: {coverage_data['markdown_count']} Markdown notes; directory distribution {coverage_data['distribution']}; source URL coverage {coverage_data['source_url_or_canonical']}; fingerprint coverage {coverage_data['content_fingerprint']}; fingerprint mismatches {invalid_count}; invalid frontmatter values {invalid_fm_count}",
        "",
        "## Auto-processed",
        f"- Duplicate archival: {len(report['applied']['duplicates']) or 'none'}",
        f"- Link additions: none (semantic link additions are only suggested by the model based on the script report)",
        f"- Metadata backfill: {len(report['applied']['metadata']) or 'none'}",
        f"- Broken links fixed: {len(report['applied']['broken_links']) or 'none'}",
        "- Empty stubs cleanup: " + ("\n" + "\n".join(empty_stub_lines) if empty_stub_lines else "none"),
        "",
        "## Report only, not auto-processed",
        "- Exact duplicate candidates: " + ("; ".join(duplicate_lines) if duplicate_lines else "none"),
        f"- Suspected duplicates: {len(suspected) if suspected else 'none'}",
        f"- Orphan notes: {len(report['orphan_notes']) if report['orphan_notes'] else 'none'}",
        "- Invalid frontmatter values (Obsidian properties break; quote any value containing `: `): " + ("\n" + "\n".join(invalid_fm_lines) if invalid_fm_lines else "none"),
        "",
        "## Skipped / uncertain",
        "- protected paths: " + (", ".join(f"`{p}`" for p in report["protected_paths"]) if report["protected_paths"] else "none"),
        "- Uncertain matches: " + uncertain_summary,
        "- Insufficient evidence: " + evidence_summary,
        "- Unfixable empty stubs: " + ("\n" + "\n".join(unfixable_stub_lines) if unfixable_stub_lines else "none"),
        "",
        "## Verification results",
        f"- git status: {report['verification'].get('git_status', 'not checked')}",
        f"- self-check: {report['verification'].get('self_check', 'not checked')}",
        "- commit: none",
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
    stub_not_deleted = False
    for item in report["applied"]["empty_stubs"]:
        if (vault / item["stub"]).exists():
            stub_not_deleted = True
            break
    report["verification"]["self_check"] = "passed" if not bad_delete and not duplicate_missing and not stub_not_deleted else "failed"


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
    parser.add_argument("--mode", choices=("scan", "apply-safe"), default="scan")
    parser.add_argument("--json", dest="json_path", help="Write JSON report to this path")
    parser.add_argument("--markdown", dest="markdown_path", help="Write Markdown report to this path")
    parser.add_argument("--date", default="", help="Date string for markers/logs, e.g. 2026-06-29")
    parser.add_argument("--no-log", action="store_true", help="Do not append .claude/optimize-vault.log in apply-safe mode")
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
    scopes: list[str] = args.scope or DEFAULT_SCOPES
    for scope in scopes:
        scope_path = (vault / scope).resolve()
        if not is_relative_inside(scope_path, vault):
            return fail(f"scope escapes vault: {scope}")

    report = build_report(vault, scopes)
    if args.mode == "apply-safe":
        protected = set(report["protected_paths"])
        notes, _by_name, _file_stems = build_index(vault, scopes, protected)
        date = args.date or "undated"
        apply_metadata(notes, report)
        notes, _by_name, _file_stems = build_index(vault, scopes, protected)
        apply_duplicates(vault, notes, report, date)
        notes, _by_name, _file_stems = build_index(vault, scopes, protected)
        apply_broken_links(vault, notes, report)
        apply_empty_stubs(vault, report)
        if not args.no_log:
            append_log(vault, report, date)
        safe_self_check(vault, report)
    else:
        report["verification"]["git_status"] = "scan mode, no changes"
        report["verification"]["self_check"] = "passed"

    try:
        write_outputs(report, json_path, markdown_path)
    except ValueError as exc:
        return fail(str(exc))
    if not json_path and not markdown_path:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
