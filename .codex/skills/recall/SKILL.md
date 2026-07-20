---
name: recall
description: 回忆 brain vault 中已整理的知识：基于标题、别名、概念画像和 wikilink 扩散检索相关笔记，并把提取结果写回 `.claude/recall.log`。用户提到回忆、recall、问 brain、brain 里有什么、检索笔记、我之前记过什么、查一下笔记时，以及任何需要参考 vault 已有笔记回答的知识性、方案性、项目相关问题（即使用户没有明说检索），都必须先走本 skill，不得用裸 grep/read 代替。
---

# Recall for Codex CLI

这是 brain-vault 的 Codex CLI recall 入口。工作目录必须是 vault 根目录。

1. 先读取 `.claude/skills/recall/SKILL.md`；它是 canonical 规则源。
2. 严格按 `.claude/skills/recall/SKILL.md` 执行；若冲突，以 `.claude` 为准。
3. 若 `.claude/skills/recall/SKILL.md` 不存在，停止并说明缺少 brain-vault recall canonical skill。
4. 正常 query 模式省略 `--json` 和 `--markdown`；canonical 脚本会写入当前操作系统 temp 目录下的 `<tempdir>/recall.json` 和 `<tempdir>/recall.md`。只有需要显式传路径时，才先用 `python3 -c 'import tempfile; print(tempfile.gettempdir())'` 计算 `<tempdir>`；不要先尝试 `/tmp`。
5. 运行 `.claude/skills/recall/scripts/recall.py`，不要切到 `.codex/skills/recall/scripts/...`。
6. 除非使用计算出的固定路径后 recall 仍失败，否则不要把 tempdir 探测或路径纠正过程提示给用户。
