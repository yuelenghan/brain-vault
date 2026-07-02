#!/usr/bin/env python3
"""Move a note's YAML frontmatter to the first line so Obsidian parses it correctly.

Handles three cases:
- BROKEN_FM: a blockquote such as `> 整理自 Inbox` precedes `---`, invalidating the frontmatter.
  → Move the YAML block to the first line; keep the blockquote after the frontmatter.
- NO_FM: no frontmatter at all.
  → Synthesize a minimal frontmatter from the file name / `> 整理自 Inbox，<date>` / `> 内容指纹：sha256:...`.
- OK_FM: the first line is already `---`; skip.
- DOUBLE_FM: the first line is `---` but another frontmatter block exists deeper in the file
  (e.g. garbled PDF content between two frontmatter blocks).
  → Merge the real (later) frontmatter into line 1, removing the minimal first block + garbled content.

Also:
- Move the `> 内容指纹：sha256:...` blockquote into the YAML `content_fingerprint` field
  (only when the YAML does not already have that field).
- Replace smart/curly quotes (""''') with straight quotes in frontmatter values,
  since YAML does not recognize smart quotes as string delimiters.

Structural fix only; field order and values inside the YAML are unchanged, keeping it auditable and reversible.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

FINGERPRINT_RE = re.compile(r"^>\s*内容指纹[：:]\s*(sha256:[0-9a-fA-F]+)\s*$")
INBOX_DATE_RE = re.compile(r"^>\s*整理自 Inbox[，,]\s*(\d{4}-\d{2}-\d{2})\s*$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$")

# Smart/curly quotes → straight quotes (YAML does not recognize smart quotes as string delimiters).
SMART_QUOTE_MAP = str.maketrans({
    "“": '"',   # " left double quotation mark
    "”": '"',   # " right double quotation mark
    "‘": "'",   # ' left single quotation mark
    "’": "'",   # ' right single quotation mark
})


def fix_smart_quotes(text: str) -> str:
    """Replace smart/curly quotes with straight ASCII quotes."""
    return text.translate(SMART_QUOTE_MAP)


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


def _find_fences(lines: list[str]) -> list[tuple[int, int]]:
    """Return all (start, end) index pairs of `---`-delimited blocks in the file."""
    pairs = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "---":
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == "---":
                    pairs.append((i, j))
                    i = j + 1
                    break
            else:
                break
        else:
            i += 1
    return pairs


def _is_likely_frontmatter(yaml_text: str) -> bool:
    """Heuristic: does this YAML block look like frontmatter (has key: value pairs)? """
    return bool(re.search(r"^\w[\w-]*:\s+", yaml_text, re.MULTILINE))


def process(path: Path) -> str | None:
    """Return a change description, or None when nothing changed."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    changed_parts = []

    # --- OK_FM: the first line is already ---. ---
    if lines and lines[0].strip() == "---":
        # Check for smart quotes in the frontmatter.
        fences = _find_fences(lines)
        if fences:
            start, end = fences[0]
            yaml_text = "\n".join(lines[start + 1 : end])
            fixed_yaml = fix_smart_quotes(yaml_text)
            quote_fixed = (fixed_yaml != yaml_text)

            # DOUBLE_FM: another frontmatter block exists deeper in the file
            # (e.g. garbled PDF content between two frontmatter blocks).
            if len(fences) >= 2 and _is_likely_frontmatter("\n".join(lines[fences[1][0] + 1 : fences[1][1]])):
                # The second block is the real frontmatter; merge it to line 1.
                real_start, real_end = fences[1]
                real_yaml = fix_smart_quotes("\n".join(lines[real_start + 1 : real_end]))
                # Merge fields: real frontmatter takes priority, but keep content_fingerprint
                # from the first (script-added) block if newer.
                first_yaml = fixed_yaml
                # Extract fingerprint from first block if present.
                fp_match = re.search(r"content_fingerprint:\s*(.+)", first_yaml)
                first_fp = fp_match.group(1).strip() if fp_match else None
                if first_fp and "content_fingerprint:" not in real_yaml:
                    real_yaml = real_yaml.rstrip() + f"\ncontent_fingerprint: {first_fp}\n"
                # Remove everything from first fence start to real fence end, then real body.
                body = "\n".join(lines[real_end + 1 :])
                new_text = "---\n" + real_yaml.rstrip("\n") + "\n---\n\n" + body.lstrip("\n")
                path.write_text(new_text, encoding="utf-8")
                changed_parts.append("双重 frontmatter 合并")
                if real_yaml != fix_smart_quotes("\n".join(lines[real_start + 1 : real_end])):
                    changed_parts.append("弯引号修复")
                return f"DOUBLE_FM 修复（{'; '.join(changed_parts)}）"

            if quote_fixed:
                # Simple smart-quote fix in the existing frontmatter.
                new_text = "---\n" + fixed_yaml.rstrip("\n") + raw[raw.find("---", 3) + 3:]
                path.write_text(new_text, encoding="utf-8")
                return "弯引号修复（frontmatter smart quotes → straight quotes）"

        return None  # OK_FM, no issues found.

    # --- BROKEN_FM: preamble first, YAML between later --- fences. ---
    first_fence = None
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            first_fence = i
            break

    if first_fence is not None and first_fence > 0:
        preamble_lines = lines[:first_fence]
        second_fence = None
        for j in range(first_fence + 1, len(lines)):
            if lines[j].strip() == "---":
                second_fence = j
                break
        if second_fence is None:
            return None  # Malformed; leave untouched.
        yaml_text = fix_smart_quotes("\n".join(lines[first_fence + 1 : second_fence]))
        body = "\n".join(lines[second_fence + 1 :])
        fingerprint, inbox_date, kept_quote = extract_preamble_metadata(preamble_lines)
        changed = []
        if fingerprint and not yaml_has_field(yaml_text, "content_fingerprint"):
            yaml_text = inject_field(yaml_text, "content_fingerprint", fingerprint)
            changed.append("移入 content_fingerprint")
        if yaml_text != fix_smart_quotes("\n".join(lines[first_fence + 1 : second_fence])):
            changed.append("弯引号修复")
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

    # --- NO_FM: no --- at all. ---
    body_lines = []
    in_preamble = True
    preamble_quote = []
    for ln in raw.split("\n"):
        if in_preamble:
            if ln.strip().startswith(">"):
                preamble_quote.append(ln)
                continue
            if ln.strip() == "":
                continue
            in_preamble = False
        body_lines.append(ln)
    body = "\n".join(body_lines)
    fingerprint, inbox_date, kept_quote = extract_preamble_metadata(preamble_quote)

    type_ = "index" if path.name == "README.md" else "reference"
    title = derive_title(path, body)
    yaml_text = fix_smart_quotes(synthesize_yaml(title, type_, inbox_date, fingerprint))
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
