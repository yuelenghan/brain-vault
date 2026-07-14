#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[3] / "brain_state.py"
SPEC = importlib.util.spec_from_file_location("brain_state_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
brain_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = brain_state
SPEC.loader.exec_module(brain_state)


TEMPLATE_CLAUDE_MD = """# Brain Vault — 身份层

## 我是谁

待补充。

## 今年的目标

待补充。

## 协作偏好

- 有根据、不瞎编。

## 当前项目

待补充。
"""


READY_CLAUDE_MD = """# Brain Vault — 身份层

## 我是谁

我是一名工程师，当前重点是维护 brain-vault。

## 今年的目标

- 建好自己的知识库。

## 协作偏好

- 有根据、不瞎编。

## 当前项目

- brain-vault：完善整理与回忆流程。
"""


class BrainStateTest(unittest.TestCase):
    def test_missing_claude_md_requires_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()

            status = brain_state.setup_brain_status(vault)

        self.assertTrue(status.needs_setup)
        self.assertEqual("missing_claude_md", status.reason)

    def test_template_identity_sections_require_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / "CLAUDE.md").write_text(TEMPLATE_CLAUDE_MD, encoding="utf-8")

            status = brain_state.setup_brain_status(vault)

        self.assertTrue(status.needs_setup)
        self.assertEqual("identity_template", status.reason)

    def test_non_template_identity_sections_are_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / "CLAUDE.md").write_text(READY_CLAUDE_MD, encoding="utf-8")

            status = brain_state.setup_brain_status(vault)

        self.assertFalse(status.needs_setup)
        self.assertEqual("ready", status.reason)

    def test_cli_prints_setup_hint_for_template_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            (vault / "CLAUDE.md").write_text(TEMPLATE_CLAUDE_MD, encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--vault",
                    str(vault),
                    "--require-setup",
                    "/ingest",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(2, completed.returncode)
        self.assertIn("请先运行 `/setup-brain`，再执行 `/ingest`。", completed.stderr)

    def test_template_sections_ignore_frontmatter_fences(self) -> None:
        text = """---
title: test
---

## 我是谁

待补充。

## 今年的目标

待补充。

## 当前项目

待补充。
"""

        sections = brain_state.section_bodies(text)

        self.assertEqual("待补充。", sections["我是谁"])
        self.assertEqual("待补充。", sections["今年的目标"])
        self.assertEqual("待补充。", sections["当前项目"])


if __name__ == "__main__":
    unittest.main()
