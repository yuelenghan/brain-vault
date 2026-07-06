---
name: recall
description: 回忆 brain vault 中已整理的知识：基于标题、别名、概念画像和 wikilink 扩散检索相关笔记，并把提取结果写回 `.claude/recall.log`。用户提到回忆、recall、问 brain、brain 里有什么、检索笔记、我之前记过什么、查一下笔记时，应优先使用本 skill。
---

# Recall for Copilot CLI

这是 brain-vault 的 GitHub Copilot CLI plugin recall 入口。工作目录必须是 vault 根目录。

1. 先读取 `.claude/skills/recall/SKILL.md`；它是 canonical 规则源。
2. 严格按 `.claude/skills/recall/SKILL.md` 执行；若冲突，以 `.claude` 为准。
3. 若 `.claude/skills/recall/SKILL.md` 不存在，停止并说明缺少 brain-vault recall canonical skill。
4. 只使用当前操作系统 temp 目录下的固定报告路径：`<tempdir>/recall.json` 和 `<tempdir>/recall.md`。
5. 运行 `.claude/skills/recall/scripts/recall.py`，不要切到 `.copilot/skills/recall/scripts/...`。
