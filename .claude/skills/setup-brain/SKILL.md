---
name: setup-brain
description: Initialize or refine this brain-vault — run a pre-check, quickly fill the shared identity layer in `CLAUDE.md` (identity, goals, current projects, and collaboration-preference handling) with AskUserQuestion so Claude Code, Codex, and Copilot can all consume it, then optionally verify local organize tools (markitdown, Pillow, whisper, ffmpeg) and configure organize capabilities. Use this whenever the user says /setup-brain, setup brain, initialize brain-vault, 初始化 brain-vault, 补全身份层, 首次配置这个 vault, or wants to refine this repo's brain-vault setup.
---

# Setup Brain

You are the brain-vault initialization wizard. The goal is a safe, repeatable initialization in the current vault root. Do not read or exfiltrate credentials. Do not delete user files. Confirm before running install commands, overwriting existing config, committing to git, or scheduling tasks.

## Prerequisites

- The working directory should be the brain-vault root.
- If the current directory is not a git repository, say so first and ask whether to initialize git.
- If `CLAUDE.md` already contains real user content, do not silently overwrite it; read it first and explain which sections will be updated.

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
command -v python3 || true
command -v python3 >/dev/null && python3 -c "import importlib.util, sys; sys.stdout.write('Pillow\n' if importlib.util.find_spec('PIL') else '')" || true
```

Command hits in pre-check only establish detection. Before claiming a tool is ready, verify it with `--help`, an import check, or the relevant validation command from the sections below.

If there are uncommitted changes, do not auto-overwrite the related files; list them as protected paths.

After pre-check, do not dump the raw command output back to the user. Summarize only the few facts that affect the next step:

- whether the current directory is the vault root,
- whether this is a git repository and whether the worktree is clean,
- whether the shared identity-layer file still looks like a template or already contains real user content,
- whether the core PARA directories already exist,
- whether any protected paths, missing prerequisites, or notable AI CLI detection status will change what happens next.

Keep this handoff short: usually 3-6 bullets plus one transition sentence. Use status words such as `ready`, `template`, `detected`, `missing`, or `protected` so the user can scan quickly. Avoid ending with a long free-text questionnaire such as “please answer these 4 questions”. Instead, give one short recommendation and then immediately open the Stage A `AskUserQuestion` interaction.

A good Chinese handoff looks like this:

```markdown
基础检查已完成：
- 当前目录正确，且是 git 仓库。
- 工作区干净。
- PARA 目录已存在。
- `CLAUDE.md` 里的共享身份层仍是模板，适合先做快速初始化。
- 工具目前仅完成 detected 级检查；是否继续 capability verification 可以稍后再定。

建议先完成共享身份层初始化；下面我会用一轮简短的交互式问题收集信息。
```

### 2. Interview the user

Prefer a two-stage interview.

#### Stage A: quick initialization (recommended)

Use one `AskUserQuestion` call with 4 questions so the user can answer in a single interactive panel and switch between questions. Prefer suggestion-style options over forcing the user to compose everything from scratch. Adapt labels, descriptions, and previews to the user's language.

Unless the user already provided equivalent information, Stage A should cover exactly these 4 slots and put the recommended option first with `(Recommended)`:

1. `身份` — choose a summary style such as `单一角色`, `多重角色`, or `转型中`.
2. `目标` — choose a goal structure such as `三项目标`, `按主题`, or `按里程碑`.
3. `项目` — choose a project layout such as `简短列表`, `按优先级`, or `按领域`.
4. `偏好` — choose whether to `保留现有`, `轻微调整`, or `完全替换` the existing collaboration preferences.

Use `preview` for the first 3 questions when comparing answer shapes; the collaboration-preference question usually does not need a preview. Explain that the built-in `Other` path can be used for custom input when none of the suggestions fit.

For the exact default Stage A payload and copy-ready option wording, read `references/interactive-prompts.md` before drafting the interaction.

If the user is not working in Chinese, localize the wording but keep the same structure, recommendation order, and preview intent.

After the interactive answers return, ask only for the missing concrete text needed to fill `## Who I am`, `## This year's goals`, and `## Current projects`. Keep this follow-up short and structured, and match the template to the formats the user selected. For example:

