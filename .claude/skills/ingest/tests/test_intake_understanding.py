#!/usr/bin/env python3
from __future__ import annotations

import base64
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest.py"
SPEC = importlib.util.spec_from_file_location("ingest_understanding_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ingest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ingest
SPEC.loader.exec_module(ingest)
VAULT_CLAUDE_DIR = MODULE_PATH.parents[3]
MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def write_note(path: Path, title: str, note_type: str, body: str, aliases: list[str] | None = None) -> None:
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


class IntakeUnderstandingTest(unittest.TestCase):
    def test_concept_normalization_keeps_short_es_plural_readable(self) -> None:
        self.assertEqual("fix", ingest.normalize_concept_token("fixes"))
        self.assertEqual("box", ingest.normalize_concept_token("boxes"))
        self.assertEqual("class", ingest.normalize_concept_token("classes"))

    def test_report_suggests_resource_topic_and_owner_for_ready_inbox_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering turns prompting into feedback loops with Claude Code, graders, and memory.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Long-term ownership for loop engineering, Claude Code loops, verifier workflows, and agent memory.",
            )
            write_note(
                vault / "Inbox" / "Loop Roadmap.md",
                "Loop Roadmap",
                "reference",
                "A loop engineering roadmap for Claude Code with timers, independent graders, and memory.",
            )

            report = ingest.make_report(vault, convert=False)

        hint = report["understanding_hints"]["Inbox/Loop Roadmap.md"]
        self.assertEqual("Resources/Loop Engineering/Loop Roadmap.md", hint["target_candidates"][0]["target"])
        self.assertEqual("Areas/Loop Engineering.md", hint["ownership_candidates"][0]["path"])
        self.assertTrue(hint["target_candidates"][0]["evidence"])

    def test_report_uses_filename_stem_for_link_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures loop design, prompt replacement, and Claude Code workflows.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Loop Engineering The Skill.md",
                "Loop Engineering: The Skill",
                "reference",
                "Loop Engineering: The Skill explains why feedback loops replace prompt engineering.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "These notes explicitly cite Loop Engineering: The Skill as a useful reference.",
            )

            report = ingest.make_report(vault, convert=False)

        links = report["understanding_hints"]["Inbox/Loop Notes.md"]["link_candidates"]
        self.assertEqual("Resources/Loop Engineering/Loop Engineering The Skill.md", links[0]["path"])
        self.assertEqual("Loop Engineering The Skill", links[0]["wikilink"])
        self.assertNotIn(":", links[0]["wikilink"])

    def test_link_verification_plan_resolves_wikilink_to_existing_filename_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures loop design and feedback loops.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Loop Engineering The Skill.md",
                "Loop Engineering: The Skill",
                "reference",
                "Loop Engineering: The Skill explains why feedback loops replace prompt engineering.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for Loop Engineering and feedback loops.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "These notes explicitly cite Loop Engineering: The Skill as a useful reference.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        plan = report["link_verification_plan"]["Inbox/Loop Notes.md"]
        self.assertEqual("pass", plan["status"])
        self.assertEqual("Loop Engineering The Skill", plan["links"][0]["wikilink"])
        self.assertEqual("Resources/Loop Engineering/Loop Engineering The Skill.md", plan["links"][0]["target_path"])
        self.assertTrue(plan["links"][0]["exists"])
        self.assertTrue(plan["links"][0]["stem_matches"])
        self.assertTrue(plan["links"][0]["safe"])
        self.assertIn("## 双链验证计划", markdown)
        self.assertIn("[[Loop Engineering The Skill]]", markdown)

    def test_link_verification_plan_blocks_unsafe_or_missing_link_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            report = {
                "candidates": [{"path": "Inbox/Bad Links.md", "status": "ready"}],
                "understanding_hints": {
                    "Inbox/Bad Links.md": {
                        "link_candidates": [
                            {"wikilink": "Inbox/Missing", "path": "Resources/Loop Engineering/Missing.md"},
                            {"wikilink": "Loop Engineering: Broken", "path": "Resources/Loop Engineering/Loop Engineering Broken.md"},
                        ]
                    }
                },
            }

            plan = ingest.link_verification_plan(report, vault)["Inbox/Bad Links.md"]

        self.assertEqual("blocked", plan["status"])
        self.assertIn("unsafe wikilink candidate: Inbox/Missing", plan["blocked_by"])
        self.assertIn("unsafe wikilink candidate: Loop Engineering: Broken", plan["blocked_by"])
        self.assertIn("missing wikilink target: Resources/Loop Engineering/Missing.md", plan["blocked_by"])

    def test_report_suggests_existing_note_link_by_topic_concept_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering practices use maker checker workflows, stop conditions, graders, and evidence loops.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Maker Checker Workflow.md",
                "Maker Checker Workflow",
                "reference",
                "A workflow pattern using maker checker separation, stop condition gates, rollback plans, grader evidence, and verifier loops.",
            )
            write_note(
                vault / "Inbox" / "Loop Guardrails.md",
                "Loop Guardrails",
                "reference",
                "Guardrails for autonomous loops: maker checker separation, stop condition gates, rollback plans, grader evidence, and verifier loops.",
            )

            report = ingest.make_report(vault, convert=False)

        links = report["understanding_hints"]["Inbox/Loop Guardrails.md"]["link_candidates"]
        self.assertEqual("Resources/Loop Engineering/Maker Checker Workflow.md", links[0]["path"])
        self.assertEqual("Maker Checker Workflow", links[0]["wikilink"])
        self.assertTrue(any("matched concepts" in evidence for evidence in links[0]["evidence"]))

    def test_concept_overlap_links_do_not_use_lower_ranked_target_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering uses maker checker stop condition workflows for autonomous loops.",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "README.md",
                "AI Agents",
                "index",
                "Agents use memory loops, tool checks, goal review, and harness evidence.",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "Agent Harness.md",
                "Agent Harness",
                "reference",
                "Agent memory loops, tool checks, goal review, harness evidence, and failure recovery.",
            )
            write_note(
                vault / "Inbox" / "Loop Guardrails.md",
                "Loop Guardrails",
                "reference",
                "Loop Engineering guardrails with agent memory loops, tool checks, goal review, harness evidence, and failure recovery.",
            )

            report = ingest.make_report(vault, convert=False)

        hint = report["understanding_hints"]["Inbox/Loop Guardrails.md"]
        self.assertEqual("Loop Engineering", hint["target_candidates"][0]["topic"])
        self.assertTrue(any(target["topic"] == "AI Agents" for target in hint["target_candidates"][1:]))
        self.assertEqual([], hint["link_candidates"])

    def test_ambiguous_topic_match_is_report_only_with_no_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Agent Memory" / "README.md",
                "Agent Memory",
                "index",
                "Shared durable signal routing patterns for adaptive agent systems.",
            )
            write_note(
                vault / "Resources" / "Agent Evaluation" / "README.md",
                "Agent Evaluation",
                "index",
                "Shared durable signal routing patterns for adaptive agent systems.",
            )
            write_note(
                vault / "Inbox" / "Ambiguous.md",
                "Ambiguous",
                "reference",
                "This material discusses shared durable signal routing patterns for adaptive agent systems.",
            )

            report = ingest.make_report(vault, convert=False)

        hint = report["understanding_hints"]["Inbox/Ambiguous.md"]
        self.assertEqual([], hint["target_candidates"])
        self.assertTrue(any("ambiguous" in note for note in hint["notes"]))

    def test_markdown_report_includes_intake_understanding_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Long-term ownership for durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Inbox" / "Loop Roadmap.md",
                "Loop Roadmap",
                "reference",
                "A Loop Engineering roadmap for durable Claude Code feedback loops.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        self.assertIn("## 摄入理解提示", markdown)
        self.assertIn("Resources/Loop Engineering/Loop Roadmap.md", markdown)
        self.assertIn("Areas/Loop Engineering.md", markdown)
        self.assertIn("report-only", markdown)

    def test_target_topic_with_exact_owner_adds_ownership_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Maker checker stop condition evidence for autonomous loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership note for this long-running area.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "Maker checker stop condition evidence for autonomous loops.",
            )

            report = ingest.make_report(vault, convert=False)

        hint = report["understanding_hints"]["Inbox/Loop Notes.md"]
        self.assertEqual("Resources/Loop Engineering/Loop Notes.md", hint["target_candidates"][0]["target"])
        self.assertEqual("Areas/Loop Engineering.md", hint["ownership_candidates"][0]["path"])
        self.assertIn("matched target topic owner", hint["ownership_candidates"][0]["evidence"])

    def test_target_without_owner_reports_create_area_ownership_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing, traffic shaping, cold starts, and GPU serving patterns.",
            )
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Notes about serverless inference routing, traffic shaping, cold starts, and GPU serving.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        hint = report["understanding_hints"]["Inbox/Routing Pattern.md"]
        self.assertEqual([], hint["ownership_candidates"])
        self.assertEqual("create_area", hint["ownership_actions"][0]["action"])
        self.assertEqual("Areas/LLM Inference.md", hint["ownership_actions"][0]["path"])
        self.assertIn("Resources/LLM Inference/Routing Pattern.md", hint["ownership_actions"][0]["target"])
        self.assertIn("承接动作", markdown)
        self.assertIn("Areas/LLM Inference.md", markdown)

    def test_existing_project_match_can_be_first_pass_target_without_area_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Projects" / "sample-project.md",
                "sample-project",
                "project",
                "Active project for workflow automation, remediation workflows, and agent playbooks.",
            )
            write_note(
                vault / "Inbox" / "Sample Project Sprint Notes.md",
                "Sample Project Sprint Notes",
                "reference",
                "sample-project sprint notes for workflow automation and remediation workflow delivery.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        hint = report["understanding_hints"]["Inbox/Sample Project Sprint Notes.md"]
        self.assertEqual("Projects/sample-project/Sample Project Sprint Notes.md", hint["target_candidates"][0]["target"])
        self.assertEqual("Projects", hint["target_candidates"][0]["scope"])
        self.assertEqual("Projects/sample-project.md", hint["ownership_candidates"][0]["path"])
        self.assertEqual([], hint["ownership_actions"])
        readiness = report["placement_readiness"]["Inbox/Sample Project Sprint Notes.md"]
        self.assertEqual("ready", readiness["status"])
        self.assertEqual(["Projects/sample-project.md"], readiness["ownership"])
        org_plan = report["organization_plan"]["Inbox/Sample Project Sprint Notes.md"]
        self.assertEqual("ready", org_plan["status"])
        self.assertFalse(org_plan["resource_index"]["required"])
        seed = report["distillation_seed"]["Inbox/Sample Project Sprint Notes.md"]
        self.assertEqual("Projects/sample-project", seed["use_context"]["target_dir"])
        content_plan = report["content_patch_plan"]["Inbox/Sample Project Sprint Notes.md"]
        self.assertIn("`Projects/sample-project`", content_plan["body_markdown"])
        self.assertNotIn("待定主题", content_plan["body_markdown"])
        self.assertIn("Projects/sample-project/Sample Project Sprint Notes.md", markdown)

    def test_placement_readiness_is_ready_when_target_and_owner_are_known(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering durable feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for Loop Engineering feedback loops.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "Loop Engineering durable feedback loops.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        readiness = report["placement_readiness"]["Inbox/Loop Notes.md"]
        self.assertEqual("ready", readiness["status"])
        self.assertEqual("Resources/Loop Engineering/Loop Notes.md", readiness["target"])
        self.assertEqual(["Areas/Loop Engineering.md"], readiness["ownership"])
        self.assertIn("## 归位就绪度", markdown)

    def test_placement_readiness_blocks_when_ownership_action_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing and GPU serving.",
            )
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Serverless inference routing and GPU serving.",
            )

            report = ingest.make_report(vault, convert=False)

        readiness = report["placement_readiness"]["Inbox/Routing Pattern.md"]
        self.assertEqual("ready", readiness["status"])
        self.assertEqual(["Areas/LLM Inference.md"], readiness["ownership"])
        self.assertEqual([], readiness["reasons"])
        self.assertEqual([], readiness["required_actions"])

    def test_placement_readiness_blocks_when_target_path_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering durable feedback loops.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Loop Notes.md",
                "Existing Loop Notes",
                "reference",
                "Existing unrelated loop engineering reference already occupies this filename.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for Loop Engineering feedback loops.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "New Loop Engineering durable feedback loops material with a conflicting target filename.",
            )

            report = ingest.make_report(vault, convert=False)

        readiness = report["placement_readiness"]["Inbox/Loop Notes.md"]
        self.assertEqual("blocked", readiness["status"])
        self.assertIn("target path conflict", readiness["reasons"])
        self.assertIn("Resources/Loop Engineering/Loop Notes.md", readiness["required_actions"])

    def test_placement_readiness_blocks_when_converted_source_path_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            source_dir = vault / "Resources" / "Loop Engineering" / "source"
            source_dir.mkdir(parents=True)
            (source_dir / "Export.csv").write_text("older,source\n", encoding="utf-8")
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(
                    vault / "Inbox" / "Export.md",
                    "Export",
                    "reference",
                    "Converted Loop Engineering source about durable Claude Code feedback loops.",
                )
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        readiness = report["placement_readiness"]["Inbox/Export.csv"]
        self.assertEqual("blocked", readiness["status"])
        self.assertIn("source path conflict", readiness["reasons"])
        self.assertIn("Resources/Loop Engineering/source/Export.csv", readiness["required_actions"])

    def test_report_surfaces_recent_meditate_feedback_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- 范围：whole vault
