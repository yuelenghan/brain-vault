---
name: meditate
description: Meditate on already-organized Projects/Areas/Resources/Archive notes in a brain vault — re-understand existing knowledge, reconnect wikilinks, handle historical duplicates, fix broken links, find missing ownership, build topic indexes, and emit an auditable report. Prefer this skill when the user mentions meditate, 冥想 vault, 知识冥想, 去重, deduplicate, 补链, link repair, 知识库体检, finding duplicate notes, improving Obsidian wikilinks, or asks for the nightly/weekly sleep-cycle cadence for organized notes. Do not use it to organize Inbox; new material still goes through ingest.
---

# Meditate on brain-vault for Codex sessions

This is the Codex-session entry point for brain-vault meditation. The working directory must be the vault root.

## Execution rules

1. First read `.claude/skills/meditate/SKILL.md`; it is the canonical workflow for organized-note meditation.
2. Follow that canonical file strictly. If this file conflicts with `.claude/skills/meditate/SKILL.md`, the `.claude` file wins.
3. If `.claude/skills/meditate/SKILL.md` does not exist, stop and say the vault is missing the canonical brain-vault meditate skill, so vault meditation cannot be run safely.
4. If the user explicitly asks for `nightly` or `weekly` cadence, route the run through `.claude/meditate.sh nightly` or `.claude/meditate.sh weekly` from the vault root, then continue following the canonical `.claude` skill for verification and reporting.
5. Only process `Projects/`, `Areas/`, `Resources/`, and `Archive/`; do not organize `Inbox/`.
6. Use the canonical fixed report paths: `/tmp/meditate.json` and `/tmp/meditate.md`; do not pass alternate report paths or `--vault`.
7. Auto-deduplication only trusts normalized URLs, recomputed non-empty `source_fingerprint`, or same-original-file evidence; legacy `content_fingerprint` is compatible but must not be treated as a strict stale/invalid signal.
8. Each run rebuilds the local deterministic knowledge model from current filenames, titles, aliases, topics, README aliases, Area/Project ownership profiles, existing links, explicit mentions, and extracted concept profiles; `apply-safe` may add high-confidence links, ownership backlinks, generated topic/ownership profiles, topic relations, safe structure moves, and its self-check must fail if moved-path wikilinks remain broken.
9. Run the scripts named by the canonical `.claude` skill. Do not switch to `.agents/skills/.../scripts/...`; this entry point intentionally does not own meditate execution logic.
