#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
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


def write_reference(path: Path, title: str, created: str = "2026-07-01") -> None:
    path.write_text(
        f"""---
title: "{title}"
type: reference
created: {created}
---

# {title}

Reference body for {title}.
""",
        encoding="utf-8",
    )


class TopicIndexAndFingerprintsTest(unittest.TestCase):
    def test_reports_missing_topic_index_for_resource_topic_with_three_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            write_reference(topic / "Article A.md", "Article A")
            write_reference(topic / "Article B.md", "Article B")
            write_reference(topic / "Article C.md", "Article C")

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(1, len(report["topic_index_gaps"]))
        gap = report["topic_index_gaps"][0]
        self.assertEqual("Resources/PKM", gap["topic_dir"])
        self.assertEqual("Resources/PKM/README.md", gap["readme"])
        self.assertEqual("missing_readme", gap["status"])
        self.assertEqual(3, gap["reference_count"])

    def test_reports_stale_topic_index_marker_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "AI Engineering"
            topic.mkdir(parents=True)
            write_reference(topic / "Reward Signals.md", "Reward Signals", "2026-07-01")
            write_reference(topic / "Paper Review.md", "Paper Review", "2026-06-30")
            write_reference(topic / "AI Engineer.md", "AI Engineer", "2026-06-29")
            (topic / "README.md").write_text(
                """---
title: AI Engineering
type: index
---

# AI Engineering

## 资料索引

<!-- BEGIN: resource-index -->

- [[Old Item]]（2026-01-01）

<!-- END: resource-index -->
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(1, len(report["topic_index_gaps"]))
        gap = report["topic_index_gaps"][0]
        self.assertEqual("stale", gap["status"])
        self.assertEqual("Resources/AI Engineering/README.md", gap["readme"])
        self.assertIn("[[Reward Signals]]", gap["expected_index"])
        self.assertNotIn("[[Old Item]]", gap["expected_index"])

    def test_apply_safe_creates_missing_topic_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            write_reference(topic / "Article A.md", "Article A")
            write_reference(topic / "Article B.md", "Article B")
            write_reference(topic / "Article C.md", "Article C")

            report = optimize_vault.build_report(vault, ["Resources"])
            optimize_vault.apply_topic_indexes(vault, report)

            readme = (topic / "README.md").read_text(encoding="utf-8")

        self.assertIn('title: "PKM"', readme)
        self.assertIn("type: index", readme)
        self.assertIn("# PKM", readme)
        self.assertIn("## 主题定位", readme)
        self.assertIn("## 资料索引", readme)
        self.assertIn("<!-- BEGIN: resource-index -->", readme)
        self.assertIn("[[Article A]]", readme)
        self.assertEqual(
            [{"topic_dir": "Resources/PKM", "readme": "Resources/PKM/README.md", "status": "created"}],
            report["applied"]["topic_indexes"],
        )

    def test_topic_index_gap_skipped_once_when_apply_retries_protected_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            write_reference(topic / "Article A.md", "Article A")
            write_reference(topic / "Article B.md", "Article B")
            write_reference(topic / "Article C.md", "Article C")
            readme = topic / "README.md"
            readme.write_text(
                """---
title: PKM
type: index
---

# PKM
""",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)
            readme.write_text(readme.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")

            report = optimize_vault.build_report(vault, ["Resources"])
            optimize_vault.apply_topic_indexes(vault, report)
            optimize_vault.apply_topic_indexes(vault, report)

        skipped = [
            item
            for item in report["skipped_uncertain"]
            if item.get("type") == "topic_index_gap"
            and item.get("topic_dir") == "Resources/PKM"
        ]
        self.assertEqual(1, len(skipped))

    def test_apply_safe_updates_stale_marker_block_without_touching_manual_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "AI Engineering"
            topic.mkdir(parents=True)
            write_reference(topic / "Reward Signals.md", "Reward Signals", "2026-07-01")
            write_reference(topic / "Paper Review.md", "Paper Review", "2026-06-30")
            write_reference(topic / "AI Engineer.md", "AI Engineer", "2026-06-29")
            (topic / "README.md").write_text(
                """---
title: AI Engineering
type: index
---

# AI Engineering

Manual positioning stays here.

## 资料索引

<!-- BEGIN: resource-index -->

- [[Old Item]]（2026-01-01）

<!-- END: resource-index -->

Manual note after index stays here.
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])
            optimize_vault.apply_topic_indexes(vault, report)

            readme = (topic / "README.md").read_text(encoding="utf-8")

        self.assertIn("Manual positioning stays here.", readme)
        self.assertIn("Manual note after index stays here.", readme)
        self.assertIn("[[Reward Signals]]", readme)
        self.assertNotIn("[[Old Item]]", readme)
        self.assertEqual("updated", report["applied"]["topic_indexes"][0]["status"])

    def test_apply_safe_inserts_marker_block_when_readme_has_no_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "Agent Platforms"
            topic.mkdir(parents=True)
            write_reference(topic / "Platform A.md", "Platform A", "2026-07-01")
            write_reference(topic / "Platform B.md", "Platform B", "2026-06-30")
            write_reference(topic / "Platform C.md", "Platform C", "2026-06-29")
            (topic / "README.md").write_text(
                """---
title: Agent Platforms
type: index
---

# Agent Platforms

## 主题定位

Existing manual context.
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])
            optimize_vault.apply_topic_indexes(vault, report)

            readme = (topic / "README.md").read_text(encoding="utf-8")

        self.assertIn("Existing manual context.", readme)
        self.assertIn("## 资料索引", readme)
        self.assertIn("<!-- BEGIN: resource-index -->", readme)
        self.assertIn("[[Platform A]]", readme)
        self.assertEqual("inserted_markers", report["applied"]["topic_indexes"][0]["status"])

    def test_content_fingerprint_matches_unchanged_source_after_distillation_is_added(self) -> None:
        source_text = """# Durable Memory

The durable memory layer keeps reusable decisions outside one-off chats.
It works because markdown files can be searched, linked, and versioned.
"""
        fingerprint = optimize_vault.content_fingerprint(source_text)

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            note_path = topic / "Durable Memory.md"
            note_path.write_text(
                f"""---
title: Durable Memory
type: reference
content_fingerprint: "{fingerprint}"
---

# Durable Memory

## 提炼

- This summary was added during organization.
- See also [[AI Native 转型]].

## 原文 / 摘录

The durable memory layer keeps reusable decisions outside one-off chats.
It works because markdown files can be searched, linked, and versioned.

## 关联

- [[brain-vault]]
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])
            notes, _by_name, _file_stems, _attachment_targets = optimize_vault.build_index(vault, ["Resources"], set())

        self.assertEqual([], report["invalid_fingerprints"])
        self.assertEqual(1, len(notes))
        self.assertTrue(notes[0].fingerprint_valid)

    def test_legacy_content_fingerprint_mismatch_is_not_a_strict_invalid_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "Legacy Fingerprint.md").write_text(
                """---
title: Legacy Fingerprint
type: reference
content_fingerprint: "sha256:legacy-before-source-fingerprint-semantics"
---

# Legacy Fingerprint

## 提炼

- Curated summary changed after the legacy field was written.

## 原文 / 摘录

The original source text is still useful, but the legacy content fingerprint
is not strict enough to validate after distillation.
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])
            notes, _by_name, _file_stems, _attachment_targets = optimize_vault.build_index(vault, ["Resources"], set())

        self.assertEqual([], report["invalid_fingerprints"])
        self.assertTrue(notes[0].fingerprint_valid)

    def test_preferred_source_fingerprint_mismatch_is_reported_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "Strict Fingerprint.md").write_text(
                """---
title: Strict Fingerprint
type: reference
source_fingerprint: "sha256:wrong-source-fingerprint"
---

# Strict Fingerprint

Original source text.
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(1, len(report["invalid_fingerprints"]))
        self.assertEqual("source_fingerprint", report["invalid_fingerprints"][0]["field"])

    def test_topic_readme_index_is_not_reported_missing_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "README.md").write_text(
                """---
title: "PKM"
type: index
---

# PKM

## 资料索引
""",
                encoding="utf-8",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual([], report["metadata_missing"])


if __name__ == "__main__":
    unittest.main()
