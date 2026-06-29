---
name: setup-brain
description: 初始化 brain-vault：采访用户身份和目标，生成 CLAUDE.md，检查 PARA 目录、git 状态、本机转换工具（markitdown、Pillow、whisper、ffmpeg）和 AI CLI（copilot、codex），并按用户确认安装缺失工具。
---

# Setup Brain

你是 brain-vault 初始化向导。目标是在当前 vault 根目录完成一次安全、可重复的初始化。不要读取或外传凭证。不要删除用户文件。执行安装命令、覆盖已有配置、提交 git 或设置定时任务前必须先确认。

## 适用前提

- 工作目录应是 brain-vault 根目录。
- 如果当前目录不是 git 仓库，先说明并询问是否初始化 git。
- 如果 `CLAUDE.md` 已包含用户真实内容，不要静默覆盖；先读取并说明将更新哪些段落。

## 初始化流程

### 1. 预检

运行并记录：

```bash
pwd
git status --short
find . -maxdepth 2 -type d \( -path './.git' -o -path './.claude' \) -prune -o -type d -print
command -v markitdown || true
command -v whisper || true
command -v ffmpeg || true
command -v copilot || true
command -v gh || true
command -v codex || true
command -v uv || true
command -v brew || true
command -v npm || true
command -v python3 || true
```

若存在未提交改动，不要自动覆盖相关文件；把它们列为 protected paths。

### 2. 采访用户

一次性询问必要信息，避免反复打断：

1. 你是谁？角色、主要职责、专业方向是什么？
2. 今年或近期最重要的目标是什么？
3. 当前活跃项目有哪些？每个项目一句话说明。
4. 你希望 Claude 如何协作？例如是否偏好简洁结论、详细推理、自动执行、谨慎确认等。
5. 计划整理哪些文件格式？是否启用文档/数据/网页/Notebook 转换能力（Word/PDF/PPT/Excel/TXT/CSV/JSON/HTML/EPUB/IPYNB → Markdown）和截图占位能力（图片 → Markdown 占位）？
6. 是否启用音视频转录能力（音视频 → Markdown）？如果启用，是否接受首次真实转录时下载 Whisper 模型，是否需要指定模型或语言？
7. 是否需要 Copilot CLI 或 Codex CLI 支持？
8. 是否需要离线自动整理？如果需要，偏好手动运行 `organize.sh`、系统 crontab/launchd，还是 Claude Code 会话内定时？

如用户只要求快速初始化，可使用保守默认：保留现有协作偏好，创建空 PARA 目录，只检测工具不安装。

### 3. 生成或更新 CLAUDE.md

根据用户回答更新：

- `## 我是谁`
- `## 今年的目标`
- `## 协作偏好`
- `## 当前项目`

保留下方 Vault 约定、常用命令、工具层级和项目级坑点。不要写入临时任务状态、一次性信息或凭证。

### 4. 确保目录结构

确保以下目录存在：

```text
Inbox/
Projects/
Areas/
Resources/
Archive/
.claude/bin/
.claude/skills/setup-brain/
.claude/skills/organize-inbox/
```

空目录用 `.gitkeep` 保留。

### 5. 工具检测与安装引导

#### 基础检测

- `markitdown`：用于 `.doc/.docx/.xls/.xlsx/.ppt/.pptx/.pdf/.txt/.text/.markdown/.csv/.json/.jsonl/.html/.htm/.epub/.ipynb` 转 Markdown。
- `Pillow`：用于 `.png/.jpg/.jpeg/.webp` 生成截图占位 Markdown。
- `whisper`：用于 `.mp3/.m4a/.wav/.mp4/.mov/.aac/.aiff/.flac/.ogg/.opus/.webm` 转 Markdown。
- `ffmpeg`：Whisper 解码音视频所需的本机依赖。
- Whisper 模型：首次真实转录可能下载默认模型；用 `whisper --help` 验证当前默认模型和 `--model` 参数，必要时通过 `WHISPER_MODEL` 指定。
- `copilot` / `gh copilot`：用于 GitHub Copilot CLI。
- `codex`：用于 OpenAI Codex CLI。
- `uv`、`brew`、`npm`、`python3`：用于推荐安装路径判断。

#### 安装原则

- clone 仓库不会自动安装任何工具。
- 只检测时无需确认；执行安装命令前必须确认。
- 优先给出命令，让用户自己决定是否运行。
- 不要猜测包名或参数；安装前用已存在工具的 `--help` 或官方/本机说明验证命令。无法验证时说明不确定并让用户手动安装。

#### 推荐安装路径

如果用户启用文档转换且缺少 `markitdown`：

