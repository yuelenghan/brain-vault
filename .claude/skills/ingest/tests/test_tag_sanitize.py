#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest.py"
SPEC = importlib.util.spec_from_file_location("ingest_tag_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ingest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ingest
SPEC.loader.exec_module(ingest)


class TagSanitizeTest(unittest.TestCase):
    def test_dot_replaced(self):
        # 原始触发问题：proj-2.0 在 Obsidian 显示红色+删除线
        self.assertEqual(ingest.sanitize_tag("proj-2.0"), "proj-2-0")

    def test_leading_hash_stripped(self):
        self.assertEqual(ingest.sanitize_tag("#tag"), "tag")

    def test_invalid_chars_replaced(self):
        self.assertEqual(ingest.sanitize_tag("a:b c"), "a-b-c")
        self.assertEqual(ingest.sanitize_tag("foo[bar]"), "foo-bar")
        self.assertEqual(ingest.sanitize_tag("a@b!c"), "a-b-c")

    def test_consecutive_dashes_collapsed(self):
        self.assertEqual(ingest.sanitize_tag("x..y"), "x-y")
        self.assertEqual(ingest.sanitize_tag("a . b"), "a-b")

    def test_legal_chars_preserved(self):
        for t in ["proj", "plugin", "分发/安装", "a-b_c", "v2", "proj/2-0"]:
            self.assertEqual(ingest.sanitize_tag(t), t)

    def test_empty_dropped(self):
        self.assertEqual(ingest.sanitize_tag("   ..."), "")
        self.assertEqual(ingest.parse_tag_list(["   ", "", "#"]), [])

    def test_dedup_and_clean(self):
        self.assertEqual(
            ingest.parse_tag_list(["proj-2.0", "proj-2.0", "a.b", "a-b", " c "]),
            ["proj-2-0", "a-b", "c"],
        )

    def test_pure_digit_left_as_is(self):
        # 纯数字 tag 是 Obsidian 另一条规则（XA=/^#\d+$/），sanitize 不处理
        self.assertEqual(ingest.sanitize_tag("2024"), "2024")


if __name__ == "__main__":
    unittest.main()
