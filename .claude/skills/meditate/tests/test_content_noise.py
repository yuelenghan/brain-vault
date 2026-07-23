#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "optimize_vault.py"
SPEC = importlib.util.spec_from_file_location("optimize_vault_noise_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
optimize_vault = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = optimize_vault
SPEC.loader.exec_module(optimize_vault)


class DetectContentNoiseTest(unittest.TestCase):
    def test_detect_zero_width_form_feed_nul_and_stray_control(self) -> None:
        noise = optimize_vault.detect_content_noise("hello​world\f\n\x00\x01end")
        self.assertEqual(1, noise["zero_width"])
        self.assertEqual(1, noise["form_feed"])
        self.assertEqual(1, noise["nul"])
        self.assertEqual(1, noise["stray_control"])  # \x01 only (NUL counted separately)

    def test_detect_watermark_block_threshold(self) -> None:
        short = "\n".join(list("arXiv") + ["", "real content line here"])
        self.assertEqual(0, optimize_vault.detect_content_noise(short)["watermark_lines"])
        long = "\n".join(list("arXiv:2210") + ["", "real content line here"])
        self.assertGreaterEqual(optimize_vault.detect_content_noise(long)["watermark_lines"], 8)


class CleanContentNoiseTextTest(unittest.TestCase):
    def test_clean_removes_zero_width_preserves_form_feed_and_content(self) -> None:
        cleaned, counts = optimize_vault.clean_content_noise_text("方案​编排\f\n正文")
        self.assertEqual("方案编排\f\n正文", cleaned)
        self.assertEqual(1, counts["zero_width"])

    def test_clean_removes_stray_control_preserves_newline_tab_formfeed(self) -> None:
        cleaned, counts = optimize_vault.clean_content_noise_text("line1\x07\x1b\nline2\ttab\f")
        self.assertEqual("line1\nline2\ttab\f", cleaned)
        self.assertEqual(2, counts["stray_control"])
        self.assertIn("\n", cleaned)
        self.assertIn("\t", cleaned)
        self.assertIn("\f", cleaned)

    def test_clean_removes_leading_watermark_block(self) -> None:
        text = "\n".join(list("arXiv:2210") + ["", "Published at ICLR 2023", "", "body"])
        cleaned, counts = optimize_vault.clean_content_noise_text(text)
        self.assertTrue(cleaned.startswith("Published at ICLR 2023"))
        self.assertGreaterEqual(counts["watermark_lines"], 8)


class ContentNoiseFindingsTest(unittest.TestCase):
    def _note(self, vault: Path, name: str, body: str) -> optimize_vault.Note:
        (vault / "Resources").mkdir(parents=True, exist_ok=True)
        p = vault / "Resources" / name
        p.write_text(f"---\ntitle: {name}\n---\n\n{body}", encoding="utf-8")
        return optimize_vault.read_note(vault, p, set())

    def test_nul_is_encoding_damage_and_zero_width_is_cleanable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            clean = self._note(vault, "Clean.md", "body\f\n")
            zw = self._note(vault, "ZW.md", "body​here\f\n")
            nul = self._note(vault, "NUL.md", "body\x00\x00corrupt\n")
            findings = optimize_vault.content_noise_findings([clean, zw, nul])
            by_path = {f["path"]: f for f in findings}
            self.assertNotIn("Resources/Clean.md", by_path)
            self.assertEqual("cleanable", by_path["Resources/ZW.md"]["kind"])
            self.assertEqual(1, by_path["Resources/ZW.md"]["counts"]["zero_width"])
            self.assertEqual(1, by_path["Resources/ZW.md"]["form_feed_preserved"])
            self.assertEqual("encoding_damage", by_path["Resources/NUL.md"]["kind"])
            self.assertEqual(2, by_path["Resources/NUL.md"]["nul"])


class ApplyContentNoiseTest(unittest.TestCase):
    def _note(self, vault: Path, name: str, body: str) -> optimize_vault.Note:
        (vault / "Resources").mkdir(parents=True, exist_ok=True)
        p = vault / "Resources" / name
        p.write_text(f"---\ntitle: {name}\n---\n\n{body}", encoding="utf-8")
        return optimize_vault.read_note(vault, p, set())

    def test_apply_cleans_zero_width_preserves_form_feed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            note = self._note(vault, "ZW.md", "方案​编排\f\n正文")
            report = {
                "content_noise": optimize_vault.content_noise_findings([note]),
                "protected_paths": [],
                "applied": {"content_noise": []},
                "skipped_uncertain": [],
            }
            optimize_vault.apply_content_noise(vault, report)
            text = (vault / "Resources" / "ZW.md").read_text(encoding="utf-8")
            self.assertNotIn("​", text)
            self.assertIn("\f", text)  # form-feed preserved
            self.assertEqual(1, len(report["applied"]["content_noise"]))

    def test_apply_skips_protected_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            note = self._note(vault, "ZW.md", "方案​编排\n")
            report = {
                "content_noise": optimize_vault.content_noise_findings([note]),
                "protected_paths": ["Resources/ZW.md"],
                "applied": {"content_noise": []},
                "skipped_uncertain": [],
            }
            optimize_vault.apply_content_noise(vault, report)
            self.assertEqual(0, len(report["applied"]["content_noise"]))
            self.assertEqual(1, len(report["skipped_uncertain"]))
            # protected note body unchanged
            self.assertIn("​", (vault / "Resources" / "ZW.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
