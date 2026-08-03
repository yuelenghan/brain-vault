#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "optimize_vault.py"
SPEC = importlib.util.spec_from_file_location("optimize_vault_memory_cycle_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
optimize_vault = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = optimize_vault
SPEC.loader.exec_module(optimize_vault)


def write_note(
    path: Path,
    title: str,
    note_type: str,
    body: str = "",
    created: str = "2026-07-01",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: "{title}"
type: {note_type}
created: {created}
---

# {title}

{body}
""",
        encoding="utf-8",
    )


def git_init(vault: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)


def git_commit(vault: Path, message: str, when: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = when
    env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", "add", "."], cwd=vault, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", message], cwd=vault, check=True, env=env)


def append_recall_entry(
    vault: Path,
    when: dt.datetime,
    query: str,
    activated: list[tuple[str, str]],
    result: str,
    gap_topic: str | None = None,
) -> None:
    log_path = vault / ".claude" / "recall.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"## {when:%Y-%m-%d %H:%M} recall", f"- 查询：{query}"]
    for path, strength in activated:
        lines.append(f"- 激活：{path} ({strength})")
    lines.append(f"- 结果：{result}")
    lines.append(f"- 缺口：{gap_topic or '无'}")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def run_apply_safe(vault: Path) -> dict:
    old_cwd = Path.cwd()
    old_report_dir = optimize_vault.FIXED_REPORT_DIR
    old_json_report = optimize_vault.FIXED_JSON_REPORT
    old_markdown_report = optimize_vault.FIXED_MARKDOWN_REPORT
    report_dir = vault / ".test-reports"
    json_report = report_dir / "meditate.json"
    markdown_report = report_dir / "meditate.md"
    report_dir.mkdir(parents=True, exist_ok=True)
    try:
        optimize_vault.FIXED_REPORT_DIR = report_dir.resolve()
        optimize_vault.FIXED_JSON_REPORT = json_report.resolve()
        optimize_vault.FIXED_MARKDOWN_REPORT = markdown_report.resolve()
        os.chdir(vault)
        rc = optimize_vault.main(
            [
                "--mode",
                "apply-safe",
                "--json",
                str(json_report),
                "--markdown",
                str(markdown_report),
                "--date",
                "2026-07-06",
                "--no-log",
            ]
        )
    finally:
        os.chdir(old_cwd)
        optimize_vault.FIXED_REPORT_DIR = old_report_dir
        optimize_vault.FIXED_JSON_REPORT = old_json_report
        optimize_vault.FIXED_MARKDOWN_REPORT = old_markdown_report
    assert rc == 0
    return json.loads(json_report.read_text(encoding="utf-8"))


class MemoryCycleTest(unittest.TestCase):
    def test_build_report_includes_retrieval_stats_and_staleness_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_note(vault / "Resources" / "PKM" / "README.md", "PKM", "index", "# PKM")
            write_note(vault / "Resources" / "PKM" / "Hot Note.md", "Hot Note", "reference", "Retriever memory and grader loops.")
            write_note(vault / "Resources" / "PKM" / "Cold Note.md", "Cold Note", "reference", "Dormant reference body.")
            git_commit(vault, "initial", "2025-05-01T12:00:00")

            today = dt.datetime.now().replace(second=0, microsecond=0)
            append_recall_entry(
                vault,
                today - dt.timedelta(days=5),
                "grader loops",
                [("Resources/PKM/Hot Note.md", "direct")],
                "answered",
            )
            append_recall_entry(
                vault,
                today - dt.timedelta(days=3),
                "memory routing",
                [("Resources/PKM/Hot Note.md", "concept")],
                "partial",
            )
            append_recall_entry(
                vault,
                today - dt.timedelta(days=1),
                "semantic recall gap",
                [("Resources/PKM/Hot Note.md", "spread")],
                "miss",
                gap_topic="semantic recall",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        hot = next(item for item in report["retrieval_stats"]["notes"] if item["path"] == "Resources/PKM/Hot Note.md")
        stale = next(item for item in report["staleness_report"]["candidates"] if item["path"] == "Resources/PKM/Cold Note.md")
        self.assertEqual(3, hot["retrieval_count"])
        self.assertEqual("stale", stale["status"])
        self.assertEqual("semantic recall", report["retrieval_stats"]["high_gap_topics"][0]["topic"])
        self.assertEqual(180, report["staleness_report"]["retrieval_window_days"])
        self.assertEqual(180, report["staleness_report"]["dormant_threshold_days"])
        self.assertEqual(365, report["staleness_report"]["stale_threshold_days"])

    def test_build_report_emits_synthesis_and_restatement_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "Agent Memory"
            topic.mkdir(parents=True)
            (topic / "README.md").write_text(
                """---
title: "Agent Memory"
type: index
---

# Agent Memory
""",
                encoding="utf-8",
            )
            write_note(
                topic / "Memory Routing Foundations.md",
                "Memory Routing Foundations",
                "reference",
                "## 提炼\n\nMemory routing, retrieval planning, and memory schemas set the baseline.\n",
                created="2026-01-01",
            )
            write_note(
                topic / "Memory Routing Benchmarks.md",
                "Memory Routing Benchmarks",
                "reference",
                "Memory routing benchmarks compare retrieval planning and memory schemas.",
                created="2026-06-01",
            )
            write_note(
                topic / "Memory Routing Evaluations.md",
                "Memory Routing Evaluations",
                "reference",
                "Memory routing evaluations compare retrieval planning and memory schemas.",
                created="2026-06-02",
            )
            write_note(
                topic / "Memory Routing Patterns.md",
                "Memory Routing Patterns",
                "reference",
                "Memory routing patterns evolve retrieval planning and memory schemas.",
                created="2026-06-03",
            )
            write_note(
                topic / "Memory Routing Case Studies.md",
                "Memory Routing Case Studies",
                "reference",
                "Memory routing case studies evolve retrieval planning and memory schemas.",
                created="2026-06-04",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual("Resources/Agent Memory", report["synthesis_candidates"][0]["topic_dir"])
        restatement_paths = {item["path"] for item in report["restatement_candidates"]}
        self.assertIn("Resources/Agent Memory/Memory Routing Foundations.md", restatement_paths)

    def test_build_report_emits_project_restructuring_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_note(vault / "Projects" / "Example.md", "Example", "project", "# Example")
            write_note(
                vault / "Projects" / "Example" / "Design Baseline.md",
                "Design Baseline",
                "reference",
                "[[Example]]\n\nEvidence policy validation keeps decision records traceable.",
            )
            write_note(
                vault / "Projects" / "Example" / "Design Revision.md",
                "Design Revision",
                "reference",
                "[[Example]]\n[[Design Baseline]]\n\nThis revision refines evidence policy validation for decision records.",
            )
            write_note(
                vault / "Projects" / "Example" / "Validation Evidence.md",
                "Validation Evidence",
                "reference",
                "[[Example]]\n[[Design Revision]]\n\nEvidence policy validation verifies decision records before release.",
            )
            git_commit(vault, "initial knowledge", "2026-07-06T10:00:00")

            report = optimize_vault.build_report(vault, ["Projects"])

        self.assertEqual(1, len(report["restructuring_candidates"]))
        candidate = report["restructuring_candidates"][0]
        self.assertEqual("Projects/Example", candidate["scope"])
        self.assertEqual("Projects/Example.md", candidate["anchor_path"])
        self.assertEqual("refresh_anchor", candidate["action"])
        self.assertEqual("high", candidate["confidence"])
        self.assertEqual(
            [
                "Projects/Example/Design Baseline.md",
                "Projects/Example/Design Revision.md",
                "Projects/Example/Validation Evidence.md",
            ],
            candidate["member_paths"],
        )
        self.assertTrue(candidate["cluster_id"].startswith("kr-"))
        self.assertTrue(candidate["source_set_digest"].startswith("sha256:"))
        self.assertIn("refines", {item["kind"] for item in candidate["relations"]})

    def test_restructuring_reports_relation_ambiguity_without_semantic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_note(vault / "Projects" / "Example.md", "Example", "project", "# Example")
            write_note(
                vault / "Projects" / "Example" / "Capacity Plan.md",
                "Capacity Plan",
                "reference",
                "[[Example]]\n\nCapacity allocation depends on regional workloads.",
            )
            write_note(
                vault / "Projects" / "Example" / "Incident Review.md",
                "Incident Review",
                "reference",
                "[[Example]]\n\nIncident containment requires operator escalation.",
            )
            write_note(
                vault / "Projects" / "Example" / "Vendor Contract.md",
                "Vendor Contract",
                "reference",
                "[[Example]]\n\nVendor clauses govern renewal obligations.",
            )
            git_commit(vault, "unrelated project materials", "2026-07-06T10:00:00")

            report = optimize_vault.build_report(vault, ["Projects"])

        self.assertEqual(1, len(report["restructuring_candidates"]))
        candidate = report["restructuring_candidates"][0]
        self.assertEqual("report_only", candidate["action"])
        self.assertEqual("medium", candidate["confidence"])
        self.assertIn("relation_ambiguous", candidate["blockers"])

    def test_restructuring_reports_missing_member_source_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_note(vault / "Projects" / "Example.md", "Example", "project", "# Example")
            write_note(
                vault / "Projects" / "Example" / "Design Baseline.md",
                "Design Baseline",
                "reference",
                "[[Example]]\n\nEvidence policy validation keeps decision records traceable.",
            )
            write_note(
                vault / "Projects" / "Example" / "Design Revision.md",
                "Design Revision",
                "reference",
                "[[Example]]\n[[Design Baseline]]\n[[Missing Source]]\n\nThis revision refines evidence policy validation for decision records.",
            )
            write_note(
                vault / "Projects" / "Example" / "Validation Evidence.md",
                "Validation Evidence",
                "reference",
                "[[Example]]\n[[Design Revision]]\n\nEvidence policy validation verifies decision records before release.",
            )
            git_commit(vault, "missing source link", "2026-07-06T10:00:00")

            report = optimize_vault.build_report(vault, ["Projects"])

        self.assertEqual(1, len(report["restructuring_candidates"]))
        candidate = report["restructuring_candidates"][0]
        self.assertEqual("report_only", candidate["action"])
        self.assertIn("source_link_missing", candidate["blockers"])

    def test_restructuring_uses_area_anchor_and_reappears_after_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            anchor = vault / "Areas" / "Automation.md"
            write_note(anchor, "Automation", "area", "# Automation")
            note_paths = [
                vault / "Resources" / "Operations" / "Evidence Policy.md",
                vault / "Resources" / "Engineering" / "Validation Plan.md",
                vault / "Resources" / "Delivery" / "Decision Record.md",
            ]
            for path, title, body in (
                (note_paths[0], "Evidence Policy", "Evidence policy validation keeps decision records traceable."),
                (note_paths[1], "Validation Plan", "Evidence policy validation checks decision records before release."),
                (note_paths[2], "Decision Record", "Evidence policy validation governs decision records for automation."),
            ):
                write_note(path, title, "reference", f"[[Automation]]\n\n{body}")
            git_commit(vault, "area knowledge", "2026-07-06T10:00:00")

            initial_report = optimize_vault.build_report(vault, ["Areas", "Resources"])
            initial = initial_report["restructuring_candidates"][0]
            anchor.write_text(
                anchor.read_text(encoding="utf-8")
                + f"""

## 知识核心

<!-- BEGIN: knowledge-restructuring cluster={initial['cluster_id']} -->
- 覆盖材料：3 篇；来源集：{initial['source_set_digest']}；重构日期：2026-07-06
<!-- END: knowledge-restructuring -->
""",
                encoding="utf-8",
            )
            git_commit(vault, "restructure area knowledge", "2026-07-06T10:10:00")

            unchanged_report = optimize_vault.build_report(vault, ["Areas", "Resources"])
            changed_note = note_paths[2]
            changed_note.write_text(
                changed_note.read_text(encoding="utf-8") + "\nAdditional validation evidence changes the current understanding.\n",
                encoding="utf-8",
            )
            git_commit(vault, "new area evidence", "2026-07-06T10:20:00")
            changed_report = optimize_vault.build_report(vault, ["Areas", "Resources"])

        self.assertEqual("Areas/Automation", initial["scope"])
        self.assertEqual("Areas/Automation.md", initial["anchor_path"])
        self.assertEqual([], unchanged_report["restructuring_candidates"])
        self.assertEqual(1, len(changed_report["restructuring_candidates"]))
        refreshed = changed_report["restructuring_candidates"][0]
        self.assertEqual(initial["source_set_digest"], refreshed["last_restructured_digest"])
        self.assertNotEqual(initial["source_set_digest"], refreshed["source_set_digest"])

    def test_restructuring_reports_protected_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            anchor = vault / "Projects" / "Example.md"
            write_note(anchor, "Example", "project", "# Example")
            for filename, title in (
                ("Design Baseline.md", "Design Baseline"),
                ("Design Revision.md", "Design Revision"),
                ("Validation Evidence.md", "Validation Evidence"),
            ):
                write_note(
                    vault / "Projects" / "Example" / filename,
                    title,
                    "reference",
                    f"[[Example]]\n\nEvidence policy validation keeps decision records traceable for {title}.",
                )
            git_commit(vault, "initial project knowledge", "2026-07-06T10:00:00")
            anchor.write_text(anchor.read_text(encoding="utf-8") + "\nManual work in progress.\n", encoding="utf-8")

            report = optimize_vault.build_report(vault, ["Projects"])

        self.assertEqual(1, len(report["restructuring_candidates"]))
        candidate = report["restructuring_candidates"][0]
        self.assertEqual("report_only", candidate["action"])
        self.assertIn("anchor_protected", candidate["blockers"])

    def test_restructuring_report_markdown_and_log_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_note(vault / "Projects" / "Example.md", "Example", "project", "# Example")
            for filename, title in (
                ("Design Baseline.md", "Design Baseline"),
                ("Design Revision.md", "Design Revision"),
                ("Validation Evidence.md", "Validation Evidence"),
            ):
                write_note(
                    vault / "Projects" / "Example" / filename,
                    title,
                    "reference",
                    f"[[Example]]\n\nEvidence policy validation keeps decision records traceable for {title}.",
                )
            git_commit(vault, "report contract", "2026-07-06T10:00:00")

            report = optimize_vault.build_report(vault, ["Projects"])
            markdown = optimize_vault.markdown_report(report)
            optimize_vault.append_log(vault, report, "2026-07-06 11:09")
            log = (vault / ".claude" / "meditate.log").read_text(encoding="utf-8")

        self.assertEqual(report["restructuring_candidates"], report["report_only"]["restructuring_candidates"])
        self.assertIn("知识重构候选", markdown)
        self.assertIn(report["restructuring_candidates"][0]["cluster_id"], markdown)
        self.assertIn("- 知识重构：0", log)

    def test_append_log_reserves_semantic_fields_for_weekly_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_note(vault / "Resources" / "PKM" / "README.md", "PKM", "index", "# PKM")
            write_note(
                vault / "Resources" / "PKM" / "Hot Note.md",
                "Hot Note",
                "reference",
                "Retriever memory and grader loops.",
            )

            report = optimize_vault.build_report(vault, ["Resources"])
            optimize_vault.append_log(vault, report, "2026-07-06 11:09")

            text = (vault / ".claude" / "meditate.log").read_text(encoding="utf-8")

        self.assertIn("- 语义综合：0", text)
        self.assertIn("- 再巩固：0", text)

    def test_append_log_uses_auto_trigger_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_note(vault / "Resources" / "PKM" / "README.md", "PKM", "index", "# PKM")

            report = optimize_vault.build_report(vault, ["Resources"])
            with mock.patch.dict(os.environ, {"MEDITATE_LOG_TRIGGER": "auto"}):
                optimize_vault.append_log(vault, report, "2026-07-06 11:09")

            text = (vault / ".claude" / "meditate.log").read_text(encoding="utf-8")

        self.assertIn("## 2026-07-06 11:09 auto", text)

    def test_apply_safe_marks_stale_notes_and_reorders_resource_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "README.md").write_text(
                """---
title: "PKM"
type: index
---

# PKM

## 资料索引

<!-- BEGIN: resource-index -->

- [[Cold Note]]（2025-01-01）
- [[Hot Note]]（2026-07-01）

<!-- END: resource-index -->
""",
                encoding="utf-8",
            )
            write_note(topic / "Hot Note.md", "Hot Note", "reference", "Retriever memory and grader loops.", created="2026-07-01")
            write_note(topic / "Cold Note.md", "Cold Note", "reference", "Dormant reference body.", created="2025-01-01")
            git_commit(vault, "initial", "2025-05-01T12:00:00")

            today = dt.datetime.now().replace(second=0, microsecond=0)
            append_recall_entry(
                vault,
                today - dt.timedelta(days=2),
                "grader loops",
                [("Resources/PKM/Hot Note.md", "direct")],
                "answered",
            )
            append_recall_entry(
                vault,
                today - dt.timedelta(days=1),
                "memory routing",
                [("Resources/PKM/Hot Note.md", "concept")],
                "answered",
            )

            report = run_apply_safe(vault)
            cold_text = (topic / "Cold Note.md").read_text(encoding="utf-8")
            readme_text = (topic / "README.md").read_text(encoding="utf-8")

        self.assertIn("last_relevance_check:", cold_text)
        self.assertEqual("Resources/PKM/Cold Note.md", report["applied"]["staleness"][0]["path"])
        self.assertLess(readme_text.index("[[Hot Note]]"), readme_text.index("[[Cold Note]]（休眠）"))
