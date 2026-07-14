---
name: setup-brain
description: Initialize the brain-vault shared identity layer and optional organize capabilities for Codex sessions by following the canonical `.claude/skills/setup-brain/SKILL.md`. Triggers: setup brain, initialize brain-vault, 初始化 brain-vault, 补全身份层, 安装工具.
---

# Setup Brain for Codex sessions

This is the Codex-session entry point for brain-vault setup. The working directory must be the vault root.

## Execution rules

1. First read `.claude/skills/setup-brain/SKILL.md`; it is the canonical workflow for initializing the shared identity layer and optional organize capabilities.
2. Follow that canonical file strictly. If this file conflicts with `.claude/skills/setup-brain/SKILL.md`, the `.claude` file wins.
3. If `.claude/skills/setup-brain/SKILL.md` does not exist, stop and say the vault is missing the canonical brain-vault setup skill, so setup cannot be run safely.
4. Do not delete user files; confirm before running install commands, overwriting existing config, committing to git, or scheduling tasks.
5. Treat `CLAUDE.md` as the vault's shared identity layer. When Codex needs the user's long-term identity, goals, current projects, or collaboration preferences, read `## 我是谁`, `## 今年的目标`, `## 协作偏好`, and `## 当前项目` there instead of maintaining a duplicate copy in `AGENTS.md`.
6. For Codex CLI / Copilot CLI support, only update project-local instruction or skill files; do not modify global `~/.codex` / `~/.copilot` configuration unless the user explicitly asks.
