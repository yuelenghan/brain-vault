---
name: recall
description: Recall from the brain-vault by spreading activation over titles, aliases, concepts, and wikilinks, then log retrieval outcomes back into .claude/recall.log. Triggers: 回忆、recall、问 brain、brain 里有什么、检索笔记、我之前记过什么、查一下笔记.
---

# Recall for Codex sessions

This is the Codex-session entry point for brain-vault recall.

1. First read `.claude/skills/recall/SKILL.md`; it is the canonical workflow.
2. Follow that file strictly. If this file conflicts with `.claude/skills/recall/SKILL.md`, the `.claude` file wins.
3. If `.claude/skills/recall/SKILL.md` does not exist, stop and say the vault is missing the canonical brain-vault recall skill.
4. Use the canonical fixed report paths under the current OS temp directory: `<tempdir>/recall.json` and `<tempdir>/recall.md`.
5. Run `.claude/skills/recall/scripts/recall.py`, not `.agents/skills/.../scripts/...`.