- 补链：3，需要摄入阶段优先识别 Loop Engineering 与 AI Agents 的显式关系
- 结构建议：Resources/AI Agents 中的 loop 子簇应更早归入 Loop Engineering
- 普通统计：扫描 49 篇
commit: 无
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "Loop Engineering and AI Agents relationship notes.",
            )

            report = ingest.make_report(vault, convert=False)

        feedback = report["meditate_feedback"]
        self.assertEqual(".claude/meditate.log", feedback["source"])
        self.assertEqual(2, len(feedback["items"]))
        self.assertIn("补链", feedback["items"][0])
        self.assertIn("结构建议", feedback["items"][1])

    def test_markdown_report_includes_recent_meditate_feedback_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- 承接：Resources/LLM Inference 缺少清晰 Area ownership
commit: 无
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Inbox" / "Serving Notes.md",
                "Serving Notes",
                "reference",
                "Serving notes for LLM inference.",
            )

            markdown = ingest.markdown_report(ingest.make_report(vault, convert=False))

        self.assertIn("## meditate 反馈提醒", markdown)
        self.assertIn("Resources/LLM Inference 缺少清晰 Area ownership", markdown)

    def test_meditate_ownership_feedback_becomes_intake_rule_for_matching_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- 承接：Resources/LLM Inference 缺少清晰 Area ownership
