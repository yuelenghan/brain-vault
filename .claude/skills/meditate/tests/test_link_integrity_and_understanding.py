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


def run_apply_safe(vault: Path, scopes: list[str] | None = None) -> dict:
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
        args = [
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
        for scope in scopes or []:
            args.extend(["--scope", scope])
        rc = optimize_vault.main(args)
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

    def test_reunderstanding_ignores_footer_only_ownership_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Areas" / "AI Agents.md", "AI Agents", "area", "Agent ownership.")
            write_note(
                vault / "Resources" / "Data Semantic Layer" / "RAG Units.md",
                "RAG Units",
                "reference",
                """RAG retrieval units need version state, source fields, and access-control metadata.

Find me on social media for more insights and tutorials on LLMs, AI Agents, and Machine Learning.
""",
            )

            report = optimize_vault.build_report(vault, ["Areas", "Resources"])

        self.assertEqual([], report["understanding"]["link_candidates"])

    def test_apply_safe_does_not_duplicate_existing_ownership_backlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "AI Native 转型.md",
                "AI Native 转型",
                "area",
                "## 资料索引\n\n- [[Obsidian Course]]：existing custom backlink.\n",
            )
            write_note(
                vault / "Resources" / "PKM" / "Obsidian Course.md",
                "Obsidian Course",
                "reference",
                "This course supports AI Native 转型.",
            )

            report = optimize_vault.build_report(vault, ["Areas", "Resources"])
            optimize_vault.apply_understanding_links(vault, report)

            source = (vault / "Resources" / "PKM" / "Obsidian Course.md").read_text(encoding="utf-8")
            area = (vault / "Areas" / "AI Native 转型.md").read_text(encoding="utf-8")

        self.assertIn("[[AI Native 转型]]", source)
        self.assertEqual(1, area.count("[[Obsidian Course]]"))
        self.assertEqual(1, len(report["applied"]["understanding_links"]))

    def test_reunderstanding_ignores_negative_ownership_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Projects" / "devops-playbook.md", "devops-playbook", "project")
            write_note(
                vault / "Archive" / "Patents" / "Legacy Patent.md",
                "Legacy Patent",
                "archive",
                "归档为历史技术资产，内容不直接关联当前 AI Native 转型、Loop Engineering 落地实验、devops-playbook 或 orbit。",
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

    def test_structural_rehome_skips_when_incoming_path_wikilink_is_protected(self) -> None:
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
            write_note(
                vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md",
                "Claude Skills Deep Dive",
                "reference",
                "Claude Skills belongs with Agent Skills, not generic AI Agents.",
            )
            ref_path = vault / "Resources" / "PKM" / "Ref.md"
            write_note(
                ref_path,
                "Ref",
                "reference",
                "See [[Resources/AI Agents/Claude Skills Deep Dive]].",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)
            ref_path.write_text(
                ref_path.read_text(encoding="utf-8") + "\nuser edit\n",
                encoding="utf-8",
            )

            scan = optimize_vault.build_report(vault, ["Resources"])
            candidates = scan["understanding"]["structure_candidates"]
            self.assertEqual(1, len(candidates))
            self.assertFalse(candidates[0]["fixable"])
            self.assertEqual("protected", candidates[0]["status"])
            self.assertIn("incoming path-qualified wikilinks", candidates[0]["reason"])

            applied = run_apply_safe(vault)
            old_note_exists = (vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md").exists()
            new_note_exists = (vault / "Resources" / "Agent Skills" / "Claude Skills Deep Dive.md").exists()

        self.assertTrue(old_note_exists)
        self.assertFalse(new_note_exists)
        self.assertEqual([], applied["applied"]["structural_moves"])

    def test_structural_rehome_skips_when_incoming_path_wikilink_is_outside_scope(self) -> None:
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
            write_note(
                vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md",
                "Claude Skills Deep Dive",
                "reference",
                "Claude Skills belongs with Agent Skills, not generic AI Agents.",
            )
            write_note(
                vault / "Areas" / "Agent Practice.md",
                "Agent Practice",
                "area",
                "Key material: [[Resources/AI Agents/Claude Skills Deep Dive]].",
            )
            subprocess.run(["git", "add", "Areas", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            candidates = scan["understanding"]["structure_candidates"]
            self.assertEqual(1, len(candidates))
            self.assertFalse(candidates[0]["fixable"])
            self.assertEqual("outside_scope", candidates[0]["status"])
            self.assertIn("outside the requested scope", candidates[0]["reason"])

            applied = run_apply_safe(vault, scopes=["Resources"])
            old_note_exists = (vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md").exists()
            new_note_exists = (vault / "Resources" / "Agent Skills" / "Claude Skills Deep Dive.md").exists()

        self.assertTrue(old_note_exists)
        self.assertFalse(new_note_exists)
        self.assertEqual([], applied["applied"]["structural_moves"])

    def test_structural_rehome_skips_when_incoming_path_wikilink_repair_would_be_ambiguous(self) -> None:
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
            write_note(
                vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md",
                "Claude Skills Deep Dive",
                "reference",
                "Claude Skills belongs with Agent Skills, not generic AI Agents.",
            )
            write_note(
                vault / "Archive" / "Reference" / "Claude Skills Deep Dive.md",
                "Claude Skills Deep Dive",
                "archive",
                "A different note with the same filename stem.",
            )
            write_note(
                vault / "Resources" / "PKM" / "Ref.md",
                "Ref",
                "reference",
                "See [[Resources/AI Agents/Claude Skills Deep Dive]].",
            )
            subprocess.run(["git", "add", "Archive", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            candidates = [
                item
                for item in scan["understanding"]["structure_candidates"]
                if item["source"] == "Resources/AI Agents/Claude Skills Deep Dive.md"
            ]
            self.assertEqual(1, len(candidates))
            self.assertFalse(candidates[0]["fixable"])
            self.assertEqual("ambiguous_incoming_link", candidates[0]["status"])
            self.assertIn("cannot be uniquely repaired", candidates[0]["reason"])

            applied = run_apply_safe(vault)
            old_note_exists = (vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md").exists()
            new_note_exists = (vault / "Resources" / "Agent Skills" / "Claude Skills Deep Dive.md").exists()

        self.assertTrue(old_note_exists)
        self.assertFalse(new_note_exists)
        self.assertEqual([], applied["applied"]["structural_moves"])

    def test_self_check_fails_when_structural_move_leaves_broken_wikilink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            write_note(vault / "Resources" / "Agent Skills" / "Foo.md", "Foo", "reference")
            write_note(
                vault / "Resources" / "PKM" / "Ref.md",
                "Ref",
                "reference",
                "Old path link: [[Resources/AI Agents/Foo]].",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)
            report = optimize_vault.build_report(vault, ["Resources"])
            report["applied"]["structural_moves"] = [
                {
                    "source": "Resources/AI Agents/Foo.md",
                    "target": "Resources/Agent Skills/Foo.md",
                    "kind": "topic_rehome",
                    "matched": ["Agent Skills"],
                    "source_moves": [],
                }
            ]

            optimize_vault.safe_self_check(vault, report)
            rendered = optimize_vault.markdown_report(report)

        self.assertEqual("未通过", report["verification"]["self_check"])
        self.assertEqual(1, len(report["verification"]["residual_broken_links"]))
        self.assertEqual("Resources/PKM/Ref.md", report["verification"]["residual_broken_links"][0]["source"])
        self.assertEqual("Resources/AI Agents/Foo", report["verification"]["residual_broken_links"][0]["link"])
        self.assertIn("残留结构断链", rendered)
        self.assertIn("`Resources/PKM/Ref.md` 中 `[[Resources/AI Agents/Foo]]`", rendered)

    def test_structural_reorganization_repairs_in_scope_path_wikilinks_during_move(self) -> None:
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
            write_note(
                vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md",
                "Claude Skills Deep Dive",
                "reference",
                "Claude Skills belongs with Agent Skills, not generic AI Agents.",
            )
            write_note(
                vault / "Resources" / "PKM" / "Ref.md",
                "Ref",
                "reference",
                "See [[Resources/AI Agents/Claude Skills Deep Dive]].",
            )
            write_note(
                vault / "Resources" / "PKM" / "Anchored Ref.md",
                "Anchored Ref",
                "reference",
                "See [[Resources/AI Agents/Claude Skills Deep Dive#Evidence|evidence]].",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = optimize_vault.build_report(vault, ["Resources"])
            candidates = [
                item
                for item in report["understanding"]["structure_candidates"]
                if item["source"] == "Resources/AI Agents/Claude Skills Deep Dive.md"
            ]
            self.assertEqual(1, len(candidates))
            self.assertTrue(candidates[0]["fixable"])

            optimize_vault.apply_structural_reorganization(vault, report)
            ref_text = (vault / "Resources" / "PKM" / "Ref.md").read_text(encoding="utf-8")
            anchored_text = (vault / "Resources" / "PKM" / "Anchored Ref.md").read_text(encoding="utf-8")
            old_exists = (vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md").exists()
            new_exists = (vault / "Resources" / "Agent Skills" / "Claude Skills Deep Dive.md").exists()

        self.assertFalse(old_exists)
        self.assertTrue(new_exists)
        self.assertIn("[[Claude Skills Deep Dive]]", ref_text)
        self.assertNotIn("Resources/AI Agents/Claude Skills Deep Dive", ref_text)
        self.assertIn("[[Claude Skills Deep Dive#Evidence|evidence]]", anchored_text)
        self.assertNotIn("Resources/AI Agents/Claude Skills Deep Dive", anchored_text)
        self.assertEqual(
            [
                {
                    "source": "Resources/PKM/Anchored Ref.md",
                    "old": "Resources/AI Agents/Claude Skills Deep Dive#Evidence|evidence",
                    "new": "Claude Skills Deep Dive",
                },
                {
                    "source": "Resources/PKM/Ref.md",
                    "old": "Resources/AI Agents/Claude Skills Deep Dive",
                    "new": "Claude Skills Deep Dive",
                },
            ],
            report["applied"]["broken_links"],
        )

    def test_structural_reorganization_keeps_skipped_findings_unique_across_retries(self) -> None:
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
            write_note(
                vault / "Resources" / "AI Agents" / "Claude Skills Deep Dive.md",
                "Claude Skills Deep Dive",
                "reference",
                "Claude Skills belongs with Agent Skills, not generic AI Agents.",
            )
            write_note(
                vault / "Areas" / "Agent Practice.md",
                "Agent Practice",
                "area",
                "Key material: [[Resources/AI Agents/Claude Skills Deep Dive]].",
            )
            subprocess.run(["git", "add", "Areas", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = optimize_vault.build_report(vault, ["Resources"])
            optimize_vault.apply_structural_reorganization(vault, report)
            optimize_vault.apply_structural_reorganization(vault, report)

        skipped = [
            item
            for item in report["skipped_uncertain"]
            if item.get("type") == "structural_reunderstanding"
            and item.get("source") == "Resources/AI Agents/Claude Skills Deep Dive.md"
        ]
        self.assertEqual(1, len(skipped))

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

    def test_concept_rehome_ignores_generic_ml_phrases_that_only_match_broad_topic_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Resources" / "AI Agents" / "README.md", "AI Agents", "index")
            write_note(
                vault / "Resources" / "AI Agents" / "Planner Report.md",
                "Planner Report",
                "reference",
                "This technical report studies hidden state control in an agentic workflow.",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "Verifier Report.md",
                "Verifier Report",
                "reference",
                "Another technical report on hidden state evaluation inside an agentic workflow.",
            )
            write_note(vault / "Resources" / "LLM Inference" / "README.md", "LLM Inference", "index")
            write_note(
                vault / "Resources" / "LLM Inference" / "DSpark 半自回归投机解码.md",
                "DSpark 半自回归投机解码",
                "reference",
                "Speculative decoding uses a hidden state schedule in this technical report about agentic workflow orchestration.",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual([], report["understanding"]["structure_candidates"])

    def test_apply_safe_splits_stable_subcluster_into_resource_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
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
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            topic_split_candidates = [
                item
                for item in scan["understanding"]["structure_candidates"]
                if item["kind"] == "topic_split"
            ]
            self.assertEqual(3, len(topic_split_candidates))
            self.assertEqual(
                [
                    "Resources/Interactive Judge/Interactive Judge Dataset.md",
                    "Resources/Interactive Judge/Interactive Judge Metrics.md",
                    "Resources/Interactive Judge/Interactive Judge Pipeline.md",
                ],
                sorted(item["target"] for item in topic_split_candidates),
            )
            split_decisions = scan["understanding"]["resource_topic_split_decisions"]
            self.assertEqual(1, len(split_decisions))
            self.assertEqual("Resources/AI Engineering", split_decisions[0]["topic_dir"])
            self.assertEqual("split_candidate", split_decisions[0]["status"])
            self.assertEqual("Interactive Judge", split_decisions[0]["to_topic"])
            self.assertEqual(3, split_decisions[0]["material_count"])

            applied = run_apply_safe(vault)
            rescan = optimize_vault.build_report(vault, ["Resources"])
            old_interactive_exists = (
                vault / "Resources" / "AI Engineering" / "Interactive Judge Pipeline.md"
            ).exists()
            new_interactive_exists = (
                vault / "Resources" / "Interactive Judge" / "Interactive Judge Pipeline.md"
            ).exists()
            semantic_fabric_exists = (vault / "Resources" / "AI Engineering" / "Semantic Fabric.md").exists()

        self.assertFalse(old_interactive_exists)
        self.assertTrue(new_interactive_exists)
        self.assertTrue(semantic_fabric_exists)
        self.assertEqual(
            3,
            len([item for item in applied["applied"]["structural_moves"] if item["kind"] == "topic_split"]),
        )
        self.assertEqual(
            [],
            [item for item in rescan["understanding"]["structure_candidates"] if item["kind"] == "topic_split"],
        )

    def test_apply_safe_splits_title_contained_subcluster_into_resource_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            for filename, title, body in (
                (
                    "Building Durable Memory for Agents.md",
                    "Building Durable Memory for Agents",
                    "Durable memory uses episodic recall and reflection loops for agent behavior.",
                ),
                (
                    "Testing Durable Memory in Agents.md",
                    "Testing Durable Memory in Agents",
                    "Durable memory quality depends on episodic recall and reflection loops.",
                ),
                (
                    "Evaluating Durable Memory Loops.md",
                    "Evaluating Durable Memory Loops",
                    "Durable memory evaluation checks episodic recall and reflection loops.",
                ),
                (
                    "Planner Runtime.md",
                    "Planner Runtime",
                    "Planner runtime coordinates tool calls and task state.",
                ),
                (
                    "Tool Harness.md",
                    "Tool Harness",
                    "Tool harness validates action results and command output.",
                ),
            ):
                write_note(vault / "Resources" / "AI Agents" / filename, title, "reference", body)
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            topic_split_candidates = [
                item
                for item in scan["understanding"]["structure_candidates"]
                if item["kind"] == "topic_split"
            ]

            applied = run_apply_safe(vault)
            old_memory_note_exists = (
                vault / "Resources" / "AI Agents" / "Building Durable Memory for Agents.md"
            ).exists()
            new_memory_note_exists = (
                vault / "Resources" / "Durable Memory" / "Building Durable Memory for Agents.md"
            ).exists()
            planner_note_exists = (vault / "Resources" / "AI Agents" / "Planner Runtime.md").exists()

        self.assertEqual(3, len(topic_split_candidates))
        self.assertEqual(
            [
                "Resources/Durable Memory/Building Durable Memory for Agents.md",
                "Resources/Durable Memory/Evaluating Durable Memory Loops.md",
                "Resources/Durable Memory/Testing Durable Memory in Agents.md",
            ],
            sorted(item["target"] for item in topic_split_candidates),
        )
        self.assertFalse(old_memory_note_exists)
        self.assertTrue(new_memory_note_exists)
        self.assertTrue(planner_note_exists)
        self.assertEqual(
            3,
            len([item for item in applied["applied"]["structural_moves"] if item["kind"] == "topic_split"]),
        )

    def test_apply_safe_renames_broad_topic_when_all_materials_share_title_leading_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            for filename, title, body in (
                (
                    "Interactive Judge Pipeline.md",
                    "Interactive Judge Pipeline",
                    "Interactive judge uses browser state and reward signal evaluation.",
                ),
                (
                    "Interactive Judge Metrics.md",
                    "Interactive Judge Metrics",
                    "Interactive judge measures reward signal and action planner quality.",
                ),
                (
                    "Interactive Judge Dataset.md",
                    "Interactive Judge Dataset",
                    "Interactive judge training data captures browser state feedback.",
                ),
                (
                    "Interactive Judge Review.md",
                    "Interactive Judge Review",
                    "Interactive judge review traces compare action planner outputs.",
                ),
                (
                    "Interactive Judge Replay.md",
                    "Interactive Judge Replay",
                    "Interactive judge replay validates browser state transitions.",
                ),
            ):
                write_note(vault / "Resources" / "AI Engineering" / filename, title, "reference", body)
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            scan = optimize_vault.build_report(vault, ["Resources"])
            rename_candidates = [
                item
                for item in scan["understanding"]["structure_candidates"]
                if item["kind"] == "topic_rename"
            ]
            self.assertEqual(5, len(rename_candidates))
            self.assertEqual(
                ["whole_topic_rename"],
                [item["status"] for item in scan["understanding"]["resource_topic_split_decisions"]],
            )

            applied = run_apply_safe(vault)
            old_exists = (vault / "Resources" / "AI Engineering" / "Interactive Judge Pipeline.md").exists()
            new_exists = (vault / "Resources" / "Interactive Judge" / "Interactive Judge Pipeline.md").exists()

        self.assertFalse(old_exists)
        self.assertTrue(new_exists)
        self.assertEqual(
            5,
            len([item for item in applied["applied"]["structural_moves"] if item["kind"] == "topic_rename"]),
        )

    def test_report_learns_resource_topic_relations_from_shared_distinctive_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            for topic, filenames in {
                "Agent Memory": [
                    "Episodic Recall.md",
                    "Reflection Loop.md",
                    "Retrieval Practice.md",
                ],
                "Learning Systems": [
                    "Learning Recall.md",
                    "Learning Reflection.md",
                    "Learning Retrieval.md",
                ],
            }.items():
                for filename in filenames:
                    write_note(
                        vault / "Resources" / topic / filename,
                        Path(filename).stem,
                        "reference",
                        "episodic recall, reflection loop, and retrieval practice form a durable learning cycle.",
                    )
            write_note(
                vault / "Resources" / "Prompt Engineering" / "Prompt Patterns.md",
                "Prompt Patterns",
                "reference",
                "prompt pattern and instruction design are unrelated to memory learning.",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        candidates = report["understanding"]["topic_relation_candidates"]
        self.assertEqual(1, len(candidates))
        self.assertEqual("Agent Memory", candidates[0]["source_topic"])
        self.assertEqual("Learning Systems", candidates[0]["target_topic"])
        for concept in ("episodic recall", "reflection loop", "retrieval practice"):
            self.assertIn(concept, candidates[0]["concepts"])

    def test_apply_safe_writes_reciprocal_topic_relation_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            for topic, filenames in {
                "Agent Memory": [
                    "Episodic Recall.md",
                    "Reflection Loop.md",
                    "Retrieval Practice.md",
                ],
                "Learning Systems": [
                    "Learning Recall.md",
                    "Learning Reflection.md",
                    "Learning Retrieval.md",
                ],
            }.items():
                for filename in filenames:
                    write_note(
                        vault / "Resources" / topic / filename,
                        Path(filename).stem,
                        "reference",
                        "episodic recall, reflection loop, and retrieval practice form a durable learning cycle.",
                    )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = run_apply_safe(vault)
            agent_memory = (vault / "Resources" / "Agent Memory" / "README.md").read_text(encoding="utf-8")
            learning_systems = (vault / "Resources" / "Learning Systems" / "README.md").read_text(encoding="utf-8")

        self.assertIn("<!-- BEGIN: topic-relations -->", agent_memory)
        self.assertIn("<!-- END: topic-relations -->", agent_memory)
        self.assertIn("[[Resources/Learning Systems/README|Learning Systems]]", agent_memory)
        self.assertIn("episodic recall", agent_memory)
        self.assertIn("[[Resources/Agent Memory/README|Agent Memory]]", learning_systems)
        self.assertIn(
            {
                "topic_dir": "Resources/Agent Memory",
                "readme": "Resources/Agent Memory/README.md",
                "relation_count": 1,
            },
            report["applied"]["topic_relations"],
        )
        self.assertIn(
            {
                "topic_dir": "Resources/Learning Systems",
                "readme": "Resources/Learning Systems/README.md",
                "relation_count": 1,
            },
            report["applied"]["topic_relations"],
        )

    def test_apply_safe_propagates_topic_relations_to_owned_areas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            for topic, filenames in {
                "Agent Memory": [
                    "Episodic Recall.md",
                    "Reflection Loop.md",
                    "Retrieval Practice.md",
                ],
                "Learning Systems": [
                    "Learning Recall.md",
                    "Learning Reflection.md",
                    "Learning Retrieval.md",
                ],
            }.items():
                for filename in filenames:
                    write_note(
                        vault / "Resources" / topic / filename,
                        Path(filename).stem,
                        "reference",
                        "episodic recall, reflection loop, and retrieval practice form a durable learning cycle.",
                    )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = run_apply_safe(vault)
            agent_memory_area = (vault / "Areas" / "Agent Memory.md").read_text(encoding="utf-8")
            learning_systems_area = (vault / "Areas" / "Learning Systems.md").read_text(encoding="utf-8")

        self.assertIn("## 相关承接", agent_memory_area)
        self.assertIn("<!-- BEGIN: ownership-relations -->", agent_memory_area)
        self.assertIn("<!-- END: ownership-relations -->", agent_memory_area)
        self.assertIn("[[Learning Systems]]", agent_memory_area)
        self.assertIn("episodic recall", agent_memory_area)
        self.assertIn("## 相关承接", learning_systems_area)
        self.assertIn("<!-- BEGIN: ownership-relations -->", learning_systems_area)
        self.assertIn("<!-- END: ownership-relations -->", learning_systems_area)
        self.assertIn("[[Agent Memory]]", learning_systems_area)
        self.assertIn(
            {
                "area": "Areas/Agent Memory.md",
                "relation_count": 1,
            },
            report["applied"]["ownership_relations"],
        )
        self.assertIn(
            {
                "area": "Areas/Learning Systems.md",
                "relation_count": 1,
            },
            report["applied"]["ownership_relations"],
        )

    def test_apply_safe_refreshes_stale_ownership_relation_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            for area, topic, related in (
                ("Agent Memory", "Agent Memory", "Learning Systems"),
                ("Learning Systems", "Learning Systems", "Agent Memory"),
            ):
                write_note(
                    vault / "Areas" / f"{area}.md",
                    area,
                    "area",
                    f"""自动承接 `Resources/{topic}`。

## 适用范围

- 主题来源：`Resources/{topic}`

## 相关承接

<!-- BEGIN: ownership-relations -->

- [[{related}]]（共享 Resource 概念：episodic recall、reflection loop、retrieval practice；来源：`Resources/{topic}` ↔ `Resources/{related}`）

<!-- END: ownership-relations -->
""",
                )
            write_note(
                vault / "Resources" / "Agent Memory" / "Cache Notes.md",
                "Cache Notes",
                "reference",
                "cache invalidation and summarization policy",
            )
            write_note(
                vault / "Resources" / "Learning Systems" / "Curriculum Design.md",
                "Curriculum Design",
                "reference",
                "curriculum design and assessment rubric",
            )
            subprocess.run(["git", "add", "Areas", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = run_apply_safe(vault)
            agent_memory_area = (vault / "Areas" / "Agent Memory.md").read_text(encoding="utf-8")
            learning_systems_area = (vault / "Areas" / "Learning Systems.md").read_text(encoding="utf-8")

        self.assertIn("暂无稳定相关承接", agent_memory_area)
        self.assertIn("暂无稳定相关承接", learning_systems_area)
        self.assertNotIn("[[Learning Systems]]", agent_memory_area)
        self.assertNotIn("[[Agent Memory]]", learning_systems_area)
        self.assertIn(
            {"area": "Areas/Agent Memory.md", "relation_count": 0},
            report["applied"]["ownership_relations"],
        )
        self.assertIn(
            {"area": "Areas/Learning Systems.md", "relation_count": 0},
            report["applied"]["ownership_relations"],
        )

    def test_apply_safe_refreshes_stale_topic_relation_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            for topic, related in (
                ("Agent Memory", "Learning Systems"),
                ("Learning Systems", "Agent Memory"),
            ):
                readme = vault / "Resources" / topic / "README.md"
                readme.parent.mkdir(parents=True, exist_ok=True)
                relation_link = f"[[Resources/{related}/README|{related}]]"
                readme.write_text(
                    f"""---
title: "{topic}"
type: index
---

# {topic}

## 相关主题

<!-- BEGIN: topic-relations -->

- {relation_link}（共享概念：episodic recall、reflection loop、retrieval practice）

<!-- END: topic-relations -->
""",
                        encoding="utf-8",
                    )
            write_note(
                vault / "Resources" / "Agent Memory" / "Cache Notes.md",
                "Cache Notes",
                "reference",
                "cache invalidation and summarization policy",
            )
            write_note(
                vault / "Resources" / "Learning Systems" / "Curriculum Design.md",
                "Curriculum Design",
                "reference",
                "curriculum design and assessment rubric",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = run_apply_safe(vault)
            agent_memory = (vault / "Resources" / "Agent Memory" / "README.md").read_text(encoding="utf-8")
            learning_systems = (vault / "Resources" / "Learning Systems" / "README.md").read_text(encoding="utf-8")

        self.assertIn("暂无稳定相关主题", agent_memory)
        self.assertIn("暂无稳定相关主题", learning_systems)
        self.assertNotIn("[[Resources/Learning Systems/README|Learning Systems]]", agent_memory)
        self.assertNotIn("[[Resources/Agent Memory/README|Agent Memory]]", learning_systems)
        self.assertIn(
            {
                "topic_dir": "Resources/Agent Memory",
                "readme": "Resources/Agent Memory/README.md",
                "relation_count": 0,
            },
            report["applied"]["topic_relations"],
        )
        self.assertIn(
            {
                "topic_dir": "Resources/Learning Systems",
                "readme": "Resources/Learning Systems/README.md",
                "relation_count": 0,
            },
            report["applied"]["topic_relations"],
        )

    def test_resource_topic_split_requires_title_leading_subtopic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            for filename, title, body in (
                (
                    "Loop Engineering Clearly Explained.md",
                    "Loop Engineering Clearly Explained",
                    "Loop engineering differs from prompt engineering through iterative feedback.",
                ),
                (
                    "Loop Engineering Replacing Prompt Engineering.md",
                    "Loop Engineering Replacing Prompt Engineering",
                    "Loop engineering replaces prompt engineering with closed-loop evaluation.",
                ),
                (
                    "Loop Engineering Ate Prompt Engineering.md",
                    "Loop Engineering Ate Prompt Engineering",
                    "Loop engineering expands prompt engineering into system-level loops.",
                ),
                (
                    "Loop Search.md",
                    "Loop Search",
                    "Loop search explores candidate outputs and review traces.",
                ),
                (
                    "Output Review.md",
                    "Output Review",
                    "Output review checks candidate answers against success criteria.",
                ),
            ):
                write_note(vault / "Resources" / "Loop Engineering" / filename, title, "reference", body)

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(
            [],
            [item for item in report["understanding"]["structure_candidates"] if item["kind"] == "topic_split"],
        )
        split_decisions = report["understanding"]["resource_topic_split_decisions"]
        self.assertEqual(1, len(split_decisions))
        self.assertEqual("Resources/Loop Engineering", split_decisions[0]["topic_dir"])
        self.assertEqual("no_title_leading_subcluster", split_decisions[0]["status"])
        self.assertIn("title-leading", split_decisions[0]["reason"])

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

    def test_report_adds_same_topic_peer_links_by_distinctive_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Memory Architecture.md",
                "Durable Memory Architecture",
                "reference",
                "Durable memory stores episodic recall, reflection loop notes, and retrieval practice evidence.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Memory Evaluation.md",
                "Durable Memory Evaluation",
                "reference",
                "Durable memory evaluation checks episodic recall, reflection loop quality, and retrieval practice.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Planner Runtime.md",
                "Planner Runtime",
                "reference",
                "Planner runtime coordinates tool calls and task state.",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        peer_candidates = [
            item
            for item in report["understanding"]["link_candidates"]
            if item["kind"] == "same_topic_concept"
        ]
        self.assertEqual(2, len(peer_candidates))
        self.assertEqual(
            {
                (
                    "Resources/Agent Memory/Durable Memory Architecture.md",
                    "Resources/Agent Memory/Durable Memory Evaluation.md",
                ),
                (
                    "Resources/Agent Memory/Durable Memory Evaluation.md",
                    "Resources/Agent Memory/Durable Memory Architecture.md",
                ),
            },
            {(item["source"], item["target"]) for item in peer_candidates},
        )
        for item in peer_candidates:
            self.assertIn("durable memory", item["matched"])
            self.assertIn("episodic recall", item["matched"])
            self.assertIn("reflection loop", item["matched"])

    def test_apply_safe_adds_reciprocal_same_topic_peer_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Memory Architecture.md",
                "Durable Memory Architecture",
                "reference",
                "Durable memory stores episodic recall, reflection loop notes, and retrieval practice evidence.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Durable Memory Evaluation.md",
                "Durable Memory Evaluation",
                "reference",
                "Durable memory evaluation checks episodic recall, reflection loop quality, and retrieval practice.",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Planner Runtime.md",
                "Planner Runtime",
                "reference",
                "Planner runtime coordinates tool calls and task state.",
            )
            subprocess.run(["git", "add", "Resources"], cwd=vault, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)

            report = run_apply_safe(vault)
            architecture = (
                vault / "Resources" / "Agent Memory" / "Durable Memory Architecture.md"
            ).read_text(encoding="utf-8")
            evaluation = (
                vault / "Resources" / "Agent Memory" / "Durable Memory Evaluation.md"
            ).read_text(encoding="utf-8")
            planner = (vault / "Resources" / "Agent Memory" / "Planner Runtime.md").read_text(encoding="utf-8")

        self.assertIn("[[Durable Memory Evaluation]]", architecture)
        self.assertIn("[[Durable Memory Architecture]]", evaluation)
        self.assertNotIn("[[Durable Memory Architecture]]", planner)
        self.assertEqual(
            2,
            len([item for item in report["applied"]["understanding_links"] if item["kind"] == "same_topic_concept"]),
        )

    def test_same_topic_peer_links_require_shared_title_concept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "AI Engineering" / "Review Workflow.md",
                "Review Workflow",
                "reference",
                "The coding task checks output against each requirement and cannot scale without automated review.",
            )
            write_note(
                vault / "Resources" / "AI Engineering" / "Reward Signal.md",
                "Reward Signal",
                "reference",
                "The coding task checks output against each result and cannot scale without automated review.",
            )
            write_note(
                vault / "Resources" / "AI Engineering" / "Dataset Curation.md",
                "Dataset Curation",
                "reference",
                "Dataset curation tracks labels and benchmark drift.",
            )

            report = optimize_vault.build_report(vault, ["Resources"])

        self.assertEqual(
            [],
            [
                item
                for item in report["understanding"]["link_candidates"]
                if item["kind"] == "same_topic_concept"
            ],
        )

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

    def test_apply_safe_refreshes_generated_area_scope_concept_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "Agent Memory.md",
                "Agent Memory",
                "area",
                """自动承接 `Resources/Agent Memory`。

## 适用范围

- 主题来源：`Resources/Agent Memory`
- 核心概念：old memory、what they、file when

## 概念画像

<!-- BEGIN: understanding-profile -->

- 核心概念：old memory、what they、file when
- 资料数量：1

<!-- END: understanding-profile -->

## 资料索引

<!-- BEGIN: ownership-index -->

- [[Old Memory]]（自动承接：`Resources/Agent Memory`）

<!-- END: ownership-index -->
""",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Current Memory.md",
                "Current Memory",
                "reference",
                "Current memory uses episodic recall, reflection loop, and retrieval practice.",
            )

            report = run_apply_safe(vault)
            area_text = (vault / "Areas" / "Agent Memory.md").read_text(encoding="utf-8")
            rescan = optimize_vault.build_report(vault, ["Resources", "Areas"])

        self.assertIn("- 核心概念：episodic recall、reflection loop、retrieval practice", area_text)
        self.assertNotIn("old memory", area_text)
        self.assertNotIn("what they", area_text)
        self.assertNotIn("file when", area_text)
        self.assertEqual([], rescan["understanding"]["ownership_area_profile_gaps"])
        self.assertIn(
            {
                "area": "Areas/Agent Memory.md",
                "topic_dir": "Resources/Agent Memory",
                "material_count": 1,
                "status": "updated",
                "reverse_updates": 1,
            },
            report["applied"]["ownership_area_profiles"],
        )

    def test_apply_safe_refreshes_stale_auto_area_material_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "Agent Memory.md",
                "Agent Memory",
                "area",
                """自动承接 `Resources/Agent Memory`。

## 适用范围

- 主题来源：`Resources/Agent Memory`

## 概念画像

<!-- BEGIN: understanding-profile -->

- 核心概念：old memory
- 资料数量：1

<!-- END: understanding-profile -->

## 资料索引

<!-- BEGIN: ownership-index -->

- [[Old Memory]]（自动承接：`Resources/Agent Memory`）

<!-- END: ownership-index -->
""",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Current Memory.md",
                "Current Memory",
                "reference",
                "Current memory uses episodic recall, reflection loop, and retrieval practice.",
            )

            report = run_apply_safe(vault)
            area_text = (vault / "Areas" / "Agent Memory.md").read_text(encoding="utf-8")

        self.assertIn("<!-- BEGIN: ownership-index -->", area_text)
        self.assertIn("<!-- END: ownership-index -->", area_text)
        self.assertIn("[[Current Memory]]", area_text)
        self.assertNotIn("[[Old Memory]]", area_text)
        self.assertIn(
            {
                "area": "Areas/Agent Memory.md",
                "topic_dir": "Resources/Agent Memory",
                "material_count": 1,
                "status": "updated",
                "reverse_updates": 1,
            },
            report["applied"]["ownership_area_profiles"],
        )

    def test_apply_safe_inserts_ownership_index_without_removing_existing_bullets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "Agent Memory.md",
                "Agent Memory",
                "area",
                """自动承接 `Resources/Agent Memory`。

## 适用范围

- 主题来源：`Resources/Agent Memory`

## 概念画像

<!-- BEGIN: understanding-profile -->

- 核心概念：episodic recall、reflection loop、retrieval practice
- 资料数量：1

<!-- END: understanding-profile -->

## 资料索引

- [[Manual Memory]]（重新理解：Agent Memory）

## 下一步

- Keep manual notes.
""",
            )
            write_note(
                vault / "Resources" / "Agent Memory" / "Current Memory.md",
                "Current Memory",
                "reference",
                "Current memory uses episodic recall, reflection loop, and retrieval practice.",
            )
            write_note(
                vault / "Resources" / "PKM" / "Manual Memory.md",
                "Manual Memory",
                "reference",
                "Manual memory note kept outside the generated ownership index.",
            )

            report = run_apply_safe(vault)
            area_text = (vault / "Areas" / "Agent Memory.md").read_text(encoding="utf-8")

        self.assertIn("<!-- BEGIN: ownership-index -->", area_text)
        self.assertIn("[[Current Memory]]", area_text)
        self.assertIn("- [[Manual Memory]]（重新理解：Agent Memory）", area_text)
        self.assertIn("## 下一步", area_text)
        self.assertIn(
            {
                "area": "Areas/Agent Memory.md",
                "topic_dir": "Resources/Agent Memory",
                "material_count": 1,
                "status": "updated",
                "reverse_updates": 1,
            },
            report["applied"]["ownership_area_profiles"],
        )

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

    def test_apply_safe_creates_child_area_for_title_contained_subcluster_inside_broad_area(self) -> None:
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
                    "Architecture for Interactive Judge.md",
                    "Architecture for Interactive Judge",
                    "Interactive judge architecture connects browser state, reward signal, and evaluator feedback.",
                ),
                (
                    "Metrics for Interactive Judge.md",
                    "Metrics for Interactive Judge",
                    "Interactive judge metrics compare browser state, reward signal, and evaluator feedback.",
                ),
                (
                    "Dataset for Interactive Judge.md",
                    "Dataset for Interactive Judge",
                    "Interactive judge dataset records browser state, reward signal, and evaluator feedback.",
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
            source_text = (vault / "Resources" / "AI Engineering" / "Architecture for Interactive Judge.md").read_text(
                encoding="utf-8"
            )
            unrelated_text = (vault / "Resources" / "AI Engineering" / "Semantic Fabric.md").read_text(
                encoding="utf-8"
            )

        self.assertIn("[[AI Engineering]]", child_text)
        self.assertIn("[[Architecture for Interactive Judge]]", child_text)
        self.assertIn("[[Metrics for Interactive Judge]]", child_text)
        self.assertIn("[[Dataset for Interactive Judge]]", child_text)
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

    def test_ownership_split_candidate_scoring_reuses_normalized_source_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Areas" / "AI Engineering.md",
                "AI Engineering",
                "area",
                "自动承接 `Resources/AI Engineering`。",
            )
            long_context = " ".join(
                [
                    "browser state",
                    "reward signal",
                    "action planner",
                    "evaluator feedback",
                    "tool trajectory",
                    "policy update",
                    "benchmark harness",
                    "test environment",
                    "trace analysis",
                    "agent runtime",
                ]
                * 20
            )
            for filename, title, body in (
                (
                    "Interactive Judge Pipeline.md",
                    "Interactive Judge Pipeline",
                    f"Interactive judge pipeline evaluates web agents with {long_context}.",
                ),
                (
                    "Interactive Judge Metrics.md",
                    "Interactive Judge Metrics",
                    f"Interactive judge metrics score web agents with {long_context}.",
                ),
                (
                    "Interactive Judge Dataset.md",
                    "Interactive Judge Dataset",
                    f"Interactive judge dataset records web agents with {long_context}.",
                ),
                (
                    "Semantic Fabric.md",
                    "Semantic Fabric",
                    "Semantic fabric models governed metrics and business contracts.",
                ),
                (
                    "Semantic Layer.md",
                    "Semantic Layer",
                    "Semantic layer documents governed metrics and definitions.",
                ),
            ):
                write_note(vault / "Resources" / "AI Engineering" / filename, title, "reference", body)

            notes, _by_name, _file_stems, _attachment_targets = optimize_vault.build_index(
                vault,
                ["Areas", "Resources"],
                set(),
            )
            call_counts: dict[str, int] = {}
            original = optimize_vault.source_text_without_wikilinks

            def counted_source_text(note: optimize_vault.Note) -> str:
                call_counts[note.path] = call_counts.get(note.path, 0) + 1
                return original(note)

            optimize_vault.source_text_without_wikilinks = counted_source_text
            try:
                candidates = optimize_vault.ownership_split_candidates(vault, notes, set())
            finally:
                optimize_vault.source_text_without_wikilinks = original

        self.assertEqual(1, len(candidates))
        self.assertEqual("Areas/Interactive Judge.md", candidates[0]["target"])
        material_calls = {
            path: count
            for path, count in call_counts.items()
            if path.startswith("Resources/AI Engineering/")
        }
        expected_material_paths = {
            note.path
            for note in notes
            if note.path.startswith("Resources/AI Engineering/") and note.path.endswith(".md")
        }
        self.assertEqual(material_calls.keys(), expected_material_paths)
        self.assertLessEqual(max(material_calls.values()), 1)

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
