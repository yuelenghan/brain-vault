---
name: meditate
description: 冥想 brain vault 中已整理的 Projects/Areas/Resources/Archive 笔记：重新理解已有知识、重连双链、处理历史重复、修复失效链接、发现缺失承接、沉淀主题索引并输出可审计报告。用户提到 meditate、冥想 vault、知识冥想、去重、deduplicate、补链、修复链接、知识库体检、发现重复笔记、改善 Obsidian 双链，或要求已整理笔记的 nightly/weekly 睡眠周期时，应优先使用本 skill；不要用于整理 Inbox，新资料入库仍使用 ingest。
---

# Meditate for Codex CLI

这是 brain-vault 的 Codex CLI 入口。工作目录必须是 vault 根目录。

## 执行规则

1. 先读取 `.claude/skills/meditate/SKILL.md`；它是已整理笔记优化流程的 canonical 规则源。
2. 严格按该文件执行。若本文件与 `.claude/skills/meditate/SKILL.md` 冲突，以 `.claude/skills/meditate/SKILL.md` 为准。
3. 若 `.claude/skills/meditate/SKILL.md` 不存在，停止并说明当前仓库缺少 brain-vault Claude Code skill，不能安全优化。
4. 如果用户明确要求 `nightly` 或 `weekly` cadence，必须从 vault 根目录走 `.claude/meditate.sh nightly` 或 `.claude/meditate.sh weekly`，再按 canonical `.claude` skill 做验证与结果汇报，而不是在本入口里手拼底层 `scan` / `apply-safe` 流程。
5. 只优化 `Projects/`、`Areas/`、`Resources/`、`Archive/`，不要整理 `Inbox/`。
6. 优先使用固定报告路径：`/tmp/meditate.json` 和 `/tmp/meditate.md`。不要给优化脚本传其他 report 路径或 `--vault`。
7. 自动去重只信任规范化 URL、非空重新计算源内容指纹或同一原文附件证据；优先使用并严格校验 `source_fingerprint`，兼容旧 `content_fingerprint` 但不把它当作严格 stale/invalid 信号，也不要基于 frontmatter 中不匹配的旧指纹或空内容指纹自动移动或编辑文件。
8. 每次运行都通过本地 deterministic knowledge model 重新理解当前 vault：基于最新文件名、title、alias、topic 目录、README alias、Area/Project 承接画像、现有链接、正文显式提及和自动抽取的概念画像重新生成补链 / 承接 / 结构候选，并过滤 generated section、arXiv/preprint/conference/annual-meeting 等出版元信息噪声、低信号 function-word 短语，以及表格粘连 / ordinal 后缀异常 token；`apply-safe` 自动写入高置信显式链接、同 topic 成对独特概念 peer link、Area / Project 概念画像回链、稳定无承接 topic 的新 Area，并在 topic 增长或变化后刷新这些 Area 的画像 / ownership-index marker / 回链 / 相关承接，等价自动 Area 会归档重复承接并迁移链接，宽泛自动 Area 中形成稳定 title-leading / title-contained 子簇时会自动分化子 Area、写入父级 `## 子承接` 并补齐资料回链；同时更新 topic README 概念画像、把 Resource topic 之间稳定且成对或小簇独特的概念关联写入 reciprocal README `topic-relations` marker，并在双方已有 Area owner 时写入 reciprocal `## 相关承接`、等价 topic 合并、明确 topic re-home、高重合概念 re-home、整 topic 更名，以及宽泛 Resource topic 中稳定 title-leading / title-contained 子簇的 narrower topic split；结构迁移会保护入站路径型 wikilink，若引用旧路径的笔记已有未提交改动、位于当前 `--scope` 之外，或目标 filename stem 在 PARA 中不唯一，则只报告 protected / outside_scope / ambiguous_incoming_link，不会先移动造成不可安全修复的断链；否则会在结构迁移时把 scope 内旧路径 wikilink 修复为迁移后文件名 stem，并保留 anchor / alias；并报告未拆分 topic 的证据原因。`meditate` 不合并 `ingest`，Inbox intake / conversion 仍由 `ingest` 处理。
9. `apply-safe` 自检会复扫本次结构迁移旧路径相关的残留失效 wikilink；若仍有旧路径断链，`self_check` 必须为未通过。
