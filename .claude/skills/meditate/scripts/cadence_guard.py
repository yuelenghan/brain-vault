#!/usr/bin/env python3
"""Guard weekly meditate semantic generation against report drift."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


SYNTHESIS_BEGIN = "<!-- BEGIN: synthesis -->"
SYNTHESIS_END = "<!-- END: synthesis -->"
RECONSOLIDATION_RE = re.compile(r"^### 再巩固 (?P<date>\d{4}-\d{2}-\d{2})$", re.MULTILINE)
KNOWLEDGE_RESTRUCTURING_BEGIN_RE = re.compile(
    r"<!-- BEGIN: knowledge-restructuring cluster=(?P<cluster_id>kr-[0-9a-f]+) -->"
)
KNOWLEDGE_RESTRUCTURING_END = "<!-- END: knowledge-restructuring -->"
KNOWLEDGE_RESTRUCTURING_DIGEST_RE = re.compile(r"来源集：(?P<digest>sha256:[0-9a-f]{64})")
WIKILINK_RE = re.compile(r"!?(?<!\!)\[\[([^\]]+)\]\]")
KNOWLEDGE_ENTRY_RE = re.compile(r"(?m)^-\s*(?P<id>K-\d+)\s*[:：]")


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def synthesis_targets_from_report(report: dict) -> list[str]:
    targets = {
        item["readme"]
        for item in report.get("synthesis_candidates") or []
        if isinstance(item, dict) and item.get("readme")
    }
    return sorted(targets)


def restatement_targets_from_report(report: dict) -> list[str]:
    targets = {
        item["path"]
        for item in report.get("restatement_candidates") or []
        if isinstance(item, dict) and item.get("path")
    }
    return sorted(targets)


def restructuring_targets_from_report(report: dict) -> list[dict]:
    """Return every high-confidence, write-eligible restructuring target."""
    targets = [
        item
        for item in report.get("restructuring_candidates") or []
        if isinstance(item, dict)
        and item.get("action") == "refresh_anchor"
        and item.get("confidence") == "high"
        and item.get("cluster_id")
        and item.get("anchor_path")
        and item.get("source_set_digest")
    ]
    return sorted(targets, key=lambda item: (item["anchor_path"], item["cluster_id"]))


def weekly_prompt_from_report(report: dict) -> str:
    synthesis_targets = synthesis_targets_from_report(report)
    restatement_targets = restatement_targets_from_report(report)
    restructuring_targets = restructuring_targets_from_report(report)
    synthesis_lines = synthesis_targets or ["无"]
    restatement_lines = restatement_targets or ["无"]
    restructuring_lines = restructuring_targets or [{"anchor_path": "无", "cluster_id": "无", "source_set_digest": "无"}]
    return "\n".join(
        [
            "Weekly semantic candidate guard from the JSON report:",
            f"- Allowed synthesis targets ({len(synthesis_targets)}):",
            *[f"  - {item}" for item in synthesis_lines],
            f"- Allowed restatement targets ({len(restatement_targets)}):",
            *[f"  - {item}" for item in restatement_lines],
            f"- Allowed knowledge-restructuring targets ({len(restructuring_targets)}):",
            *[
                f"  - {item['anchor_path']} cluster={item['cluster_id']} digest={item['source_set_digest']}"
                for item in restructuring_lines
            ],
            "Do not write synthesis or restatement to any other files. If a useful topic is not listed here, leave it untouched and report it instead.",
            "Every allowed high-confidence knowledge-restructuring target must receive exactly one valid marker update; do not set a candidate limit or submit a partial weekly result.",
        ]
    )


def run_git_capture(vault: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=vault,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def changed_files_for_commit(vault: Path, commit_hash: str) -> list[str]:
    output = run_git_capture(vault, ["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit_hash])
    return [line.strip() for line in output.splitlines() if line.strip()]


def changed_files_for_staged(vault: Path) -> list[str]:
    output = run_git_capture(vault, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def read_file_at_commit(vault: Path, commit_hash: str, path: str) -> str:
    return run_git_capture(vault, ["show", f"{commit_hash}:{path}"])


def read_file_at_parent(vault: Path, commit_hash: str, path: str) -> str:
    return run_git_capture(vault, ["show", f"{commit_hash}^:{path}"])


def read_file_at_head(vault: Path, path: str) -> str:
    return run_git_capture(vault, ["show", f"HEAD:{path}"])


def read_file_from_index(vault: Path, path: str) -> str:
    return run_git_capture(vault, ["show", f":{path}"])


def extract_synthesis_block(text: str) -> str | None:
    start = text.find(SYNTHESIS_BEGIN)
    if start == -1:
        return None
    end = text.find(SYNTHESIS_END, start)
    if end == -1:
        return None
    return text[start + len(SYNTHESIS_BEGIN) : end].strip()


def extract_reconsolidation_tail(text: str) -> str | None:
    match = RECONSOLIDATION_RE.search(text)
    if not match:
        return None
    return text[match.start() :].strip()


def parse_restructuring_blocks(text: str) -> tuple[list[dict], bool]:
    """Return complete marker blocks and flag malformed / unterminated blocks."""
    blocks: list[dict] = []
    malformed = False
    for match in KNOWLEDGE_RESTRUCTURING_BEGIN_RE.finditer(text):
        end = text.find(KNOWLEDGE_RESTRUCTURING_END, match.end())
        if end == -1:
            malformed = True
            continue
        body = text[match.end() : end]
        digest = KNOWLEDGE_RESTRUCTURING_DIGEST_RE.search(body)
        blocks.append(
            {
                "cluster_id": match.group("cluster_id"),
                "digest": digest.group("digest") if digest else None,
                "body": body,
                "start": match.start(),
                "end": end + len(KNOWLEDGE_RESTRUCTURING_END),
            }
        )
    return blocks, malformed


def text_outside_restructuring_markers(text: str) -> tuple[str, bool]:
    blocks, malformed = parse_restructuring_blocks(text)
    if malformed:
        return text, True
    pieces: list[str] = []
    previous = 0
    for block in blocks:
        pieces.append(text[previous : block["start"]])
        previous = block["end"]
    pieces.append(text[previous:])
    # A marker may be appended with surrounding blank lines; that formatting is
    # part of insertion, not a handwritten outside-marker mutation.
    normalized = re.sub(r"\n{3,}", "\n\n", "".join(pieces)).rstrip()
    return normalized, False


def restructuring_block_signature(block: dict | None) -> tuple[str, str | None, str] | None:
    if block is None:
        return None
    return (block["cluster_id"], block["digest"], block["body"])


def filename_stem_counts(vault: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for root_name in ("Projects", "Areas", "Resources", "Archive"):
        root = vault / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            if not path.is_file() or path.is_symlink():
                continue
            key = path.stem.casefold()
            counts[key] = counts.get(key, 0) + 1
    return counts


def source_wikilink_targets(body: str) -> list[str]:
    targets: list[str] = []
    for raw in WIKILINK_RE.findall(body):
        target = raw.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.append(target)
    return targets


def invalid_restructuring_source_links(block: dict, stem_counts: dict[str, int]) -> list[str]:
    invalid: list[str] = []
    for target in source_wikilink_targets(block["body"]):
        if "/" in target or "\\" in target or stem_counts.get(target.casefold(), 0) != 1:
            invalid.append(target)
    return sorted(set(invalid))


def invalid_knowledge_entries(block: dict) -> list[str]:
    invalid: list[str] = []
    matches = list(KNOWLEDGE_ENTRY_RE.finditer(block["body"]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block["body"])
        entry = block["body"][match.start() : end]
        preceding = block["body"][: match.start()]
        headings = re.findall(r"(?m)^###\s+(.+?)\s*$", preceding)
        section = headings[-1] if headings else ""
        source_count = len(source_wikilink_targets(entry))
        requires_two_sources = (
            "已取代" in section
            or "未决冲突" in section
            or re.search(r"\b(supersedes?|conflicts?)\b|取代|冲突", entry, re.IGNORECASE) is not None
        )
        if source_count < (2 if requires_two_sources else 1):
            invalid.append(match.group("id"))
    return invalid


def restructuring_audit_summary(
    vault: Path,
    report: dict,
    changed_paths: list[str],
    before_reader,
    after_reader,
) -> dict:
    targets = restructuring_targets_from_report(report)
    targets_by_cluster = {item["cluster_id"]: item for item in targets}
    target_anchors = {item["anchor_path"] for item in targets}
    stem_counts = filename_stem_counts(vault)
    restructuring_paths: set[str] = set()
    unauthorized_paths: set[str] = set()
    marker_boundary_violations: set[str] = set()
    digest_mismatches: set[str] = set()
    invalid_source_links: set[str] = set()
    invalid_entries: set[str] = set()
    changed_target_clusters: set[str] = set()
    after_blocks_by_cluster: dict[str, list[tuple[str, dict]]] = {}

    for path in changed_paths:
        if not path.endswith(".md"):
            continue
        before_text = before_reader(path)
        after_text = after_reader(path)
        before_blocks, before_malformed = parse_restructuring_blocks(before_text)
        after_blocks, after_malformed = parse_restructuring_blocks(after_text)
        before_by_cluster = {block["cluster_id"]: block for block in before_blocks}
        after_by_cluster: dict[str, list[dict]] = {}
        for block in after_blocks:
            after_by_cluster.setdefault(block["cluster_id"], []).append(block)
            after_blocks_by_cluster.setdefault(block["cluster_id"], []).append((path, block))

        changed_blocks = {
            cluster_id
            for cluster_id in set(before_by_cluster) | set(after_by_cluster)
            if restructuring_block_signature(before_by_cluster.get(cluster_id))
            != restructuring_block_signature(after_by_cluster.get(cluster_id, [None])[0])
            or len(after_by_cluster.get(cluster_id, [])) != 1
        }
        if changed_blocks:
            restructuring_paths.add(path)

        if path in target_anchors and before_text != after_text:
            outside_before, outside_before_malformed = text_outside_restructuring_markers(before_text)
            outside_after, outside_after_malformed = text_outside_restructuring_markers(after_text)
            if (
                before_malformed
                or after_malformed
                or outside_before_malformed
                or outside_after_malformed
                or outside_before != outside_after
                or not changed_blocks
            ):
                marker_boundary_violations.add(path)

        for cluster_id in changed_blocks:
            target = targets_by_cluster.get(cluster_id)
            if target is None or target["anchor_path"] != path:
                unauthorized_paths.add(path)
                continue
            blocks = after_by_cluster.get(cluster_id, [])
            if len(blocks) != 1:
                invalid_entries.add(f"{path}:{cluster_id}")
                continue
            block = blocks[0]
            changed_target_clusters.add(cluster_id)
            if block["digest"] != target["source_set_digest"]:
                digest_mismatches.add(path)
            if invalid_restructuring_source_links(block, stem_counts):
                invalid_source_links.add(path)
            if invalid_knowledge_entries(block):
                invalid_entries.add(f"{path}:{cluster_id}")

    missing_clusters: set[str] = set()
    for target in targets:
        blocks = after_blocks_by_cluster.get(target["cluster_id"], [])
        if len(blocks) != 1 or blocks[0][0] != target["anchor_path"] or target["cluster_id"] not in changed_target_clusters:
            missing_clusters.add(target["cluster_id"])

    return {
        "allowed_restructuring_targets": targets,
        "restructuring_paths": sorted(restructuring_paths),
        "unauthorized_restructuring_paths": sorted(unauthorized_paths),
        "marker_boundary_violations": sorted(marker_boundary_violations),
        "digest_mismatches": sorted(digest_mismatches),
        "invalid_source_links": sorted(invalid_source_links),
        "invalid_knowledge_entries": sorted(invalid_entries),
        "missing_restructuring_clusters": sorted(missing_clusters),
    }


def summarize_semantic_changes(
    report: dict,
    vault: Path,
    changed_paths: list[str],
    before_reader,
    after_reader,
) -> dict:
    allowed_synthesis = set(synthesis_targets_from_report(report))
    allowed_restatement = set(restatement_targets_from_report(report))
    synthesis_paths: set[str] = set()
    restatement_paths: set[str] = set()

    for path in changed_paths:
        if not path.endswith(".md"):
            continue
        before_text = before_reader(path)
        after_text = after_reader(path)
        before_synthesis = extract_synthesis_block(before_text)
        after_synthesis = extract_synthesis_block(after_text)
        if before_synthesis != after_synthesis and (before_synthesis is not None or after_synthesis is not None):
            synthesis_paths.add(path)
        before_restatement = extract_reconsolidation_tail(before_text)
        after_restatement = extract_reconsolidation_tail(after_text)
        if before_restatement != after_restatement and (before_restatement is not None or after_restatement is not None):
            restatement_paths.add(path)

    unauthorized_synthesis = sorted(path for path in synthesis_paths if path not in allowed_synthesis)
    unauthorized_restatement = sorted(path for path in restatement_paths if path not in allowed_restatement)
    restructuring = restructuring_audit_summary(vault, report, changed_paths, before_reader, after_reader)
    return {
        "allowed_synthesis_targets": sorted(allowed_synthesis),
        "allowed_restatement_targets": sorted(allowed_restatement),
        "changed_paths": sorted(changed_paths),
        "synthesis_count": len(synthesis_paths),
        "restatement_count": len(restatement_paths),
        "synthesis_paths": sorted(synthesis_paths),
        "restatement_paths": sorted(restatement_paths),
        "unauthorized_synthesis_paths": unauthorized_synthesis,
        "unauthorized_restatement_paths": unauthorized_restatement,
        **restructuring,
    }


def audit_weekly_semantic_changes(vault: Path, report: dict, commit_hash: str) -> dict:
    return summarize_semantic_changes(
        report,
        vault,
        changed_files_for_commit(vault, commit_hash),
        lambda path: read_file_at_parent(vault, commit_hash, path),
        lambda path: read_file_at_commit(vault, commit_hash, path),
    )


def audit_weekly_staged_changes(vault: Path, report: dict) -> dict:
    return summarize_semantic_changes(
        report,
        vault,
        changed_files_for_staged(vault),
        lambda path: read_file_at_head(vault, path),
        lambda path: read_file_from_index(vault, path),
    )


def format_unauthorized_message(summary: dict) -> str:
    parts: list[str] = []
    if summary["unauthorized_synthesis_paths"]:
        parts.append("unauthorized synthesis targets: " + ", ".join(summary["unauthorized_synthesis_paths"]))
    if summary["unauthorized_restatement_paths"]:
        parts.append("unauthorized restatement targets: " + ", ".join(summary["unauthorized_restatement_paths"]))
    if summary.get("unauthorized_restructuring_paths"):
        parts.append("unauthorized restructuring targets: " + ", ".join(summary["unauthorized_restructuring_paths"]))
    if summary.get("marker_boundary_violations"):
        parts.append("restructuring marker boundary violations: " + ", ".join(summary["marker_boundary_violations"]))
    if summary.get("digest_mismatches"):
        parts.append("restructuring digest mismatches: " + ", ".join(summary["digest_mismatches"]))
    if summary.get("invalid_source_links"):
        parts.append("invalid restructuring source links: " + ", ".join(summary["invalid_source_links"]))
    if summary.get("invalid_knowledge_entries"):
        parts.append("invalid restructuring knowledge entries: " + ", ".join(summary["invalid_knowledge_entries"]))
    if summary.get("missing_restructuring_clusters"):
        parts.append("missing restructuring clusters: " + ", ".join(summary["missing_restructuring_clusters"]))
    return "; ".join(parts)


def weekly_guard_has_violations(summary: dict) -> bool:
    return any(
        summary.get(field)
        for field in (
            "unauthorized_synthesis_paths",
            "unauthorized_restatement_paths",
            "unauthorized_restructuring_paths",
            "marker_boundary_violations",
            "digest_mismatches",
            "invalid_source_links",
            "invalid_knowledge_entries",
            "missing_restructuring_clusters",
        )
    )


def update_latest_log_semantic_fields(
    log_path: Path,
    synthesis_count: int,
    restatement_count: int,
    restructuring_count: int = 0,
) -> None:
    if not log_path.exists():
        raise ValueError(f"log does not exist: {log_path}")
    lines = log_path.read_text(encoding="utf-8").splitlines(keepends=True)
    entry_start = max((index for index, line in enumerate(lines) if line.startswith("## ")), default=-1)
    if entry_start == -1:
        raise ValueError("meditate log has no entry header")
    commit_index = next((index for index in range(entry_start, len(lines)) if lines[index].startswith("commit: ")), -1)
    if commit_index == -1:
        raise ValueError("latest meditate log has no commit line")

    entry_body = [
        line
        for line in lines[entry_start + 1 : commit_index]
        if not line.startswith("- 语义综合：")
        and not line.startswith("- 再巩固：")
        and not line.startswith("- 知识重构：")
    ]
    semantic_lines = [
        f"- 语义综合：{synthesis_count}\n",
        f"- 再巩固：{restatement_count}\n",
        f"- 知识重构：{restructuring_count}\n",
    ]
    updated = lines[: entry_start + 1] + entry_body + semantic_lines + lines[commit_index:]
    log_path.write_text("".join(updated), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Guard weekly meditate cadence contracts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prompt_parser = subparsers.add_parser("weekly-prompt")
    prompt_parser.add_argument("--report", required=True)

    commit_parser = subparsers.add_parser("audit-weekly-commit")
    commit_parser.add_argument("--report", required=True)
    commit_parser.add_argument("--commit", required=True)

    staged_parser = subparsers.add_parser("audit-weekly-staged")
    staged_parser.add_argument("--report", required=True)

    patch_parser = subparsers.add_parser("patch-log")
    patch_parser.add_argument("--log", required=True)
    patch_parser.add_argument("--synthesis-count", type=int, required=True)
    patch_parser.add_argument("--restatement-count", type=int, required=True)
    patch_parser.add_argument("--restructuring-count", type=int, default=0)

    args = parser.parse_args(argv)
    if args.command == "weekly-prompt":
        print(weekly_prompt_from_report(load_report(Path(args.report))))
        return 0

    if args.command == "audit-weekly-commit":
        summary = audit_weekly_semantic_changes(Path.cwd(), load_report(Path(args.report)), args.commit)
        print(json.dumps(summary, ensure_ascii=False))
        return 2 if weekly_guard_has_violations(summary) else 0

    if args.command == "audit-weekly-staged":
        summary = audit_weekly_staged_changes(Path.cwd(), load_report(Path(args.report)))
        print(json.dumps(summary, ensure_ascii=False))
        return 2 if weekly_guard_has_violations(summary) else 0

    if args.command == "patch-log":
        try:
            update_latest_log_semantic_fields(
                Path(args.log),
                synthesis_count=args.synthesis_count,
                restatement_count=args.restatement_count,
                restructuring_count=args.restructuring_count,
            )
        except ValueError as exc:
            print(f"cadence_guard: {exc}", file=sys.stderr)
            return 2
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
