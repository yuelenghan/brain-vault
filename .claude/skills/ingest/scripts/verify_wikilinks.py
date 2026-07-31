#!/usr/bin/env python3
"""Verify wikilinks in a note resolve to actual filename stems (codepoint-exact).

Obsidian resolves [[X]] -> X.md by filename, so a wikilink whose text differs
from the target file's stem by even one visually-identical character is broken:
clicking it auto-creates a 0-byte stub. The most common case is the apostrophe -
ASCII U+0027 ' vs curly U+2019 ' - which look identical but are distinct
codepoints. ingest's link_verification_plan validates the proposed wikilinks it
generates itself, but it cannot see what the model actually writes when it
hand-edits a note. This script is the post-edit guard: run it on the files
moved/edited this run during the pre-commit self-check.

Usage:
    python3 verify_wikilinks.py [--vault DIR] --file PATH [--file PATH ...]

Exit code is non-zero if any wikilink fails to resolve or has an apostrophe-like
mismatch; the correct stem is printed so the model can fix it before committing.
"""
import argparse
import re
import sys
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")

# Visually-identical characters that Obsidian treats as distinct filename
# characters. Normalized to ASCII only to detect "looks the same" mismatches;
# the real fix is always to use the file's actual stem.
APPROX_MAP = {
    "'": "'",
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / curly apostrophe
    "ʼ": "'",  # modifier letter apostrophe
    "“": '"',  # left double quote
    "”": '"',  # right double quote
}


def approx_normalize(s: str) -> str:
    return s.translate(str.maketrans(APPROX_MAP))


def char_hint(s: str) -> str:
    hints = sorted({f"U+{ord(c):04X}" for c in s if c in APPROX_MAP})
    return ", ".join(hints) if hints else "ascii"


def extract_wikilinks(text: str) -> list[str]:
    targets: list[str] = []
    for raw in WIKILINK_RE.findall(text):
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.append(target)
    return targets


def build_stem_index(vault: Path) -> tuple[set[str], dict[str, list[str]]]:
    exact: set[str] = set()
    approx: dict[str, list[str]] = {}
    for path in vault.rglob("*.md"):
        stem = path.stem
        exact.add(stem)
        approx.setdefault(approx_normalize(stem), []).append(stem)
    return exact, approx


def strip_frontmatter(text: str) -> str:
    """Drop the leading YAML frontmatter so author/aliases [[links]] there
    are not mistaken for content wikilinks."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4:]
    return text


def extract_frontmatter(text: str) -> str:
    """Return the leading YAML frontmatter block including the --- fences, or ''."""
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    return text[:end + 4]


def check_frontmatter_authors(text: str, rel: str) -> list[str]:
    """Flag [[...]] wikilinks in the frontmatter author field.

    Authors must be plain text. Upstream clippers may wrap social handles as
    wikilinks (author: ["[[@Vercantez]]"]); such a wikilink points to a
    non-existent @handle.md and becomes an unresolved graph node whose click
    creates a 0-byte stub. verify_wikilinks strips the whole frontmatter for
    content-link checks, so author wikilinks slip through - this catches them.
    """
    fm = extract_frontmatter(text)
    if not fm:
        return []
    errors: list[str] = []
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^author:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        inline = m.group(1).strip()
        if inline:
            if "[[" in inline and "]]" in inline:
                errors.append(
                    f"{rel}: author field contains wikilink {inline}; "
                    f"author must be plain text, not [[...]]"
                )
            i += 1
            continue
        # block list: consume following indented "  - item" lines
        i += 1
        while i < len(lines):
            item_match = re.match(r"^\s+-\s+(.*)$", lines[i])
            if not item_match:
                break
            item = item_match.group(1).strip()
            if "[[" in item and "]]" in item:
                errors.append(
                    f"{rel}: author field contains wikilink {item}; "
                    f"author must be plain text, not [[...]]"
                )
            i += 1
    return errors


def verify_file(rel: str, vault: Path, exact: set[str], approx: dict[str, list[str]]) -> list[str]:
    path = vault / rel
    if not path.is_file():
        return [f"{rel}: file not found"]
    raw = path.read_text(encoding="utf-8")
    errors: list[str] = check_frontmatter_authors(raw, rel)
    text = strip_frontmatter(raw)
    seen: set[str] = set()
    for target in extract_wikilinks(text):
        if target in seen:
            continue
        seen.add(target)
        if "/" in target or target.startswith("Inbox/"):
            if not (vault / target).exists():
                errors.append(f"{rel}: broken path link [[{target}]] (file not found)")
            continue
        if target in exact:
            continue
        similar = approx.get(approx_normalize(target), [])
        if similar:
            for actual in similar:
                errors.append(
                    f"{rel}: [[{target}]] apostrophe mismatch "
                    f"(wikilink {char_hint(target)} vs file stem {char_hint(actual)}); "
                    f"use [[{actual}]]"
                )
        else:
            errors.append(f"{rel}: broken link [[{target}]] (no matching file stem)")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=".", help="vault root (default cwd)")
    ap.add_argument("--file", action="append", required=True,
                    help="note path relative to vault (repeatable)")
    args = ap.parse_args()
    vault = Path(args.vault).resolve()
    exact, approx = build_stem_index(vault)
    errors: list[str] = []
    for rel in args.file:
        errors.extend(verify_file(rel, vault, exact, approx))
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print(f"ok: {len(args.file)} file(s), all wikilinks resolve by filename stem")
    return 0


if __name__ == "__main__":
    sys.exit(main())
