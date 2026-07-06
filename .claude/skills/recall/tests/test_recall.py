#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import json
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "recall.py"
SPEC = importlib.util.spec_from_file_location("recall_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
recall = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recall
SPEC.loader.exec_module(recall)


def write_note(path: Path, title: str, note_type: str, body: str = "", aliases: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    aliases_block = ""
    if aliases:
        aliases_block = "aliases:\n" + "".join(f"  - {alias}\n" for alias in aliases)
    path.write_text(
        f"""---
title: "{title}"
type: {note_type}
{aliases_block}---

# {title}

{body}
""",
        encoding="utf-8",
    )


class RecallTest(unittest.TestCase):
    def test_query_report_returns_direct_concept_and_spread_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "Loop Engineering Primer.md",
                "Loop Engineering Primer",
                "reference",
                "Loop engineering uses grader loop checkpoints and memory routing.\n\nSee [[Adjacent Memory Habits]].",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Adjacent Memory Habits.md",
                "Adjacent Memory Habits",
                "reference",
                "This note records adjacent follow-up habits without query terms.",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "Verifier Workflow.md",
                "Verifier Workflow",
                "reference",
                "A verifier workflow uses grader loop checkpoints and memory routing for autonomous agents.",
            )

            report = recall.build_query_report(vault, "loop engineering grader loop memory routing")

        strengths = {item["path"]: item["strength"] for item in report["activations"]}
        self.assertEqual("direct", strengths["Resources/Loop Engineering/Loop Engineering Primer.md"])
        self.assertEqual("concept", strengths["Resources/AI Agents/Verifier Workflow.md"])
        self.assertEqual("spread", strengths["Resources/Loop Engineering/Adjacent Memory Habits.md"])
        self.assertEqual(
            "Resources/Loop Engineering/Loop Engineering Primer.md",
            report["suggested_reading_order"][0]["path"],
        )

    def test_log_event_reuses_latest_query_strengths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "Loop Engineering Primer.md",
                "Loop Engineering Primer",
                "reference",
                "Loop engineering uses grader loop checkpoints and memory routing.\n\nSee [[Adjacent Memory Habits]].",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Adjacent Memory Habits.md",
                "Adjacent Memory Habits",
                "reference",
                "This note records adjacent follow-up habits without query terms.",
            )
            report_dir = vault / ".test-reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            json_report = report_dir / "recall.json"
            markdown_report = report_dir / "recall.md"
            old_report_dir = recall.FIXED_REPORT_DIR
            old_json_report = recall.FIXED_JSON_REPORT
            old_markdown_report = recall.FIXED_MARKDOWN_REPORT
            try:
                recall.FIXED_REPORT_DIR = report_dir.resolve()
                recall.FIXED_JSON_REPORT = json_report.resolve()
                recall.FIXED_MARKDOWN_REPORT = markdown_report.resolve()
                report = recall.build_query_report(vault, "loop engineering memory routing")
                recall.write_outputs(report, json_report.resolve(), markdown_report.resolve())

                recall.append_log_event(
                    vault,
                    query="loop engineering memory routing",
                    result="answered",
                    activated_paths=[
                        "Resources/Loop Engineering/Loop Engineering Primer.md",
                        "Resources/Loop Engineering/Adjacent Memory Habits.md",
                    ],
                    gap_topic=None,
                )
            finally:
                recall.FIXED_REPORT_DIR = old_report_dir
                recall.FIXED_JSON_REPORT = old_json_report
                recall.FIXED_MARKDOWN_REPORT = old_markdown_report

            log_text = (vault / ".claude" / "recall.log").read_text(encoding="utf-8")
            logged_report = json.loads(json_report.read_text(encoding="utf-8"))

        self.assertIn("- 激活：Resources/Loop Engineering/Loop Engineering Primer.md (direct)", log_text)
        self.assertIn("- 激活：Resources/Loop Engineering/Adjacent Memory Habits.md (spread)", log_text)
        self.assertIn("- 结果：answered", log_text)
        self.assertIn("- 缺口：无", log_text)
        self.assertEqual("loop engineering memory routing", logged_report["query"])

    def test_create_gap_note_writes_inbox_note_with_query_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()

            created = recall.create_gap_note(
                vault,
                query="How do we close semantic recall gaps?",
                gap_topic="semantic recall",
                description="Need a durable practice for recall misses and follow-up study.",
            )

            self.assertEqual(vault / "Inbox" / "知识缺口 - semantic recall.md", created)
            text = created.read_text(encoding="utf-8")

        self.assertIn('title: "知识缺口 - semantic recall"', text)
        self.assertIn("type: gap", text)
        self.assertIn("- 原始查询：How do we close semantic recall gaps?", text)
        self.assertIn("- 缺口主题：semantic recall", text)
        self.assertIn("Need a durable practice for recall misses and follow-up study.", text)

    def test_query_report_matches_short_cjk_query_inside_longer_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "DSpark 半自回归投机解码.md",
                "DSpark 半自回归投机解码",
                "reference",
                "DSpark uses speculative decoding to accelerate inference.",
            )

            report = recall.build_query_report(vault, "投机解码")

        self.assertTrue(report["activations"])
        self.assertEqual("Resources/LLM Inference/DSpark 半自回归投机解码.md", report["activations"][0]["path"])
        self.assertEqual("direct", report["activations"][0]["strength"])

    def test_query_report_matches_single_latin_proper_noun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Agent Memory" / "XSpark 记忆编排方案.md",
                "XSpark 记忆编排方案",
                "reference",
                "XSpark coordinates retrieval memory and replay.",
            )

            report = recall.build_query_report(vault, "XSpark")

        self.assertTrue(report["activations"])
        self.assertEqual("Resources/Agent Memory/XSpark 记忆编排方案.md", report["activations"][0]["path"])
        self.assertEqual("direct", report["activations"][0]["strength"])

    def test_query_report_matches_single_phrase_concept_from_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "DSpark 半自回归推理.md",
                "DSpark 半自回归推理",
                "reference",
                "This method uses speculative decoding to accelerate language model inference.",
            )

            report = recall.build_query_report(vault, "speculative decoding")

        self.assertTrue(report["activations"])
        self.assertEqual("Resources/LLM Inference/DSpark 半自回归推理.md", report["activations"][0]["path"])
        self.assertEqual("concept", report["activations"][0]["strength"])

    def test_query_report_spreads_through_inbound_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "Loop Engineering Primer.md",
                "Loop Engineering Primer",
                "reference",
                "Loop engineering primer.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Backlink Note.md",
                "Backlink Note",
                "reference",
                "See [[Loop Engineering Primer]] for the base concept.",
            )

            report = recall.build_query_report(vault, "Loop Engineering Primer")

        strengths = {item["path"]: item["strength"] for item in report["activations"]}
        evidence = {item["path"]: item["evidence"] for item in report["activations"]}
        self.assertEqual("direct", strengths["Resources/Loop Engineering/Loop Engineering Primer.md"])
        self.assertEqual("spread", strengths["Resources/Loop Engineering/Backlink Note.md"])
        self.assertTrue(
            any("links to Resources/Loop Engineering/Loop Engineering Primer.md" in line for line in evidence["Resources/Loop Engineering/Backlink Note.md"])
        )

    def test_short_query_does_not_expand_into_broad_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(vault / "Resources" / "AI Agents" / "AI Agent Basics.md", "AI Agent Basics", "reference", "Agent basics.")
            write_note(vault / "Resources" / "AI Native" / "AI Native Delivery.md", "AI Native Delivery", "reference", "Delivery basics.")
            write_note(vault / "Resources" / "AI Infra" / "AI Infra Notes.md", "AI Infra Notes", "reference", "Infra basics.")

            report = recall.build_query_report(vault, "AI")

        self.assertLessEqual(len(report["activations"]), 1)

    def test_suggested_reading_order_is_truncated_to_fixed_top_n(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            for index in range(25):
                write_note(
                    vault / "Resources" / "Loop Engineering" / f"Loop Engineering Note {index:02d}.md",
                    f"Loop Engineering Note {index:02d}",
                    "reference",
                    "Loop engineering note with planner memory routing and verifier loops.",
                )

            report = recall.build_query_report(vault, "loop engineering")

        self.assertEqual(25, len(report["activations"]))
        self.assertEqual(20, len(report["suggested_reading_order"]))

    def test_log_event_skips_nonexistent_activated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            report_dir = vault / ".test-reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            old_cwd = Path.cwd()
            old_report_dir = recall.FIXED_REPORT_DIR
            old_json_report = recall.FIXED_JSON_REPORT
            old_markdown_report = recall.FIXED_MARKDOWN_REPORT
            stderr = io.StringIO()
            try:
                os.chdir(vault)
                recall.FIXED_REPORT_DIR = report_dir.resolve()
                recall.FIXED_JSON_REPORT = (report_dir / "recall.json").resolve()
                recall.FIXED_MARKDOWN_REPORT = (report_dir / "recall.md").resolve()
                with contextlib.redirect_stderr(stderr):
                    rc = recall.main(
                        [
                            "--mode",
                            "log-event",
                            "--query",
                            "test",
                            "--result",
                            "answered",
                            "--activated",
                            "Resources/不存在/x.md",
                        ]
                    )
            finally:
                os.chdir(old_cwd)
                recall.FIXED_REPORT_DIR = old_report_dir
                recall.FIXED_JSON_REPORT = old_json_report
                recall.FIXED_MARKDOWN_REPORT = old_markdown_report

            log_text = (vault / ".claude" / "recall.log").read_text(encoding="utf-8")

        self.assertEqual(0, rc)
        self.assertIn("skip", stderr.getvalue().lower())
        self.assertNotIn("Resources/不存在/x.md", log_text)
