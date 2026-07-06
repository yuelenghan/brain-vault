---
name: setup-brain
description: Initialize a brain-vault — interview the user for identity and goals, generate AGENTS.md, check PARA directories, git status, local conversion tools (markitdown, Pillow, whisper, ffmpeg) and AI CLIs (copilot, codex), and install missing tools on user confirmation. Triggers: setup brain, initialize brain-vault, 初始化 brain-vault, 安装工具.
---

# Setup Brain

You are the brain-vault initialization wizard. The goal is a safe, repeatable initialization in the current vault root. Do not read or exfiltrate credentials. Do not delete user files. Confirm before running install commands, overwriting existing config, committing to git, or scheduling tasks.

## Prerequisites

- The working directory should be the brain-vault root.
- If the current directory is not a git repository, say so first and ask whether to initialize git.
- If `AGENTS.md` already contains real user content, do not silently overwrite it; read it first and explain which sections will be updated.

## Initialization flow

### 1. Pre-check

Run and record:

```bash
pwd
git status --short
find . -maxdepth 2 -type d \( -path './.git' -o -path './.claude' -o -path './.agents' -o -path './.codex' -o -path './.copilot' -o -path './.github' \) -prune -o -type d -print
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

If there are uncommitted changes, do not auto-overwrite the related files; list them as protected paths.

### 2. Interview the user

Ask for the essential information in one pass to avoid repeated interruptions:

1. Who are you? Role, main responsibilities, professional focus?
2. What are the most important goals for this year or near term?
3. What are the active projects? One sentence per project.
4. How do you want Codex to collaborate? For example, preference for concise conclusions, detailed reasoning, autonomous execution, cautious confirmation, etc.
5. Which file formats do you plan to organize? Should document/data/web/Notebook conversion (Word/PDF/PPT/Excel/TXT/CSV/JSON/HTML/EPUB/IPYNB → Markdown) and screenshot-placeholder capability (image → Markdown placeholder) be enabled?
6. Should audio/video transcription (audio/video → Markdown) be enabled? If yes, do you accept downloading the Whisper model on first real transcription, and do you need to specify a model or language?
7. Do you need Copilot CLI or Codex CLI support?
8. Do you need offline auto-organize? If yes, do you prefer running `ingest.sh` manually, system crontab/launchd, or in-session Codex scheduling?

If the user only wants a quick initialization, conservative defaults are acceptable: keep existing collaboration preferences, create empty PARA directories, and only detect tools without installing.

### 3. Generate or update AGENTS.md

Update these sections from the user's answers:

- `## 我是谁`
- `## 今年的目标`
- `## 协作偏好`
- `## 当前项目`

Keep the Vault conventions, common commands, tool tiers, and project-level pitfalls below those sections. Do not write temporary task state, one-off information, or credentials.

### 4. Ensure directory structure

Ensure these directories exist:

```text
Inbox/
Projects/
Areas/
Resources/
Archive/
.claude/bin/
.claude/skills/setup-brain/
.claude/skills/ingest/
.claude/skills/meditate/
.claude/skills/recall/
.agents/skills/setup-brain/
.agents/skills/ingest/
.agents/skills/meditate/
.agents/skills/recall/
.codex/skills/setup-brain/
.codex/skills/ingest/
.codex/skills/meditate/
.codex/skills/recall/
.copilot/.github/plugin/
.copilot/skills/setup-brain/
.copilot/skills/ingest/
.copilot/skills/meditate/
.copilot/skills/recall/
.github/
```

Preserve empty directories with `.gitkeep`.

The personal vault maintains the same multi-AI entry structure as the open-source projections: `.claude/` is canonical and owns scripts/wrappers, `.agents/` is the Codex session copy, `.codex/` is the Codex CLI thin entry, and `.copilot/` plus `.github/copilot-instructions.md` are the Copilot CLI / GitHub Copilot entries. Do not maintain `.Codex/` as a runtime directory unless a target host explicitly requires that legacy casing.

### 5. Tool detection and install guidance

#### Basic detection

