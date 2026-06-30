#!/usr/bin/env python3
"""Generate/update a pure-Markdown resource index for a topic directory, with no Obsidian third-party plugins.

How it works:
- Scan every .md under the given topic directory (excluding README.md itself).
- Parse frontmatter title / type / created / source_url / source_file.
- Notes with type == "reference" are listed in the resource index.
- Generate/update the index section between two markers in the topic README.md; reruns only replace this block:
    <!-- BEGIN: resource-index -->
    ...
    <!-- END: resource-index -->
- If the README does not exist or has no marker block, only report; do not create it
  (README creation is the responsibility of the optimize-vault topic-index check).
- Anything outside the marker block (topic positioning, ownership notes, annotations) is left untouched.

Usage:
  python3 generate_resource_index.py --dir "Resources/Loop Engineering"
  python3 generate_resource_index.py --dir "Resources/Loop Engineering" --check
  python3 generate_resource_index.py --all            # scan every Resources/<topic>/
  python3 generate_resource_index.py --all --check
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

BEGIN_MARKER = "<!-- BEGIN: resource-index -->"
END_MARKER = "<!-- END: resource-index -->"

FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
KV_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", re.MULTILINE)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FM_RE.match(text)
    if not m:
        return {}
    fm: dict[str, str] = {}
    for km in KV_RE.finditer(m.group(1)):
        key = km.group(1)
        raw = km.group(2).strip()
        # Strip quotes.
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        # For multi-line lists, keep only the first item as a simplification; tags etc. are not indexed and are ignored.
        if key not in fm:
            fm[key] = raw
    return fm


def strip_quotes(v: str) -> str:
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def collect_resources(dir_path: Path) -> list[dict]:
    """Return metadata for type=reference notes under the topic directory, sorted by created desc, filename asc."""
    items: list[dict] = []
    for md in sorted(dir_path.glob("*.md")):
        if md.name.lower() == "readme.md":
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        if fm.get("type", "reference").strip() not in ("reference", ""):
            continue
        title = strip_quotes(fm.get("title", "")).strip() or md.stem
        created = fm.get("created", "").strip()
        source = strip_quotes(fm.get("source_url", "") or fm.get("source_file", "") or fm.get("source", "")).strip()
        items.append({"title": title, "file": md.name, "created": created, "source": source})
    items.sort(key=lambda x: (x["created"], x["file"]), reverse=True)
    # After created desc, break ties by filename asc via two stable sorts.
    items.sort(key=lambda x: x["file"])
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


def render_index(items: list[dict]) -> str:
    """Render the pure-Markdown list inside the marker block."""
    if not items:
        return f"{BEGIN_MARKER}\n\n> 暂无 reference 类资料。\n\n{END_MARKER}"
    lines = [BEGIN_MARKER, ""]
    for it in items:
        link = f"[[{it['file'][:-3]}]]"  # Drop the .md suffix to form the wikilink.
        created = it["created"] or "—"
        if it["source"]:
            lines.append(f"- {link}（{created}）— {it['source']}")
        else:
            lines.append(f"- {link}（{created}）")
    lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines)


def find_marker_span(text: str) -> tuple[int, int] | None:
    """Return the character span of the marker block (including BEGIN/END lines), or None if absent."""
    b = text.find(BEGIN_MARKER)
    if b == -1:
        return None
    e = text.find(END_MARKER, b)
    if e == -1:
        return None
    return b, e + len(END_MARKER)


def update_readme(readme: Path, items: list[dict]) -> str:
    """Update the README marker block. Returns 'updated' / 'unchanged' / 'no-marker' / 'no-readme'."""
    if not readme.exists():
        return "no-readme"
    text = readme.read_text(encoding="utf-8")
    span = find_marker_span(text)
    if span is None:
        return "no-marker"
    new_block = render_index(items)
    new_text = text[: span[0]] + new_block + text[span[1] :]
    if new_text == text:
        return "unchanged"
    readme.write_text(new_text, encoding="utf-8")
    return "updated"


def check_status(readme: Path, items: list[dict]) -> str:
    """Return the check status: no-readme / no-marker / stale / fresh."""
    if not readme.exists():
        return "no-readme"
    text = readme.read_text(encoding="utf-8")
    span = find_marker_span(text)
    if span is None:
        return "no-marker"
    current = text[span[0] : span[1]]
    return "stale" if current != render_index(items) else "fresh"


def process_dir(dir_path: Path, check_only: bool) -> tuple[str, int]:
    """Process one topic directory. Returns (status description, resource count)."""
    if not dir_path.is_dir():
        return f"跳过（非目录）: {dir_path}", 0
    items = collect_resources(dir_path)
    readme = dir_path / "README.md"
    if check_only:
        st = check_status(readme, items)
        label = {
            "no-readme": f"无 README（需先由 optimize-vault 创建）: {dir_path}",
            "no-marker": f"README 无标记段（需先插入）: {dir_path}",
            "stale": f"过期: {dir_path}（{len(items)} 篇资料）",
            "fresh": f"最新: {dir_path}（{len(items)} 篇）",
        }[st]
        return label, len(items)
    status = update_readme(readme, items)
    mapping = {
        "updated": f"已更新: {dir_path}（{len(items)} 篇）",
        "unchanged": f"无变化: {dir_path}（{len(items)} 篇）",
        "no-marker": f"跳过（README 无标记段）: {dir_path}",
        "no-readme": f"跳过（无 README）: {dir_path}",
    }
    return mapping[status], len(items)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/更新主题目录的纯 Markdown 资料索引。")
    parser.add_argument("--dir", help="主题目录，如 Resources/Loop Engineering")
    parser.add_argument("--all", action="store_true", help="扫描所有 Resources/<主题>/ 目录")
    parser.add_argument("--check", action="store_true", help="只读检查哪些目录索引过期，不修改")
    args = parser.parse_args()

    if not args.dir and not args.all:
        parser.error("需要 --dir <目录> 或 --all")

    vault = Path.cwd()
    dirs: list[Path] = []
    if args.all:
        res = vault / "Resources"
        if not res.is_dir():
            print("无 Resources/ 目录")
            return 0
        dirs = sorted(d for d in res.iterdir() if d.is_dir())
    else:
        d = Path(args.dir)
        dirs = [d if d.is_absolute() else vault / d]

    changed = 0
    total = 0
    for d in dirs:
        msg, n = process_dir(d, args.check)
        print(f"  {msg}")
        total += n
        if "已更新" in msg or "过期" in msg:
            changed += 1
    print(f"\n共 {len(dirs)} 个主题目录，{total} 篇资料，{changed} 个待更新/过期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