1. 若有 `uv`，先运行 `uv tool install --help` 验证命令存在，再建议：

   ```bash
   uv tool install markitdown
   ```

2. 若无 `uv` 但有 `python3`，建议用户选择自己的 Python 包管理方式安装 MarkItDown；不要替用户猜测全局 pip 安装策略。
3. 安装后验证：

   ```bash
   command -v markitdown
   markitdown --help
   ```

如果用户启用音频转录：

1. 检测 `whisper` 和 `ffmpeg`：

   ```bash
   command -v whisper || true
   command -v ffmpeg || true
   ```

2. 若缺少 `whisper` 且有 `brew`，先运行 `brew info openai-whisper` 验证 formula 存在；若输出显示依赖 `ffmpeg`，说明 Homebrew 安装会一并处理该依赖，再建议：

   ```bash
   brew install openai-whisper
   ```

3. 若缺少 `ffmpeg` 且不会通过 `brew install openai-whisper` 一并安装，先运行 `brew info ffmpeg` 验证 formula 存在，再建议：

   ```bash
   brew install ffmpeg
   ```

4. 若无 `brew` 但有 `uv`，先运行 `uv pip install --help` 验证命令存在；Python 安装 Whisper 通常需要目标环境，且 `ffmpeg` 仍可能需要单独安装，先让用户选择环境，不要静默全局安装。
5. 若用户已有 Python 或系统包管理方案，允许用户提供安装命令。
6. 安装后验证：

   ```bash
   command -v whisper
   command -v ffmpeg
   whisper --help
   ffmpeg -version
   ```

`whisper --help` 会显示当前默认模型和 `--model` 参数；若默认模型不是用户想要的模型，可建议用 `WHISPER_MODEL=<模型名>` 运行整理。Whisper 模型可能较大，首次真实转录可能下载模型；不要在 setup 阶段静默触发模型下载，执行真实转录前提醒用户。

如果用户启用 Copilot CLI 支持：

1. 若已有 `copilot`，运行 `copilot --help` 验证可用。
2. 若无 `copilot` 但有 `gh`，运行 `gh copilot --help` 验证 GitHub CLI 支持；可建议用户用 `gh copilot` 启动或下载 Copilot CLI。
3. 登录、下载、更新或修改 Copilot 配置前必须确认。
4. 说明 `.github/copilot-instructions.md` 是本仓库的 Copilot 指令文件；运行 `copilot init` 前应检查是否会覆盖已有定制内容。

如果用户启用 Codex CLI 支持：

1. 若已有 `codex`，运行 `codex --help` 验证可用；如果命令存在但报二进制缺失或启动失败，提示用户重装或修复。
2. 若无 `codex` 但有 `npm`，可建议：

   ```bash
   npm install -g @openai/codex
   ```

3. 若有 `brew`，可建议：

   ```bash
   brew install --cask codex
   ```

4. 安装、登录或配置 API key 前必须确认。
5. 说明 `AGENTS.md` 是通用 agent 指令文件，供 Codex CLI 和其他 agent 参考。

### 6. Wrapper 检查

确认以下文件存在且可执行：

```bash
test -x .claude/bin/safe-markitdown
test -x .claude/bin/safe-whisper
```

如不可执行，执行：

```bash
chmod +x .claude/bin/safe-markitdown .claude/bin/safe-whisper .claude/organize.sh
```

运行语法检查：

```bash
python3 -m py_compile .claude/bin/safe-markitdown .claude/bin/safe-whisper
zsh -n .claude/organize.sh
```

### 7. 可选自动整理

如果用户需要自动整理，说明三种方式：

- 会话内：用 Claude Code 定时任务触发 `/organize-inbox`，但会话关闭或任务过期会影响运行。
- 系统级：用 crontab/launchd 调 `VAULT=/path/to/brain .claude/organize.sh`。
- 手动：定期运行 `/organize-inbox` 或 `.claude/organize.sh`。

修改系统 crontab/launchd 前必须确认。

### 8. 最终验证和输出

运行：

```bash
git status --short
```

输出保持简洁：

- 已初始化的身份层段落。
- 工具状态：`markitdown` 已安装/未安装，`whisper` 已安装/未安装，`ffmpeg` 已安装/未安装，Whisper 默认模型/模型下载提醒，`copilot` 已安装/未安装，`codex` 已安装/未安装。
- 已启用能力：Markdown 整理、文档/数据/网页/Notebook 转换、截图占位、音视频转录、Copilot CLI 指令、Codex/通用 agent 指令。
- 下一步：把资料放入 `Inbox/`，运行 `/organize-inbox`。
