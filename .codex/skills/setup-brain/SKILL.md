---
name: setup-brain
description: 初始化 brain-vault：按 canonical setup-brain 流程初始化共享身份层（以 `CLAUDE.md` 为准），并检查 PARA 目录、本机整理工具（markitdown、Pillow、whisper、ffmpeg）以及现有 AI CLI 入口。
---

# Setup Brain for Codex CLI

这是 brain-vault 的 Codex CLI 入口。工作目录必须是 vault 根目录。

## 执行规则

1. 先读取 `.claude/skills/setup-brain/SKILL.md`；它是本仓库初始化流程的 canonical 规则源。
2. 严格按该文件执行。若本文件与 `.claude/skills/setup-brain/SKILL.md` 冲突，以 `.claude/skills/setup-brain/SKILL.md` 为准。
3. 若 `.claude/skills/setup-brain/SKILL.md` 不存在，停止并说明当前仓库缺少 brain-vault Claude Code skill，不能安全初始化。
4. 不要删除用户文件；执行安装命令、覆盖已有配置、提交 git 或设置定时任务前必须先确认。
5. 对 Copilot CLI / Codex CLI 支持，只在当前项目内更新说明或 skill 文件；不要修改用户全局 `~/.codex` / `~/.copilot` 配置，除非用户明确要求。