- `markitdown`: converts `.doc/.docx/.xls/.xlsx/.ppt/.pptx/.pdf/.txt/.text/.markdown/.csv/.json/.jsonl/.html/.htm/.epub/.ipynb` to Markdown.
- `Pillow`: generates screenshot-placeholder Markdown for `.png/.jpg/.jpeg/.webp`.
- `whisper`: converts `.mp3/.m4a/.wav/.mp4/.mov/.aac/.aiff/.flac/.ogg/.opus/.webm` to Markdown.
- `ffmpeg`: local dependency required by Whisper to decode audio/video.
- Whisper model: the first real transcription may download the default model; verify the current default model and `--model` parameter with `whisper --help`, and specify via `WHISPER_MODEL` if needed.
- `copilot` / `gh copilot`: for the GitHub Copilot CLI.
- `codex`: for the OpenAI Codex CLI.
- `uv`, `brew`, `npm`, `python3`: used to decide the recommended install path.

#### Install principles

- Cloning the repository does not install any tool.
- Detection only needs no confirmation; confirm before running any install command.
- Prefer giving commands and letting the user decide whether to run them.
- Do not guess package names or parameters; before installing, verify the command against `--help` or official/local docs of an existing tool. When verification is impossible, state the uncertainty and let the user install manually.

#### Recommended install paths

If the user enables document conversion and `markitdown` is missing:

1. If `uv` is available, first run `uv tool install --help` to verify the command exists, then suggest:

   ```bash
   uv tool install markitdown
   ```

2. If there is no `uv` but `python3` is available, suggest the user pick their own Python package manager to install MarkItDown; do not guess a global pip strategy for them.
3. Verify after install:

   ```bash
   command -v markitdown
   markitdown --help
   ```

If the user enables audio transcription:

1. Detect `whisper` and `ffmpeg`:

   ```bash
   command -v whisper || true
   command -v ffmpeg || true
   ```

2. If `whisper` is missing and `brew` is available, first run `brew info openai-whisper` to verify the formula exists; if the output shows it depends on `ffmpeg`, Homebrew will handle that dependency, then suggest:

   ```bash
   brew install openai-whisper
   ```

3. If `ffmpeg` is missing and will not be installed via `brew install openai-whisper`, first run `brew info ffmpeg` to verify the formula exists, then suggest:

   ```bash
   brew install ffmpeg
   ```

4. If there is no `brew` but `uv` is available, first run `uv pip install --help` to verify the command exists; installing Whisper via Python usually needs a target environment and `ffmpeg` may still need a separate install, so let the user choose the environment first; do not silently install globally.
5. If the user already has a Python or system package manager workflow, allow them to provide the install command.
6. Verify after install:

   ```bash
   command -v whisper
   command -v ffmpeg
   whisper --help
   ffmpeg -version
   ```

`whisper --help` shows the current default model and the `--model` parameter; if the default is not the model the user wants, suggest running organize with `WHISPER_MODEL=<model>`. Whisper models can be large and the first real transcription may download one; do not silently trigger a model download at setup time — remind the user before a real transcription.

If the user enables Copilot CLI support:

1. If `copilot` is available, run `copilot --help` to verify it works.
2. If there is no `copilot` but `gh` is available, run `gh copilot --help` to verify GitHub CLI support; you may suggest the user start with `gh copilot` or download the Copilot CLI.
3. Confirm before login, download, update, or modifying Copilot config.
4. Explain that `.github/copilot-instructions.md` is this vault's GitHub Copilot repo instruction file, and `.copilot/.github/plugin/plugin.json` plus `.copilot/skills/*/SKILL.md` are in-project Copilot CLI plugin skills. Before running `copilot init`, check whether it would overwrite existing customizations.

If the user enables Codex CLI support:

1. If `codex` is available, run `codex --help` to verify it works; if the command exists but reports a missing binary or fails to start, suggest the user reinstall or repair it.
2. If there is no `codex` but `npm` is available, suggest:

   ```bash
   npm install -g @openai/codex
   ```

3. If `brew` is available, suggest:

   ```bash
   brew install --cask codex
   ```

