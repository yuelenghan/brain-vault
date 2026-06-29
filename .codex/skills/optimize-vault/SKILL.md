---
name: optimize-vault
description: 优化 brain vault 中已整理的 Projects/Areas/Resources/Archive 笔记，处理历史重复、补充新出现的双链、修复失效链接、发现缺失承接、沉淀主题索引并输出可审计优化报告。用户提到 optimize vault、优化 vault、去重、deduplicate-vault、补链、链接优化、整理后再优化、知识库体检、发现重复笔记或改善 Obsidian 双链时，应优先使用本 skill；不要用于整理 Inbox，新资料入库仍使用 organize-inbox。
---

# Optimize Vault for Codex

这是 brain-vault 的 Codex CLI 入口。工作目录必须是 vault 根目录。

## 执行规则

1. 先读取 `.claude/skills/optimize-vault/SKILL.md`；它是已整理笔记优化流程的 canonical 规则源。
2. 严格按该文件执行。若本文件与 `.claude/skills/optimize-vault/SKILL.md` 冲突，以 `.claude/skills/optimize-vault/SKILL.md` 为准。
3. 若 `.claude/skills/optimize-vault/SKILL.md` 不存在，停止并说明当前仓库缺少 brain-vault Claude Code skill，不能安全优化。
4. 只优化 `Projects/`、`Areas/`、`Resources/`、`Archive/`，不要整理 `Inbox/`。
5. 优先使用固定报告路径：`/tmp/optimize-vault.json` 和 `/tmp/optimize-vault.md`。不要给优化脚本传其他 report 路径或 `--vault`。
6. 自动去重只信任重新计算的正文指纹或规范化 URL；不要基于 frontmatter 中不匹配的旧 `content_fingerprint` 自动移动或编辑文件。
