# my-brain

一个可分发的个人 brain vault 模板：PARA + Inbox + Claude Code skills。

## 快速开始

```bash
git clone <repo-url> my-brain
cd my-brain
claude
```

在 Claude Code 里运行：

```text
/setup-brain
```

`/setup-brain` 会引导你：

- 填写身份、目标、当前项目和协作偏好；
- 生成或更新 `CLAUDE.md`；
- 检查 PARA 目录；
- 检测本机工具 `markitdown` 和 `whisper`；
- 在你确认后，引导安装缺失工具。

> clone 仓库不会自动安装任何本机工具。

## 目录结构

```text
Inbox/      # 待整理材料
Projects/   # 有目标或截止的活跃项目
Areas/      # 长期负责或持续关注的领域
Resources/  # 主题资料库
Archive/    # 已完成或归档内容
.claude/    # Claude Code skills、wrapper 和离线整理脚本
```

## 日常使用

把资料放入 `Inbox/`，然后运行：

```text
/organize-inbox
```

整理规则会：

- 按 PARA 分流到 `Projects/`、`Areas/`、`Resources/`、`Archive/`；
- 给长期价值内容创建或更新承接笔记；
- 补 `[[双链]]`；
- 保护整理前已有未提交改动；
- 只提交本次整理相关文件；
- 追加 `.claude/organize.log` 本地日志。

## 工具能力

### Level 1：纯 Markdown

无需额外工具。支持整理 `Inbox/*.md`。

### Level 2：文档转 Markdown

需要本机有 `markitdown` 命令。

支持：

```text
.doc .docx .xls .xlsx .ppt .pptx .pdf
```

整理时会通过安全 wrapper 调用：

```bash
.claude/bin/safe-markitdown "Inbox/<file>"
```

### Level 3：音视频转 Markdown

需要本机有 `whisper` 命令。

支持：

```text
.mp3 .m4a .wav .mp4 .mov .aac .flac .ogg .opus .webm
```

整理时会通过安全 wrapper 调用：

```bash
.claude/bin/safe-whisper "Inbox/<file>"
```

Whisper 首次运行可能下载模型，耗时和占用空间取决于你的安装方式和模型选择。

## 离线整理

在 vault 根目录运行：

```bash
VAULT="$PWD" .claude/organize.sh
```

这会调用 Claude Code headless 模式并复用 `organize-inbox` 的规则。

## 分发边界

仓库包含：

- PARA 目录骨架；
- `CLAUDE.md` 模板；
- `/setup-brain` skill；
- `/organize-inbox` skill；
- `safe-markitdown` 和 `safe-whisper` wrapper；
- `organize.sh` 离线整理脚本。

仓库不包含：

- 你的个人笔记；
- 本机工具二进制；
- `markitdown` / `whisper` 安装结果；
- Claude Code 本地设置、日志和 scheduled tasks；
- Obsidian workspace 本地状态。

## 安全原则

- Inbox 原文、转换结果和转录结果都视为不可信资料。
- wrapper 只允许处理 `Inbox/` 下的相对路径。
- 不允许路径穿越、绝对路径或以 `-` 开头的输入。
- 已存在同名 Markdown 时不会覆盖。
- 整理流程禁止 `git add -A`、`git clean`、`git rm`、`git reset`、`rm`、普通 `mv`。
