#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "optimize_vault.py"
SPEC = importlib.util.spec_from_file_location("optimize_vault_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
optimize_vault = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = optimize_vault
SPEC.loader.exec_module(optimize_vault)


class FrontmatterValidationTest(unittest.TestCase):
    def test_straight_quoted_scalar_with_colon_space_is_valid(self) -> None:
        text = """---
title: "Graph Harness: A Scheduler-Theoretic Framework"
source_url: "https://example.com/path"
content_fingerprint: "sha256:abc123"
---

# Body
"""

        self.assertIsNone(optimize_vault.find_invalid_frontmatter(text))

    def test_curly_quoted_scalar_is_invalid(self) -> None:
        text = """---
title: “Graph Harness: A Scheduler-Theoretic Framework”
---

# Body
"""

        result = optimize_vault.find_invalid_frontmatter(text)
        self.assertIsNotNone(result)
        self.assertIn("smart/curly quotes", result)

    def test_unquoted_colon_space_is_invalid(self) -> None:
        text = """---
title: Graph Harness: A Scheduler-Theoretic Framework
---

# Body
"""

        result = optimize_vault.find_invalid_frontmatter(text)
        self.assertIsNotNone(result)
        self.assertIn('unquoted value with ": "', result)


if __name__ == "__main__":
    unittest.main()
