#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_resource_index.py"
SPEC = importlib.util.spec_from_file_location("generate_resource_index_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def write_note(
    path: Path,
    title: str,
    note_type: str,
    body: str = "",
    created: str = "2026-07-01",
    salience: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    salience_line = f"salience: {salience}\n" if salience else ""
    path.write_text(
        f"""---
title: "{title}"
type: {note_type}
created: {created}
{salience_line}---

# {title}

{body}
""",
        encoding="utf-8",
    )


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


def append_recall_entry(
    vault: Path,
    when: dt.datetime,
    query: str,
    activated: list[tuple[str, str]],
    result: str,
) -> None:
    log_path = vault / ".claude" / "recall.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"## {when:%Y-%m-%d %H:%M} recall", f"- 查询：{query}"]
    for path, strength in activated:
        lines.append(f"- 激活：{path} ({strength})")
    lines.append(f"- 结果：{result}")
    lines.append("- 缺口：无")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


class GenerateResourceIndexTest(unittest.TestCase):
    def test_generator_matches_memory_cycle_ordering_and_marks_stale_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            git_init(vault)
            topic = vault / "Resources" / "PKM"
            topic.mkdir(parents=True)
            (topic / "README.md").write_text(
                """---
title: "PKM"
type: index
---

# PKM

## 资料索引

<!-- BEGIN: resource-index -->

> old

<!-- END: resource-index -->
""",
                encoding="utf-8",
            )
            write_note(
                topic / "Hot Note.md",
                "Hot Note",
                "reference",
                "Retriever memory and grader loops.",
                created="2025-01-01",
                salience="high",
            )
            write_note(
                topic / "Cold Note.md",
                "Cold Note",
                "reference",
                "Dormant reference body.",
                created="2026-07-01",
            )
            git_commit(vault, "initial", "2025-05-01T12:00:00")

            today = dt.datetime.now().replace(second=0, microsecond=0)
            append_recall_entry(
                vault,
                today - dt.timedelta(days=2),
                "grader loops",
                [("Resources/PKM/Hot Note.md", "direct")],
                "answered",
            )

            old_cwd = Path.cwd()
            try:
                os.chdir(vault)
                result = generator.process_dir(topic, check_only=False)
            finally:
                os.chdir(old_cwd)

            self.assertTrue(result[0].startswith("已更新:"))
            self.assertEqual(2, result[1])
            readme_text = (topic / "README.md").read_text(encoding="utf-8")

        hot_pos = readme_text.index("[[Hot Note]]")
        cold_pos = readme_text.index("[[Cold Note]]")
        self.assertLess(hot_pos, cold_pos)
        self.assertIn("[[Cold Note]]（休眠）", readme_text)
