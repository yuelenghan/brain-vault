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
  (README creation is the responsibility of the meditate topic-index check).
- Anything outside the marker block (topic positioning, ownership notes, annotations) is left untouched.

Usage:
  python3 generate_resource_index.py --dir "Resources/Loop Engineering"
  python3 generate_resource_index.py --dir "Resources/Loop Engineering" --check
  python3 generate_resource_index.py --all            # scan every Resources/<topic>/
  python3 generate_resource_index.py --all --check
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
from pathlib import Path

BEGIN_MARKER = "<!-- BEGIN: resource-index -->"
END_MARKER = "<!-- END: resource-index -->"


def load_sibling_module(module_name: str, filename: str):
    module_path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


optimize_vault = load_sibling_module("resource_index_optimize_vault", "optimize_vault.py")


def collect_resources(vault: Path, dir_path: Path) -> list[dict]:
    """Return resource-index items aligned with meditate-side retrieval and staleness ordering."""
    notes, _by_name, _file_stems, _attachment_targets = optimize_vault.build_index(vault, ["Resources"], set())
    retrieval_90 = optimize_vault.retrieval_stats(vault, notes, days=90)
    retrieval_180 = optimize_vault.retrieval_stats(vault, notes, days=180)
    staleness = optimize_vault.staleness_report(vault, notes, retrieval_180)
    return optimize_vault.resource_index_items(dir_path.resolve(), retrieval=retrieval_90, staleness=staleness)


def render_index(items: list[dict]) -> str:
    return optimize_vault.render_resource_index(items)


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
    vault = Path.cwd().resolve()
    try:
        dir_path.resolve().relative_to(vault)
    except ValueError:
        return f"跳过（目录不在 vault 内）: {dir_path}", 0
    items = collect_resources(vault, dir_path)
    readme = dir_path / "README.md"
    if check_only:
        st = check_status(readme, items)
        label = {
            "no-readme": f"无 README（需先由 meditate 创建）: {dir_path}",
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