```markdown
Please fill in the template below:
- Who I am: I am a …, mainly responsible for …, current focus is …
- This year's goals:
  - …
  - …
  - …
- Current projects:
  1. Project A: …
  2. Project B: …
```

If the user chose `轻微调整` or `完全替换`, add `- 协作偏好：……` to the same follow-up instead of opening a fresh broad interview.

Recommend this path first. Explain that organize capability choices, AI CLI verification, and automation can be configured afterward if needed.

If the user only wants a quick initialization, conservative defaults are acceptable: keep existing collaboration preferences, create empty PARA directories, and only detect tools without installing. Do not pull Stage B questions into the first round unless the user explicitly asks to continue capability setup.

#### Stage B: optional capability details

Only ask follow-up questions when the user explicitly wants to customize capabilities after Stage A, or when a later decision depends on them. Prefer `AskUserQuestion` here as well because these are mostly bounded choices. Keep each call within the tool limit of 1-4 questions; if needed, use a second short call instead of a large free-text prompt.

Scope discipline matters in Stage B:

- If the user only wants one Stage B slot, ask only that slot; do not reconstruct the full Stage B checklist.
- If the user already said some slots should be skipped, deferred, or handled later, confirm that in one short line and do not reopen those slots in the same turn.
- If the user is asking for the *shape of the next question* rather than asking you to actually continue the whole setup, answer with the exact next bounded question you would send, not a broader recap of unrelated setup work.
- Do not drag shared-identity-layer collection back into a Stage B-only turn unless the user explicitly asked to resume Stage A or you are actually about to update `CLAUDE.md`.

Stage B should usually cover these 3 slots, and if the user only wants a subset, trim the payload rather than asking irrelevant questions:

1. `格式` — choose among `文档+图片 (Recommended)`, `仅文档`, `仅图片`, or `暂不启用`.
2. `转录` — choose among `暂不启用 (Recommended)`, `启用默认`, `稍后再配`, or `现在指定`.
3. `自动化` — choose among `手动运行 (Recommended)`, `会话内定时`, `系统定时`, or `以后再说`.

For the exact default Stage B payload and canonical option wording, read `references/interactive-prompts.md` before drafting the interaction.

Only ask for free-text details after a Stage B choice actually requires them. For example, ask for Whisper model/language only after `现在指定`.

When the user narrows Stage B to a single slot, keep the answer equally narrow:

- `格式` only → ask only the `格式` question and stop there.
- `转录` only + `现在指定` → first acknowledge that `格式` / `自动化` stay skipped or deferred, then ask only for `Whisper model` and `language`.
- In that transcription-only branch, do **not** re-ask whether the user accepts first-download behavior if they already said they want to specify the values now; save the reminder for the final output or the moment before a real transcription.
- In that transcription-only branch, do **not** pull `Who I am` / `goals` / `projects` back into the turn unless the user explicitly switched back to identity initialization.

### 3. Generate or update the shared identity layer

Update these sections in `CLAUDE.md` from the user's answers:

- `## Who I am`
- `## This year's goals`
- `## Collaboration preferences`
- `## Current projects`

Treat `CLAUDE.md` as the canonical shared identity layer for this vault — the single maintenance source. Claude Code reads it directly; Codex and DeepSeek Harness read `AGENTS.md`, which is a symlink to `CLAUDE.md` (`AGENTS.md -> CLAUDE.md`) so content stays identical by construction. If the symlink is ever replaced by a plain file (e.g. Windows checkout or accidental edit), `.githooks/pre-commit` restores it on the next commit, or run `.claude/bin/sync-agents-md` manually. Never edit `AGENTS.md` directly. `.github/copilot-instructions.md` should point Copilot at the same sections rather than duplicating identity text.

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

### 5. Tool detection and limited CLI verification