commit: 无
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing, traffic shaping, and GPU serving patterns.",
            )
            write_note(
                vault / "Inbox" / "Serving Notes.md",
                "Serving Notes",
                "reference",
                "Notes about serverless inference routing and GPU serving patterns.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        rule = report["intake_rules"][0]
        self.assertEqual("ensure_ownership", rule["action"])
        self.assertEqual("Resources/LLM Inference", rule["topic_path"])
        hint = report["understanding_hints"]["Inbox/Serving Notes.md"]
        action = hint["ownership_actions"][0]
        self.assertEqual("meditate_feedback", action["source"])
        self.assertTrue(any("meditate feedback" in evidence for evidence in action["evidence"]))
        self.assertIn("## 摄入学习规则", markdown)
        self.assertIn("Resources/LLM Inference", markdown)

    def test_meditate_structure_feedback_prefers_topic_for_future_inbox_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- 结构建议：Resources/AI Agents 中的 loop 子簇应更早归入 Loop Engineering
commit: 无
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "README.md",
                "AI Agents",
                "index",
                "AI Agents use helper workers, tool calling, memory, and autonomous coding agent workflows.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering uses feedback loops, stop conditions, failing tests, helper workers, and autonomous coding loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for feedback loops, stop conditions, and autonomous coding loops.",
            )
            write_note(
                vault / "Inbox" / "Agent Loop Notes.md",
                "Agent Loop Notes",
                "reference",
                "AI agents use helper workers inside feedback loops with stop conditions and failing tests.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        rule = next(rule for rule in report["intake_rules"] if rule["action"] == "prefer_topic")
        self.assertEqual("Resources/AI Agents", rule["from_topic_path"])
        self.assertEqual("Resources/Loop Engineering", rule["topic_path"])
        hint = report["understanding_hints"]["Inbox/Agent Loop Notes.md"]
        self.assertEqual("Loop Engineering", hint["target_candidates"][0]["topic"])
        self.assertTrue(any("meditate feedback topic preference" in evidence for evidence in hint["target_candidates"][0]["evidence"]))
        audit = report["intake_learning_audit"]
        self.assertEqual(1, audit["rules_total"])
        self.assertEqual({"prefer_topic": 1}, audit["by_action"])
        self.assertEqual(
            {
                "candidate": "Inbox/Agent Loop Notes.md",
                "action": "prefer_topic",
                "source": "meditate_feedback",
                "effect": "target candidate boosted",
                "target": "Resources/Loop Engineering/Agent Loop Notes.md",
                "rule_evidence": "结构建议：Resources/AI Agents 中的 loop 子簇应更早归入 Loop Engineering",
            },
            audit["applied"][0],
        )
        readiness = report["placement_readiness"]["Inbox/Agent Loop Notes.md"]
        self.assertEqual("ready", readiness["status"])
        self.assertIn("结构反馈优先归入", markdown)
        self.assertIn("## 摄入学习审计", markdown)
        self.assertIn("target candidate boosted", markdown)

    def test_meditate_structure_feedback_ignores_missing_suggested_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- 结构建议：Resources/AI Agents 中的 loop 子簇应更早归入 Missing Topic
commit: 无
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "README.md",
                "AI Agents",
                "index",
                "AI Agents use helper workers, tool calling, and memory.",
            )
            write_note(
                vault / "Inbox" / "Agent Loop Notes.md",
                "Agent Loop Notes",
                "reference",
                "AI agents use helper workers inside feedback loops.",
            )

            report = ingest.make_report(vault, convert=False)

        self.assertFalse(any(rule["action"] == "prefer_topic" for rule in report["intake_rules"]))

    def test_intake_quality_metrics_count_readiness_blockers_and_learning_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- 结构建议：Resources/AI Agents 中的 loop 子簇应更早归入 Loop Engineering
