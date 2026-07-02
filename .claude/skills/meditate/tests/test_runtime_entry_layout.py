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
    ".claude/bin/safe-markitdown",
    ".claude/skills/meditate/SKILL.md",
    ".agents/skills/meditate/SKILL.md",
    ".codex/skills/meditate/SKILL.md",
    ".copilot/.github/plugin/plugin.json",
    ".copilot/skills/meditate/SKILL.md",
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


if __name__ == "__main__":
    unittest.main()