4. Confirm before installing, logging in, or configuring an API key.
5. Explain that `AGENTS.md` is the generic agent instructions file, `.agents/skills/*/SKILL.md` are this personal vault's Codex session skills, and `.codex/skills/*/SKILL.md` are Codex CLI thin entry skills that read the canonical `.claude/skills/*/SKILL.md`.

### 6. Wrapper check

Confirm the following files exist and are executable:

```bash
test -x .claude/bin/safe-markitdown
test -x .claude/bin/safe-whisper
test -x .claude/bin/safe-mkdir
test -x .claude/bin/safe-git-add
test -x .claude/bin/safe-git-mv
test -x .claude/bin/safe-git-commit
test -x .claude/bin/ingest-scan
test -x .claude/bin/ingest-prepare
test -x .claude/bin/ingest-apply-duplicates
test -x .claude/bin/meditate-scan
test -x .claude/bin/meditate-apply-safe
test -x .claude/bin/meditate-finalize-log
test -x .claude/meditate.sh
```

If not executable, run:

```bash
chmod +x .claude/bin/safe-markitdown .claude/bin/safe-whisper .claude/bin/safe-mkdir .claude/bin/safe-git-add .claude/bin/safe-git-mv .claude/bin/safe-git-commit .claude/bin/ingest-scan .claude/bin/ingest-prepare .claude/bin/ingest-apply-duplicates .claude/bin/meditate-scan .claude/bin/meditate-apply-safe .claude/bin/meditate-finalize-log .claude/ingest.sh .claude/meditate.sh
```

Run syntax checks:

```bash
python3 -m py_compile .claude/bin/safe-markitdown .claude/bin/safe-whisper .claude/bin/safe-mkdir .claude/bin/safe-git-add .claude/bin/safe-git-mv .claude/bin/safe-git-commit .claude/bin/ingest-scan .claude/bin/ingest-prepare .claude/bin/ingest-apply-duplicates .claude/bin/meditate-scan .claude/bin/meditate-apply-safe .claude/bin/meditate-finalize-log
zsh -n .claude/ingest.sh
zsh -n .claude/meditate.sh
python3 -m json.tool .copilot/.github/plugin/plugin.json >/tmp/brain-vault-plugin-json-check.out
```

### 7. Optional auto-organize

If the user wants auto-organize, explain the three options. The default recommendation is now **ingest + meditate rhythm**: run `ingest` first, then `meditate` after it. Nightly cadence = `ingest.sh` then `meditate.sh nightly`; weekly cadence = `ingest.sh` then `meditate.sh weekly`.

- In-session: use a Codex scheduled task to trigger `/ingest` and `/meditate`; closing the session or task expiry affects execution.
- System-level: use crontab/launchd to run `VAULT=/path/to/brain .claude/ingest.sh` and then `VAULT=/path/to/brain .claude/meditate.sh nightly`, plus a weekly `VAULT=/path/to/brain .claude/meditate.sh weekly`.
- Manual: periodically run `/ingest`, `/meditate`, `.claude/ingest.sh`, or `.claude/meditate.sh [nightly|weekly]`.

Confirm before modifying the system crontab/launchd.

### 8. Final verification and output

Run:

```bash
git status --short
```

Keep the output concise:

- Initialized identity-layer sections.
- Tool status: `markitdown` installed/missing, `whisper` installed/missing, `ffmpeg` installed/missing, Whisper default model/model-download reminder, `copilot` installed/missing, `codex` installed/missing.
- Enabled capabilities: Markdown organizing, document/data/web/Notebook conversion, screenshot placeholder, audio/video transcription, brain recall/retrieval logging, organized-note meditation/optimization, nightly/weekly meditate automation, Claude Code instructions/skills, Codex session `.agents` skills, Codex CLI `.codex` skills, Copilot CLI `.copilot` skills, and GitHub Copilot `.github/copilot-instructions.md`.
- Next steps: put material into `Inbox/` and run `/ingest`; run `/recall` when you want to query existing knowledge; run `/meditate` or `.claude/meditate.sh [nightly|weekly]` when you want consolidation or a health check on already-organized notes.
