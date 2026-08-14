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


TEMPLATE_CLAUDE_MD = """# Brain Vault — Identity layer

## Who I am

To be filled in.

## This year's goals

To be filled in.

## Collaboration preferences

- Evidence over invention.

## Current projects

To be filled in.
"""


READY_CLAUDE_MD = """# Brain Vault — Identity layer

## Who I am

I am an engineer focused on maintaining brain-vault.

## This year's goals

- Build my knowledge base.

## Collaboration preferences

- Evidence over invention.

## Current projects

- brain-vault: improve the organize and recall flows.
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
        self.assertIn("Please run `/setup-brain` first, then run `/ingest`.", completed.stderr)

    def test_template_sections_ignore_frontmatter_fences(self) -> None:
        text = """---
title: test
---

## Who I am

To be filled in.

## This year's goals

To be filled in.

## Current projects

To be filled in.
"""

        sections = brain_state.section_bodies(text)

        self.assertEqual("To be filled in.", sections["Who I am"])
        self.assertEqual("To be filled in.", sections["This year's goals"])
        self.assertEqual("To be filled in.", sections["Current projects"])


if __name__ == "__main__":
    unittest.main()