commit: 无
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "README.md",
                "AI Agents",
                "index",
                "AI Agents use helper workers, tool calling, memory, and autonomous coding agent workflows.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering uses feedback loops, stop conditions, failing tests, helper workers, and autonomous coding loops.",
            )
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "LLM inference covers model serving, serverless routing patterns, latency, and deployment.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for feedback loops, stop conditions, and autonomous coding loops.",
            )
            write_note(
                vault / "Inbox" / "Agent Loop Notes.md",
                "Agent Loop Notes",
                "reference",
                "AI agents use helper workers inside feedback loops with stop conditions and failing tests.",
            )
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Serverless routing patterns for LLM inference reduce latency in model serving deployments.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        metrics = report["intake_quality_metrics"]
        self.assertEqual(2, metrics["candidates_total"])
        self.assertEqual(2, metrics["ready_for_apply"])
        self.assertEqual(0, metrics["blocked"])
        self.assertEqual(2, metrics["handoff_ready"])
        self.assertEqual(0, metrics["handoff_blocked"])
        self.assertEqual({}, metrics["blocked_by_reason"])
        self.assertEqual(0, metrics["source_understanding_blocked"])
        self.assertEqual(1, metrics["learning_rules_total"])
        self.assertEqual(1, metrics["learning_rules_applied"])
        self.assertIn("## 摄入质量指标", markdown)
        self.assertIn("ready_for_apply=2", markdown)
        self.assertIn("阻断原因：无", markdown)

    def test_intake_quality_trends_parse_prior_log_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "ingest.log").write_text(
                """## 2026-07-01 09:00 manual
- 摄入质量：ready_rate=0.25, ready_for_apply=1, blocked=3, handoff_ready=1, handoff_blocked=3, learning_rules_applied=0
- 阻断原因：ownership action required=2, source understanding required=1
commit: aaa111

## 2026-07-02 09:00 manual
- 摄入质量：ready_rate=0.5, ready_for_apply=2, blocked=2, handoff_ready=2, handoff_blocked=2, learning_rules_applied=1
- 阻断原因：ownership action required=1, source understanding required=1
commit: bbb222
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering uses feedback loops and verifier evidence.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for feedback loops and verifier evidence.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "Loop Engineering feedback loops with verifier evidence.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        trends = report["intake_quality_trends"]
        self.assertEqual(2, trends["history_runs"])
        self.assertEqual(0.375, trends["historical_average_ready_rate"])
        self.assertEqual(0.5, trends["historical_latest_ready_rate"])
        self.assertEqual(1.0, trends["current_ready_rate"])
        self.assertEqual("improving", trends["ready_rate_trend"])
        self.assertEqual({"ownership action required": 3, "source understanding required": 2}, trends["recurring_blockers"])
        self.assertIn("## 摄入质量趋势", markdown)
        self.assertIn("ready_rate_trend=improving", markdown)
        self.assertIn("ownership action required=3", markdown)

    def test_meditate_link_feedback_prefers_verified_links_for_future_inbox_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- 补链：需要摄入阶段优先识别 Loop Engineering 与 AI Agents 的显式关系
commit: 无
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures feedback loops, stop conditions, and verifier evidence.",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "README.md",
                "AI Agents",
                "index",
                "AI Agents use tools, memory, autonomous workflows, and verifier harnesses.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for loop engineering and verifier feedback loops.",
            )
            write_note(
                vault / "Areas" / "AI Agents.md",
                "AI Agents",
                "area",
                "Ownership for agent tools, memory, and autonomous workflow practice.",
            )
            write_note(
                vault / "Inbox" / "Agent Loop Links.md",
                "Agent Loop Links",
                "reference",
                "Loop Engineering and AI Agents increasingly overlap around verifier feedback loops and memory tools.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        rule = next(rule for rule in report["intake_rules"] if rule["action"] == "prefer_link")
        self.assertEqual(["Loop Engineering", "AI Agents"], rule["terms"])
        hint = report["understanding_hints"]["Inbox/Agent Loop Links.md"]
        links_by_wikilink = {link["wikilink"]: link for link in hint["link_candidates"]}
        self.assertEqual("Areas/Loop Engineering.md", links_by_wikilink["Loop Engineering"]["path"])
        self.assertEqual("Areas/AI Agents.md", links_by_wikilink["AI Agents"]["path"])
        self.assertTrue(any("meditate feedback link attention" in evidence for evidence in links_by_wikilink["Loop Engineering"]["evidence"]))
        plan = report["link_verification_plan"]["Inbox/Agent Loop Links.md"]
        self.assertEqual("pass", plan["status"])
        self.assertIn("Loop Engineering", plan["verified_wikilinks"])
        self.assertIn("AI Agents", plan["verified_wikilinks"])
        self.assertIn("补链反馈优先连链", markdown)

    def test_english_meditate_missing_link_feedback_becomes_intake_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "meditate.log").write_text(
                """## 2026-07-01 09:00 manual
- Missing link: between Loop Engineering and AI Agents relationship
commit: none
""",
                encoding="utf-8",
            )
            write_note(vault / "Areas" / "Loop Engineering.md", "Loop Engineering", "area", "Loop ownership.")
            write_note(vault / "Areas" / "AI Agents.md", "AI Agents", "area", "Agent ownership.")
            write_note(
                vault / "Inbox" / "Agent Loop Links.md",
                "Agent Loop Links",
                "reference",
                "Loop Engineering and AI Agents overlap around autonomous feedback loops.",
            )

            report = ingest.make_report(vault, convert=False)

        rule = next(rule for rule in report["intake_rules"] if rule["action"] == "prefer_link")
        self.assertEqual(["Loop Engineering", "AI Agents"], rule["terms"])

    def test_ingest_history_owner_mapping_becomes_intake_rule_for_matching_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude").mkdir(parents=True)
            (vault / ".claude" / "ingest.log").write_text(
                """## 2026-07-01 09:00 manual
- Inbox/Old Agent Note.md → Resources/AI Agents/Old Agent Note.md
- 承接笔记：[[AI Native 转型]]
commit: abc123
""",
                encoding="utf-8",
            )
            write_note(
                vault / "Resources" / "AI Agents" / "README.md",
                "AI Agents",
                "index",
                "Agent orchestration, memory tools, tool calling, and evaluator harnesses.",
            )
            write_note(
                vault / "Areas" / "AI Native 转型.md",
                "AI Native 转型",
                "area",
                "Long-term team transformation and engineering adoption ownership.",
            )
            write_note(
                vault / "Inbox" / "Agent Harness.md",
                "Agent Harness",
                "reference",
                "Agent orchestration with memory tools, tool calling, and evaluator harnesses.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        rule = next(rule for rule in report["intake_rules"] if rule["source"] == "ingest_history")
        self.assertEqual("prefer_ownership", rule["action"])
        self.assertEqual("Resources/AI Agents", rule["topic_path"])
        self.assertEqual("Areas/AI Native 转型.md", rule["suggested_owner"])
        hint = report["understanding_hints"]["Inbox/Agent Harness.md"]
        self.assertEqual("Areas/AI Native 转型.md", hint["ownership_candidates"][0]["path"])
        self.assertTrue(any("ingest history" in evidence for evidence in hint["ownership_candidates"][0]["evidence"]))
        readiness = report["placement_readiness"]["Inbox/Agent Harness.md"]
        self.assertEqual("ready", readiness["status"])
        self.assertIn("ingest history", markdown)

    def test_prepare_report_suggests_target_for_converted_source_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True)
            (vault / "Inbox" / "Loop Source.txt").write_text("raw exported text", encoding="utf-8")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(
                    vault / "Inbox" / "Loop Source.md",
                    "Loop Source",
                    "reference",
                    "Converted source material about Loop Engineering and Claude Code feedback loops.",
                )
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        hint = report["understanding_hints"]["Inbox/Loop Source.txt"]
        self.assertEqual("Inbox/Loop Source.md", report["candidates"][0]["markdown_path"])
        self.assertEqual("Resources/Loop Engineering/Loop Source.md", hint["target_candidates"][0]["target"])

    def test_prepare_leaves_source_in_inbox_when_conversion_output_is_error_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / ".claude" / "bin").mkdir(parents=True)
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.write_text(
                """#!/bin/sh
out="${1%.*}.md"
printf 'ERROR: markitdown failed to parse the source file\\n' > "$out"
exit 0
""",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            (vault / "Inbox").mkdir(parents=True)
            (vault / "Inbox" / "Broken.txt").write_text("original text export", encoding="utf-8")

            report = ingest.make_report(vault, convert=True)

        candidate = report["candidates"][0]
        self.assertEqual("left_in_inbox", candidate["status"])
        self.assertEqual("conversion output looks like an error message", candidate["reason"])
        self.assertNotIn("Inbox/Broken.txt", report["understanding_hints"])

    def test_encoding_plan_requires_distillation_for_long_ready_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            long_body = " ".join("durable loop engineering evidence" for _ in range(220))
            write_note(vault / "Inbox" / "Long Article.md", "Long Article", "reference", long_body)

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        plan = report["encoding_plan"]["Inbox/Long Article.md"]
        self.assertTrue(plan["distillation"]["required"])
        self.assertIn("## 提炼", plan["distillation"]["sections"])
        self.assertIn("## 原文 / 摘录", plan["distillation"]["sections"])
        self.assertEqual(report["candidates"][0]["source_fingerprint"], plan["frontmatter"]["recommended"]["source_fingerprint"])
        self.assertIn("## 首次编码计划", markdown)
        self.assertIn("提炼：必须", markdown)

    def test_encoding_plan_requires_source_file_for_converted_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / "Inbox").mkdir(parents=True)
            (vault / "Inbox" / "Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(vault / "Inbox" / "Export.md", "Export", "reference", "Converted CSV export about loops.")
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        plan = report["encoding_plan"]["Inbox/Export.csv"]
        self.assertTrue(plan["source_file"]["required"])
        self.assertEqual("source/Export.csv", plan["source_file"]["expected"])
        self.assertIn("原始文件：[[source/Export.csv]]", plan["source_file"]["visible_link"])

    def test_image_placeholder_requires_manual_visual_understanding_before_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Loop Engineering Screenshot.png").write_bytes(b"fake png bytes")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                (vault / "Inbox" / "Loop Engineering Screenshot.md").write_text(
                    """# Loop Engineering Screenshot

Filename: Loop Engineering Screenshot.png
Format: PNG
Size: 1024x768
""",
                    encoding="utf-8",
                )
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)
                markdown = ingest.markdown_report(report)

        plan = report["encoding_plan"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("blocked", plan["source_understanding"]["status"])
        self.assertIn("manual visual inspection", plan["source_understanding"]["required_action"])
        readiness = report["placement_readiness"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("blocked", readiness["status"])
        self.assertIn("source understanding required", readiness["reasons"])
        handoff = report["meditate_handoff"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertIn("source understanding required", handoff["blocked_by"])
        org_plan = report["organization_plan"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("blocked", org_plan["status"])
        self.assertIn("inspect original source: Inbox/Loop Engineering Screenshot.png", org_plan["next_actions"])
        self.assertIn("源素材理解：blocked", markdown)

    def test_image_ocr_from_safe_markitdown_feeds_first_pass_understanding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops, maker checker workflows, and verifier evidence.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops and verifier evidence.",
            )
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text((VAULT_CLAUDE_DIR / "bin" / "safe-markitdown").read_text(encoding="utf-8"), encoding="utf-8")
            converter.chmod(0o755)
            fake_bin = vault / "fake-bin"
            fake_bin.mkdir()
            tesseract = fake_bin / "tesseract"
            tesseract.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'Loop Engineering screenshot shows durable Claude Code feedback loops, maker checker workflows, verifier evidence, and stop conditions for autonomous coding.'\n",
                encoding="utf-8",
            )
            tesseract.chmod(0o755)
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Loop Engineering Screenshot.png").write_bytes(MINIMAL_PNG)

            with patch.dict(os.environ, {"PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"}):
                report = ingest.make_report(vault, convert=True)
            converted = (vault / "Inbox" / "Loop Engineering Screenshot.md").read_text(encoding="utf-8")

        self.assertIn("## 自动识别文本", converted)
        self.assertIn("maker checker workflows", converted)
        plan = report["encoding_plan"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("pass", plan["source_understanding"]["status"])
        self.assertEqual("image", plan["source_understanding"]["modality"])
        readiness = report["placement_readiness"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("ready", readiness["status"])
        self.assertEqual("Resources/Loop Engineering/Loop Engineering Screenshot.md", readiness["target"])

    def test_image_placeholder_from_safe_markitdown_without_ocr_blocks_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            converter = vault / ".claude" / "bin" / "safe-markitdown"
            converter.parent.mkdir(parents=True)
            converter.write_text((VAULT_CLAUDE_DIR / "bin" / "safe-markitdown").read_text(encoding="utf-8"), encoding="utf-8")
            converter.chmod(0o755)
            fake_bin = vault / "fake-bin"
            fake_bin.mkdir()
            (fake_bin / "python3").symlink_to(Path(sys.executable))
            git_path = shutil.which("git")
            self.assertIsNotNone(git_path)
            (fake_bin / "git").symlink_to(Path(git_path))
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Loop Engineering Screenshot.png").write_bytes(MINIMAL_PNG)

            with patch.dict(os.environ, {"PATH": str(fake_bin)}):
                report = ingest.make_report(vault, convert=True)
                markdown = ingest.markdown_report(report)
            converted = (vault / "Inbox" / "Loop Engineering Screenshot.md").read_text(encoding="utf-8")

        self.assertIn("## 图片信息", converted)
        self.assertIn("## 待整理", converted)
        plan = report["encoding_plan"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("blocked", plan["source_understanding"]["status"])
        readiness = report["placement_readiness"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("blocked", readiness["status"])
        self.assertIn("source understanding required", readiness["reasons"])
        handoff = report["meditate_handoff"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("blocked", handoff["status"])
        self.assertIn("source understanding required", handoff["blocked_by"])
        org_plan = report["organization_plan"]["Inbox/Loop Engineering Screenshot.png"]
        self.assertEqual("blocked", org_plan["status"])
        self.assertIn("源素材理解：blocked", markdown)

    def test_audio_transcript_too_short_blocks_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Loop Engineering Voice Note.mp3").write_bytes(b"fake mp3 bytes")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(vault / "Inbox" / "Loop Engineering Voice Note.md", "Loop Engineering Voice Note", "reference", "Loop.")
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        plan = report["encoding_plan"]["Inbox/Loop Engineering Voice Note.mp3"]
        self.assertEqual("blocked", plan["source_understanding"]["status"])
        self.assertIn("transcript too short", plan["source_understanding"]["reason"])
        readiness = report["placement_readiness"]["Inbox/Loop Engineering Voice Note.mp3"]
        self.assertEqual("blocked", readiness["status"])
        self.assertIn("source understanding required", readiness["reasons"])

    def test_safe_whisper_writes_plain_inbox_source_reference_not_wikilink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            wrapper = vault / ".claude" / "bin" / "safe-whisper"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text((VAULT_CLAUDE_DIR / "bin" / "safe-whisper").read_text(encoding="utf-8"), encoding="utf-8")
            wrapper.chmod(0o755)
            fake_bin = vault / "fake-bin"
            fake_bin.mkdir()
            (fake_bin / "python3").symlink_to(Path(sys.executable))
            whisper = fake_bin / "whisper"
            whisper.write_text(
                """#!/bin/sh
outdir=""
input=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output_format) shift ;;
    --output_dir) shift; outdir="$1" ;;
    --model|--language) shift ;;
    --*) ;;
    *) if [ -z "$input" ]; then input="$1"; fi ;;
  esac
  shift