#### Basic detection

- `markitdown`: converts `.doc/.docx/.xls/.xlsx/.ppt/.pptx/.pdf/.txt/.text/.markdown/.csv/.json/.jsonl/.html/.htm/.epub/.ipynb` to Markdown.
- `Pillow`: generates screenshot-placeholder Markdown for `.png/.jpg/.jpeg/.webp`.
- `whisper`: converts `.mp3/.m4a/.wav/.mp4/.mov/.aac/.aiff/.flac/.ogg/.opus/.webm` to Markdown.
- `ffmpeg`: local dependency required by Whisper to decode audio/video.
- Whisper model: the first real transcription may download the default model; verify the current default model and `--model` parameter with `whisper --help`, and specify via `WHISPER_MODEL` if needed.
- `copilot` / `gh copilot`: for the GitHub Copilot CLI entry.
- `codex`: for the OpenAI Codex CLI entry.
- `uv`, `brew`, `python3`: used to decide the recommended install path.

#### Install principles

- Cloning the repository does not install any tool.
- Detection and read-only verification need no confirmation; confirm before running any install command.
- For AI CLI support in this template, focus on detecting and verifying existing commands, not on guiding installation.
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

If the user wants to confirm which AI CLI entries in this repo are already usable, do read-only verification only:

1. If `copilot` is available, run `copilot --help` to verify the command works.
2. If `gh` is available, run `gh copilot --help` to verify the GitHub CLI entry is present.
3. If `codex` is available, run `codex --help` to verify the command works. If the command exists but fails to start, report that clearly as detected-but-not-usable instead of turning setup into an installation guide.
4. Do not ask a dedicated Stage B AI CLI question. Only surface this verification when the user explicitly asks, or as a short factual note in the pre-check / final summary.
5. Explain the repo entry points factually when relevant: `.claude/` is canonical, `.agents/` is the Codex app/session copy, `.codex/` is the Codex CLI thin entry, and `.copilot/` plus `.github/copilot-instructions.md` are the Copilot CLI / GitHub Copilot entries.

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
test -x .claude/ingest.sh
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

Treat this as an after-initialization option, not a first-round requirement. If the user wants auto-organize after the identity layer is initialized, explain the three options. The default recommendation is now **ingest + meditate rhythm**: run `ingest` first, then `meditate` after it. Nightly cadence = `ingest.sh` then `meditate.sh nightly`; weekly cadence = `ingest.sh` then `meditate.sh weekly`.

- In-session: use a Claude Code scheduled task to trigger `/ingest` and `/meditate`; closing the session or task expiry affects execution.
- System-level: use crontab/launchd to run `VAULT=/path/to/brain .claude/ingest.sh` and then `VAULT=/path/to/brain .claude/meditate.sh nightly`, plus a weekly `VAULT=/path/to/brain .claude/meditate.sh weekly`. On Windows, prefer Task Scheduler with the PowerShell ingest entry plus the same meditate shell entry through a compatible shell.
- Manual: periodically run `/ingest`, `/meditate`, `.claude/ingest.sh`, `.claude/ingest.ps1`, or `.claude/meditate.sh [nightly|weekly]`.

Confirm before modifying the system crontab/launchd.

### 8. Final verification and output

Run:

```bash
git status --short
```

Keep the output concise and organized around outcomes the user can act on:

- Shared identity layer initialized: which sections in `CLAUDE.md` were updated.
- Multi-client alignment: Codex / Copilot entry files now point to the same shared identity layer.
- Capability status: document conversion, screenshot placeholder, audio/video transcription, and AI CLI verification status.
- Use status words such as `detected`, `verified usable`, `missing`, or `deferred` so command detection is not confused with readiness.
- Reminders: Whisper default model / model-download reminder when transcription is enabled or requested.
- Next steps: put material into `Inbox/` and run `/ingest`; run `/recall` when you want to query existing knowledge; run `/meditate` or `.claude/meditate.sh [nightly|weekly]` when you want consolidation or a health check on already-organized notes.
