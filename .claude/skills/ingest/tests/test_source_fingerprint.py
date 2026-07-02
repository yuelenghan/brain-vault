#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest.py"
SPEC = importlib.util.spec_from_file_location("ingest_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ingest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ingest
SPEC.loader.exec_module(ingest)


class SourceFingerprintTest(unittest.TestCase):
    def test_normalize_url_drops_documented_tracking_parameters(self) -> None:
        self.assertEqual(
            "https://example.com/articles/loop?id=42",
            ingest.normalize_url("https://EXAMPLE.com/articles/loop?utm_source=x&spm=a2c&id=42#section"),
        )

    def test_existing_note_fingerprint_ignores_added_distillation_and_links(self) -> None:
        source_text = """# Durable Memory

The durable memory layer keeps reusable decisions outside one-off chats.
It works because markdown files can be searched, linked, and versioned.
"""
        fingerprint = ingest.fingerprint(source_text)

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "Durable Memory.md").write_text(
                f"""---
title: Durable Memory
type: reference
content_fingerprint: "{fingerprint}"
---

# Durable Memory

## 提炼

- This summary was added after the original source fingerprint was generated.
- See also [[AI Native 转型]].

## 原文 / 摘录

The durable memory layer keeps reusable decisions outside one-off chats.
It works because markdown files can be searched, linked, and versioned.

## 关联

- [[brain-vault]]
""",
                encoding="utf-8",
            )

            notes, invalid = ingest.existing_notes(vault)

        self.assertEqual([], invalid)
        self.assertEqual(1, len(notes))
        self.assertEqual(fingerprint, notes[0]["fingerprint"])

    def test_existing_note_accepts_preferred_source_fingerprint_field(self) -> None:
        source_text = """# Source Field

Preferred source_fingerprint should be treated as the source identity.
"""
        fingerprint = ingest.fingerprint(source_text)

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "Source Field.md").write_text(
                f"""---
title: Source Field
type: reference
source_fingerprint: "{fingerprint}"
---

# Source Field

## 提炼

- Curated summary.

## 原文

Preferred source_fingerprint should be treated as the source identity.
""",
                encoding="utf-8",
            )

            notes, invalid = ingest.existing_notes(vault)

        self.assertEqual([], invalid)
        self.assertEqual(fingerprint, notes[0]["fingerprint"])

    def test_legacy_content_fingerprint_mismatch_does_not_block_duplicate_indexing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "Legacy Fingerprint.md").write_text(
                """---
title: Legacy Fingerprint
type: reference
content_fingerprint: "sha256:legacy-before-source-fingerprint-semantics"
---

# Legacy Fingerprint

## 提炼

- Curated summary.

## 原文 / 摘录

Legacy content fingerprints are compatibility metadata, not strict source validators.
""",
                encoding="utf-8",
            )

            notes, invalid = ingest.existing_notes(vault)

        self.assertEqual([], invalid)
        self.assertIsNotNone(notes[0]["fingerprint"])

    def test_preferred_source_fingerprint_mismatch_is_reported_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "Strict Fingerprint.md").write_text(
                """---
title: Strict Fingerprint
type: reference
source_fingerprint: "sha256:wrong-source-fingerprint"
---

# Strict Fingerprint

Original source text.
""",
                encoding="utf-8",
            )

            notes, invalid = ingest.existing_notes(vault)

        self.assertEqual(1, len(invalid))
        self.assertEqual("source_fingerprint", invalid[0]["field"])
        self.assertIsNone(notes[0]["fingerprint"])


if __name__ == "__main__":
    unittest.main()
