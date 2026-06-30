---
name: setup-brain
description: Initialize brain-vault — interview the user for identity and goals, generate CLAUDE.md, check PARA directories, git status, local conversion tools (markitdown, Pillow, whisper, ffmpeg) and AI CLIs (copilot, codex), and install missing tools on user confirmation.
---

# Setup Brain

You are the brain-vault initialization wizard. The goal is a safe, repeatable initialization in the current vault root. Do not read or exfiltrate credentials. Do not delete user files. Confirm before running install commands, overwriting existing config, committing to git, or setting up scheduled tasks.

## Preconditions

- The working directory should be the brain-vault root.
- If the current directory is not a git repo, explain first and ask whether to init git.
- If `CLAUDE.md` already contains real user content, do not silently overwrite; read it first and state which sections will be updated.

## Initialization flow

### 1. Precheck

Run and record:

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

If there are uncommitted changes, do not auto-overwrite the related files; list them as protected paths.

### 2. Interview the user

Ask for the necessary information in one pass to avoid repeated interruptions:

1. Who are you? Role, main responsibilities, professional focus?
2. What are the most important goals this year or near-term?
3. What are the active projects? One sentence each.
4. How do you want Claude to collaborate? E.g. preference for concise conclusions, detailed reasoning, autonomous execution, cautious confirmation, etc.
5. Which file formats do you plan to organize? Enable document/data/web/Notebook conversion (Word/PDF/PPT/Excel/TXT/CSV/JSON/HTML/EPUB/IPYNB → Markdown) and screenshot-placeholder capability (image → Markdown placeholder)?
6. Enable audio/video transcription (audio/video → Markdown)? If yes, accept downloading the Whisper model on first real transcription, and do you need to specify a model or language?
7. Need Copilot CLI or Codex CLI support?
8. Need offline auto-organize? If yes, prefer manually running `organize.sh`, system crontab/launchd, or in-session Claude Code scheduling?

If the user only wants a quick init, conservative defaults are fine: keep existing collaboration preferences, create empty PARA directories, detect tools only without installing.

### 3. Generate or update CLAUDE.md

Update from the user's answers:

- `## Who I am`
- `## This year's goals`
- `## Collaboration preferences`
- `## Current projects`

