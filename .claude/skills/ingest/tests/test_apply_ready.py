#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest.py"
SPEC = importlib.util.spec_from_file_location("ingest_apply_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ingest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ingest
SPEC.loader.exec_module(ingest)


def run(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(args, cwd=cwd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=process_env)


def isolated_report_env(vault: Path) -> tuple[Path, Path, dict[str, str]]:
    report_dir = vault / ".tmp" / "ingest-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir / "ingest.json", report_dir / "ingest.md", {"INGEST_TEST_REPORT_DIR": str(report_dir)}


def write_note(path: Path, title: str, note_type: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: "{title}"
type: {note_type}
---

# {title}

{body}
""",
        encoding="utf-8",
    )


class ApplyReadyTest(unittest.TestCase):
    def setup_ready_vault(self, vault: Path) -> None:
        self.assertEqual(0, run(vault, "git", "init").returncode)
        self.assertEqual(0, run(vault, "git", "config", "user.email", "test@example.com").returncode)
        self.assertEqual(0, run(vault, "git", "config", "user.name", "Test User").returncode)
        write_note(
            vault / "Resources" / "Loop Engineering" / "README.md",
            "Loop Engineering",
            "index",
            "Loop Engineering captures maker checker workflows, stop conditions, and verifier evidence.",
        )
        write_note(
            vault / "Resources" / "Loop Engineering" / "Loop Engineering Clearly Explained.md",
            "Loop Engineering Clearly Explained",
            "reference",
            "Loop Engineering Clearly Explained covers maker checker workflows and verifier evidence.",
        )
        write_note(
            vault / "Areas" / "Loop Engineering.md",
            "Loop Engineering",
            "area",
            "Ownership for maker checker workflows and verifier evidence in autonomous coding loops.",
        )
        self.assertEqual(0, run(vault, "git", "add", "Resources", "Areas").returncode)
        self.assertEqual(0, run(vault, "git", "commit", "-m", "baseline").returncode)
        body = "\n".join(
            [
                "Maker checker workflows keep autonomous coding loops grounded in independent verification.",
                "Stop condition design prevents a loop from continuing after evidence becomes weak.",
                "Verifier evidence should be attached to every handoff so meditate can trust the source.",
            ]
            * 20
        )
        write_note(vault / "Inbox" / "Loop Notes.md", "Loop Notes", "reference", body)

    def test_apply_ready_moves_markdown_and_writes_first_pass_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)

            report = ingest.make_report(vault, convert=False)
            self.assertEqual("ready", report["organization_plan"]["Inbox/Loop Notes.md"]["status"])

            ingest.apply_ready(vault, report, "2026-07-02")

            target = vault / "Resources" / "Loop Engineering" / "Loop Notes.md"
            self.assertFalse((vault / "Inbox" / "Loop Notes.md").exists())
            self.assertTrue(target.exists())
            organized = target.read_text(encoding="utf-8")
            self.assertTrue(organized.startswith("---\n"))
            self.assertIn('created: "2026-07-02"', organized)
            self.assertNotIn("<YYYY-MM-DD>", organized)
            self.assertIn("source_fingerprint: sha256:", organized)
            self.assertIn("> 整理自 Inbox，2026-07-02", organized)
            self.assertIn("## 提炼", organized)
            self.assertIn("关键点（基于原文摘录）：", organized)
            self.assertNotIn("当前重点围绕", organized)
            self.assertNotIn("\n- checker workflow\n", organized)
            self.assertNotIn("report-only", organized)
            self.assertIn("[[Loop Engineering Clearly Explained]]", organized)
            self.assertIn("## 原文 / 摘录", organized)
            self.assertIn("Maker checker workflows keep autonomous coding loops grounded", organized)
            notes, invalid = ingest.existing_notes(vault)
            self.assertEqual([], invalid)
            self.assertTrue(any(note["path"] == "Resources/Loop Engineering/Loop Notes.md" for note in notes))
            owner = (vault / "Areas" / "Loop Engineering.md").read_text(encoding="utf-8")
            self.assertIn("[[Loop Notes]]", owner)
            self.assertEqual(
                [{"from": "Inbox/Loop Notes.md", "to": "Resources/Loop Engineering/Loop Notes.md"}],
                report["applied"]["ready"],
            )
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/Loop Notes.md", staged)
            self.assertIn("Areas/Loop Engineering.md", staged)
            self.assertNotIn("Inbox/Loop Notes.md", staged)

    def test_apply_ready_blocks_exact_duplicates_from_normal_para_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            write_note(
                vault / "Resources" / "Loop Engineering" / "Canonical Loop Notes.md",
                "Canonical Loop Notes",
                "reference",
                "Source: https://example.com/loop-notes\n\nCanonical source about maker checker workflows and verifier evidence.",
            )
            self.assertEqual(0, run(vault, "git", "add", "Resources/Loop Engineering/Canonical Loop Notes.md").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "canonical source").returncode)
            canonical = vault / "Resources" / "Loop Engineering" / "Canonical Loop Notes.md"
            canonical.write_text(
                canonical.read_text(encoding="utf-8").replace('title: "Canonical Loop Notes"', 'title: "Canonical: Loop Notes"'),
                encoding="utf-8",
            )
            self.assertEqual(0, run(vault, "git", "add", "Resources/Loop Engineering/Canonical Loop Notes.md").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "title differs from stem").returncode)
            (vault / "Inbox" / "Loop Notes.md").write_text(
                """---
title: "Loop Notes"
type: reference
source_url: "https://example.com/loop-notes?utm_source=newsletter"
tags: [loop]
---

# Loop Notes

Maker checker workflows keep autonomous coding loops grounded in independent verification.
""",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=False)

            self.assertEqual("Inbox/Loop Notes.md", report["duplicates"][0]["inbox_path"])
            self.assertEqual("blocked", report["placement_readiness"]["Inbox/Loop Notes.md"]["status"])
            self.assertIn("exact duplicate", report["placement_readiness"]["Inbox/Loop Notes.md"]["reasons"])
            self.assertEqual("blocked", report["organization_plan"]["Inbox/Loop Notes.md"]["status"])

            ingest.apply_ready(vault, report, "2026-07-02")

            self.assertTrue((vault / "Inbox" / "Loop Notes.md").exists())
            self.assertFalse((vault / "Resources" / "Loop Engineering" / "Loop Notes.md").exists())
            self.assertEqual([], report["applied"]["ready"])

    def test_apply_duplicates_archives_untracked_markdown_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            write_note(
                vault / "Resources" / "Loop Engineering" / "Canonical Loop Notes.md",
                "Canonical Loop Notes",
                "reference",
                "Source: https://example.com/loop-notes\n\nCanonical source about maker checker workflows and verifier evidence.",
            )
            self.assertEqual(0, run(vault, "git", "add", "Resources/Loop Engineering/Canonical Loop Notes.md").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "canonical source").returncode)
            (vault / "Inbox" / "Loop Notes.md").write_text(
                """---
title: "Loop Notes"
type: reference
source_url: "https://example.com/loop-notes"
---

# Loop Notes

Maker checker workflows keep autonomous coding loops grounded in independent verification.
""",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=False)
            self.assertEqual(1, len(report["duplicates"]))

            ingest.apply_duplicates(vault, report, "2026-07-02")

            target = vault / "Archive" / "Duplicates" / "Loop Notes.md"
            self.assertTrue(target.exists())
            self.assertFalse((vault / "Inbox" / "Loop Notes.md").exists())
            archived = target.read_text(encoding="utf-8")
            self.assertTrue(archived.startswith("---\n"))
            self.assertIn("重复内容，canonical：[[Canonical Loop Notes]]", archived)
            self.assertNotIn("[[Canonical: Loop Notes]]", archived)
            self.assertEqual(
                [{
                    "from": "Inbox/Loop Notes.md",
                    "to": "Archive/Duplicates/Loop Notes.md",
                    "canonical": report["duplicates"][0]["canonical"],
                    "evidence": report["duplicates"][0]["evidence"],
                }],
                report["applied"]["duplicates"],
            )
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertIn("Archive/Duplicates/Loop Notes.md", staged)
            self.assertNotIn("Inbox/Loop Notes.md", staged)
            self.assertEqual([], report["skipped"])

    def test_apply_duplicates_skips_protected_archive_target_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            write_note(
                vault / "Resources" / "Loop Engineering" / "Canonical Loop Notes.md",
                "Canonical Loop Notes",
                "reference",
                "Source: https://example.com/loop-notes\n\nCanonical source about maker checker workflows.",
            )
            write_note(
                vault / "Archive" / "Duplicates" / "Loop Notes.md",
                "Previous Loop Notes",
                "archive",
                "Previous duplicate archive entry.",
            )
            self.assertEqual(0, run(vault, "git", "add", "Resources/Loop Engineering/Canonical Loop Notes.md", "Archive/Duplicates/Loop Notes.md").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "canonical and duplicate archive").returncode)
            (vault / "Archive" / "Duplicates" / "Loop Notes.md").unlink()
            (vault / "Inbox" / "Loop Notes.md").write_text(
                """---
title: "Loop Notes"
type: reference
source_url: "https://example.com/loop-notes"
---

# Loop Notes

Maker checker workflows keep autonomous coding loops grounded in independent verification.
""",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=False)
            self.assertIn("Archive/Duplicates/Loop Notes.md", report["protected_paths"])

            ingest.apply_duplicates(vault, report, "2026-07-02")

            self.assertFalse((vault / "Archive" / "Duplicates" / "Loop Notes.md").exists())
            self.assertTrue((vault / "Archive" / "Duplicates" / "Loop Notes-2.md").exists())
            status = run(vault, "git", "status", "--short", "--", "Archive/Duplicates/Loop Notes.md", "Archive/Duplicates/Loop Notes-2.md").stdout.replace('"', "")
            self.assertIn(" D Archive/Duplicates/Loop Notes.md", status)
            self.assertIn("A  Archive/Duplicates/Loop Notes-2.md", status)

    def test_cli_apply_duplicates_log_records_duplicate_move_truthfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            write_note(
                vault / "Resources" / "Loop Engineering" / "Canonical Loop Notes.md",
                "Canonical Loop Notes",
                "reference",
                "Source: https://example.com/loop-notes\n\nCanonical source about maker checker workflows.",
            )
            self.assertEqual(0, run(vault, "git", "add", "Resources/Loop Engineering/Canonical Loop Notes.md").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "canonical source").returncode)
            (vault / "Inbox" / "Loop Notes.md").write_text(
                """---
title: "Loop Notes"
type: reference
source_url: "https://example.com/loop-notes"
---

# Loop Notes

Maker checker workflows keep autonomous coding loops grounded in independent verification.
""",
                encoding="utf-8",
            )

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-duplicates",
                "--date",
                "2026-07-02",
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            log = (vault / ".claude" / "ingest.log").read_text(encoding="utf-8")
            self.assertIn("- Inbox/Loop Notes.md → Archive/Duplicates/Loop Notes.md", log)
            self.assertIn("- 留在 Inbox：无", log)
            self.assertNotIn("- 无移动", log)
            self.assertNotIn("Inbox/Loop Notes.md（exact duplicate）", log)

    def test_apply_duplicates_archives_converted_duplicate_with_original_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            write_note(
                vault / "Resources" / "Loop Engineering" / "Canonical Export.md",
                "Canonical Export",
                "reference",
                "Source: https://example.com/loop-export\n\nCanonical export about maker checker workflows.",
            )
            self.assertEqual(0, run(vault, "git", "add", "Resources/Loop Engineering/Canonical Export.md").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "canonical export").returncode)
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
cat > "$out" <<'EOF'
---
title: "Loop Export"
type: reference
source_url: "https://example.com/loop-export"
source_file: "Inbox/Loop Export.csv"
---

# Loop Export

Converted Loop Engineering export about maker checker workflows.
EOF
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox" / "Loop Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            report = ingest.make_report(vault, convert=True)
            self.assertEqual(1, len(report["duplicates"]))

            ingest.apply_duplicates(vault, report, "2026-07-02")

            markdown_target = vault / "Archive" / "Duplicates" / "Loop Export.md"
            source_target = vault / "Archive" / "Duplicates" / "source" / "Loop Export.csv"
            self.assertTrue(markdown_target.exists())
            self.assertTrue(source_target.exists())
            self.assertFalse((vault / "Inbox" / "Loop Export.md").exists())
            self.assertFalse((vault / "Inbox" / "Loop Export.csv").exists())
            archived = markdown_target.read_text(encoding="utf-8")
            self.assertTrue(archived.startswith("---\n"))
            self.assertIn("重复内容，canonical：[[Canonical Export]]", archived)
            self.assertIn("原始文件：[[source/Loop Export.csv]]", archived)
            self.assertIn('source_file: "source/Loop Export.csv"', archived)
            self.assertNotIn('source_file: "Inbox/Loop Export.csv"', archived)
            self.assertEqual("metric,value\nloops,3\n", source_target.read_text(encoding="utf-8"))
            applied = report["applied"]["duplicates"][0]
            self.assertEqual("Inbox/Loop Export.md", applied["from"])
            self.assertEqual("Archive/Duplicates/Loop Export.md", applied["to"])
            self.assertEqual([{"from": "Inbox/Loop Export.csv", "to": "Archive/Duplicates/source/Loop Export.csv"}], applied["source_moves"])
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertIn("Archive/Duplicates/Loop Export.md", staged)
            self.assertIn("Archive/Duplicates/source/Loop Export.csv", staged)
            self.assertEqual([], report["skipped"])

    def test_apply_ready_normalizes_stale_wrapper_source_lines_for_converted_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            (vault / "Inbox" / "Loop Audio.m4a").write_bytes(b"fake audio bytes")
            write_note(
                vault / "Inbox" / "Loop Audio.md",
                "Loop Audio",
                "reference",
                "\n".join([
                    "原始文件：[[Loop Audio.m4a]]",
                    "",
                    "## 转录",
                    "",
                    "Maker checker workflows keep autonomous coding loops grounded in independent verification.",
                    "Stop condition design prevents a loop from continuing after evidence becomes weak.",
                    "Verifier evidence should be attached to every handoff so meditate can trust the source.",
                ]),
            )

            report = ingest.make_report(vault, convert=True)
            self.assertEqual("ready", report["organization_plan"]["Inbox/Loop Audio.m4a"]["status"])

            ingest.apply_ready(vault, report, "2026-07-02")

            target = vault / "Resources" / "Loop Engineering" / "Loop Audio.md"
            self.assertTrue(target.exists())
            organized = target.read_text(encoding="utf-8")
            self.assertIn("原始文件：[[source/Loop Audio.m4a]]", organized)
            self.assertNotIn("原始文件：[[Loop Audio.m4a]]", organized)
            self.assertTrue((vault / "Resources" / "Loop Engineering" / "source" / "Loop Audio.m4a").exists())

    def test_apply_ready_preserves_source_provenance_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").write_text(
                """---
title: "Loop Notes"
type: reference
tags:
  - loop
  - provenance
canonical_url: "https://example.com/canonical-loop-notes"
author: "Ada Lovelace"
published: "2026-06-30"
description: "Original capture with provenance metadata."
---

# Loop Notes

Maker checker workflows keep autonomous coding loops grounded in independent verification.
Stop condition design prevents a loop from continuing after evidence becomes weak.
Verifier evidence should be attached to every handoff so meditate can trust the source.
""",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=False)
            ingest.apply_ready(vault, report, "2026-07-02")

            organized = (vault / "Resources" / "Loop Engineering" / "Loop Notes.md").read_text(encoding="utf-8")
            self.assertIn("tags:\n  - loop\n  - provenance", organized)
            self.assertIn('canonical_url: "https://example.com/canonical-loop-notes"', organized)
            self.assertNotIn('source_url: "https://example.com/canonical-loop-notes"', organized)
            self.assertIn('author: "Ada Lovelace"', organized)
            self.assertIn('published: "2026-06-30"', organized)
            self.assertIn('description: "Original capture with provenance metadata."', organized)
            self.assertIn("source_fingerprint: sha256:", organized)

    def test_apply_ready_writes_normalized_source_urls_to_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").write_text(
                """---
title: "Loop Notes"
type: reference
source_url: "https://EXAMPLE.com/articles/loop?utm_source=newsletter&spm=a2c&id=42#section"
canonical_url: "https://EXAMPLE.com/articles/loop?utm_campaign=x&spm=a2c&id=42#canonical"
---

# Loop Notes

Maker checker workflows keep autonomous coding loops grounded in independent verification.
Stop condition design prevents a loop from continuing after evidence becomes weak.
Verifier evidence should be attached to every handoff so meditate can trust the source.
""",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=False)
            ingest.apply_ready(vault, report, "2026-07-02")

            organized = (vault / "Resources" / "Loop Engineering" / "Loop Notes.md").read_text(encoding="utf-8")
            self.assertIn('source_url: "https://example.com/articles/loop?id=42"', organized)
            self.assertIn('canonical_url: "https://example.com/articles/loop?id=42"', organized)
            self.assertNotIn("utm_", organized)
            self.assertNotIn("spm=", organized)
            self.assertNotIn("#section", organized)

    def test_apply_ready_creates_missing_area_owner_from_reported_create_area_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.assertEqual(0, run(vault, "git", "init").returncode)
            self.assertEqual(0, run(vault, "git", "config", "user.email", "test@example.com").returncode)
            self.assertEqual(0, run(vault, "git", "config", "user.name", "Test User").returncode)
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing, traffic shaping, cold starts, and GPU serving patterns.",
            )
            self.assertEqual(0, run(vault, "git", "add", "Resources").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "baseline").returncode)
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Serverless inference routing, traffic shaping, cold starts, and GPU serving patterns.",
            )

            report = ingest.make_report(vault, convert=False)
            self.assertEqual("ready", report["organization_plan"]["Inbox/Routing Pattern.md"]["status"])

            ingest.apply_ready(vault, report, "2026-07-02")

            target = vault / "Resources" / "LLM Inference" / "Routing Pattern.md"
            owner = vault / "Areas" / "LLM Inference.md"
            self.assertTrue(target.exists())
            self.assertTrue(owner.exists())
            self.assertFalse((vault / "Inbox" / "Routing Pattern.md").exists())
            self.assertIn("[[Routing Pattern]]", owner.read_text(encoding="utf-8"))
            self.assertIn("由 `Areas/LLM Inference.md` 承接", target.read_text(encoding="utf-8"))
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertIn("Resources/LLM Inference/Routing Pattern.md", staged)
            self.assertIn("Areas/LLM Inference.md", staged)

    def test_cli_apply_ready_runs_first_pass_apply_without_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-ready",
                "--date",
                "2026-07-02",
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((vault / "Resources" / "Loop Engineering" / "Loop Notes.md").exists())
            self.assertFalse((vault / "Inbox" / "Loop Notes.md").exists())
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/Loop Notes.md", staged)
            self.assertIn("Areas/Loop Engineering.md", staged)
            self.assertFalse((vault / ".claude" / "ingest.log").exists())

    def test_cli_apply_ready_only_applies_reviewed_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            write_note(
                vault / "Inbox" / "Loop Extra.md",
                "Loop Extra",
                "reference",
                "Loop Engineering extra notes about maker checker workflows and verifier evidence.",
            )
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
cat > "$out" <<'EOF'
---
title: "Unselected Export"
type: reference
---

# Unselected Export

Converted Loop Engineering export about maker checker workflows.
EOF
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox" / "Unselected Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")
            json_report, markdown_report, env = isolated_report_env(vault)

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-ready",
                "--json",
                str(json_report),
                "--markdown",
                str(markdown_report),
                "--date",
                "2026-07-02",
                "--only",
                "Inbox/Loop Notes.md",
                "--commit",
                env=env,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((vault / "Resources" / "Loop Engineering" / "Loop Notes.md").exists())
            self.assertFalse((vault / "Inbox" / "Loop Notes.md").exists())
            self.assertTrue((vault / "Inbox" / "Loop Extra.md").exists())
            self.assertTrue((vault / "Inbox" / "Unselected Export.csv").exists())
            self.assertFalse((vault / "Inbox" / "Unselected Export.md").exists())
            self.assertFalse((vault / "Resources" / "Loop Engineering" / "Loop Extra.md").exists())
            committed = run(vault, "git", "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/Loop Notes.md", committed)
            self.assertNotIn("Resources/Loop Engineering/Loop Extra.md", committed)
            log = (vault / ".claude" / "ingest.log").read_text(encoding="utf-8")
            self.assertIn("- 留在 Inbox：Inbox/Loop Extra.md（not selected for apply-ready）", log)
            self.assertIn("- 留在 Inbox：Inbox/Unselected Export.csv（not selected for apply-ready）", log)
            report = json.loads(json_report.read_text(encoding="utf-8"))
            self.assertEqual(["Inbox/Loop Notes.md"], report["apply_selection_audit"]["selected_only"])
            self.assertEqual(["Inbox/Loop Notes.md"], report["apply_selection_audit"]["applied_ready"])
            self.assertEqual(
                ["Inbox/Loop Extra.md", "Inbox/Unselected Export.csv"],
                report["apply_selection_audit"]["skipped_ready_not_selected"],
            )
            self.assertEqual([], report["apply_selection_audit"]["unmatched_only"])
            metrics = report["intake_quality_metrics"]
            self.assertEqual(1, metrics["candidates_total"])
            self.assertEqual(1, metrics["ready_for_apply"])
            self.assertEqual(0, metrics["blocked"])
            self.assertEqual(1.0, metrics["ready_rate"])
            self.assertEqual({}, metrics["blocked_by_reason"])
            self.assertEqual(2, metrics["excluded_by_selection"])
            markdown = markdown_report.read_text(encoding="utf-8")
            self.assertIn("## apply-ready 选择审计", markdown)
            self.assertIn("- selected_only：`Inbox/Loop Notes.md`", markdown)
            self.assertIn("- skipped_ready_not_selected：`Inbox/Loop Extra.md`", markdown)
            self.assertIn("- `Inbox/Loop Extra.md`：not selected for apply-ready", markdown)

    def test_cli_apply_ready_fails_for_unmatched_only_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
echo "# Converted Export" > "$out"
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox" / "Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-ready",
                "--date",
                "2026-07-02",
                "--only",
                "Inbox/Missing.md",
            )

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("unmatched --only path", completed.stderr)
            self.assertTrue((vault / "Inbox" / "Loop Notes.md").exists())
            self.assertTrue((vault / "Inbox" / "Export.csv").exists())
            self.assertFalse((vault / "Inbox" / "Export.md").exists())

    def test_cli_apply_ready_commit_records_hash_without_committing_unrelated_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            write_note(vault / "Areas" / "Unrelated.md", "Unrelated", "area", "Existing unrelated area.")
            self.assertEqual(0, run(vault, "git", "add", "Areas/Unrelated.md").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "add unrelated").returncode)
            unrelated = vault / "Areas" / "Unrelated.md"
            unrelated.write_text(unrelated.read_text(encoding="utf-8") + "\nPre-existing staged edit.\n", encoding="utf-8")
            self.assertEqual(0, run(vault, "git", "add", "Areas/Unrelated.md").returncode)

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-ready",
                "--date",
                "2026-07-02",
                "--commit",
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            head = run(vault, "git", "log", "-1", "--format=%H%n%s").stdout.splitlines()
            self.assertEqual("ingest: Loop Notes", head[1])
            committed = run(vault, "git", "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/Loop Notes.md", committed)
            self.assertIn("Areas/Loop Engineering.md", committed)
            self.assertNotIn("Areas/Unrelated.md", committed)
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertEqual(["Areas/Unrelated.md"], staged)
            log = (vault / ".claude" / "ingest.log").read_text(encoding="utf-8")
            self.assertIn("Inbox/Loop Notes.md → Resources/Loop Engineering/Loop Notes.md", log)
            self.assertIn("- 摄入质量：ready_rate=1.0, ready_for_apply=1, blocked=0, handoff_ready=1, handoff_blocked=0, learning_rules_applied=0", log)
            self.assertIn("- 阻断原因：无", log)
            self.assertIn("- 留在 Inbox：无", log)
            self.assertIn(f"commit: {head[0]}", log)

    def test_cli_apply_ready_log_records_converted_source_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
cat > "$out" <<'EOF'
---
title: "Loop Metrics"
type: reference
source_file: "Inbox/Loop Metrics.csv"
---

# Loop Metrics

Converted Loop Engineering export about maker checker workflows and verifier evidence.
EOF
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox" / "Loop Metrics.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-ready",
                "--date",
                "2026-07-02",
                "--commit",
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            log = (vault / ".claude" / "ingest.log").read_text(encoding="utf-8")
            self.assertIn("Inbox/Loop Metrics.md → Resources/Loop Engineering/Loop Metrics.md", log)
            self.assertIn("Inbox/Loop Metrics.csv → Resources/Loop Engineering/source/Loop Metrics.csv", log)
            self.assertIn("- 留在 Inbox：无", log)

    def test_cli_apply_ready_log_lists_left_inbox_files_with_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Raw Capture.bin").write_bytes(b"raw unsupported capture")

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-ready",
                "--date",
                "2026-07-02",
                "--commit",
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((vault / "Inbox" / "Raw Capture.bin").exists())
            log = (vault / ".claude" / "ingest.log").read_text(encoding="utf-8")
            self.assertIn("Inbox/Loop Notes.md → Resources/Loop Engineering/Loop Notes.md", log)
            self.assertIn("- 留在 Inbox：Inbox/Raw Capture.bin（unsupported file type）", log)

    def test_apply_ready_skips_candidate_when_owner_becomes_protected_after_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)

            report = ingest.make_report(vault, convert=False)
            self.assertEqual("ready", report["organization_plan"]["Inbox/Loop Notes.md"]["status"])

            owner = vault / "Areas" / "Loop Engineering.md"
            owner.write_text(owner.read_text(encoding="utf-8") + "\nUser draft that must not be staged.\n", encoding="utf-8")

            ingest.apply_ready(vault, report, "2026-07-02")

            self.assertTrue((vault / "Inbox" / "Loop Notes.md").exists())
            self.assertFalse((vault / "Resources" / "Loop Engineering" / "Loop Notes.md").exists())
            self.assertEqual([], report["applied"]["ready"])
            self.assertIn(
                {"path": "Inbox/Loop Notes.md", "reason": "protected paths changed after report", "paths": ["Areas/Loop Engineering.md"]},
                report["skipped"],
            )
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertEqual([], staged)

    def test_apply_ready_refreshes_resource_index_when_generator_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            readme = vault / "Resources" / "Loop Engineering" / "README.md"
            readme.write_text(
                """---
title: "Loop Engineering"
type: index
---

# Loop Engineering

<!-- BEGIN: resource-index -->
<!-- END: resource-index -->
""",
                encoding="utf-8",
            )
            generator = vault / ".claude" / "skills" / "meditate" / "scripts" / "generate_resource_index.py"
            generator.parent.mkdir(parents=True)
            generator.write_text(
                """#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--dir", required=True)
args = parser.parse_args()
readme = Path(args.dir) / "README.md"
text = readme.read_text(encoding="utf-8")
readme.write_text(text.replace("<!-- BEGIN: resource-index -->\\n<!-- END: resource-index -->", "<!-- BEGIN: resource-index -->\\n- [[Loop Notes]]\\n<!-- END: resource-index -->"), encoding="utf-8")
""",
                encoding="utf-8",
            )
            generator.chmod(0o755)
            self.assertEqual(0, run(vault, "git", "add", "Resources/Loop Engineering/README.md", ".claude/skills/meditate/scripts/generate_resource_index.py").returncode)
            self.assertEqual(0, run(vault, "git", "commit", "-m", "resource index generator").returncode)

            report = ingest.make_report(vault, convert=False)
            self.assertEqual("ready", report["organization_plan"]["Inbox/Loop Notes.md"]["status"])

            ingest.apply_ready(vault, report, "2026-07-02")

            self.assertIn("[[Loop Notes]]", readme.read_text(encoding="utf-8"))
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/README.md", staged)

    def test_apply_ready_moves_converted_markdown_and_original_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
cat > "$out" <<'EOF'
---
title: "Loop Metrics"
type: reference
---

# Loop Metrics

Converted Loop Engineering export about maker checker workflows and verifier evidence.
EOF
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox" / "Loop Metrics.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            report = ingest.make_report(vault, convert=True)
            plan = report["organization_plan"]["Inbox/Loop Metrics.csv"]
            self.assertEqual("ready", plan["status"])
            self.assertEqual(
                [{"from": "Inbox/Loop Metrics.csv", "to": "Resources/Loop Engineering/source/Loop Metrics.csv"}],
                plan["source_moves"],
            )

            ingest.apply_ready(vault, report, "2026-07-02")

            target = vault / "Resources" / "Loop Engineering" / "Loop Metrics.md"
            source = vault / "Resources" / "Loop Engineering" / "source" / "Loop Metrics.csv"
            self.assertTrue(target.exists())
            self.assertTrue(source.exists())
            self.assertFalse((vault / "Inbox" / "Loop Metrics.md").exists())
            self.assertFalse((vault / "Inbox" / "Loop Metrics.csv").exists())
            organized = target.read_text(encoding="utf-8")
            self.assertIn('source_file: "source/Loop Metrics.csv"', organized)
            notes, invalid = ingest.existing_notes(vault)
            self.assertEqual([], invalid)
            self.assertTrue(any(note["path"] == "Resources/Loop Engineering/Loop Metrics.md" for note in notes))
            self.assertIn("原始文件：[[source/Loop Metrics.csv]]", organized)
            self.assertIn("## 提炼", organized)
            self.assertIn("Converted Loop Engineering export", organized)
            self.assertEqual("metric,value\nloops,3\n", source.read_text(encoding="utf-8"))
            staged = run(vault, "git", "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/Loop Metrics.md", staged)
            self.assertIn("Resources/Loop Engineering/source/Loop Metrics.csv", staged)
            self.assertIn("Areas/Loop Engineering.md", staged)
            self.assertNotIn("Inbox/Loop Metrics.md", staged)
            self.assertNotIn("Inbox/Loop Metrics.csv", staged)

    def test_make_report_pairs_existing_conversion_markdown_without_wrapper_source_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            (vault / "Inbox" / "2606.13392v2.pdf").write_bytes(b"%PDF-1.4 fake paper bytes\n")
            (vault / "Inbox" / "2606.13392v2.md").write_text(
                """MiniMax Sparse Attention

Loop Engineering notes about maker checker workflows, verifier evidence, and autonomous coding loops.
Stop condition design keeps the loop grounded before evidence becomes weak.
Verifier evidence should be attached to every handoff so meditate can trust the source.
""",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=True, only_paths={"Inbox/2606.13392v2.md"})
            by_path = {candidate["path"]: candidate for candidate in report["candidates"]}

            self.assertEqual("ready", by_path["Inbox/2606.13392v2.pdf"]["status"])
            self.assertEqual("Inbox/2606.13392v2.md", by_path["Inbox/2606.13392v2.pdf"]["markdown_path"])
            self.assertNotIn("Inbox/2606.13392v2.md", by_path)
            self.assertEqual("ready", report["organization_plan"]["Inbox/2606.13392v2.pdf"]["status"])

            ingest.apply_ready(vault, report, "2026-07-02", only_paths={"Inbox/2606.13392v2.md"})

            self.assertTrue((vault / "Resources" / "Loop Engineering" / "MiniMax Sparse Attention.md").exists())
            self.assertTrue((vault / "Resources" / "Loop Engineering" / "source" / "MiniMax Sparse Attention.pdf").exists())
            self.assertFalse((vault / "Inbox" / "2606.13392v2.md").exists())
            self.assertFalse((vault / "Inbox" / "2606.13392v2.pdf").exists())

    def test_convertible_target_and_source_use_converted_markdown_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
cat > "$out" <<'EOF'
MiniMax Sparse Attention

Loop Engineering notes about maker checker workflows, verifier evidence, and autonomous coding loops.
Stop condition design keeps the loop grounded before evidence becomes weak.
Verifier evidence should be attached to every handoff so meditate can trust the source.
EOF
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox" / "2606.13392v2.pdf").write_bytes(b"%PDF-1.4 fake paper bytes\n")

            report = ingest.make_report(vault, convert=True, only_paths={"Inbox/2606.13392v2.pdf"})
            candidate = next(item for item in report["candidates"] if item["path"] == "Inbox/2606.13392v2.pdf")
            plan = report["organization_plan"]["Inbox/2606.13392v2.pdf"]
            encoding = report["encoding_plan"]["Inbox/2606.13392v2.pdf"]

            self.assertEqual("MiniMax Sparse Attention", candidate["title"])
            self.assertEqual("Resources/Loop Engineering/MiniMax Sparse Attention.md", plan["target"])
            self.assertEqual(
                [{"from": "Inbox/2606.13392v2.pdf", "to": "Resources/Loop Engineering/source/MiniMax Sparse Attention.pdf"}],
                plan["source_moves"],
            )
            self.assertEqual("source/MiniMax Sparse Attention.pdf", encoding["source_file"]["expected"])

    def test_apply_ready_does_not_duplicate_existing_owner_backlink_by_wikilink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            owner = vault / "Areas" / "Loop Engineering.md"
            owner.write_text(
                owner.read_text(encoding="utf-8")
                + "\n## 资料索引\n\n- [[Loop Notes]]：existing custom backlink.\n",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=False)
            ingest.apply_ready(vault, report, "2026-07-02")

            owner_text = owner.read_text(encoding="utf-8")
            self.assertEqual(1, owner_text.count("[[Loop Notes]]"))

    def test_apply_ready_leaves_existing_same_name_markdown_without_source_evidence_in_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            converter.chmod(0o755)
            (vault / "Inbox" / "Loop Metrics.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")
            write_note(
                vault / "Inbox" / "Loop Metrics.md",
                "Loop Metrics",
                "reference",
                "Converted Loop Engineering export about maker checker workflows and verifier evidence. The old dashboard mentions Loop Metrics.csv as a dataset.",
            )

            report = ingest.make_report(vault, convert=True)

            by_path = {candidate["path"]: candidate for candidate in report["candidates"]}
            self.assertEqual("left_in_inbox", by_path["Inbox/Loop Metrics.csv"]["status"])
            self.assertEqual("same-name markdown conflict", by_path["Inbox/Loop Metrics.csv"]["reason"])
            self.assertEqual("left_in_inbox", by_path["Inbox/Loop Metrics.md"]["status"])
            self.assertEqual("same-name markdown conflict", by_path["Inbox/Loop Metrics.md"]["reason"])

            ingest.apply_ready(vault, report, "2026-07-02")

            self.assertFalse((vault / "Resources" / "Loop Engineering" / "Loop Metrics.md").exists())
            self.assertFalse((vault / "Resources" / "Loop Engineering" / "source" / "Loop Metrics.csv").exists())
            self.assertTrue((vault / "Inbox" / "Loop Metrics.md").exists())
            self.assertTrue((vault / "Inbox" / "Loop Metrics.csv").exists())

    def test_cli_apply_ready_commit_includes_converted_original_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            (vault / "Inbox" / "Loop Notes.md").unlink()
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
cat > "$out" <<'EOF'
---
title: "Loop Metrics"
type: reference
---

# Loop Metrics

Converted Loop Engineering export about maker checker workflows and verifier evidence.
EOF
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox" / "Loop Metrics.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            completed = run(
                vault,
                sys.executable,
                str(MODULE_PATH),
                "--mode",
                "apply-ready",
                "--date",
                "2026-07-02",
                "--only",
                "Inbox/Loop Metrics.csv",
                "--commit",
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            committed = run(vault, "git", "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/Loop Metrics.md", committed)
            self.assertIn("Resources/Loop Engineering/source/Loop Metrics.csv", committed)
            organized = (vault / "Resources" / "Loop Engineering" / "Loop Metrics.md").read_text(encoding="utf-8")
            self.assertIn('source_file: "source/Loop Metrics.csv"', organized)
            self.assertIn("原始文件：[[source/Loop Metrics.csv]]", organized)

    def test_headless_wrapper_exists_for_apply_ready(self) -> None:
        wrapper = MODULE_PATH.resolve().parents[3] / "bin" / "ingest-apply-ready"
        self.assertTrue(wrapper.exists())
        self.assertTrue(wrapper.stat().st_mode & 0o111)
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn("apply-ready", text)
        self.assertIn("--only", text)
        self.assertIn("INGEST_TEST_REPORT_DIR", text)
        self.assertIn('"/tmp"', text)
        self.assertIn("ingest.json", text)
        self.assertIn("ingest.md", text)
        repo = MODULE_PATH.resolve().parents[4]
        ignored = run(repo, "git", "check-ignore", "--no-index", "-q", ".claude/bin/ingest-apply-ready")
        self.assertNotEqual(0, ignored.returncode, "ingest-apply-ready must be whitelisted from .gitignore")

    def test_headless_wrapper_runs_apply_ready_only_commit_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            self.setup_ready_vault(vault)
            write_note(
                vault / "Inbox" / "Loop Extra.md",
                "Loop Extra",
                "reference",
                "Loop Engineering extra notes about maker checker workflows and verifier evidence.",
            )
            source_root = MODULE_PATH.resolve().parents[4]
            wrapper_src = source_root / ".claude" / "bin" / "ingest-apply-ready"
            wrapper_dst = vault / ".claude" / "bin" / "ingest-apply-ready"
            script_dst = vault / ".claude" / "skills" / "ingest" / "scripts" / "ingest.py"
            wrapper_dst.parent.mkdir(parents=True, exist_ok=True)
            script_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wrapper_src, wrapper_dst)
            shutil.copy2(MODULE_PATH, script_dst)
            wrapper_dst.chmod(0o755)
            _json_report, markdown_report, env = isolated_report_env(vault)

            completed = run(
                vault,
                ".claude/bin/ingest-apply-ready",
                "2026-07-02",
                "--only",
                "Inbox/Loop Notes.md",
                "--commit",
                env=env,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((vault / "Resources" / "Loop Engineering" / "Loop Notes.md").exists())
            self.assertFalse((vault / "Inbox" / "Loop Notes.md").exists())
            self.assertTrue((vault / "Inbox" / "Loop Extra.md").exists())
            committed = run(vault, "git", "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
            self.assertIn("Resources/Loop Engineering/Loop Notes.md", committed)
            self.assertIn("Areas/Loop Engineering.md", committed)
            self.assertNotIn("Resources/Loop Engineering/Loop Extra.md", committed)
            head_hash = run(vault, "git", "log", "-1", "--format=%H").stdout.strip()
            log = (vault / ".claude" / "ingest.log").read_text(encoding="utf-8")
            self.assertIn(f"commit: {head_hash}", log)
            self.assertIn("- 留在 Inbox：Inbox/Loop Extra.md（not selected for apply-ready）", log)
            markdown = markdown_report.read_text(encoding="utf-8")
            self.assertIn("## apply-ready 选择审计", markdown)
            self.assertIn("- selected_only：`Inbox/Loop Notes.md`", markdown)
            self.assertIn("- skipped_ready_not_selected：`Inbox/Loop Extra.md`", markdown)


if __name__ == "__main__":
    unittest.main()
