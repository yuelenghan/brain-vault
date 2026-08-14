#!/usr/bin/env python3
"""Check whether the vault still needs the minimal /setup-brain initialization."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


IDENTITY_SECTIONS = ("Who I am", "This year's goals", "Current projects")
TEMPLATE_PLACEHOLDER = "To be filled in."
SECTION_NOISE_LINES = {"---"}


@dataclass(frozen=True)
class SetupBrainStatus:
    needs_setup: bool
    reason: str


def normalize_section_body(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip() and line.strip() not in SECTION_NOISE_LINES]
    return "\n".join(cleaned).strip()


def section_bodies(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = normalize_section_body(body)
            current = line[3:].strip()
            body = []
            continue
        if current is not None:
            body.append(line)
    if current is not None:
        sections[current] = normalize_section_body(body)
    return sections


def setup_brain_status(vault: Path) -> SetupBrainStatus:
    claude_md = vault / "CLAUDE.md"
    if not claude_md.exists():
        return SetupBrainStatus(needs_setup=True, reason="missing_claude_md")
    sections = section_bodies(claude_md.read_text(encoding="utf-8"))
    placeholders = [
        heading
        for heading in IDENTITY_SECTIONS
        if sections.get(heading, "").strip() == TEMPLATE_PLACEHOLDER
    ]
    if len(placeholders) == len(IDENTITY_SECTIONS):
        return SetupBrainStatus(needs_setup=True, reason="identity_template")
    return SetupBrainStatus(needs_setup=False, reason="ready")


def setup_block_message(vault: Path, next_command: str) -> str | None:
    status = setup_brain_status(vault)
    if not status.needs_setup:
        return None
    if status.reason == "missing_claude_md":
        detail = "This vault is missing `CLAUDE.md`; minimal initialization is not complete."
    else:
        detail = (
            "This vault has not completed minimal initialization: the `Who I am`, "
            "`This year's goals`, and `Current projects` sections in `CLAUDE.md` still "
            "contain the template placeholder."
        )
    return f"{detail}\nPlease run `/setup-brain` first, then run `{next_command}`."


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check whether the vault still requires /setup-brain.")
    parser.add_argument("--vault", default=".")
    parser.add_argument("--require-setup", dest="next_command")
    args = parser.parse_args(argv)

    if not args.next_command:
        parser.error("--require-setup is required")

    vault = Path(args.vault).resolve()
    if not vault.exists() or not vault.is_dir():
        print(f"brain-state: vault does not exist: {vault}", file=sys.stderr)
        return 2

    message = setup_block_message(vault, args.next_command)
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