Keep the Vault conventions, common commands, tool tiers, and project-level pitfalls below. Do not write temporary task state, one-off info, or credentials.

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
.claude/skills/organize-inbox/
.claude/skills/optimize-vault/
.codex/skills/setup-brain/
.codex/skills/organize-inbox/
.codex/skills/optimize-vault/
.copilot/.github/plugin/
.copilot/skills/setup-brain/
.copilot/skills/organize-inbox/
.copilot/skills/optimize-vault/
```

Keep empty directories with `.gitkeep`.

### 5. Tool detection and install guidance

#### Basic detection

- `markitdown`: for `.doc/.docx/.xls/.xlsx/.ppt/.pptx/.pdf/.txt/.text/.markdown/.csv/.json/.jsonl/.html/.htm/.epub/.ipynb` → Markdown.
- `Pillow`: for `.png/.jpg/.jpeg/.webp` → screenshot-placeholder Markdown.
- `whisper`: for `.mp3/.m4a/.wav/.mp4/.mov/.aac/.aiff/.flac/.ogg/.opus/.webm` → Markdown.
- `ffmpeg`: local dependency Whisper needs to decode audio/video.
- Whisper model: the first real transcription may download the default model; verify the current default model and `--model` parameter with `whisper --help`, and specify via `WHISPER_MODEL` if needed.
- `copilot` / `gh copilot`: for GitHub Copilot CLI.
- `codex`: for OpenAI Codex CLI.
- `uv`, `brew`, `npm`, `python3`: for recommending install paths.

#### Install principles

- Cloning the repo does not auto-install any tool.
- Detection only needs no confirmation; confirm before running install commands.
- Prefer giving commands and letting the user decide whether to run them.
- Do not guess package names or parameters; before installing, verify the command with the existing tool's `--help` or official/local docs. When unverifiable, state the uncertainty and let the user install manually.

#### Recommended install paths

If the user enables document conversion and lacks `markitdown`:

1. If `uv` is present, first run `uv tool install --help` to verify the command exists, then suggest:

   ```bash
   uv tool install markitdown
   ```

2. If no `uv` but `python3` is present, suggest the user pick their own Python package manager to install MarkItDown; do not guess a global pip strategy for them.
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

2. If `whisper` is missing and `brew` is present, first run `brew info openai-whisper` to verify the formula exists; if the output shows it depends on `ffmpeg`, Homebrew will handle that dependency, then suggest:

   ```bash
   brew install openai-whisper
   ```

3. If `ffmpeg` is missing and will not be installed via `brew install openai-whisper`, first run `brew info ffmpeg` to verify the formula exists, then suggest:

   ```bash
   brew install ffmpeg
   ```

4. If no `brew` but `uv` is present, first run `uv pip install --help` to verify the command exists; installing Whisper via Python usually needs a target environment, and `ffmpeg` may still need separate install — let the user choose the environment first; do not silently install globally.
5. If the user already has a Python or system package manager, allow them to provide the install command.
6. Verify after install:

   ```bash
   command -v whisper
   command -v ffmpeg
   whisper --help
   ffmpeg -version
   ```

`whisper --help` shows the current default model and `--model` parameter; if the default is not what the user wants, suggest running organize with `WHISPER_MODEL=<model name>`. Whisper models can be large and the first real transcription may download one; do not silently trigger a model download at setup time — remind the user before real transcription.

If the user enables Copilot CLI support:

1. If `copilot` is present, run `copilot --help` to verify it works.
2. If no `copilot` but `gh` is present, run `gh copilot --help` to verify GitHub CLI support; you may suggest the user start with `gh copilot` or download Copilot CLI.
3. Confirm before login, download, update, or modifying Copilot config.
4. Note that `.github/copilot-instructions.md` is this repo's Copilot instructions file, and `.copilot/.github/plugin/plugin.json` and `.copilot/skills/*/SKILL.md` are in-project Copilot CLI plugin skills; before running `copilot init`, check whether it would overwrite existing customization.

If the user enables Codex CLI support:

1. If `codex` is present, run `codex --help` to verify it works; if the command exists but reports a missing binary or startup failure, suggest reinstalling or repairing.
2. If no `codex` but `npm` is present, suggest:

   ```bash
   npm install -g @openai/codex
   ```

3. If `brew` is present, suggest:

   ```bash
   brew install --cask codex
   ```

4. Confirm before installing, logging in, or configuring an API key.
5. Note that `AGENTS.md` is the general agent instructions file, and `.codex/skills/*/SKILL.md` are in-project Codex skills, for Codex CLI and other agents to reference.

### 6. Wrapper check

Confirm these files exist and are executable:

```bash
test -x .claude/bin/safe-markitdown
test -x .claude/bin/safe-whisper
test -x .claude/bin/safe-mkdir
test -x .claude/bin/safe-git-add
test -x .claude/bin/safe-git-mv
test -x .claude/bin/safe-git-commit
test -x .claude/bin/organize-inbox-scan
test -x .claude/bin/organize-inbox-prepare
test -x .claude/bin/organize-inbox-apply-duplicates
```

If not executable, run:

```bash
chmod +x .claude/bin/safe-markitdown .claude/bin/safe-whisper .claude/bin/safe-mkdir .claude/bin/safe-git-add .claude/bin/safe-git-mv .claude/bin/safe-git-commit .claude/bin/organize-inbox-scan .claude/bin/organize-inbox-prepare .claude/bin/organize-inbox-apply-duplicates .claude/organize.sh
```

Run syntax checks:

```bash
python3 -m py_compile .claude/bin/safe-markitdown .claude/bin/safe-whisper .claude/bin/safe-mkdir .claude/bin/safe-git-add .claude/bin/safe-git-mv .claude/bin/safe-git-commit .claude/bin/organize-inbox-scan .claude/bin/organize-inbox-prepare .claude/bin/organize-inbox-apply-duplicates
zsh -n .claude/organize.sh
python3 -m json.tool .copilot/.github/plugin/plugin.json >/tmp/brain-vault-plugin-json-check.out
```

### 7. Optional auto-organize

If the user wants auto-organize, explain three options:

- In-session: trigger `/organize-inbox` via Claude Code scheduling, but session close or task expiry affects runs.
- System-level: call `VAULT=/path/to/brain .claude/organize.sh` via crontab/launchd.
- Manual: periodically run `/organize-inbox` or `.claude/organize.sh`.

Confirm before modifying system crontab/launchd.

### 8. Final verification and output

Run:

```bash
git status --short
```

Keep the output concise:

- Initialized identity-layer sections.
- Tool status: `markitdown` installed/not installed, `whisper` installed/not installed, `ffmpeg` installed/not installed, Whisper default model / model-download reminder, `copilot` installed/not installed, `codex` installed/not installed.
- Enabled capabilities: Markdown organize, document/data/web/Notebook conversion, screenshot placeholder, audio/video transcription, organized-note optimization, Copilot CLI instructions and plugin skills, Codex/general-agent instructions and in-project skills.
- Next steps: put material into `Inbox/` and run `/organize-inbox`; run `/optimize-vault` when you want a health check on organized notes.