done
stem="${input##*/}"
stem="${stem%.*}"
{
  printf '%s\n' 'Maker checker workflows keep autonomous coding loops grounded in independent verification.'
  printf '%s\n' 'Stop condition design prevents a loop from continuing after evidence becomes weak.'
  printf '%s\n' 'Verifier evidence should be attached to every handoff so meditate can trust the source.'
} > "$outdir/$stem.txt"
exit 0
""",
                encoding="utf-8",
            )
            whisper.chmod(0o755)
            (vault / "Inbox").mkdir(parents=True)
            (vault / "Inbox" / "Loop Audio.m4a").write_bytes(b"fake audio bytes")

            completed = subprocess.run(
                [str(wrapper), "Inbox/Loop Audio.m4a"],
                cwd=vault,
                env={**os.environ, "PATH": str(fake_bin)},
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            converted = (vault / "Inbox" / "Loop Audio.md").read_text(encoding="utf-8")
            self.assertIn("原始文件：`Inbox/Loop Audio.m4a`", converted)
            self.assertNotIn("[[Loop Audio.m4a]]", converted)

    def test_distillation_seed_extracts_key_concepts_use_context_and_source_excerpts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures maker checker workflows, stop conditions, and verifier evidence.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for maker checker workflows and verifier evidence in autonomous coding loops.",
            )
            body = "\n".join(
                [
                    "Maker checker workflows keep autonomous coding loops grounded in independent verification.",
                    "Stop condition design prevents a loop from continuing after evidence becomes weak.",
                    "Verifier evidence should be attached to every handoff so the next meditation pass can trust the source.",
                    "A timer and rollback plan make the loop operational for production engineering teams.",
                ]
                * 12
            )
            write_note(vault / "Inbox" / "Loop Control.md", "Loop Control", "reference", body)

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        seed = report["distillation_seed"]["Inbox/Loop Control.md"]
        self.assertEqual("ready", seed["status"])
        self.assertEqual("Resources/Loop Engineering/Loop Control.md", seed["target"])
        self.assertEqual(["Areas/Loop Engineering.md"], seed["ownership"])
        self.assertIn("maker checker", seed["key_concepts"])
        self.assertIn("stop condition", seed["key_concepts"])
        self.assertEqual("Resources/Loop Engineering", seed["use_context"]["topic_dir"])
        self.assertIn("Areas/Loop Engineering.md", seed["use_context"]["ownership"])
        self.assertGreaterEqual(len(seed["evidence_excerpts"]), 3)
        self.assertTrue(any("Stop condition design" in item["text"] for item in seed["evidence_excerpts"]))
        self.assertIn("## 提炼种子", markdown)
        self.assertIn("maker checker", markdown)

    def test_distillation_seed_blocks_when_source_understanding_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Loop Screenshot.png").write_bytes(b"fake png bytes")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                (vault / "Inbox" / "Loop Screenshot.md").write_text(
                    "Filename: Loop Screenshot.png\nFormat: PNG\nSize: 1024x768\n",
                    encoding="utf-8",
                )
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        seed = report["distillation_seed"]["Inbox/Loop Screenshot.png"]
        self.assertEqual("blocked", seed["status"])
        self.assertIn("source understanding required", seed["blocked_by"])
        self.assertEqual([], seed["evidence_excerpts"])

    def test_distillation_seed_prioritizes_understanding_hint_concepts_and_skips_image_only_excerpts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures maker checker workflows, stop conditions, graders, and failing tests.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for loop engineering practices.",
            )
            body = """Maker checker workflow and stop condition design make grader evidence reliable.
