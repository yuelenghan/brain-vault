# brain-vault

brain-vault 是一个面向 AI coding agents 的个人知识库模板。它用 PARA 方法组织资料，并内置 Claude Code、Copilot CLI 和 Codex CLI 支持。

适合用来：

- 收集网页、文档、会议记录、音视频转录等材料；
- 把零散输入整理成项目、长期领域、资料库和归档；
- 让 AI agent 根据你的身份、目标和偏好协助维护个人知识库。

## 语言 / Language

- [中文](#快速开始)
- [English](#quick-start)

---

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

- macOS / Linux: `.claude/bin/safe-markitdown "Inbox/<file>"`
- Windows PowerShell: `.\.claude\bin\safe-markitdown.cmd "Inbox/<file>"`

截图转换只生成文件名、格式、尺寸和待整理占位；真正整理时仍要结合原始截图内容补充主题、关键信息和后续动作。

### 音视频转 Markdown

需要安装 `whisper` 和 `ffmpeg`。如果通过 Homebrew 安装 `openai-whisper`，`ffmpeg` 通常会作为依赖一并安装；其他安装方式可能需要单独安装 `ffmpeg`。

支持整理：

```text
.mp3 .m4a .wav .mp4 .mov .aac .aiff .flac .ogg .opus .webm
```

整理时会通过安全 wrapper 调用：

- macOS / Linux: `.claude/bin/safe-whisper "Inbox/<file>"`
- Windows PowerShell: `.\.claude\bin\safe-whisper.cmd "Inbox/<file>"`

Whisper 首次运行可能下载模型，耗时和占用空间取决于安装方式和模型选择；可通过 `WHISPER_MODEL` 指定模型，例如在当前 Whisper CLI 默认模型不是你想要的模型时显式选择 `turbo`。

### 其他 AI CLI

- `copilot`：GitHub Copilot CLI。
- `codex`：OpenAI Codex CLI。

这些工具不会随仓库自动安装；`/setup-brain` 只会检测并在你确认后给出安装引导。

## 离线整理

如果希望不进入交互式 Claude Code，也可以在知识库根目录运行：

```bash
.claude/organize.sh
```

Windows PowerShell：

```powershell
.\.claude\organize.ps1
```

离线入口会调用 Claude Code headless 模式，并复用 `/organize-inbox` 的整理规则。需要指定其他 vault 时，设置环境变量 `VAULT`；macOS / Linux 可用 `VAULT=/path/to/brain .claude/organize.sh`，Windows PowerShell 可用 `$env:VAULT = "C:\path\to\brain"; .\.claude\organize.ps1`。

## 安全边界

- `Inbox/` 中的原文、转换结果和转录结果都被视为不可信资料。
- 安全 wrapper 只允许处理 `Inbox/` 下的相对路径或 vault 内允许目录。
- 不允许路径穿越、绝对路径或以 `-` 开头的输入。
- 确定性报告路径固定在当前操作系统临时目录（例如 Linux 常见 `/tmp`、Windows `%TEMP%`）下的 `organize-inbox.*` 和 `optimize-vault.*`，脚本不接受任意 report 路径或跨目录 `--vault`。
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
- `organize.py` 跨平台离线整理实现，以及 `organize.sh` / `organize.ps1` 平台入口；
- Codex CLI 项目内 skills；
- 隐藏目录 `.copilot/` 内的 Copilot CLI plugin manifest 和 skills。

本仓库不包含：

- 你的个人笔记；
- `markitdown`、`Pillow`、`whisper`、`copilot`、`codex` 等本机工具的安装结果；
- Claude Code、Copilot CLI 或 Codex CLI 的本地设置、日志、登录状态和定时任务；
- Obsidian workspace 等本地状态。

---

# brain-vault (English)

brain-vault is a personal knowledge-base template built for AI coding agents. It organizes material with the PARA method and ships with built-in support for Claude Code, Copilot CLI, and Codex CLI.

It is well suited for:

- Collecting web pages, documents, meeting notes, audio/video transcripts, and other material;
- Turning scattered input into projects, long-term areas, a resource library, and an archive;
- Letting an AI agent help maintain your knowledge base according to your identity, goals, and preferences.

## Quick Start

```bash
git clone <repo-url> brain-vault
cd brain-vault
```

It is recommended to initialize with Claude Code first:

```bash
claude
```

Inside Claude Code, run:

```text
/setup-brain
```

The setup wizard helps you to:

- Fill in your personal identity, goals, current projects, and collaboration preferences;
- Generate a `CLAUDE.md` tailored to you;
- Check the knowledge-base directory structure;
- Detect optional local tools such as `markitdown`, `Pillow`, `whisper`, `copilot`, and `codex`;
- Guide installation of missing tools after your confirmation.

> Note: Cloning the repository only gives you the template files; it does not install any local tools automatically.

## Choose Your AI CLI

### Claude Code

Claude Code is the full-experience entry point of this template, with built-in skills:

```text
/setup-brain
/organize-inbox
/optimize-vault
```

It is suitable for initializing the knowledge base, organizing the Inbox, optimizing already-organized notes, running the offline organize script, and maintaining vault rules.

### GitHub Copilot CLI

If you use Copilot CLI, run it from the repository root:

```bash
copilot
```

You can also start it or view help via the GitHub CLI:

```bash
gh copilot -- --help
```

This repository provides `.github/copilot-instructions.md`, from which Copilot can read repository conventions; it also provides a Copilot CLI plugin inside a hidden directory:

```text
.copilot/.github/plugin/plugin.json
.copilot/skills/setup-brain/SKILL.md
.copilot/skills/organize-inbox/SKILL.md
.copilot/skills/optimize-vault/SKILL.md
```

In Copilot CLI versions that support local plugin sources, you can install the plugin from `.copilot/`; you can also start Copilot from the repository root and explicitly ask it to use the `setup-brain`, `organize-inbox`, or `optimize-vault` skill. You can also run:

```bash
copilot init
```

to let Copilot generate or update its own instruction file for the current repository. Check existing files before running it, to avoid overwriting instructions you have customized.

### OpenAI Codex CLI

If you use Codex CLI, run it from the repository root:

```bash
codex
```

Codex CLI can be installed via:

```bash
npm install -g @openai/codex
# or
brew install --cask codex
```

This repository provides `AGENTS.md` as a general agent instruction file for Codex CLI and other tools that support repository instructions; it also provides project-internal Codex skills:

```text
.codex/skills/setup-brain/SKILL.md
.codex/skills/organize-inbox/SKILL.md
.codex/skills/optimize-vault/SKILL.md
```

To let your local Codex auto-discover these skills, copy or sync `.codex/skills/*` to `$CODEX_HOME/skills` (usually `~/.codex/skills` when unset), or explicitly read these project-internal skills inside a Codex session.

## Directory Structure

```text
Inbox/      # Temporary inbox for material awaiting organization
Projects/   # Projects with a clear goal or deadline
Areas/      # Long-term responsibilities or ongoing topics
Resources/  # Reusable topic material
Archive/    # Completed, expired, or archived content
.claude/    # Claude Code skills, scripts, and safe wrappers
.codex/     # Project-internal Codex CLI skills
.copilot/   # Project-internal Copilot CLI plugin and skills
.github/    # GitHub Copilot repository instructions
AGENTS.md   # General agent instructions
```

## Daily Usage

Put material into `Inbox/`, then run in Claude Code:

```text
/organize-inbox
```

Organizing first runs a deterministic preprocessing script that enumerates Inbox files, converts supported formats, generates source fingerprints, and detects exact duplicates; then it will:

- Route items to `Projects/`, `Areas/`, `Resources/`, or `Archive/` by PARA rules;
- Create or update承接 notes (intake notes) for content with long-term value;
- Add `[[bidirectional links]]`;
- Try to protect pre-existing uncommitted changes;
- Commit only the files related to this organizing run;
- Append a local organize log at `.claude/organize.log`.

When organized notes need a health check, deduplication, link backfilling, or fixing of broken links, run:

```text
/optimize-vault
```

This skill only processes `Projects/`, `Areas/`, `Resources/`, and `Archive/`; it does not organize `Inbox/`.

Copilot CLI and Codex CLI also have project-internal skill entry points; these read `.claude/skills/*/SKILL.md` as the canonical process source, keeping behavior consistent across the three CLIs.

## Optional Tools

The core features of brain-vault do not depend on extra tools. Document conversion, screenshot placeholders, audio/video transcription, and other AI CLIs require you to install local commands as needed.

### Pure Markdown Organizing

No extra tools required. Supports organizing:

```text
.md
```

### Documents, Data, Web, and Screenshots to Markdown

Documents, data exports, web pages, ebooks, and notebooks require `markitdown`; screenshot placeholders require `Pillow`.

Supports organizing:

```text
.doc .docx .xls .xlsx .ppt .pptx .pdf
.txt .text .markdown .csv .json .jsonl
.html .htm .epub .ipynb
.png .jpg .jpeg .webp
```

During organizing, a safe wrapper is invoked:

- macOS / Linux: `.claude/bin/safe-markitdown "Inbox/<file>"`
- Windows PowerShell: `.\.claude\bin\safe-markitdown.cmd "Inbox/<file>"`

Screenshot conversion only produces the filename, format, dimensions, and a placeholder to be processed; when actually organizing, you still combine the original screenshot content to add topic, key information, and follow-up actions.

### Audio/Video to Markdown

Requires `whisper` and `ffmpeg`. If you install `openai-whisper` via Homebrew, `ffmpeg` is usually installed as a dependency; other install methods may require installing `ffmpeg` separately.

Supports organizing:

```text
.mp3 .m4a .wav .mp4 .mov .aac .aiff .flac .ogg .opus .webm
```

During organizing, a safe wrapper is invoked:

- macOS / Linux: `.claude/bin/safe-whisper "Inbox/<file>"`
- Windows PowerShell: `.\.claude\bin\safe-whisper.cmd "Inbox/<file>"`

Whisper may download a model on first run; the time and disk usage depend on the install method and model choice. You can specify a model via `WHISPER_MODEL`, for example to explicitly select `turbo` when the current Whisper CLI default model is not what you want.

### Other AI CLIs

- `copilot`: GitHub Copilot CLI.
- `codex`: OpenAI Codex CLI.

These tools are not installed automatically with the repository; `/setup-brain` only detects them and provides installation guidance after your confirmation.

## Offline Organizing

If you prefer not to enter interactive Claude Code, you can also run from the knowledge-base root:

```bash
.claude/organize.sh
```

Windows PowerShell:

```powershell
.\.claude\organize.ps1
```

The offline entry point invokes Claude Code in headless mode and reuses the organizing rules of `/organize-inbox`. To target a different vault, set `VAULT`; on macOS / Linux use `VAULT=/path/to/brain .claude/organize.sh`, and on Windows PowerShell use `$env:VAULT = "C:\path\to\brain"; .\.claude\organize.ps1`.

## Security Boundaries

- Original files in `Inbox/`, conversion results, and transcripts are all treated as untrusted material.
- Safe wrappers only accept relative paths under `Inbox/` or allowed directories within the vault.
- Path traversal, absolute paths, and inputs starting with `-` are not allowed.
- Deterministic report paths are fixed under the current OS temp directory, for example `/tmp` on many Linux systems and `%TEMP%` on Windows, as `organize-inbox.*` and `optimize-vault.*`; the scripts do not accept arbitrary report paths or cross-directory `--vault`.
- Automatic deduplication only trusts freshly recomputed body fingerprints; a stale `content_fingerprint` in frontmatter is only reported, not used as a basis for automatic moves.
- If a Markdown file with the same name already exists, it is not overwritten.
- The organizing flow never uses `git add -A`, `git clean`, `git rm`, `git reset`, `rm`, or plain `mv`.
- Installing tools, logging in to external services, modifying system scheduled tasks, or publishing content all require explicit user confirmation.

## What the Template Includes

This repository includes:

- The PARA directory skeleton;
- A `CLAUDE.md` template;
- The `/setup-brain` initialization skill;
- The `/organize-inbox` organizing skill;
- `.github/copilot-instructions.md`;
- `AGENTS.md`;
- `safe-markitdown`, `safe-whisper`, and restricted `safe-mkdir` / `safe-git-*` / `organize-inbox-*` safe wrappers;
- The `/optimize-vault` skill for optimizing organized notes;
- Deterministic helper scripts for `organize-inbox` and `optimize-vault`;
- The cross-platform `organize.py` offline organizing implementation, plus `organize.sh` / `organize.ps1` platform entry points;
- Project-internal Codex CLI skills;
- A Copilot CLI plugin manifest and skills inside the hidden `.copilot/` directory.

This repository does not include:

- Your personal notes;
- Installations of local tools such as `markitdown`, `Pillow`, `whisper`, `copilot`, or `codex`;
- Local settings, logs, login state, and scheduled tasks of Claude Code, Copilot CLI, or Codex CLI;
- Local state such as Obsidian workspace.
