---
name: setup-brain
description: 初始化 brain-vault：采访用户身份和目标，生成 CLAUDE.md，检查 PARA 目录、git 状态、本机转换工具（markitdown、Pillow、whisper、ffmpeg）和 AI CLI（copilot、codex），并按用户确认安装缺失工具。
---

# Setup Brain for Copilot CLI

这是 brain-vault 的 GitHub Copilot CLI plugin skill。工作目录必须是 vault 根目录。

## 执行规则

1. 先读取 `.claude/skills/setup-brain/SKILL.md`；它是本仓库初始化流程的 canonical 规则源。
2. 严格按该文件执行。若本文件与 `.claude/skills/setup-brain/SKILL.md` 冲突，以 `.claude/skills/setup-brain/SKILL.md` 为准。
3. 若 `.claude/skills/setup-brain/SKILL.md` 不存在，停止并说明当前仓库缺少 brain-vault Claude Code skill，不能安全初始化。
4. 不要删除用户文件；执行安装命令、覆盖已有配置、提交 git 或设置定时任务前必须先确认。
5. 对 Copilot CLI / Codex CLI 支持，只在当前项目内更新说明或 skill 文件；不要修改用户全局 `~/.codex` / `~/.copilot` 配置，除非用户明确要求。
