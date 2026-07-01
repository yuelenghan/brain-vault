---
name: optimize-vault
description: Optimize already-organized Projects/Areas/Resources/Archive notes in a brain vault — handle historical duplicates, add newly-relevant wikilinks, fix broken links, find missing ownership, build topic indexes, and emit an auditable optimization report. Prefer this skill when the user mentions optimize vault, deduplicate-vault, link optimization, knowledge-base health check, finding duplicate notes, or improving Obsidian wikilinks. Do not use it to organize Inbox; new material still goes through ingest.
---

# Optimize brain-vault for Codex sessions

This is the Codex-session entry point for brain-vault optimization. The working directory must be the vault root.

## Execution rules

1. First read `.claude/skills/optimize-vault/SKILL.md`; it is the canonical workflow for organized-note optimization.
2. Follow that canonical file strictly. If this file conflicts with `.claude/skills/optimize-vault/SKILL.md`, the `.claude` file wins.
3. If `.claude/skills/optimize-vault/SKILL.md` does not exist, stop and say the vault is missing the canonical brain-vault optimize-vault skill, so vault optimization cannot be run safely.
4. Only optimize `Projects/`, `Areas/`, `Resources/`, and `Archive/`; do not organize `Inbox/`.
5. Use the canonical fixed report paths: `/tmp/optimize-vault.json` and `/tmp/optimize-vault.md`; do not pass alternate report paths or `--vault`.
6. Auto-deduplication only trusts normalized URLs, recomputed `source_fingerprint`, or compatible legacy `content_fingerprint`; do not auto-move or edit files based on stale strict fingerprints.
7. Run the scripts named by the canonical `.claude` skill. This entry point intentionally does not own optimize-vault execution logic.
