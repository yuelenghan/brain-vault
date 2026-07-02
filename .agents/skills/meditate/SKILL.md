---
name: meditate
description: Meditate on already-organized Projects/Areas/Resources/Archive notes in a brain vault — handle historical duplicates, add newly-relevant wikilinks, fix broken links, find missing ownership, build topic indexes, and emit an auditable auditable report. Prefer this skill when the user mentions meditate, deduplicate, link repair, knowledge-base health check, finding duplicate notes, or improving Obsidian wikilinks. Do not use it to organize Inbox; new material still goes through ingest.
---

# Meditate on brain-vault for Codex sessions

This is the Codex-session entry point for brain-vault meditation. The working directory must be the vault root.

## Execution rules

1. First read `.claude/skills/meditate/SKILL.md`; it is the canonical workflow for organized-note optimization.
2. Follow that canonical file strictly. If this file conflicts with `.claude/skills/meditate/SKILL.md`, the `.claude` file wins.
3. If `.claude/skills/meditate/SKILL.md` does not exist, stop and say the vault is missing the canonical brain-vault meditate skill, so vault meditation cannot be run safely.
4. Only process `Projects/`, `Areas/`, `Resources/`, and `Archive/`; do not organize `Inbox/`.
5. Use the canonical fixed report paths: `/tmp/meditate.json` and `/tmp/meditate.md`; do not pass alternate report paths or `--vault`.
6. Auto-deduplication only trusts normalized URLs, recomputed `source_fingerprint`, or compatible legacy `content_fingerprint`; do not auto-move or edit files based on stale strict fingerprints.
7. Run the scripts named by the canonical `.claude` skill. This entry point intentionally does not own meditate execution logic.
