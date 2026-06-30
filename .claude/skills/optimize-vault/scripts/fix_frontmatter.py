#!/usr/bin/env python3
"""Move a note's YAML frontmatter to the first line so Obsidian parses it correctly.

Handles three cases:
- BROKEN_FM: a blockquote such as `> 整理自 Inbox` precedes `---`, invalidating the frontmatter.
  → Move the YAML block to the first line; keep the blockquote after the frontmatter.
- NO_FM: no frontmatter at all.
  → Synthesize a minimal frontmatter from the file name / `> 整理自 Inbox，<date>` / `> 内容指纹：sha256:...`.
- OK_FM: the first line is already `---`; skip.

Also: move the `> 内容指纹：sha256:...` blockquote into the YAML `content_fingerprint` field
(only when the YAML does not already have that field).

Structural fix only; field order and values inside the YAML are unchanged, keeping it auditable and reversible.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

FINGERPRINT_RE = re.compile(r"^>\s*内容指纹[：:]\s*(sha256:[0-9a-fA-F]+)\s*$")
INBOX_DATE_RE = re.compile(r"^>\s*整理自 Inbox[，,]\s*(\d{4}-\d{2}-\d{2})\s*$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$")


def split_yaml(text: str):
    """Return (preamble_lines, yaml_text_or_None, body_text).

    preamble: all lines before the first `---` (including blockquotes / blank lines).
    yaml_text: the raw text between the two `---` fences (excluding the fences), or None.
    body: everything after the second `---` (including the trailing newline).
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return lines, None, None
    # Find the second ---.
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            yaml_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            return [], yaml_text, body
    return [], None, None


def extract_preamble_metadata(preamble_lines):
    """Extract fingerprint / inbox_date / cleaned blockquote lines from the preamble blockquotes."""
    fingerprint = None
    inbox_date = None
    kept_quote = []
    for ln in preamble_lines:
        m = FINGERPRINT_RE.match(ln)
        if m:
            fingerprint = m.group(1)
            continue
        m = INBOX_DATE_RE.match(ln)
        if m:
            inbox_date = m.group(1)
            kept_quote.append(ln)
            continue
        if ln.strip().startswith(">"):
            kept_quote.append(ln)
    return fingerprint, inbox_date, kept_quote


def yaml_has_field(yaml_text: str, field: str) -> bool:
    return re.search(rf"^#*\s*{re.escape(field)}\s*:", yaml_text, re.MULTILINE) is not None


def inject_field(yaml_text: str, field: str, value: str) -> str:
    """Append `field: value` to the end of the YAML (simple scalar, quoted when needed)."""
    if value.startswith("sha256:"):
        line = f'{field}: "{value}"'
    elif re.search(r"[:#\[\]{},&*?|>%@`\"']", value) or value != value.strip():
        line = f'{field}: "{value}"'
    else:
        line = f"{field}: {value}"
    if yaml_text and not yaml_text.endswith("\n"):
        yaml_text += "\n"
    return yaml_text + line + "\n"


def synthesize_yaml(title: str, type_: str, created: str | None, fingerprint: str | None) -> str:
    parts = [f'title: "{title}"', f"type: {type_}"]
    if created:
        parts.append(f"created: {created}")
    if fingerprint:
        parts.append(f'content_fingerprint: "{fingerprint}"')
    parts.append(f"status: {type_ if type_ != 'index' else 'resource'}")
    parts.append("tags: []")
    return "\n".join(parts) + "\n"


def derive_title(path: Path, body: str) -> str:
    for ln in body.split("\n"):
        m = H1_RE.match(ln)
        if m:
            return m.group(1).strip()
    return path.stem


def process(path: Path) -> str | None:
    """Return a change description, or None when nothing changed."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    # OK_FM: the first line is already ---.
    if lines and lines[0].strip() == "---":
        # Still check for an unmigrated `> 内容指纹：` blockquote (OK_FM should not have one; skip).
        return None

    # Find the first --- (BROKEN_FM) or confirm there is none (NO_FM).
    first_fence = None
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            first_fence = i
            break

    if first_fence is not None and first_fence > 0:
        # BROKEN_FM: preamble first, YAML between the two --- fences.
        preamble_lines = lines[:first_fence]
        # Find the second ---.
        second_fence = None
        for j in range(first_fence + 1, len(lines)):
            if lines[j].strip() == "---":
                second_fence = j
                break
        if second_fence is None:
            return None  # Malformed; leave untouched.
        yaml_text = "\n".join(lines[first_fence + 1 : second_fence])
        body = "\n".join(lines[second_fence + 1 :])
        fingerprint, inbox_date, kept_quote = extract_preamble_metadata(preamble_lines)
        changed = []
        if fingerprint and not yaml_has_field(yaml_text, "content_fingerprint"):
            yaml_text = inject_field(yaml_text, "content_fingerprint", fingerprint)
            changed.append("移入 content_fingerprint")
        # Rebuild: frontmatter first.
        new_parts = ["---", yaml_text.rstrip("\n"), "---", ""]
        if kept_quote:
            new_parts.extend(kept_quote)
            new_parts.append("")
        new_text = "\n".join(new_parts) + ("\n" if not body.startswith("\n") else "") + body
        if new_text == raw:
            return None
        path.write_text(new_text, encoding="utf-8")
        return f"BROKEN_FM 修复（frontmatter 提至第1行{'; ' + '; '.join(changed) if changed else ''}）"

    # NO_FM: no --- at all.
    # Collect the leading contiguous blockquote run (lines starting with `>` plus blank lines between them),
    # stopping at the first non-blockquote, non-blank line.
    body_lines = []
    in_preamble = True
    preamble_quote = []
    for ln in raw.split("\n"):
        if in_preamble:
            if ln.strip().startswith(">"):
                preamble_quote.append(ln)
                continue
            if ln.strip() == "":
                continue  # Skip blank lines between blockquotes.
            in_preamble = False
        body_lines.append(ln)
    body = "\n".join(body_lines)
    fingerprint, inbox_date, kept_quote = extract_preamble_metadata(preamble_quote)

    type_ = "index" if path.name == "README.md" else "reference"
    title = derive_title(path, body)
    yaml_text = synthesize_yaml(title, type_, inbox_date, fingerprint)
    new_parts = ["---", yaml_text.rstrip("\n"), "---"]
    if kept_quote:
        new_parts.append("")
        new_parts.extend(kept_quote)
    new_text = "\n".join(new_parts) + "\n\n" + body.lstrip("\n")
    path.write_text(new_text, encoding="utf-8")
    return f"NO_FM 合成（title={title!r}, type={type_}, created={inbox_date}, fingerprint={'有' if fingerprint else '无'}）"


def main():
    if not sys.argv[1:]:
        print("usage: fix_frontmatter.py <file>...", file=sys.stderr)
        sys.exit(2)
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"  跳过（不存在）: {arg}")
            continue
        msg = process(p)
        if msg:
            print(f"  改: {arg} — {msg}")
        else:
            print(f"  跳过（已OK）: {arg}")


if __name__ == "__main__":
    main()
