---
name: recall
description: Recall from the brain-vault by spreading activation over titles, aliases, concepts, and wikilinks, then log retrieval outcomes back into .claude/recall.log. Triggers: 回忆、recall、问 brain、brain 里有什么、检索笔记、我之前记过什么、查一下笔记；以及任何需要参考 vault 已有笔记回答的知识性、方案性、项目相关问题（即使用户没有明说检索）。回答此类问题时必须先走本 skill，不得用裸 Grep/Read 代替。
---

# Recall for Codex sessions

This is the Codex-session entry point for brain-vault recall.

1. First read `.claude/skills/recall/SKILL.md`; it is the canonical workflow.
2. Follow that file strictly. If this file conflicts with `.claude/skills/recall/SKILL.md`, the `.claude` file wins.
3. If `.claude/skills/recall/SKILL.md` does not exist, stop and say the vault is missing the canonical brain-vault recall skill.
4. In normal query mode, omit `--json` and `--markdown`; the canonical script writes `<tempdir>/recall.json` and `<tempdir>/recall.md` under the current OS temp directory. If explicit paths are needed, compute `<tempdir>` with `python3 -c 'import tempfile; print(tempfile.gettempdir())'`; do not try `/tmp` first.
5. Run `.claude/skills/recall/scripts/recall.py`, not `.agents/skills/.../scripts/...`.
6. Do not show tempdir discovery or path-correction chatter to the user unless recall still fails after using the computed fixed paths.
