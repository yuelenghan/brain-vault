---
name: optimize-vault
description: Optimize already-organized Projects/Areas/Resources/Archive notes in a brain vault — handle historical duplicates, add newly-appeared wikilinks, fix broken links, find missing supporting notes, distill topic indexes, and output an auditable optimization report. When users mention optimize vault, deduplicate-vault, link optimization, optimize after organizing, knowledge-base health check, find duplicate notes, or improve Obsidian wikilinks, prefer this skill; do not use it to organize Inbox — new material still goes through organize-inbox.
---

# Optimize Vault for Copilot CLI

This is the brain-vault GitHub Copilot CLI plugin skill. The working directory must be the vault root.

## Execution rules

1. First read `.claude/skills/optimize-vault/SKILL.md`; it is the canonical rule source for the organized-note optimization flow.
2. Execute strictly per that file. If this file conflicts with `.claude/skills/optimize-vault/SKILL.md`, `.claude/skills/optimize-vault/SKILL.md` wins.
3. If `.claude/skills/optimize-vault/SKILL.md` does not exist, stop and state the repo is missing the brain-vault Claude Code skill and cannot safely optimize.
4. Only optimize `Projects/`, `Areas/`, `Resources/`, `Archive/`; do not organize `Inbox/`.
5. Prefer the fixed report paths: `/tmp/optimize-vault.json` and `/tmp/optimize-vault.md`. Do not pass other report paths or `--vault` to the optimizer script.
6. Auto-deduplication only trusts recomputed body fingerprints or normalized URLs; do not auto-move or edit files based on stale `content_fingerprint` values in frontmatter that do not match.
