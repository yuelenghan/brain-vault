#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cadence_guard.py"


def load_module():
    if not MODULE_PATH.exists():
        raise AssertionError("cadence_guard.py is missing")
    spec = importlib.util.spec_from_file_location("meditate_cadence_guard_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def head_commit(vault: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=vault, text=True).strip()


def write_readme(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: "{title}"
type: index
---

# {title}
""",
        encoding="utf-8",
    )


def write_note(path: Path, title: str, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: "{title}"
type: reference
---

# {title}

{body}
""",
        encoding="utf-8",
    )


class CadenceGuardTest(unittest.TestCase):
    def test_weekly_prompt_lists_explicit_candidate_targets(self) -> None:
        module = load_module()
        prompt = module.weekly_prompt_from_report(
            {
                "synthesis_candidates": [{"readme": "Resources/AI Agents/README.md"}],
                "restatement_candidates": [{"path": "Resources/AI Agents/Agent Loops.md"}],
            }
        )

        self.assertIn("Resources/AI Agents/README.md", prompt)
        self.assertIn("Resources/AI Agents/Agent Loops.md", prompt)
        self.assertIn("Do not write synthesis or restatement to any other files", prompt)

    def test_audit_weekly_semantic_changes_flags_unauthorized_synthesis_targets(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_readme(vault / "Resources" / "AI Agents" / "README.md", "AI Agents")
            write_readme(vault / "Resources" / "LLM Inference" / "README.md", "LLM Inference")
            git_commit(vault, "initial", "2026-07-06T10:00:00")

            llm_readme = vault / "Resources" / "LLM Inference" / "README.md"
            llm_readme.write_text(
                llm_readme.read_text(encoding="utf-8")
                + "\n## 综合理解\n\n<!-- BEGIN: synthesis -->\n\nUnauthorized synthesis.\n\n<!-- END: synthesis -->\n",
                encoding="utf-8",
            )
            git_commit(vault, "weekly unauthorized", "2026-07-06T10:10:00")

            summary = module.audit_weekly_semantic_changes(
                vault,
                {
                    "synthesis_candidates": [{"readme": "Resources/AI Agents/README.md"}],
                    "restatement_candidates": [],
                },
                head_commit(vault),
            )

        self.assertEqual(["Resources/LLM Inference/README.md"], summary["synthesis_paths"])
        self.assertEqual(["Resources/LLM Inference/README.md"], summary["unauthorized_synthesis_paths"])
        self.assertEqual([], summary["restatement_paths"])
        self.assertEqual([], summary["unauthorized_restatement_paths"])

    def test_audit_weekly_semantic_changes_counts_authorized_synthesis_and_restatement(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            write_readme(vault / "Resources" / "AI Agents" / "README.md", "AI Agents")
            write_note(
                vault / "Resources" / "AI Agents" / "Agent Loops.md",
                "Agent Loops",
                "## 提炼\n\nInitial summary.\n",
            )
            git_commit(vault, "initial", "2026-07-06T10:00:00")

            ai_readme = vault / "Resources" / "AI Agents" / "README.md"
            ai_readme.write_text(
                ai_readme.read_text(encoding="utf-8")
                + "\n## 综合理解\n\n<!-- BEGIN: synthesis -->\n\nAuthorized synthesis.\n\n<!-- END: synthesis -->\n",
                encoding="utf-8",
            )
            note = vault / "Resources" / "AI Agents" / "Agent Loops.md"
            note.write_text(
                note.read_text(encoding="utf-8") + "\n### 再巩固 2026-07-06\n\nAuthorized reconsolidation.\n",
                encoding="utf-8",
            )
            git_commit(vault, "weekly authorized", "2026-07-06T10:10:00")

            summary = module.audit_weekly_semantic_changes(
                vault,
                {
                    "synthesis_candidates": [{"readme": "Resources/AI Agents/README.md"}],
                    "restatement_candidates": [{"path": "Resources/AI Agents/Agent Loops.md"}],
                },
                head_commit(vault),
            )

        self.assertEqual(1, summary["synthesis_count"])
        self.assertEqual(1, summary["restatement_count"])
        self.assertEqual([], summary["unauthorized_synthesis_paths"])
        self.assertEqual([], summary["unauthorized_restatement_paths"])

    def test_audit_weekly_restructuring_rejects_invalid_or_partial_marker_output(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            anchor = vault / "Projects" / "Example.md"
            write_note(anchor, "Example", "# Example\n\nHand-written context.\n")
            write_note(vault / "Projects" / "Example" / "Design Baseline.md", "Design Baseline")
            write_note(vault / "Projects" / "Example" / "Design Revision.md", "Design Revision")
            write_note(vault / "Projects" / "Other.md", "Other", "# Other")
            git_commit(vault, "initial", "2026-07-06T10:00:00")

            anchor.write_text(
                anchor.read_text(encoding="utf-8")
                + """
Manual change outside the generated marker.

<!-- BEGIN: knowledge-restructuring cluster=kr-a1b2c3d4 -->
- 覆盖材料：2 篇；来源集：sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff；重构日期：2026-07-06

### 当前有效理解
- K-01：This statement cites a missing source. 证据：[[Missing Source]]。
<!-- END: knowledge-restructuring -->
""",
                encoding="utf-8",
            )
            git_commit(vault, "invalid weekly restructuring", "2026-07-06T10:10:00")

            summary = module.audit_weekly_semantic_changes(
                vault,
                {
                    "synthesis_candidates": [],
                    "restatement_candidates": [],
                    "restructuring_candidates": [
                        {
                            "cluster_id": "kr-a1b2c3d4",
                            "anchor_path": "Projects/Example.md",
                            "source_set_digest": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
                            "action": "refresh_anchor",
                            "confidence": "high",
                        },
                        {
                            "cluster_id": "kr-b1c2d3e4",
                            "anchor_path": "Projects/Other.md",
                            "source_set_digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
                            "action": "refresh_anchor",
                            "confidence": "high",
                        },
                    ],
                },
                head_commit(vault),
            )

        self.assertEqual(["Projects/Example.md"], summary["restructuring_paths"])
        self.assertEqual([], summary["unauthorized_restructuring_paths"])
        self.assertEqual(["Projects/Example.md"], summary["marker_boundary_violations"])
        self.assertEqual(["Projects/Example.md"], summary["digest_mismatches"])
        self.assertEqual(["Projects/Example.md"], summary["invalid_source_links"])
        self.assertEqual(["kr-b1c2d3e4"], summary["missing_restructuring_clusters"])

    def test_audit_weekly_staged_restructuring_accepts_every_valid_target(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            anchor = vault / "Projects" / "Example.md"
            write_note(anchor, "Example", "# Example")
            write_note(vault / "Projects" / "Example" / "Design Baseline.md", "Design Baseline")
            write_note(vault / "Projects" / "Example" / "Design Revision.md", "Design Revision")
            git_commit(vault, "initial", "2026-07-06T10:00:00")

            digest = "sha256:3333333333333333333333333333333333333333333333333333333333333333"
            anchor.write_text(
                anchor.read_text(encoding="utf-8")
                + f"""

<!-- BEGIN: knowledge-restructuring cluster=kr-c1d2e3f4 -->
- 覆盖材料：2 篇；来源集：{digest}；重构日期：2026-07-06

### 当前有效理解
- K-01：The revised design preserves the source history. 证据：[[Design Baseline]]。
<!-- END: knowledge-restructuring -->
""",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "Projects/Example.md"], cwd=vault, check=True)
            summary = module.audit_weekly_staged_changes(
                vault,
                {
                    "synthesis_candidates": [],
                    "restatement_candidates": [],
                    "restructuring_candidates": [
                        {
                            "cluster_id": "kr-c1d2e3f4",
                            "anchor_path": "Projects/Example.md",
                            "source_set_digest": digest,
                            "action": "refresh_anchor",
                            "confidence": "high",
                        }
                    ],
                },
            )

        self.assertEqual(["Projects/Example.md"], summary["restructuring_paths"])
        self.assertEqual([], summary["unauthorized_restructuring_paths"])
        self.assertEqual([], summary["marker_boundary_violations"])
        self.assertEqual([], summary["digest_mismatches"])
        self.assertEqual([], summary["invalid_source_links"])
        self.assertEqual([], summary["invalid_knowledge_entries"])
        self.assertEqual([], summary["missing_restructuring_clusters"])

    def test_update_latest_log_semantic_fields_patches_only_latest_entry(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp).resolve() / ".claude" / "meditate.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                """## 2026-07-05 auto
- 范围：Resources
- 语义综合：9
- 再巩固：8
commit: 1111111111111111111111111111111111111111

## 2026-07-06 auto
- 范围：Resources
commit: 无
""",
                encoding="utf-8",
            )

            module.update_latest_log_semantic_fields(log_path, synthesis_count=2, restatement_count=1, restructuring_count=3)

            text = log_path.read_text(encoding="utf-8")

        self.assertIn("- 语义综合：9", text)
        self.assertIn("- 再巩固：8", text)
        self.assertIn("## 2026-07-06 auto\n- 范围：Resources\n- 语义综合：2\n- 再巩固：1\n- 知识重构：3\ncommit: 无", text)


if __name__ == "__main__":
    unittest.main()