Failing test gates keep the loop honest before the next action.
![Image](https://example.com/diagram.png)
"""
            write_note(vault / "Inbox" / "Loop Designer.md", "Loop Designer", "reference", body)

            report = ingest.make_report(vault, convert=False)

        seed = report["distillation_seed"]["Inbox/Loop Designer.md"]
        self.assertEqual("ready", seed["status"])
        self.assertIn("maker checker", seed["key_concepts"])
        self.assertIn("stop condition", seed["key_concepts"])
        self.assertTrue(seed["evidence_excerpts"])
        self.assertFalse(any(item["text"].startswith("![Image]") for item in seed["evidence_excerpts"]))

    def test_ownership_update_plan_uses_target_stem_backlink_for_existing_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "Loop Engineering notes about durable Claude Code feedback loops.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        plan = report["ownership_update_plan"]["Inbox/Loop Notes.md"]
        self.assertEqual("ready", plan["status"])
        self.assertEqual("Resources/Loop Engineering/Loop Notes.md", plan["target"])
        self.assertEqual("Loop Notes", plan["wikilink"])
        self.assertEqual("update_existing", plan["updates"][0]["action"])
        self.assertEqual("Areas/Loop Engineering.md", plan["updates"][0]["path"])
        self.assertIn("[[Loop Notes]]", plan["updates"][0]["snippet"])
        self.assertNotIn("Inbox/", plan["updates"][0]["snippet"])
        self.assertIn("## 承接更新计划", markdown)
        self.assertIn("[[Loop Notes]]", markdown)

    def test_ownership_update_plan_describes_create_area_action_when_owner_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing and GPU serving.",
            )
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Serverless inference routing and GPU serving notes.",
            )

            report = ingest.make_report(vault, convert=False)

        plan = report["ownership_update_plan"]["Inbox/Routing Pattern.md"]
        self.assertEqual("ready", plan["status"])
        self.assertEqual("Routing Pattern", plan["wikilink"])
        self.assertEqual("create_area", plan["updates"][0]["action"])
        self.assertEqual("Areas/LLM Inference.md", plan["updates"][0]["path"])
        self.assertIn("[[Routing Pattern]]", plan["updates"][0]["snippet"])
        self.assertIn("定位", plan["updates"][0]["template"])
        self.assertEqual([], plan["blocked_by"])
        self.assertNotIn("Inbox/", plan["updates"][0]["snippet"])

    def test_frontmatter_patch_plan_quotes_special_values_and_omits_resource_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            inbox = vault / "Inbox"
            inbox.mkdir(parents=True)
            (inbox / "Loop Skill.md").write_text(
                """---
title: "Loop Engineering: The Skill"
source_url: "https://example.com/articles/loop?ref=agent"
---

# Loop Engineering: The Skill

Loop Engineering captures durable Claude Code feedback loops.
""",
                encoding="utf-8",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        plan = report["frontmatter_patch_plan"]["Inbox/Loop Skill.md"]
        self.assertEqual("ready", plan["status"])
        yaml = plan["yaml"]
        self.assertTrue(yaml.startswith("---\n"))
        self.assertIn('title: "Loop Engineering: The Skill"', yaml)
        self.assertIn("type: reference", yaml)
        self.assertNotIn("status: resource", yaml)
        self.assertIn('source_url: "https://example.com/articles/loop?ref=agent"', yaml)
        self.assertIn("source_fingerprint: sha256:", yaml)
        self.assertIn("## 元数据写入计划", markdown)
        self.assertIn('title: "Loop Engineering: The Skill"', markdown)

    def test_frontmatter_patch_plan_includes_source_file_for_converted_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(vault / "Inbox" / "Export.md", "Export", "reference", "Converted Loop Engineering source.")
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        plan = report["frontmatter_patch_plan"]["Inbox/Export.csv"]
        self.assertEqual("ready", plan["status"])
        self.assertIn('source_file: "source/Export.csv"', plan["yaml"])
        self.assertIn("source_fingerprint: sha256:", plan["yaml"])

    def test_meditate_handoff_is_ready_when_first_pass_encoding_has_target_owner_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures grader evidence and feedback loop practice.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Grader Evidence.md",
                "Grader Evidence",
                "reference",
                "Grader evidence keeps loop engineering runs verifiable.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for loop engineering and grader evidence practice.",
            )
            write_note(
                vault / "Inbox" / "Loop Notes.md",
                "Loop Notes",
                "reference",
                "Loop Engineering notes citing Grader Evidence for feedback loop practice.",
            )

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        handoff = report["meditate_handoff"]["Inbox/Loop Notes.md"]
        self.assertEqual("ready", handoff["status"])
        self.assertEqual("Resources/Loop Engineering/Loop Notes.md", handoff["target"])
        self.assertEqual(["Areas/Loop Engineering.md"], handoff["ownership"])
        check_names = [check["name"] for check in handoff["checks"]]
        self.assertEqual(
            ["placement", "source_fingerprint", "source_understanding", "distillation", "source_file", "wikilinks"],
            check_names,
        )
        checks = {check["name"]: check for check in handoff["checks"]}
        self.assertEqual("pass", checks["placement"]["status"])
        self.assertEqual("pass", checks["source_understanding"]["status"])
        self.assertEqual("optional", checks["distillation"]["status"])
        self.assertEqual("not_required", checks["source_file"]["status"])
        self.assertEqual("stem_safe", checks["wikilinks"]["status"])
        self.assertEqual(["Grader Evidence"], checks["wikilinks"]["wikilinks"])
        self.assertEqual([], handoff["blocked_by"])
        self.assertIn("## meditate 交接清单", markdown)
        self.assertIn("ready → `Resources/Loop Engineering/Loop Notes.md`", markdown)

    def test_meditate_handoff_blocks_when_ownership_action_is_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing and GPU serving.",
            )
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Serverless inference routing and GPU serving notes.",
            )

            report = ingest.make_report(vault, convert=False)

        handoff = report["meditate_handoff"]["Inbox/Routing Pattern.md"]
        self.assertEqual("ready", handoff["status"])
        self.assertEqual(["Areas/LLM Inference.md"], handoff["ownership"])
        self.assertEqual([], handoff["blocked_by"])
        self.assertEqual([], handoff["next_actions"])

    def test_meditate_handoff_surfaces_converted_source_file_and_distillation_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(
                    vault / "Inbox" / "Export.md",
                    "Export",
                    "reference",
                    "Converted Loop Engineering source about durable Claude Code feedback loops.",
                )
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        handoff = report["meditate_handoff"]["Inbox/Export.csv"]
        source_file_check = next(check for check in handoff["checks"] if check["name"] == "source_file")
        distillation_check = next(check for check in handoff["checks"] if check["name"] == "distillation")
        self.assertEqual("ready", handoff["status"])
        self.assertEqual("required", source_file_check["status"])
        self.assertEqual("source/Export.csv", source_file_check["expected"])
        self.assertEqual("required", distillation_check["status"])

    def test_organization_plan_lists_first_pass_operations_for_ready_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Resources" / "Loop Engineering" / "Loop Engineering Clearly Explained.md",
                "Loop Engineering Clearly Explained",
                "reference",
                "Loop Engineering Clearly Explained is a reference about feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            long_body = " ".join("Loop Engineering Clearly Explained feedback loop evidence" for _ in range(180))
            write_note(vault / "Inbox" / "Loop Notes.md", "Loop Notes", "reference", long_body)

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        plan = report["organization_plan"]["Inbox/Loop Notes.md"]
        self.assertEqual("ready", plan["status"])
        self.assertEqual(
            {"from": "Inbox/Loop Notes.md", "to": "Resources/Loop Engineering/Loop Notes.md"},
            plan["markdown_move"],
        )
        self.assertEqual([], plan["source_moves"])
        self.assertEqual(["Areas/Loop Engineering.md"], plan["ownership_updates"])
        self.assertTrue(plan["distillation"]["required"])
        self.assertIn("Loop Engineering Clearly Explained", plan["wikilinks"])
        self.assertEqual("Resources/Loop Engineering", plan["resource_index"]["topic_dir"])
        self.assertIn('generate_resource_index.py --dir "Resources/Loop Engineering"', plan["resource_index"]["command"])
        self.assertIn("Resources/Loop Engineering/Loop Notes.md", plan["commit_scope"])
        self.assertIn("Areas/Loop Engineering.md", plan["commit_scope"])
        self.assertIn("## 首次归位执行计划", markdown)

    def test_organization_plan_includes_source_move_for_converted_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(
                    vault / "Inbox" / "Export.md",
                    "Export",
                    "reference",
                    "Converted Loop Engineering source about durable Claude Code feedback loops.",
                )
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        plan = report["organization_plan"]["Inbox/Export.csv"]
        self.assertEqual("ready", plan["status"])
        self.assertEqual(
            {"from": "Inbox/Export.md", "to": "Resources/Loop Engineering/Export.md"},
            plan["markdown_move"],
        )
        self.assertEqual(
            [{"from": "Inbox/Export.csv", "to": "Resources/Loop Engineering/source/Export.csv"}],
            plan["source_moves"],
        )
        self.assertIn("Resources/Loop Engineering/source/Export.csv", plan["commit_scope"])

    def test_organization_plan_for_blocked_candidate_lists_blockers_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing and GPU serving.",
            )
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Serverless inference routing and GPU serving notes.",
            )

            report = ingest.make_report(vault, convert=False)

        plan = report["organization_plan"]["Inbox/Routing Pattern.md"]
        self.assertEqual("ready", plan["status"])
        self.assertEqual([], plan["source_moves"])
        self.assertEqual(
            {"from": "Inbox/Routing Pattern.md", "to": "Resources/LLM Inference/Routing Pattern.md"},
            plan["markdown_move"],
        )
        self.assertEqual(["Areas/LLM Inference.md"], plan["ownership_updates"])
        self.assertIn("Areas/LLM Inference.md", plan["commit_scope"])

    def test_content_patch_plan_drafts_marker_distillation_and_safe_links_for_ready_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
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
            body = "\n".join(
                [
                    "Maker checker workflows keep autonomous coding loops grounded in independent verification.",
                    "Stop condition design prevents a loop from continuing after evidence becomes weak.",
                    "Verifier evidence should be attached to every handoff so meditate can trust the source.",
                ]
                * 20
            )
            write_note(vault / "Inbox" / "Loop Notes.md", "Loop Notes", "reference", body)

            report = ingest.make_report(vault, convert=False)
            markdown = ingest.markdown_report(report)

        plan = report["content_patch_plan"]["Inbox/Loop Notes.md"]
        self.assertEqual("ready", plan["status"])
        self.assertEqual("Resources/Loop Engineering/Loop Notes.md", plan["target"])
        self.assertIsNone(plan["visible_source_line"])
        body_markdown = plan["body_markdown"]
        self.assertTrue(body_markdown.startswith("> 整理自 Inbox，<YYYY-MM-DD>\n"))
        self.assertIn("## 提炼", body_markdown)
        self.assertIn("一句话判断：", body_markdown)
        self.assertIn("关键点（基于原文摘录）：", body_markdown)
        self.assertIn("Maker checker", body_markdown)
        self.assertNotIn("当前重点围绕", body_markdown)
        self.assertNotIn("\n- checker workflow\n", body_markdown)
        self.assertIn("Areas/Loop Engineering.md", body_markdown)
        self.assertIn("[[Loop Engineering Clearly Explained]]", body_markdown)
        self.assertIn("## 原文 / 摘录", body_markdown)
        self.assertNotIn("[[Inbox/", body_markdown)
        self.assertNotIn("[[Loop Engineering: Clearly Explained]]", body_markdown)
        self.assertIn("## 正文写入计划", markdown)

    def test_content_patch_plan_includes_visible_source_link_for_converted_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "Loop Engineering" / "README.md",
                "Loop Engineering",
                "index",
                "Loop Engineering captures durable Claude Code feedback loops.",
            )
            write_note(
                vault / "Areas" / "Loop Engineering.md",
                "Loop Engineering",
                "area",
                "Ownership for durable Claude Code feedback loops.",
            )
            (vault / "Inbox").mkdir(parents=True, exist_ok=True)
            (vault / "Inbox" / "Export.csv").write_text("metric,value\nloops,3\n", encoding="utf-8")

            def fake_conversion(_vault: Path, _path: Path) -> tuple[bool, str | None]:
                write_note(
                    vault / "Inbox" / "Export.md",
                    "Export",
                    "reference",
                    "Converted Loop Engineering source about durable Claude Code feedback loops.",
                )
                return True, None

            with patch.object(ingest, "run_conversion", side_effect=fake_conversion):
                report = ingest.make_report(vault, convert=True)

        plan = report["content_patch_plan"]["Inbox/Export.csv"]
        self.assertEqual("ready", plan["status"])
        self.assertEqual("原始文件：[[source/Export.csv]]", plan["visible_source_line"])
        self.assertIn("> 整理自 Inbox，<YYYY-MM-DD>", plan["body_markdown"])
        self.assertIn("原始文件：[[source/Export.csv]]", plan["body_markdown"])
        self.assertIn("## 提炼", plan["body_markdown"])

    def test_content_patch_plan_for_blocked_candidate_has_no_body_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            write_note(
                vault / "Resources" / "LLM Inference" / "README.md",
                "LLM Inference",
                "index",
                "Serverless inference routing and GPU serving.",
            )
            write_note(
                vault / "Inbox" / "Routing Pattern.md",
                "Routing Pattern",
                "reference",
                "Serverless inference routing and GPU serving notes.",
            )

            report = ingest.make_report(vault, convert=False)

        plan = report["content_patch_plan"]["Inbox/Routing Pattern.md"]
        self.assertEqual("ready", plan["status"])
        self.assertIn("由 `Areas/LLM Inference.md` 承接", plan["body_markdown"])
        self.assertEqual([], plan["blocked_by"])


if __name__ == "__main__":
    unittest.main()
