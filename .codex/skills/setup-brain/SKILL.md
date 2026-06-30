---
name: setup-brain
description: Initialize brain-vault — interview the user for identity and goals, generate CLAUDE.md, check PARA directories, git status, local conversion tools (markitdown, Pillow, whisper, ffmpeg) and AI CLIs (copilot, codex), and install missing tools on user confirmation.
---

# Setup Brain for Codex

This is the brain-vault Codex CLI entry point. The working directory must be the vault root.

## Execution rules

1. First read `.claude/skills/setup-brain/SKILL.md`; it is the canonical rule source for this repo's initialization flow.
2. Execute strictly per that file. If this file conflicts with `.claude/skills/setup-brain/SKILL.md`, `.claude/skills/setup-brain/SKILL.md` wins.
3. If `.claude/skills/setup-brain/SKILL.md` does not exist, stop and state the repo is missing the brain-vault Claude Code skill and cannot safely initialize.
4. Do not delete user files; confirm before running install commands, overwriting existing config, committing to git, or setting up scheduled tasks.
5. For Copilot CLI / Codex CLI support, only update descriptions or skill files within the current project; do not modify the user's global `~/.codex` / `~/.copilot` config unless explicitly asked.
