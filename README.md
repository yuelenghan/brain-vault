# brain-vault

brain-vault 是一个面向 AI coding agents 的个人知识库模板。它用 PARA 方法组织资料，并内置 Claude Code、Copilot CLI 和 Codex CLI 支持。

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
- 检测可选本地工具，例如 `markitdown`、`Pillow`、`whisper`、`copilot` 和 `codex`；
- 在你确认后，引导安装缺失工具。

> 说明：克隆仓库只会获得模板文件，不会自动安装任何本地工具。

## 选择你的 AI CLI

### Claude Code

Claude Code 是当前模板的完整体验入口，支持内置技能：

```text
/setup-brain
/organize-inbox
/optimize-vault
```

适合初始化知识库、整理 Inbox、优化已整理笔记、运行离线整理脚本和维护 vault 规则。

### GitHub Copilot CLI

如果你使用 Copilot CLI，可以在仓库根目录运行：

```bash
copilot
```

也可以通过 GitHub CLI 启动或查看帮助：

```bash
gh copilot -- --help
```

本仓库提供 `.github/copilot-instructions.md`，Copilot 可以读取其中的仓库约定；同时提供隐藏目录内的 Copilot CLI plugin：

```text
.copilot/.github/plugin/plugin.json
.copilot/skills/setup-brain/SKILL.md
.copilot/skills/organize-inbox/SKILL.md
.copilot/skills/optimize-vault/SKILL.md
```

在支持本地插件源的 Copilot CLI 中，可从 `.copilot/` 安装 plugin；也可以在仓库根目录启动 Copilot 后明确要求使用 `setup-brain`、`organize-inbox` 或 `optimize-vault` skill。你也可以运行：

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

本仓库提供 `AGENTS.md` 作为通用 agent 指令文件，供 Codex CLI 和其他支持仓库指令的工具参考；同时提供项目内 Codex skills：

```text
.codex/skills/setup-brain/SKILL.md
.codex/skills/organize-inbox/SKILL.md
.codex/skills/optimize-vault/SKILL.md
```

如需让本机 Codex 自动发现这些 skills，可将 `.codex/skills/*` 复制或同步到 `$CODEX_HOME/skills`（未设置时通常是 `~/.codex/skills`），或在 Codex 会话中显式读取这些项目内 skill。

## 目录结构

```text
Inbox/      # 临时收集箱，放待整理材料
Projects/   # 有明确目标或截止日期的项目
Areas/      # 长期负责或持续关注的领域
Resources/  # 可复用的主题资料
Archive/    # 已完成、过期或归档内容
.claude/    # Claude Code 技能、脚本和安全 wrapper
.codex/     # 项目内 Codex CLI skills
.copilot/   # 项目内 Copilot CLI plugin 和 skills
.github/    # GitHub Copilot 仓库指令
AGENTS.md   # 通用 agent 指令
```

## 日常使用

把材料放入 `Inbox/`，然后在 Claude Code 中运行：

```text
/organize-inbox
```

整理时会先运行确定性预处理脚本，枚举 Inbox 文件、转换可支持格式、生成来源指纹并识别完全重复；随后会：

- 按 PARA 规则分流到 `Projects/`、`Areas/`、`Resources/` 或 `Archive/`；
- 为有长期价值的内容创建或更新承接笔记；
- 补充 `[[双链]]`；
- 尽量保护整理前已有的未提交改动；
- 只提交本次整理相关文件；
- 在本地追加整理日志 `.claude/organize.log`。

已整理笔记需要体检、去重、补链或修复失效链接时，运行：

```text
/optimize-vault
```

该技能只处理 `Projects/`、`Areas/`、`Resources/` 和 `Archive/`，不会整理 `Inbox/`。

Copilot CLI 和 Codex CLI 也有项目内 skill 入口；这些入口会读取 `.claude/skills/*/SKILL.md` 作为 canonical 流程源，以保持三种 CLI 的行为一致。

## 可选工具

brain-vault 的基础功能不依赖额外工具。文档转换、截图占位、音视频转录和其他 AI CLI 需要你按需安装本机命令。

### 纯 Markdown 整理

无需额外工具。支持整理：

```text
.md
```

### 文档、数据、网页和截图转 Markdown

文档、数据导出、网页、电子书和 Notebook 需要安装 `markitdown`；截图占位需要 `Pillow`。

支持整理：

```text
.doc .docx .xls .xlsx .ppt .pptx .pdf
.txt .text .markdown .csv .json .jsonl
.html .htm .epub .ipynb
.png .jpg .jpeg .webp
```

整理时会通过安全 wrapper 调用：

```bash
.claude/bin/safe-markitdown "Inbox/<file>"
```

截图转换只生成文件名、格式、尺寸和待整理占位；真正整理时仍要结合原始截图内容补充主题、关键信息和后续动作。

### 音视频转 Markdown

需要安装 `whisper` 和 `ffmpeg`。如果通过 Homebrew 安装 `openai-whisper`，`ffmpeg` 通常会作为依赖一并安装；其他安装方式可能需要单独安装 `ffmpeg`。

支持整理：

```text
.mp3 .m4a .wav .mp4 .mov .aac .aiff .flac .ogg .opus .webm
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
- 安全 wrapper 只允许处理 `Inbox/` 下的相对路径或 vault 内允许目录。
- 不允许路径穿越、绝对路径或以 `-` 开头的输入。
- 确定性报告路径固定为 `/tmp/organize-inbox.*` 和 `/tmp/optimize-vault.*`，脚本不接受任意 report 路径或跨目录 `--vault`。
- 自动去重只信任重新计算的正文指纹；frontmatter 中不匹配的旧 `content_fingerprint` 只报告，不作为自动移动依据。
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
- `safe-markitdown`、`safe-whisper` 和受限 `safe-mkdir` / `safe-git-*` / `organize-inbox-*` 安全 wrapper；
- `/optimize-vault` 已整理笔记优化技能；
- `organize-inbox` 和 `optimize-vault` 的确定性辅助脚本；
- `organize.sh` 离线整理脚本；
- Codex CLI 项目内 skills；
- 隐藏目录 `.copilot/` 内的 Copilot CLI plugin manifest 和 skills。

本仓库不包含：

- 你的个人笔记；
- `markitdown`、`Pillow`、`whisper`、`copilot`、`codex` 等本机工具的安装结果；
- Claude Code、Copilot CLI 或 Codex CLI 的本地设置、日志、登录状态和定时任务；
- Obsidian workspace 等本地状态。
