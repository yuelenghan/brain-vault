# brain-vault

brain-vault 是一个面向 AI coding agents 的个人知识库模板。它用 PARA 方法组织资料，并内置 Claude Code 支持；同时提供 Copilot CLI 和 Codex CLI 可读取的仓库指令。

适合用来：

- 收集网页、文档、会议记录、音视频转录等材料；
- 把零散输入整理成项目、长期领域、资料库和归档；
- 让 AI agent 根据你的身份、目标和偏好协助维护个人知识库。

## 快速开始

```bash
git clone <repo-url> brain-vault
cd brain-vault
```

推荐先用 Claude Code 完成初始化：

```bash
claude
```

进入 Claude Code 后运行：

```text
/setup-brain
```

初始化向导会帮助你：

- 填写个人身份、目标、当前项目和协作偏好；
- 生成适合你的 `CLAUDE.md`；
- 检查知识库目录结构；
- 检测可选本地工具，例如 `markitdown`、`whisper`、`copilot` 和 `codex`；
- 在你确认后，引导安装缺失工具。

> 说明：克隆仓库只会获得模板文件，不会自动安装任何本地工具。

## 选择你的 AI CLI

### Claude Code

Claude Code 是当前模板的完整体验入口，支持内置技能：

```text
/setup-brain
/organize-inbox
```

适合初始化知识库、整理 Inbox、运行离线整理脚本和维护 vault 规则。

### GitHub Copilot CLI

如果你使用 Copilot CLI，可以在仓库根目录运行：

```bash
copilot
```

也可以通过 GitHub CLI 启动或查看帮助：

```bash
gh copilot -- --help
```

本仓库提供 `.github/copilot-instructions.md`，Copilot 可以读取其中的仓库约定。你也可以运行：

```bash
copilot init
```

让 Copilot 根据当前仓库生成或更新自己的指令文件。运行前请注意检查已有文件，避免覆盖你已经定制过的说明。

### OpenAI Codex CLI

如果你使用 Codex CLI，可以在仓库根目录运行：

```bash
codex
```

Codex CLI 可通过以下方式安装：

```bash
npm install -g @openai/codex
# 或
brew install --cask codex
```

本仓库提供 `AGENTS.md` 作为通用 agent 指令文件，供 Codex CLI 和其他支持仓库指令的工具参考。

## 目录结构

```text
Inbox/      # 临时收集箱，放待整理材料
Projects/   # 有明确目标或截止日期的项目
Areas/      # 长期负责或持续关注的领域
Resources/  # 可复用的主题资料
Archive/    # 已完成、过期或归档内容
.claude/    # Claude Code 技能、脚本和安全 wrapper
.github/    # GitHub Copilot 仓库指令
AGENTS.md   # 通用 agent 指令
```

## 日常使用

把材料放入 `Inbox/`，然后在 Claude Code 中运行：

```text
/organize-inbox
```

整理时会：

- 按 PARA 规则分流到 `Projects/`、`Areas/`、`Resources/` 或 `Archive/`；
- 为有长期价值的内容创建或更新承接笔记；
- 补充 `[[双链]]`；
- 尽量保护整理前已有的未提交改动；
- 只提交本次整理相关文件；
- 在本地追加整理日志 `.claude/organize.log`。

Copilot CLI 和 Codex CLI 当前主要通过 `.github/copilot-instructions.md` 与 `AGENTS.md` 获得仓库约定；如果用它们整理内容，请明确要求遵守这些文件中的安全边界。

## 可选工具

brain-vault 的基础功能不依赖额外工具。文档转换、音视频转录和其他 AI CLI 需要你按需安装本机命令。

### 纯 Markdown 整理

无需额外工具。支持整理：

```text
.md
```

### 文档转 Markdown

需要安装 `markitdown`。

支持整理：

```text
.doc .docx .xls .xlsx .ppt .pptx .pdf
```

整理时会通过安全 wrapper 调用：

```bash
.claude/bin/safe-markitdown "Inbox/<file>"
```

### 音视频转 Markdown

需要安装 `whisper` 和 `ffmpeg`。如果通过 Homebrew 安装 `openai-whisper`，`ffmpeg` 通常会作为依赖一并安装；其他安装方式可能需要单独安装 `ffmpeg`。

支持整理：

```text
.mp3 .m4a .wav .mp4 .mov .aac .flac .ogg .opus .webm
```

整理时会通过安全 wrapper 调用：

```bash
.claude/bin/safe-whisper "Inbox/<file>"
```

Whisper 首次运行可能下载模型，耗时和占用空间取决于安装方式和模型选择；可通过 `WHISPER_MODEL` 指定模型，例如在当前 Whisper CLI 默认模型不是你想要的模型时显式选择 `turbo`。

### 其他 AI CLI

- `copilot`：GitHub Copilot CLI。
- `codex`：OpenAI Codex CLI。

这些工具不会随仓库自动安装；`/setup-brain` 只会检测并在你确认后给出安装引导。

## 离线整理

如果希望不进入交互式 Claude Code，也可以在知识库根目录运行：

```bash
VAULT="$PWD" .claude/organize.sh
```

该脚本会调用 Claude Code headless 模式，并复用 `/organize-inbox` 的整理规则。

## 安全边界

- `Inbox/` 中的原文、转换结果和转录结果都被视为不可信资料。
- 安全 wrapper 只允许处理 `Inbox/` 下的相对路径。
- 不允许路径穿越、绝对路径或以 `-` 开头的输入。
- 如果同名 Markdown 已存在，不会覆盖。
- 整理流程不会使用 `git add -A`、`git clean`、`git rm`、`git reset`、`rm` 或普通 `mv`。
- 安装工具、登录外部服务、修改系统定时任务或发布内容前，都需要用户明确确认。

## 模板包含什么

本仓库包含：

- PARA 目录骨架；
- `CLAUDE.md` 模板；
- `/setup-brain` 初始化技能；
- `/organize-inbox` 整理技能；
- `.github/copilot-instructions.md`；
- `AGENTS.md`；
- `safe-markitdown` 和 `safe-whisper` 安全 wrapper；
- `organize.sh` 离线整理脚本。

本仓库不包含：

- 你的个人笔记；
- `markitdown`、`whisper`、`copilot`、`codex` 等本机工具的安装结果；
- Claude Code、Copilot CLI 或 Codex CLI 的本地设置、日志、登录状态和定时任务；
- Obsidian workspace 等本地状态。
