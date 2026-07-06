#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


VAULT_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_SKILL_ROOTS = (
    VAULT_ROOT / ".claude" / "skills",
    VAULT_ROOT / ".agents" / "skills",
    VAULT_ROOT / ".codex" / "skills",
    VAULT_ROOT / ".copilot" / "skills",
)
IGNORED_GENERATED_PATHS = (
    ".obsidian/app.json",
    ".obsidian/graph.json",
    ".obsidian/plugins/quickadd/data.json",
    ".obsidian/workspace.json",
    ".claude/cache/output.txt",
    ".claude/skills/example-workspace/output.txt",
    ".agents/cache/output.txt",
    ".agents/skills/example-workspace/output.txt",
    ".codex/cache/output.txt",
    ".codex/skills/example-workspace/output.txt",
    ".copilot/cache/output.txt",
    ".copilot/skills/example-workspace/output.txt",
    ".skill-workspaces/agents/meditate-workspace/output.txt",
)
WHITELISTED_RUNTIME_PATHS = (
    ".claude/ingest.sh",
    ".claude/meditate.sh",
    ".claude/bin/safe-markitdown",
    ".claude/bin/meditate-scan",
    ".claude/bin/meditate-apply-safe",
    ".claude/bin/meditate-finalize-log",
    ".claude/skills/meditate/SKILL.md",
    ".claude/skills/meditate/scripts/knowledge_model.py",
    ".claude/skills/meditate/tests/test_knowledge_model.py",
    ".claude/skills/recall/SKILL.md",
    ".claude/skills/recall/scripts/recall.py",
    ".agents/skills/meditate/SKILL.md",
    ".agents/skills/recall/SKILL.md",
    ".codex/skills/meditate/SKILL.md",
    ".codex/skills/recall/SKILL.md",
    ".copilot/.github/plugin/plugin.json",
    ".copilot/skills/meditate/SKILL.md",
    ".copilot/skills/recall/SKILL.md",
)


