#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
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


def write_note(path: Path, title: str, note_type: str, body: str = "") -> None:
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
                "2026-07-01",
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


class LinkIntegrityAndUnderstandingTest(unittest.TestCase):
    def test_apply_safe_test_reports_are_isolated_per_temp_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Resources" / "PKM" / "Note.md", "Note", "reference")

            run_apply_safe(vault)

            self.assertTrue((vault / ".test-reports" / "meditate.json").exists())
            self.assertTrue((vault / ".test-reports" / "meditate.md").exists())

    def test_path_prefixed_wikilink_is_broken_even_when_same_stem_exists_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Resources" / "PKM" / "Foo.md", "Foo", "reference")
            write_note(vault / "Resources" / "PKM" / "Ref.md", "Ref", "reference", "See [[Inbox/Foo]].")

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(1, len(report["broken_links"]))
        finding = report["broken_links"][0]
        self.assertEqual("Resources/PKM/Ref.md", finding["source"])
        self.assertEqual("Inbox/Foo", finding["link"])
        self.assertEqual("unique", finding["status"])
        self.assertEqual(["Resources/PKM/Foo.md"], finding["matches"])

    def test_apply_empty_stubs_keeps_stub_when_causal_reference_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            write_note(vault / "Resources" / "PKM" / "Foo Actual.md", "Foo", "reference")
            write_note(vault / "Resources" / "PKM" / "Ref.md", "Ref", "reference", "See [[Foo]].")
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)
            (vault / "Resources" / "PKM" / "Ref.md").write_text(
                (vault / "Resources" / "PKM" / "Ref.md").read_text(encoding="utf-8") + "\nuser edit\n",
                encoding="utf-8",
            )
            (vault / "Foo.md").write_text("", encoding="utf-8")

            report = optimize_vault.build_report(vault, ["Resources"])
            optimize_vault.apply_empty_stubs(vault, report)

            self.assertTrue((vault / "Foo.md").exists())
            self.assertEqual([], report["applied"]["empty_stubs"])
            self.assertIn(
                {"type": "protected_stub_reference", "stub": "Foo.md", "source": "Resources/PKM/Ref.md"},
                report["skipped_uncertain"],
            )

    def test_empty_material_notes_are_not_exact_duplicates_by_empty_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            for filename, title in (("A.md", "A"), ("B.md", "B")):
                (vault / "Resources" / "PKM").mkdir(parents=True, exist_ok=True)
                (vault / "Resources" / "PKM" / filename).write_text(
                    f"""---
title: "{title}"
type: reference
---
""",
                    encoding="utf-8",
                )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual([], report["duplicates"])

    def test_apply_safe_reunderstands_explicit_ownership_mentions_and_adds_backlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Areas" / "AI Native 转型.md", "AI Native 转型", "area")
            write_note(vault / "Projects" / "Loop Engineering 落地实验.md", "Loop Engineering 落地实验", "project")
            write_note(
                vault / "Resources" / "PKM" / "Obsidian Course.md",
                "Obsidian Course",
                "reference",
                "This course supports AI Native 转型 and Loop Engineering 落地实验.",
            )

            report = optimize_vault.build_report(vault, ["Areas", "Projects", "Resources"])
            optimize_vault.apply_understanding_links(vault, report)

            source = (vault / "Resources" / "PKM" / "Obsidian Course.md").read_text(encoding="utf-8")
            area = (vault / "Areas" / "AI Native 转型.md").read_text(encoding="utf-8")
            project = (vault / "Projects" / "Loop Engineering 落地实验.md").read_text(encoding="utf-8")

        self.assertEqual(2, len(report["understanding"]["link_candidates"]))
        self.assertIn("[[AI Native 转型]]", source)
        self.assertIn("[[Loop Engineering 落地实验]]", source)
        self.assertIn("[[Obsidian Course]]", area)
        self.assertIn("[[Obsidian Course]]", project)
        self.assertEqual(2, len(report["applied"]["understanding_links"]))

    def test_reunderstanding_ignores_negative_ownership_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Projects" / "sample-project.md", "sample-project", "project")
            write_note(
                vault / "Archive" / "Patents" / "Legacy Patent.md",
                "Legacy Patent",
                "archive",
                "归档为历史技术资产，内容不直接关联当前 AI Native 转型、Loop Engineering 落地实验、sample-project 或 orbit。",
            )

            report = optimize_vault.build_report(vault, ["Projects", "Archive"])

        self.assertEqual([], report["understanding"]["link_candidates"])

    def test_apply_safe_reunderstands_topic_and_moves_note_with_source_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            (vault / "Resources" / "Agent Skills").mkdir(parents=True, exist_ok=True)
            (vault / "Resources" / "Agent Skills" / "README.md").write_text(
                """---
title: "Agent Skills"
type: index
aliases: [Claude Skills]
---

# Agent Skills
""",
                encoding="utf-8",
            )
            note_path = vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md"
            write_note(
                note_path,
                "Claude Skills Deep Dive",
                "reference",
                "Claude Skills should be understood as part of Agent Skills, not generic AI Agents.",
            )
            source_path = vault / "Resources" / "AI Agents" / "source" / "Claude Skills Deep Dive.pdf"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"%PDF test source")
            note_path.write_text(
                note_path.read_text(encoding="utf-8").replace(
                    "---\n\n# Claude Skills Deep Dive",
                    'source_file: "source/Claude Skills Deep Dive.pdf"\n---\n\n# Claude Skills Deep Dive',
                ),
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "PKM" / "Ref.md",
                "Ref",
                "reference",
                "See [[Resources/AI Agents/Claude Skills Deep Dive]].",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            self.assertEqual(1, len(scan["understanding"]["structure_candidates"]))

            applied = run_apply_safe(vault)

            old_note = vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md"
            new_note = vault / "Resources" / "Agent Skills" / "Claude Skills Deep Dive.md"
            old_source = vault / "Resources" / "AI Agents" / "source" / "Claude Skills Deep Dive.pdf"
            new_source = vault / "Resources" / "Agent Skills" / "source" / "Claude Skills Deep Dive.pdf"
            ref_text = (vault / "Resources" / "PKM" / "Ref.md").read_text(encoding="utf-8")
            old_note_exists = old_note.exists()
            new_note_exists = new_note.exists()
            old_source_exists = old_source.exists()
            new_source_exists = new_source.exists()

        self.assertFalse(old_note_exists)
        self.assertTrue(new_note_exists)
        self.assertFalse(old_source_exists)
        self.assertTrue(new_source_exists)
        self.assertIn("[[Claude Skills Deep Dive]]", ref_text)
        self.assertEqual([], applied["invalid_fingerprints"])
        self.assertIn(
            {
                "source": "Resources/AI Agents/Claude Skills Deep Dive.md",
                "target": "Resources/Agent Skills/Claude Skills Deep Dive.md",
                "kind": "topic_rehome",
                "matched": ["Agent Skills", "Claude Skills"],
                "source_moves": [
                    {
                        "old": "Resources/AI Agents/source/Claude Skills Deep Dive.pdf",
                        "new": "Resources/Agent Skills/source/Claude Skills Deep Dive.pdf",
                    }
                ],
            },
            applied["applied"]["structural_moves"],
        )

    def test_apply_safe_merges_equivalent_resource_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            write_note(vault / "Resources" / "AI Agents" / "README.md", "AI Agents", "index")
            write_note(vault / "Resources" / "AI Agents" / "Planner.md", "Planner", "reference", "Planner agent notes.")
            write_note(vault / "Resources" / "AI Agent" / "Runtime.md", "Runtime", "reference", "Runtime notes.")
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            self.assertEqual(1, len(scan["understanding"]["structure_candidates"]))

            applied = run_apply_safe(vault)
            old_note = vault / "Resources" / "AI Agent" / "Runtime.md"
            new_note = vault / "Resources" / "AI Agents" / "Runtime.md"
            old_note_exists = old_note.exists()
            new_note_exists = new_note.exists()

        self.assertFalse(old_note_exists)
        self.assertTrue(new_note_exists)
        self.assertIn(
            {
                "source": "Resources/AI Agent/Runtime.md",
                "target": "Resources/AI Agents/Runtime.md",
                "kind": "topic_merge",
                "matched": ["AI Agent", "AI Agents"],
                "source_moves": [],
            },
            applied["applied"]["structural_moves"],
        )

    def test_apply_safe_persists_topic_understanding_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            write_note(vault / "Resources" / "Agent Memory" / "README.md", "Agent Memory", "index")
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Recall.md",
                "Durable Recall",
                "reference",
                "Durable memory uses reflection loops and episodic recall for agent behavior.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Reflection Store.md",
                "Reflection Store",
                "reference",
                "Reflection loops preserve durable memory and episodic recall across sessions.",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = run_apply_safe(vault)
            readme = (vault / "Resources" / "Agent Memory" / "README.md").read_text(encoding="utf-8")

        self.assertIn("<!-- BEGIN: understanding-profile -->", readme)
        self.assertIn("## 概念画像", readme)
        self.assertIn("durable memory", readme)
        self.assertIn("reflection loop", readme)
        self.assertIn(
            {
                "topic_dir": "Resources/Agent Memory",
                "readme": "Resources/Agent Memory/README.md",
                "status": "updated",
            },
            report["applied"]["understanding_profiles"],
        )

    def test_apply_safe_rehomes_note_by_understanding_profile_overlap_without_topic_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            write_note(vault / "Resources" / "Agent Memory" / "README.md", "Agent Memory", "index")
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Recall.md",
                "Durable Recall",
                "reference",
                "Durable memory uses reflection loops and episodic recall for agent behavior.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Reflection Store.md",
                "Reflection Store",
                "reference",
                "Reflection loops preserve durable memory and episodic recall across sessions.",
            )
            write_note(vault / "Resources" / "PKM" / "README.md", "PKM", "index")
            write_note(
                vault / "Resources" / "PKM" / "Recall Pattern.md",
                "Recall Pattern",
                "reference",
                "This pattern uses durable memory, reflection loops, and episodic recall for long-running agents.",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            self.assertEqual(1, len(scan["understanding"]["structure_candidates"]))
            self.assertEqual("concept_rehome", scan["understanding"]["structure_candidates"][0]["kind"])

            applied = run_apply_safe(vault)
            old_note = vault / "Resources" / "PKM" / "Recall Pattern.md"
            new_note = vault / "Resources" / "Agent Memory" / "Recall Pattern.md"
            old_note_exists = old_note.exists()
            new_note_exists = new_note.exists()

        self.assertFalse(old_note_exists)
        self.assertTrue(new_note_exists)
        self.assertIn(
            {
                "source": "Resources/PKM/Recall Pattern.md",
                "target": "Resources/Agent Memory/Recall Pattern.md",
                "kind": "concept_rehome",
                "matched": ["durable memory", "episodic recall", "reflection loop"],
                "source_moves": [],
            },
            applied["applied"]["structural_moves"],
        )

    def test_concept_rehome_ignores_generic_cross_topic_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Resources" / "Agent Platforms" / "README.md", "Agent Platforms", "index")
            write_note(
                vault / "Resources" / "Agent Platforms" / "Claude Runtime.md",
                "Claude Runtime",
                "reference",
                "Claude Code runs every time rather than once inside the project folder.",
            )
            write_note(
                vault / "Resources" / "Agent Platforms" / "Runtime Folders.md",
                "Runtime Folders",
                "reference",
                "Claude Code checks every time rather than once inside the project folder.",
            )
            write_note(vault / "Resources" / "PKM" / "README.md", "PKM", "index")
            write_note(
                vault / "Resources" / "PKM" / "Vault Workflow.md",
                "Vault Workflow",
                "reference",
                "Claude Code writes every time rather than once inside the project folder.",
            )
            write_note(
                vault / "Resources" / "PKM" / "Daily Notes.md",
                "Daily Notes",
                "reference",
                "Claude Code updates every time rather than once inside the project folder.",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual([], report["understanding"]["structure_candidates"])

    def test_apply_safe_adds_ownership_links_by_concept_profile_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "AI Native 转型.md",
                "AI Native 转型",
                "area",
                "This area owns AI native adoption, team enablement, and loop engineering practice.",
            )
            write_note(
                vault / "Resources" / "AI Engineering" / "Adoption Playbook.md",
                "Adoption Playbook",
                "reference",
                "A playbook for AI native adoption, team enablement, and loop engineering practice.",
            )

            report = optimize_vault.build_report(vault, ["Areas", "Resources"])
            self.assertEqual(1, len(report["understanding"]["link_candidates"]))
            self.assertEqual("ownership_concept", report["understanding"]["link_candidates"][0]["kind"])

            optimize_vault.apply_understanding_links(vault, report)
            source = (vault / "Resources" / "AI Engineering" / "Adoption Playbook.md").read_text(encoding="utf-8")
            area = (vault / "Areas" / "AI Native 转型.md").read_text(encoding="utf-8")

        self.assertIn("[[AI Native 转型]]", source)
        self.assertIn("[[Adoption Playbook]]", area)
        self.assertEqual(1, len(report["applied"]["understanding_links"]))

    def test_ownership_concept_matching_ignores_generic_cross_owner_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "Claude Workflows.md",
                "Claude Workflows",
                "area",
                "Claude Code checks every time rather than once inside the project folder.",
            )
            write_note(
                vault / "Projects" / "PKM Migration.md",
                "PKM Migration",
                "project",
                "Claude Code writes every time rather than once inside the project folder.",
            )
            write_note(
                vault / "Resources" / "PKM" / "Vault Workflow.md",
                "Vault Workflow",
                "reference",
                "Claude Code updates every time rather than once inside the project folder.",
            )

            report = optimize_vault.build_report(vault, ["Areas", "Projects", "Resources"])

        self.assertEqual([], report["understanding"]["link_candidates"])

    def test_ownership_concept_matching_ignores_incidental_tooling_phrases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "PKM.md",
                "PKM",
                "area",
                """自动承接 `Resources/PKM`。

## 概念画像

<!-- BEGIN: understanding-profile -->

- 核心概念：second brain、project folder、obsidian vault、what changed
- 资料数量：3

<!-- END: understanding-profile -->
""",
            )
            write_note(
                vault / "Resources" / "Agent Platforms" / "Claude Mastery.md",
                "Claude Mastery",
                "reference",
                "Claude can work with a project folder or an Obsidian vault, then summarize what changed.",
            )

            report = optimize_vault.build_report(vault, ["Areas", "Resources"])

        self.assertEqual([], report["understanding"]["link_candidates"])

    def test_concept_profiles_ignore_generated_relationship_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Agent Platforms" / "Runtime.md",
                "Runtime",
                "reference",
                """Claude Code runtime uses slash commands and workspace skills.

## 关联

- [[Loop Engineering]]（重新理解：Loop Engineering）
""",
            )
            note = optimize_vault.read_note(
                vault,
                vault / "Resources" / "Agent Platforms" / "Runtime.md",
                set(),
            )

            counts = optimize_vault.note_concept_counts(note)

        self.assertIn("slash command", counts)
        self.assertNotIn("loop engineering", counts)

    def test_upsert_section_bullet_preserves_form_feed_source_text(self) -> None:
        text = "Page 1\n\fPage 2\n\n## 关联\n\n- [[Existing]]\n"

        updated = optimize_vault.upsert_section_bullet(text, "关联", "- [[AI Agents]]")

        self.assertIn("\fPage 2", updated)
        self.assertTrue(updated.startswith("Page 1\n\fPage 2\n"))
        self.assertIn("## 关联\n\n- [[Existing]]\n- [[AI Agents]]\n", updated)

    def test_apply_safe_creates_area_for_stable_unowned_resource_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Recall.md",
                "Durable Recall",
                "reference",
                "Durable memory uses reflection loops and episodic recall for agent behavior.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Reflection Store.md",
                "Reflection Store",
                "reference",
                "Reflection loops preserve durable memory and episodic recall across sessions.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Memory Evaluation.md",
                "Memory Evaluation",
                "reference",
                "Episodic recall and durable memory need reflection loops for evaluation.",
            )

            scan = optimize_vault.build_report(vault, ["Resources", "Areas"])
            self.assertEqual(1, len(scan["understanding"]["ownership_area_candidates"]))

            first_report = run_apply_safe(vault)
            area_path = vault / "Areas" / "Agent Memory.md"
            area_exists = area_path.exists()
            area_text = area_path.read_text(encoding="utf-8")
            durable_text = (vault / "Resources" / "Agent Memory" / "Durable Recall.md").read_text(encoding="utf-8")

            second_report = run_apply_safe(vault)
            second_area_text = area_path.read_text(encoding="utf-8")

        self.assertTrue(area_exists)
        self.assertIn('type: area', area_text)
        self.assertIn("# Agent Memory", area_text)
        self.assertIn("## 概念画像", area_text)
        self.assertIn("durable memory", area_text)
        self.assertIn("episodic recall", area_text)
        self.assertIn("reflection loop", area_text)
        self.assertIn("## 资料索引", area_text)
        self.assertIn("[[Durable Recall]]", area_text)
        self.assertIn("[[Reflection Store]]", area_text)
        self.assertIn("[[Memory Evaluation]]", area_text)
        self.assertIn("[[Agent Memory]]", durable_text)
        self.assertIn(
            {
                "topic_dir": "Resources/Agent Memory",
                "target": "Areas/Agent Memory.md",
                "material_count": 3,
                "concepts": ["durable memory", "episodic recall", "reflection loop"],
            },
            first_report["applied"]["ownership_areas"],
        )
        self.assertEqual([], second_report["applied"]["ownership_areas"])
        self.assertEqual(area_text, second_area_text)

    def test_apply_safe_refreshes_existing_auto_area_when_topic_grows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Recall.md",
                "Durable Recall",
                "reference",
                "Durable memory uses reflection loops and episodic recall for agent behavior.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Reflection Store.md",
                "Reflection Store",
                "reference",
                "Reflection loops preserve durable memory and episodic recall across sessions.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Memory Evaluation.md",
                "Memory Evaluation",
                "reference",
                "Episodic recall and durable memory need reflection loops for evaluation.",
            )
            first_report = run_apply_safe(vault)
            self.assertEqual(1, len(first_report["applied"]["ownership_areas"]))

            write_note(
                vault / "Resources" / "Agent Memory" / "Memory Consolidation.md",
                "Memory Consolidation",
                "reference",
                "Durable memory, reflection loops, and episodic recall support memory consolidation.",
            )

            scan = optimize_vault.build_report(vault, ["Resources", "Areas"])
            self.assertEqual(1, len(scan["understanding"]["ownership_area_profile_gaps"]))

            second_report = run_apply_safe(vault)
            area_text = (vault / "Areas" / "Agent Memory.md").read_text(encoding="utf-8")
            new_note_text = (vault / "Resources" / "Agent Memory" / "Memory Consolidation.md").read_text(
                encoding="utf-8"
            )

        self.assertIn(
            {
                "area": "Areas/Agent Memory.md",
                "topic_dir": "Resources/Agent Memory",
                "material_count": 4,
                "status": "updated",
                "reverse_updates": 1,
            },
            second_report["applied"]["ownership_area_profiles"],
        )
        self.assertIn("- 资料数量：4", area_text)
        self.assertIn("[[Memory Consolidation]]", area_text)
        self.assertIn("[[Agent Memory]]", new_note_text)

    def test_stable_resource_topic_does_not_create_area_when_existing_owner_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "AI Native 转型.md",
                "AI Native 转型",
                "area",
                "This area owns AI native adoption, team enablement, and loop engineering practice.",
            )
            for filename, title in (
                ("Adoption Playbook.md", "Adoption Playbook"),
                ("Team Enablement.md", "Team Enablement"),
                ("Loop Practice.md", "Loop Practice"),
            ):
                write_note(
                    vault / "Resources" / "AI Engineering" / filename,
                    title,
                    "reference",
                    "AI native adoption, team enablement, and loop engineering practice are the core operating model.",
                )

            report = run_apply_safe(vault)
            area_created = (vault / "Areas" / "AI Engineering.md").exists()
            note_text = (vault / "Resources" / "AI Engineering" / "Adoption Playbook.md").read_text(encoding="utf-8")

        self.assertFalse(area_created)
        self.assertEqual([], report["applied"]["ownership_areas"])
        self.assertIn("[[AI Native 转型]]", note_text)

    def test_stable_resource_topic_does_not_create_area_from_generic_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Claude Workflows" / "Runtime Folders.md",
                "Runtime Folders",
                "reference",
                "Claude Code checks every time rather than once inside the project folder.",
            )
            write_note(
                vault / "Resources" / "Claude Workflows" / "Command Setup.md",
                "Command Setup",
                "reference",
                "Claude Code runs every time rather than once inside the project folder.",
            )
            write_note(
                vault / "Resources" / "Claude Workflows" / "Session Setup.md",
                "Session Setup",
                "reference",
                "Claude Code writes every time rather than once inside the project folder.",
            )

            report = optimize_vault.build_report(vault, ["Resources", "Areas"])

        self.assertEqual([], report["understanding"]["ownership_area_candidates"])
        self.assertFalse((vault / "Areas" / "Claude Workflows.md").exists())

    def test_apply_safe_merges_equivalent_auto_created_areas_and_rewrites_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            write_note(
                vault / "Areas" / "AI Agents.md",
                "AI Agents",
                "area",
                "自动承接 `Resources/AI Agents`。\n\n## 资料索引\n\n- [[Planner]]（自动承接：`Resources/AI Agents`）\n",
            )
            write_note(
                vault / "Areas" / "AI Agent.md",
                "AI Agent",
                "area",
                "自动承接 `Resources/AI Agent`。\n\n## 资料索引\n\n- [[Runtime]]（自动承接：`Resources/AI Agent`）\n",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "Planner.md",
                "Planner",
                "reference",
                "Planner notes. See [[AI Agent]].",
            )
            subprocess.run(["git", "add", "Areas", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Areas", "Resources", "Archive"])
            self.assertEqual(1, len(scan["understanding"]["ownership_structure_candidates"]))

            report = run_apply_safe(vault)
            canonical_text = (vault / "Areas" / "AI Agents.md").read_text(encoding="utf-8")
            source_text = (vault / "Resources" / "AI Agents" / "Planner.md").read_text(encoding="utf-8")
            archived_text = (vault / "Archive" / "Duplicates" / "AI Agent.md").read_text(encoding="utf-8")
            rescan = optimize_vault.build_report(vault, ["Areas", "Resources", "Archive"])

        self.assertFalse((vault / "Areas" / "AI Agent.md").exists())
        self.assertIn("[[AI Agents]]", source_text)
        self.assertNotIn("[[AI Agent]]", source_text)
        self.assertIn("重复承接", archived_text)
        self.assertIn("[[AI Agents]]", archived_text)
        self.assertIn("[[AI Agent]]", canonical_text)
        self.assertIn(
            {
                "source": "Areas/AI Agent.md",
                "target": "Archive/Duplicates/AI Agent.md",
                "canonical": "Areas/AI Agents.md",
                "kind": "ownership_merge",
                "matched": ["ai agent"],
            },
            report["applied"]["ownership_structure"],
        )
        self.assertEqual([], rescan["understanding"]["ownership_structure_candidates"])

    def test_apply_safe_creates_child_area_for_stable_subcluster_inside_broad_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "AI Engineering.md",
                "AI Engineering",
                "area",
                "自动承接 `Resources/AI Engineering`。\n\n## 资料索引\n\n",
            )
            for filename, title, body in (
                (
                    "Interactive Judge Pipeline.md",
                    "Interactive Judge Pipeline",
                    "Interactive judge uses browser state, action planner, and reward signal evaluation.",
                ),
                (
                    "Interactive Judge Metrics.md",
                    "Interactive Judge Metrics",
                    "Interactive judge checks reward signal quality with browser state evidence.",
                ),
                (
                    "Interactive Judge Dataset.md",
                    "Interactive Judge Dataset",
                    "Interactive judge training data links browser state to reward signal feedback.",
                ),
                (
                    "Semantic Fabric.md",
                    "Semantic Fabric",
                    "Semantic fabric models business metrics and governed data contracts.",
                ),
                (
                    "Semantic Layer.md",
                    "Semantic Layer",
                    "Semantic layer documents governed metrics and business definitions.",
                ),
            ):
                write_note(vault / "Resources" / "AI Engineering" / filename, title, "reference", body)

            scan = optimize_vault.build_report(vault, ["Areas", "Resources"])
            self.assertEqual(1, len(scan["understanding"]["ownership_split_candidates"]))
            self.assertEqual("Areas/Interactive Judge.md", scan["understanding"]["ownership_split_candidates"][0]["target"])

            report = run_apply_safe(vault)
            child_text = (vault / "Areas" / "Interactive Judge.md").read_text(encoding="utf-8")
            parent_text = (vault / "Areas" / "AI Engineering.md").read_text(encoding="utf-8")
            source_text = (vault / "Resources" / "AI Engineering" / "Interactive Judge Pipeline.md").read_text(
                encoding="utf-8"
            )
            unrelated_text = (vault / "Resources" / "AI Engineering" / "Semantic Fabric.md").read_text(
                encoding="utf-8"
            )
            rescan = optimize_vault.build_report(vault, ["Areas", "Resources"])

        self.assertIn("[[AI Engineering]]", child_text)
        self.assertIn("[[Interactive Judge Pipeline]]", child_text)
        self.assertIn("[[Interactive Judge Metrics]]", child_text)
        self.assertIn("[[Interactive Judge Dataset]]", child_text)
        self.assertIn("[[Interactive Judge]]", parent_text)
        self.assertIn("[[Interactive Judge]]", source_text)
        self.assertNotIn("[[Interactive Judge]]", unrelated_text)
        self.assertIn(
            {
                "parent": "Areas/AI Engineering.md",
                "target": "Areas/Interactive Judge.md",
                "topic_dir": "Resources/AI Engineering",
                "concept": "interactive judge",
                "material_count": 3,
            },
            report["applied"]["ownership_splits"],
        )
        self.assertEqual([], rescan["understanding"]["ownership_split_candidates"])

    def test_ownership_split_does_not_create_child_when_concept_covers_entire_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "Agent Memory.md",
                "Agent Memory",
                "area",
                "自动承接 `Resources/Agent Memory`。",
            )
            for filename in ("Recall.md", "Reflection.md", "Consolidation.md"):
                write_note(
                    vault / "Resources" / "Agent Memory" / filename,
                    filename[:-3],
                    "reference",
                    "Durable memory uses reflection loops and episodic recall.",
                )

            report = optimize_vault.build_report(vault, ["Areas", "Resources"])

        self.assertEqual([], report["understanding"]["ownership_split_candidates"])


if __name__ == "__main__":
    unittest.main()
