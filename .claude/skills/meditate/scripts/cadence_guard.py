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


def weekly_prompt_from_report(report: dict) -> str:
    synthesis_targets = synthesis_targets_from_report(report)
    restatement_targets = restatement_targets_from_report(report)
    synthesis_lines = synthesis_targets or ["无"]
    restatement_lines = restatement_targets or ["无"]
    return "\n".join(
        [
            "Weekly semantic candidate guard from /tmp/meditate.json:",
            f"- Allowed synthesis targets ({len(synthesis_targets)}):",
            *[f"  - {item}" for item in synthesis_lines],
            f"- Allowed restatement targets ({len(restatement_targets)}):",
            *[f"  - {item}" for item in restatement_lines],
            "Do not write synthesis or restatement to any other files. If a useful topic is not listed here, leave it untouched and report it instead.",
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


def summarize_semantic_changes(
    report: dict,
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
    }


def audit_weekly_semantic_changes(vault: Path, report: dict, commit_hash: str) -> dict:
    return summarize_semantic_changes(
        report,
        changed_files_for_commit(vault, commit_hash),
        lambda path: read_file_at_parent(vault, commit_hash, path),
        lambda path: read_file_at_commit(vault, commit_hash, path),
    )


def audit_weekly_staged_changes(vault: Path, report: dict) -> dict:
    return summarize_semantic_changes(
        report,
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
    return "; ".join(parts)


def update_latest_log_semantic_fields(log_path: Path, synthesis_count: int, restatement_count: int) -> None:
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
        if not line.startswith("- 语义综合：") and not line.startswith("- 再巩固：")
    ]
    semantic_lines = [f"- 语义综合：{synthesis_count}\n", f"- 再巩固：{restatement_count}\n"]
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

    args = parser.parse_args(argv)
    if args.command == "weekly-prompt":
        print(weekly_prompt_from_report(load_report(Path(args.report))))
        return 0

    if args.command == "audit-weekly-commit":
        summary = audit_weekly_semantic_changes(Path.cwd(), load_report(Path(args.report)), args.commit)
        print(json.dumps(summary, ensure_ascii=False))
        return 2 if summary["unauthorized_synthesis_paths"] or summary["unauthorized_restatement_paths"] else 0

    if args.command == "audit-weekly-staged":
        summary = audit_weekly_staged_changes(Path.cwd(), load_report(Path(args.report)))
        print(json.dumps(summary, ensure_ascii=False))
        return 2 if summary["unauthorized_synthesis_paths"] or summary["unauthorized_restatement_paths"] else 0

    if args.command == "patch-log":
        try:
            update_latest_log_semantic_fields(
                Path(args.log),
                synthesis_count=args.synthesis_count,
                restatement_count=args.restatement_count,
            )
        except ValueError as exc:
            print(f"cadence_guard: {exc}", file=sys.stderr)
            return 2
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