class RuntimeEntryLayoutTest(unittest.TestCase):
    def test_experiment_workspaces_stay_out_of_runtime_skill_roots(self) -> None:
        offenders: list[str] = []
        for root in RUNTIME_SKILL_ROOTS:
            if not root.exists():
                continue
            offenders.extend(
                path.relative_to(VAULT_ROOT).as_posix()
                for path in sorted(root.iterdir())
                if path.is_dir() and path.name.endswith("-workspace")
            )

        self.assertEqual([], offenders)

    def test_generated_tool_outputs_are_gitignored(self) -> None:
        for ignored_path in IGNORED_GENERATED_PATHS:
            with self.subTest(path=ignored_path):
                result = subprocess.run(
                    ["git", "check-ignore", "--quiet", "--no-index", ignored_path],
                    cwd=VAULT_ROOT,
                    check=False,
                )

                self.assertEqual(0, result.returncode)

    def test_runtime_allowlist_paths_are_not_gitignored(self) -> None:
        for allowed_path in WHITELISTED_RUNTIME_PATHS:
            with self.subTest(path=allowed_path):
                result = subprocess.run(
                    ["git", "check-ignore", "--quiet", "--no-index", allowed_path],
                    cwd=VAULT_ROOT,
                    check=False,
                )

                self.assertNotEqual(0, result.returncode)

    def test_canonical_meditate_skill_uses_claude_script_paths(self) -> None:
        text = (VAULT_ROOT / ".claude" / "skills" / "meditate" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn(".claude/skills/meditate/scripts/optimize_vault.py", text)
        self.assertIn(".claude/skills/meditate/scripts/generate_resource_index.py", text)
        self.assertIn(".claude/skills/meditate/scripts/fix_frontmatter.py", text)
        self.assertNotIn(".agents/skills/meditate/scripts/", text)

    def test_canonical_meditate_skill_routes_cadence_requests_through_headless_entry_script(self) -> None:
        text = (VAULT_ROOT / ".claude" / "skills" / "meditate" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn(".claude/meditate.sh nightly", text)
        self.assertIn(".claude/meditate.sh weekly", text)
        self.assertIn("When the user explicitly asks for `nightly` or `weekly` cadence", text)

    def test_canonical_recall_skill_uses_claude_script_paths(self) -> None:
        text = (VAULT_ROOT / ".claude" / "skills" / "recall" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn(".claude/skills/recall/scripts/recall.py", text)
        self.assertIn(".claude/skills/meditate/scripts/knowledge_model.py", text)
        self.assertNotIn(".agents/skills/recall/scripts/", text)

    def test_agents_meditate_entrypoint_stays_thin(self) -> None:
        agents_root = VAULT_ROOT / ".agents" / "skills" / "meditate"
        unexpected = [
            child.name
            for child in sorted(agents_root.iterdir())
            if child.is_dir() and child.name in {"scripts", "tests", "evals"}
        ]
        text = (agents_root / "SKILL.md").read_text(encoding="utf-8")

        self.assertEqual([], unexpected)
        self.assertIn(".claude/skills/meditate/SKILL.md", text)
        self.assertIn(".claude/meditate.sh nightly", text)
        self.assertIn(".claude/meditate.sh weekly", text)
        self.assertNotIn(".agents/skills/meditate/scripts/", text)

    def test_agents_recall_entrypoint_stays_thin(self) -> None:
        agents_root = VAULT_ROOT / ".agents" / "skills" / "recall"
        unexpected = [
            child.name
            for child in sorted(agents_root.iterdir())
            if child.is_dir() and child.name in {"scripts", "tests", "evals"}
        ]
        text = (agents_root / "SKILL.md").read_text(encoding="utf-8")

        self.assertEqual([], unexpected)
        self.assertIn(".claude/skills/recall/SKILL.md", text)
        self.assertNotIn(".agents/skills/recall/scripts/", text)

    def test_cli_wrappers_delegate_meditate_to_canonical_claude_skill(self) -> None:
        for wrapper in (
            VAULT_ROOT / ".codex" / "skills" / "meditate" / "SKILL.md",
            VAULT_ROOT / ".copilot" / "skills" / "meditate" / "SKILL.md",
        ):
            with self.subTest(path=wrapper.relative_to(VAULT_ROOT).as_posix()):
                text = wrapper.read_text(encoding="utf-8")
                self.assertIn(".claude/skills/meditate/SKILL.md", text)
                self.assertIn(".claude/meditate.sh nightly", text)
                self.assertIn(".claude/meditate.sh weekly", text)
                self.assertIn("不要整理 `Inbox/`", text)
                self.assertIn("ingest", text)

    def test_cli_wrappers_delegate_recall_to_canonical_claude_skill(self) -> None:
        for wrapper in (
            VAULT_ROOT / ".codex" / "skills" / "recall" / "SKILL.md",
            VAULT_ROOT / ".copilot" / "skills" / "recall" / "SKILL.md",
        ):
            with self.subTest(path=wrapper.relative_to(VAULT_ROOT).as_posix()):
                text = wrapper.read_text(encoding="utf-8")
                self.assertIn(".claude/skills/recall/SKILL.md", text)
                self.assertIn("recall", text.lower())
                self.assertIn("<tempdir>/recall.json", text)

    def test_copilot_plugin_manifest_lists_recall_skill(self) -> None:
        text = (VAULT_ROOT / ".copilot" / ".github" / "plugin" / "plugin.json").read_text(encoding="utf-8")

        self.assertIn("../../skills/recall", text)

    def test_headless_meditate_entry_script_is_valid_zsh(self) -> None:
        result = subprocess.run(
            ["zsh", "-n", str(VAULT_ROOT / ".claude" / "meditate.sh")],
            cwd=VAULT_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(0, result.returncode, msg=result.stderr)

    def test_weekly_prompt_does_not_use_backticks_for_literal_text(self) -> None:
        text = (VAULT_ROOT / ".claude" / "meditate.sh").read_text(encoding="utf-8")

        self.assertNotIn("`/tmp/meditate.json`", text)
        self.assertNotIn("`### 再巩固 <YYYY-MM-DD>`", text)

    def test_weekly_runtime_uses_cadence_guard_for_candidate_binding_and_audit(self) -> None:
        text = (VAULT_ROOT / ".claude" / "meditate.sh").read_text(encoding="utf-8")

        self.assertIn(".claude/skills/meditate/scripts/cadence_guard.py", text)
        self.assertIn("weekly-prompt", text)
        self.assertIn("audit-weekly-commit", text)

    def test_meditate_baseline_checks_ignore_obsidian_graph_runtime_state(self) -> None:
        text = (VAULT_ROOT / ".claude" / "meditate.sh").read_text(encoding="utf-8")

        self.assertEqual(6, text.count("':!.obsidian/graph.json'"))


if __name__ == "__main__":
    unittest.main()
