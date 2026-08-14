# Ingest 维护者须知

> 本文件给「改整理逻辑 / 脚本的人」看，不随 skill 运行、不随每会话自动加载。
> 运行时硬约束在 `SKILL.md` 与 vault 根 `CLAUDE.md` / `AGENTS.md`，本文件只放设计 rationale 与维护流程。

## 整理逻辑源与三路径

当前 brain 的整理逻辑有多套 AI 工具入口：`.claude/skills/ingest/SKILL.md` 服务 Claude Code/headless 且作为 canonical 规则源，`.agents/skills/ingest/SKILL.md`、`.codex/skills/ingest/SKILL.md` 与 `.copilot/skills/ingest/SKILL.md` 都是薄入口并读取 `.claude` 规则。Claude 会话内手动、CronCreate 定时、`.claude/ingest.sh` 离线兜底都调 `.claude` 这份 skill；Codex 会话内由 `.agents` 入口触发后也必须转读 `.claude` canonical。修 skill、脚本或 `ingest.sh` 后，必须用临时 vault 跑 `VAULT=<临时目录> .claude/ingest.sh` 验证，覆盖"实际移动 + 提交 + 日志"完整路径，不要只看 Inbox 是否为空。

`.claude/` 是当前 vault 的 Claude Code/headless 运行副本，版本化 `ingest.sh`、`skills/`、`bin/`，其余（`ingest.log`、`scheduled_tasks.json` 等）被 `.gitignore` 忽略，均为本地态；`.agents/skills/ingest/`、`.codex/`、`.copilot/`、`.github/copilot-instructions.md` 也在当前 vault 维护，但只作为入口，不拥有整理逻辑。

## CronCreate 定时整理的局限

CronCreate 创建的定时整理是 durable，但 **7 天后自动过期**，且只在 Claude Code REPL idle 时 fire——不开 Claude Code 不会跑。真正离线兜底靠 `ingest.sh`（headless，不依赖会话）。cron 过期后需重建，或改用系统 crontab 调 `ingest.sh`。

## headless 执行注意

headless `claude -p` 整理不能设置过短硬超时；过短会出现已移动/编辑但未重新 `git add` 或未提交的半完成状态。脚本应接 `/dev/null` 避免等 stdin，并用较长兜底超时。

## dirty baseline 对比

`ingest.sh` 做 dirty baseline 对比时，应排除 `Inbox/**` 和 `.claude/ingest.log`：Inbox 是本次候选，ingest.log 是必写日志。但 skill 里的 protected paths 只能按 `git status` 实际列出的具体路径解释，不能把父目录误判为整体受保护。

## 转换 wrapper 与环境变量

转换 wrapper 会清理环境变量，只保留 allowlist：`safe-markitdown` 处理文档/截图，`safe-whisper` 处理音视频（额外保留 `WHISPER_MODEL` / `WHISPER_LANGUAGE`）。测试时不要用自定义环境变量控制 mock 行为，改为替换临时 `PATH` 中的 mock 可执行文件。

Inbox PDF 的自动整理边界是 `safe-markitdown` 生成的 Markdown。即使转换稿有双栏、表格或页眉页脚噪声，也不要在整理流程里追加 `pdftotext`、`pdfplumber`、`pypdf`、OCR 或手写 PDF 抽取作为第二条转换路径；否则 headless allowlist、source fingerprint 和“同名 Markdown 冲突”保护都会被绕开。信息足够时从生成的 Markdown 提炼，信息不足时留在 Inbox 并记录原因。

## tag 清洗

ingest 写入 frontmatter 的 `tags` 来自源材料或模型推荐，可能含 Obsidian 禁用字符。Obsidian tag 合法字符集见 `app.js` 的 `jx` 正则：禁止 ASCII 标点（除 `-` `_` `/`）、Unicode 标点区间 `U+2000–U+206F` / `U+2E00–U+2E7F`、空白；含禁用字符的 tag 在 Properties 面板显示红色+删除线（CSS `.multi-select-pill.is-invalid` 用 `--text-error`），悬停提示 `Invalid tag`，且不进入 tag 检索/补全。

`parse_tag_list`（`ingest.py`）在写入前对每个 tag 跑 `sanitize_tag`：去前导 `#`、禁用字符替换为 `-`、折叠连续 `-`、去首尾 `-`、去重、丢空。如 `spec-2.0` → `spec-2-0`。纯数字 tag（如 `2024`）仍被 Obsidian 判无效（`XA=/^#\d+$/`，另一规则），清洗不处理。改字符集时，先解包本机 `/Applications/Obsidian.app/Contents/Resources/obsidian.asar` 读 `app.js` 里的 `jx` 与 `XA` 确认现行规则。
