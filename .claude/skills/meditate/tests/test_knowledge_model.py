#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "knowledge_model.py"
SPEC = importlib.util.spec_from_file_location("knowledge_model_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
knowledge_model = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = knowledge_model
SPEC.loader.exec_module(knowledge_model)


class KnowledgeModelTest(unittest.TestCase):
    def test_stable_topic_concepts_require_multiple_notes(self) -> None:
        notes = [
            knowledge_model.ModelNote(
                path="Resources/Agent Memory/Episodic Recall.md",
                title="Episodic Recall",
                aliases=[],
                body="durable memory reflection loop episodic recall",
                kind="reference",
            ),
            knowledge_model.ModelNote(
                path="Resources/Agent Memory/Reflection Loop.md",
                title="Reflection Loop",
                aliases=[],
                body="durable memory reflection loop retrieval practice",
                kind="reference",
            ),
            knowledge_model.ModelNote(
                path="Resources/Agent Memory/Noise.md",
                title="Noise",
                aliases=[],
                body="one off unrelated phrase",
                kind="reference",
            ),
        ]

        concepts = knowledge_model.stable_topic_concepts(notes, "Agent Memory")

        self.assertIn("durable memory", concepts)
        self.assertIn("reflection loop", concepts)
        self.assertNotIn("retrieval practice", concepts)

    def test_top_concepts_ignore_publication_metadata_noise(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            {
                "arxiv preprint": 12,
                "preprint arxiv": 11,
                "international conference": 10,
                "computational linguistic": 9,
                "annual meeting": 8,
                "neural information": 7,
                "information processing": 7,
                "processing system": 7,
                "annual conference": 7,
                "interactive judge": 5,
                "reward signal": 4,
                "browser state": 3,
                "state machine": 3,
                "program synthesis": 3,
                "attention head": 3,
            }
        )

        self.assertEqual(
            ["interactive judge", "reward signal", "attention head", "browser state", "program synthesis", "state machine"],
            concepts,
        )

    def test_concept_normalization_keeps_non_plural_es_words_readable(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            knowledge_model.concept_counts_for_text(
                """
                An Obsidian system becomes useful after repeated review.
                An Obsidian system becomes useful when durable memory is reviewed.
                Loop searches return config and loop searches tune retrieval.
                Reflection phases define the loop and reflection phases structure review.
                Durable memory stays useful after repeated review.
                """
            ),
            limit=20,
        )

        self.assertIn("durable memory", concepts)
        self.assertIn("loop search", concepts)
        self.assertIn("reflection phase", concepts)
        self.assertNotIn("become useful", concepts)
        self.assertNotIn("becom useful", concepts)
        self.assertNotIn("loop searche", concepts)
        self.assertNotIn("reflection phas", concepts)

    def test_concept_extraction_ignores_low_signal_function_word_phrases(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            knowledge_model.concept_counts_for_text(
                """
                You now know what agents are, what they can do, and where they fit.
                Update this file when your strategy changes for the current task.
                Durable memory and episodic recall stay central to agent learning.
                Durable memory and episodic recall help agents reuse knowledge.
                """
            ),
            limit=20,
        )

        self.assertIn("durable memory", concepts)
        self.assertIn("episodic recall", concepts)
        self.assertNotIn("what they", concepts)
        self.assertNotIn("file when", concepts)
        self.assertNotIn("current task", concepts)

    def test_top_concepts_ignore_profile_quality_noise(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            {
                "first week": 14,
                "three days": 13,
                "actually think": 12,
                "best ways": 11,
                "first time": 10,
                "become context": 9,
                "return config": 8,
                "better input": 7,
                "three phase": 6,
                "independent rater": 5,
                "replication package": 4,
                "create four": 4,
                "rough idea": 4,
                "week four": 4,
                "different place": 4,
                "emoosryoa s-mem": 4,
                "vegetarian restaurant": 4,
                "simplemem memoryo": 4,
                "embedding ragmem0": 4,
                "second brain": 3,
                "folder structure": 3,
                "loop engineering": 3,
                "resource gateway": 3,
            },
            limit=12,
        )

        self.assertEqual(
            ["folder structure", "loop engineering", "resource gateway", "second brain"],
            concepts,
        )

    def test_concept_extraction_ignores_generated_area_boilerplate(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            knowledge_model.concept_counts_for_text(
                """
                自动承接 `Resources/Loop Engineering` 中已经形成稳定知识簇的资料，
                作为长期复用和重新理解的 ownership note。

                ## 适用范围

                - 主题来源：`Resources/Loop Engineering`
                - 核心概念：loop engineering、human judgment、prompt engineering

                Loop engineering relies on human judgment and prompt engineering.
                Loop engineering keeps human judgment inside the feedback loop.
                """
            )
        )

        self.assertIn("loop engineering", concepts)
        self.assertIn("human judgment", concepts)
        self.assertNotIn("中已经形成稳定知识簇的资料", concepts)
        self.assertNotIn("主题来源", concepts)

    def test_concept_extraction_ignores_low_signal_verb_and_pronoun_phrases(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            knowledge_model.concept_counts_for_text(
                """
                The system is always ready when a note gets used by someone else.
                The course says a vault gets used only when someone else can understand it.
                Give each operation a tool, push back on weak answers, and do not lose track.
                Flag anything risky when prompt Claude workflows look underspecified.
                Turn Claude into a reviewer and flag the real risk after read auth completes.
                Agentic semantic layers are useful, but driven agentssemantic is a glued token.
                Durable memory and episodic recall are the actual reusable concepts.
                Durable memory and episodic recall drive the knowledge graph.
                """
            )
        )

        self.assertIn("durable memory", concepts)
        self.assertIn("episodic recall", concepts)
        self.assertNotIn("always ready", concepts)
        self.assertNotIn("gets used", concepts)
        self.assertNotIn("someone else", concepts)
        self.assertNotIn("give each", concepts)
        self.assertNotIn("push back", concepts)
        self.assertNotIn("lose track", concepts)
        self.assertNotIn("flag anything", concepts)
        self.assertNotIn("prompt claude", concepts)
        self.assertNotIn("turn claude", concepts)
        self.assertNotIn("real risk", concepts)
        self.assertNotIn("read auth", concepts)
        self.assertNotIn("driven agentssemantic", concepts)

    def test_concept_extraction_ignores_sentence_like_cjk_fragments(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            knowledge_model.concept_counts_for_text(
                """
                ## 当前判断

                白皮书提供了一个数据 Agent 落地框架。
                每个非 Markdown 专利文件都应先转换为 Markdown，再提炼关键技术点。
                新专利内容也要先判断是否扩展本 Area。
                长期持续积累数据语义层。

                数据语义层。可验证的结构化资产。
                云游戏多人场景下的屏幕分享。以及终端异常时的自动迁移机制。
                数据智能体需要同时满足三真三好。
                数据语义层的关键不是传统。
                本质是让数据资产更快转成 AI Ready Data。
                的数据语义层。还应该包括工具调用。
                一个典型的闭源到开源能力蒸馏流程。一个代码模型负责生成答案。
                实际工作中，Semantic Fabric 的价值在于降低历史数据口径盘点成本。
                不只是生成文本，权限治理和 Agent 编排也很重要。
                这不是一个适合普通创业者或个人开发者的路线。
                而是把业务语言、指标口径、数据查询变成结构化资产。
                """
            ),
            limit=20,
        )

        self.assertIn("数据语义层", concepts)
        self.assertIn("可验证的结构化资产", concepts)
        self.assertIn("云游戏多人场景下的屏幕分享", concepts)
        self.assertIn("终端异常时的自动迁移机制", concepts)
        self.assertIn("工具调用", concepts)
        self.assertIn("闭源到开源能力蒸馏流程", concepts)
        self.assertIn("历史数据口径盘点成本", concepts)
        self.assertNotIn("当前判断", concepts)
        self.assertNotIn("提供了一个数据", concepts)
        self.assertNotIn("专利文件都应先转换为", concepts)
        self.assertNotIn("也要先判断是否扩展本", concepts)
        self.assertNotIn("长期持续积累数据语义层", concepts)
        self.assertNotIn("数据智能体需要同时满足", concepts)
        self.assertNotIn("数据语义层的关键不是传统", concepts)
        self.assertNotIn("本质是让数据资产更快转成", concepts)
        self.assertNotIn("的数据语义层", concepts)
        self.assertNotIn("还应该包括工具调用", concepts)
        self.assertNotIn("还应该包括", concepts)
        self.assertNotIn("一个典型的闭源到开源能力蒸馏流程", concepts)
        self.assertNotIn("一个代码模型负责生成答案", concepts)
        self.assertNotIn("实际工作中", concepts)
        self.assertNotIn("价值在于降低", concepts)
        self.assertNotIn("价值在于降低历史数据口径盘点成本", concepts)
        self.assertNotIn("不只是生成文本", concepts)
        self.assertNotIn("权限治理和", concepts)
        self.assertNotIn("不是一个适合普通创业者或个人开发者的路线", concepts)
        self.assertNotIn("这不是一个适合普通创业者或个人开发者的路线", concepts)
        self.assertNotIn("而是把业务语言", concepts)
        self.assertNotIn("数据查询变成结构化资产", concepts)
        self.assertNotIn("编排也很重要", concepts)

    def test_concept_extraction_ignores_malformed_ordinal_suffix_tokens(self) -> None:
        concepts = knowledge_model.top_concepts_from_counts(
            knowledge_model.concept_counts_for_text(
                """
                The chart reports cumulative proportion50th and cumulative proportion90th.
                The table glues negative reasonshighmediumlowconfidencepositiveneutralnegative78.
                Interactive judge and reward signal evaluation remain the real concept.
                Interactive judge and reward signal evaluation are repeated evidence.
                """
            )
        )

        self.assertIn("interactive judge", concepts)
        self.assertIn("reward signal", concepts)
        self.assertNotIn("cumulative proportion50th", concepts)
        self.assertNotIn("cumulative proportion90th", concepts)
        self.assertNotIn("negative reasonshighmediumlowconfidencepositiveneutralnegative78", concepts)

    def test_resource_topic_split_detects_title_contained_subcluster(self) -> None:
        notes = [
            knowledge_model.ModelNote(
                path="Resources/AI Agents/Building Durable Memory for Agents.md",
                title="Building Durable Memory for Agents",
                aliases=[],
                body="Durable memory uses episodic recall and reflection loops for agent behavior.",
                kind="reference",
            ),
            knowledge_model.ModelNote(
                path="Resources/AI Agents/Testing Durable Memory in Agents.md",
                title="Testing Durable Memory in Agents",
                aliases=[],
                body="Durable memory quality depends on episodic recall and reflection loops.",
                kind="reference",
            ),
            knowledge_model.ModelNote(
                path="Resources/AI Agents/Evaluating Durable Memory Loops.md",
                title="Evaluating Durable Memory Loops",
                aliases=[],
                body="Durable memory evaluation checks episodic recall and reflection loops.",
                kind="reference",
            ),
            knowledge_model.ModelNote(
                path="Resources/AI Agents/Planner Runtime.md",
                title="Planner Runtime",
                aliases=[],
                body="Planner runtime coordinates tool calls and task state.",
                kind="reference",
            ),
            knowledge_model.ModelNote(
                path="Resources/AI Agents/Tool Harness.md",
                title="Tool Harness",
                aliases=[],
                body="Tool harness validates action results and command output.",
                kind="reference",
            ),
        ]

        decision = knowledge_model.resource_topic_split_decision(notes, "AI Agents")

        self.assertEqual("split_candidate", decision["status"])
        self.assertEqual("durable memory", decision["concept"])
        self.assertEqual(
            [
                "Resources/AI Agents/Building Durable Memory for Agents.md",
                "Resources/AI Agents/Evaluating Durable Memory Loops.md",
                "Resources/AI Agents/Testing Durable Memory in Agents.md",
            ],
            decision["note_paths"],
        )

    def test_topic_name_score_prefers_title_match_over_body_match(self) -> None:
        note = knowledge_model.ModelNote(
            path="Resources/Misc/Agent Memory Notes.md",
            title="Agent Memory Notes",
            aliases=[],
            body="This note mentions PKM in passing.",
            kind="reference",
        )
        profile = knowledge_model.TopicProfile(
            topic="Agent Memory",
            dir="Resources/Agent Memory",
            names=["Agent Memory"],
            material_count=3,
        )

        score, matched = knowledge_model.topic_match_score(note, profile)

        self.assertGreaterEqual(score, 4)
        self.assertEqual(["Agent Memory"], matched)

    def test_ownership_concept_match_uses_distinctive_owner_terms(self) -> None:
        note = knowledge_model.ModelNote(
            path="Resources/Agent Memory/Memory Systems.md",
            title="Memory Systems",
            aliases=[],
            body="durable memory episodic recall reflection loop",
            kind="reference",
        )
        owner = knowledge_model.OwnershipProfile(
            path="Areas/Agent Memory.md",
            title="Agent Memory",
            aliases=[],
            body="durable memory episodic recall reflection loop",
        )
        unrelated = knowledge_model.OwnershipProfile(
            path="Areas/PKM.md",
            title="PKM",
            aliases=[],
            body="personal knowledge management note linking retrieval",
        )
        profiles = {owner.path: owner, unrelated.path: unrelated}
        frequency = knowledge_model.ownership_concept_frequency(profiles)

        score, matched = knowledge_model.ownership_concept_match_score(note, owner, frequency)

        self.assertGreaterEqual(score, 3)
        self.assertIn("durable memory", matched)
        self.assertIn("episodic recall", matched)
        self.assertIn("reflection loop", matched)

    def test_equivalent_topic_map_handles_simple_plural_variant(self) -> None:
        profiles = {
            "AI Agent": knowledge_model.TopicProfile(
                topic="AI Agent",
                dir="Resources/AI Agent",
                names=["AI Agent"],
                material_count=2,
            ),
            "AI Agents": knowledge_model.TopicProfile(
                topic="AI Agents",
                dir="Resources/AI Agents",
                names=["AI Agents"],
                material_count=4,
                has_readme=True,
            ),
        }

        canonical = knowledge_model.equivalent_topic_canonical_map(profiles)

        self.assertEqual({"AI Agent": "AI Agents"}, canonical)

    def test_topic_relation_candidates_use_distinctive_shared_concepts(self) -> None:
        profiles = {
            "Agent Memory": knowledge_model.TopicProfile(
                topic="Agent Memory",
                dir="Resources/Agent Memory",
                material_count=3,
                concept_counts={
                    "episodic recall": 5,
                    "retrieval practice": 4,
                    "reflection loop": 4,
                    "generic term": 9,
                },
            ),
            "Learning Systems": knowledge_model.TopicProfile(
                topic="Learning Systems",
                dir="Resources/Learning Systems",
                material_count=3,
                concept_counts={
                    "episodic recall": 4,
                    "retrieval practice": 4,
                    "reflection loop": 3,
                    "generic term": 8,
                },
            ),
            "Prompt Engineering": knowledge_model.TopicProfile(
                topic="Prompt Engineering",
                dir="Resources/Prompt Engineering",
                material_count=3,
                concept_counts={
                    "generic term": 6,
                    "prompt pattern": 5,
                    "instruction design": 4,
                },
            ),
        }

        candidates = knowledge_model.topic_relation_candidates(profiles)

        self.assertEqual(1, len(candidates))
        self.assertEqual("Agent Memory", candidates[0]["source_topic"])
        self.assertEqual("Learning Systems", candidates[0]["target_topic"])
        self.assertEqual(
            ["episodic recall", "reflection loop", "retrieval practice"],
            candidates[0]["concepts"],
        )

    def test_topic_relation_candidates_learn_small_concept_clusters(self) -> None:
        profiles = {
            "Agent Memory": knowledge_model.TopicProfile(
                topic="Agent Memory",
                dir="Resources/Agent Memory",
                material_count=3,
                concept_counts={
                    "episodic recall": 5,
                    "retrieval practice": 4,
                    "reflection loop": 4,
                    "overbroad concept": 8,
                },
            ),
            "Learning Systems": knowledge_model.TopicProfile(
                topic="Learning Systems",
                dir="Resources/Learning Systems",
                material_count=3,
                concept_counts={
                    "episodic recall": 4,
                    "retrieval practice": 4,
                    "reflection loop": 3,
                    "overbroad concept": 8,
                },
            ),
            "Memory Evaluation": knowledge_model.TopicProfile(
                topic="Memory Evaluation",
                dir="Resources/Memory Evaluation",
                material_count=3,
                concept_counts={
                    "episodic recall": 4,
                    "retrieval practice": 3,
                    "reflection loop": 3,
                    "overbroad concept": 8,
                },
            ),
            "Prompt Engineering": knowledge_model.TopicProfile(
                topic="Prompt Engineering",
                dir="Resources/Prompt Engineering",
                material_count=3,
                concept_counts={
                    "overbroad concept": 6,
                    "prompt pattern": 5,
                    "instruction design": 4,
                },
            ),
        }

        candidates = knowledge_model.topic_relation_candidates(profiles)

        self.assertEqual(
            {
                ("Agent Memory", "Learning Systems"),
                ("Agent Memory", "Memory Evaluation"),
                ("Learning Systems", "Memory Evaluation"),
            },
            {(item["source_topic"], item["target_topic"]) for item in candidates},
        )
        for candidate in candidates:
            self.assertEqual(
                ["episodic recall", "reflection loop", "retrieval practice"],
                candidate["concepts"],
            )
            self.assertNotIn("overbroad concept", candidate["concepts"])

    def test_topic_relation_candidates_ignore_publication_metadata_concepts(self) -> None:
        profiles = {
            "AI Agents": knowledge_model.TopicProfile(
                topic="AI Agents",
                dir="Resources/AI Agents",
                material_count=3,
                concept_counts={
                    "arxiv preprint": 5,
                    "preprint arxiv": 4,
                    "language model": 4,
                    "attention head": 4,
                },
            ),
            "AI Engineering": knowledge_model.TopicProfile(
                topic="AI Engineering",
                dir="Resources/AI Engineering",
                material_count=3,
                concept_counts={
                    "arxiv preprint": 4,
                    "preprint arxiv": 4,
                    "language model": 3,
                    "reward signal": 4,
                },
            ),
        }

        candidates = knowledge_model.topic_relation_candidates(profiles)

        self.assertEqual([], candidates)


if __name__ == "__main__":
    unittest.main()
