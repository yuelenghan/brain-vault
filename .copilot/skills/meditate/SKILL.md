---
name: meditate
description: Meditate on already-organized Projects/Areas/Resources/Archive notes in a brain vault — handle historical duplicates, add newly-relevant wikilinks, fix broken links, find missing ownership, build topic indexes, and emit an auditable auditable report. Prefer this skill when users mention meditate, deduplicate, link repair, knowledge-base health check, finding duplicate notes, or improving Obsidian wikilinks; do not use it to organize Inbox — new material still goes through ingest.
---

# Meditate for Copilot CLI

This is the brain-vault GitHub Copilot CLI plugin skill. The working directory must be the vault root.

## Execution rules

1. First read `.claude/skills/meditate/SKILL.md`; it is the canonical rule source for the organized-note optimization flow.
2. Execute strictly per that file. If this file conflicts with `.claude/skills/meditate/SKILL.md`, `.claude/skills/meditate/SKILL.md` wins.
3. If `.claude/skills/meditate/SKILL.md` does not exist, stop and state the repo is missing the brain-vault Claude Code skill and cannot safely optimize.
4. Only process `Projects/`, `Areas/`, `Resources/`, `Archive/`; do not organize `Inbox/`.
5. Use the canonical fixed report paths: `/tmp/meditate.json` and `/tmp/meditate.md`. Do not pass other report paths or `--vault` to the optimizer script.
6. Auto-deduplication only trusts normalized URLs, recomputed `source_fingerprint`, or compatible legacy `content_fingerprint`; do not auto-move or edit files based on stale strict fingerprints.
