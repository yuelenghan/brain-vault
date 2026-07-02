#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "optimize_vault.py"
SPEC = importlib.util.spec_from_file_location("optimize_vault_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
optimize_vault = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = optimize_vault
SPEC.loader.exec_module(optimize_vault)


class SourceFilePolicyTest(unittest.TestCase):
    def test_normalize_source_note_text_does_not_duplicate_existing_original_line(self) -> None:
        text = """---
title: Paper
---

> 整理自 Inbox，2026-07-01

# Paper

原始文件：[[Paper.pdf]]
"""

        result = optimize_vault.normalize_source_note_text(text, "source/Paper.pdf")

        self.assertEqual(1, result.count("原始文件：[[source/Paper.pdf]]"))
        self.assertNotIn("原始文件：[[Paper.pdf]]", result)
        self.assertIn("> 整理自 Inbox，2026-07-01\n原始文件：[[source/Paper.pdf]]", result)

    def test_normalize_source_note_text_preserves_english_original_file_label(self) -> None:
        text = """---
title: Paper
---

> Organized from Inbox, 2026-07-01. Original file: Paper.pdf.

# Paper

Original file: [[Paper.pdf]]
"""

        result = optimize_vault.normalize_source_note_text(text, "source/Paper.pdf")

        self.assertEqual(1, result.count("Original file: [[source/Paper.pdf]]"))
        self.assertNotIn("Original file: [[Paper.pdf]]", result)
        self.assertIn("> Organized from Inbox, 2026-07-01\nOriginal file: [[source/Paper.pdf]]", result)

    def test_normalize_source_note_text_preserves_form_feed_pages(self) -> None:
        text = """---
title: Paper
source_file: Paper.pdf
---

> 整理自 Inbox，2026-07-01。原始文件：Paper.pdf。

## 原文

page one\fpage two
"""

        result = optimize_vault.normalize_source_note_text(text, "source/Paper.pdf")

        self.assertIn("page one\fpage two", result)

    def test_existing_source_attachment_link_is_not_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "AI"
            source = topic / "source"
            source.mkdir(parents=True)
            (source / "Paper.pdf").write_bytes(b"%PDF demo\n")
            (topic / "Paper.md").write_text(
                """---
title: Paper
type: reference
source_file: source/Paper.pdf
---

> 整理自 Inbox，2026-07-01
原始文件：[[source/Paper.pdf]]

# Paper
""",
                encoding="utf-8",
            )

            notes, by_name, file_stems, attachment_targets = optimize_vault.build_index(vault, ["Resources"], set())
            findings = optimize_vault.broken_links(notes, by_name, file_stems, attachment_targets)

        self.assertEqual([], findings)

    def test_source_file_anomaly_reports_expected_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "Data Semantic Layer"
            old_source = topic / "Sources"
            old_source.mkdir(parents=True)
            (old_source / "NoETL Whitepaper.pdf").write_bytes(b"%PDF demo\n")
            (topic / "NoETL to Trusted AI 白皮书.md").write_text(
                """---
title: NoETL to Trusted AI 白皮书
type: reference
source_file: Sources/NoETL Whitepaper.pdf
---

> 整理自 Inbox，2026-07-01
原始文件：[[Sources/NoETL Whitepaper.pdf]]

# NoETL to Trusted AI 白皮书
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(1, len(report["source_file_anomalies"]))
        finding = report["source_file_anomalies"][0]
        self.assertEqual("Resources/Data Semantic Layer/Sources/NoETL Whitepaper.pdf", finding["actual"])
        self.assertEqual("Resources/Data Semantic Layer/source/NoETL to Trusted AI 白皮书.pdf", finding["expected"])
        self.assertEqual("fixable", finding["status"])

    def test_english_original_file_line_reports_source_file_anomaly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "Data Semantic Layer"
            old_source = topic / "Sources"
            old_source.mkdir(parents=True)
            (old_source / "Research Whitepaper.pdf").write_bytes(b"%PDF demo\n")
            (topic / "Trusted AI Research Whitepaper.md").write_text(
                """---
title: Trusted AI Research Whitepaper
type: reference
---

> Organized from Inbox, 2026-07-01
Original file: [[Sources/Research Whitepaper.pdf]]

# Trusted AI Research Whitepaper
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(1, len(report["source_file_anomalies"]))
        finding = report["source_file_anomalies"][0]
        self.assertEqual("Resources/Data Semantic Layer/Sources/Research Whitepaper.pdf", finding["actual"])
        self.assertEqual("Resources/Data Semantic Layer/source/Trusted AI Research Whitepaper.pdf", finding["expected"])
        self.assertEqual("fixable", finding["status"])

    def test_standalone_project_html_deliverable_is_not_source_file_anomaly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            project = vault / "Projects"
            project.mkdir(parents=True)
            (project / "AI-Agent-Second-Brain-Presentation.html").write_text(
                "<!doctype html><title>AI Agent Second Brain</title>",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Projects"])

        self.assertEqual([], report["source_file_anomalies"])


if __name__ == "__main__":
    unittest.main()
