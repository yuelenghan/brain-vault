# Meditate 通用知识重构与压缩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改写原始笔记的前提下，为 `meditate weekly` 增加由候选报告和提交安全门共同约束的通用知识重构与压缩能力。

**Architecture:** `optimize_vault.py` 只做确定性发现、锚点选择、关系证据和 source-set digest；它在 scan/apply-safe 中只报告，不生成知识核心。weekly headless agent 只可按 JSON 候选更新 anchor 内的 `knowledge-restructuring` marker；`cadence_guard.py` 在暂存和提交后检查目标、marker 边界、digest、来源链接和全量候选覆盖，任何失败都阻止整轮提交。

**Tech Stack:** Python 3 标准库、`unittest`、zsh、Git、现有 vault Markdown / wikilink 约定。

---

## File structure

- `.claude/skills/meditate/scripts/optimize_vault.py`：确定性簇发现、marker 排除、report / Markdown / log 字段。
- `.claude/skills/meditate/scripts/cadence_guard.py`：weekly prompt、重构 marker 解析、staged / committed 全量审计。
- `.claude/bin/safe-git-commit`：提交前调用统一 guard，拒绝任何 weekly 重构越界。
- `.claude/meditate.sh`：weekly 必经深度重构阶段、全量候选契约、失败原子性和 log 计数。
- `.claude/skills/meditate/SKILL.md`：canonical weekly contract、安全门和输出字段。
- `.claude/skills/meditate/tests/test_memory_cycle.py`：候选发现、scope / anchor / protected / digest 回归测试。
- `.claude/skills/meditate/tests/test_cadence_guard.py`：prompt、marker 边界、digest、source links、全量候选审计测试。
- `.claude/skills/meditate/tests/test_runtime_entry_layout.py`：headless weekly 契约文本与 shell syntax 回归测试。

### Task 1: Define the deterministic restructuring candidate contract

**Files:**
- Modify: `.claude/skills/meditate/tests/test_memory_cycle.py`
- Modify: `.claude/skills/meditate/scripts/optimize_vault.py`

- [ ] **Step 1: Write a failing Project-scope cluster test**

Add a fixture with one Project ownership note as the only anchor and three material notes whose bodies share three stable concepts and explicit version / wikilink evidence. Assert that scan returns a high-confidence candidate with stable `cluster_id`, `scope`, `anchor_path`, sorted `member_paths`, `source_set_digest`, and `action == "refresh_anchor"`.

```python
self.assertEqual("Projects/Example.md", candidate["anchor_path"])
self.assertEqual("high", candidate["confidence"])
self.assertEqual("refresh_anchor", candidate["action"])
self.assertEqual(3, len(candidate["member_paths"]))
self.assertTrue(candidate["source_set_digest"].startswith("sha256:"))
self.assertIn("refines", {item["kind"] for item in candidate["relations"]})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_memory_cycle.MemoryCycleTest.test_build_report_emits_project_restructuring_candidate
```

Expected: FAIL because `restructuring_candidates` is absent from the report.

- [ ] **Step 3: Add source-material and scope helpers**

Add these constants and functions beside the existing generated-section constants and `source_body_for_hash()`:

```python
KNOWLEDGE_RESTRUCTURING_BEGIN_RE = re.compile(
    r"<!-- BEGIN: knowledge-restructuring cluster=(?P<cluster_id>kr-[a-f0-9]+) -->"
)
KNOWLEDGE_RESTRUCTURING_END = "<!-- END: knowledge-restructuring -->"

def note_source_digest(note: Note) -> str:
    return "sha256:" + hashlib.sha256(
        source_body_for_hash(note_text(note)).encode("utf-8")
    ).hexdigest()

def restructuring_scope_for_note(vault: Path, note: Note) -> str | None:
    topic = resource_topic_name(note.path)
    if topic:
        return f"Resources/{topic}"
    return unique_owner_scope(vault, note)
```

Extend `source_body_for_hash()` so the full restructuring marker is skipped. This makes generated knowledge cores unable to change a member's source identity.

- [ ] **Step 4: Implement `restructuring_candidates()` with deterministic evidence**

Implement a function that groups only material notes in the same unique scope, requires both structural and semantic evidence, emits pairwise generic relation kinds, chooses exactly one existing natural anchor, and returns report-only records with an explicit blocker whenever safe writing is unavailable:

```python
def restructuring_candidates(vault: Path, notes: list[Note], protected: set[str]) -> list[dict]:
    """Return sorted generic knowledge-restructuring clusters; never write notes."""
    scoped = group_material_notes_by_restructuring_scope(vault, notes)
    findings = [
        candidate_for_cluster(vault, scope, members, protected)
        for scope, members in sorted(scoped.items())
    ]
    return sorted(findings, key=lambda item: (item["scope"], item["cluster_id"]))
```

For each write-eligible cluster, include exactly these fields:

```python
{
    "cluster_id": "kr-42f3c2a1",
    "scope": "Projects/example",
    "anchor_path": "Projects/example.md",
    "member_paths": ["Projects/example/Design v1.md", "Projects/example/Design v2.md", "Projects/example/Validation.md"],
    "relations": [{"from": "Projects/example/Design v1.md", "to": "Projects/example/Design v2.md", "kind": "refines", "evidence": ["explicit_link", "shared_concepts"]}],
    "evidence": {"structural": ["all members link Projects/example.md"], "semantic": ["three shared stable concepts: policy, evidence, validation"]},
    "source_set_digest": "sha256:42f3c2a13a4f2d09d416e1b4de5b0e5124567890abcdeffedcba09876543210",
    "last_restructured_digest": None,
    "action": "refresh_anchor",
    "reason": "unique anchor and dual evidence",
    "confidence": "high",
}
```

Use `related_unknown` or a report-only blocker for ambiguous relation evidence; never upgrade an uncertain relation. Limit clusters to 12 members and require a unique strong-edge split before writing a subcluster.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_memory_cycle.MemoryCycleTest.test_build_report_emits_project_restructuring_candidate
```

Expected: PASS.

- [ ] **Step 6: Commit the contract slice**

```bash
git add .claude/skills/meditate/scripts/optimize_vault.py .claude/skills/meditate/tests/test_memory_cycle.py
git commit -m "feat(meditate): report generic restructuring candidates"
```

### Task 2: Cover generic scope, safety blockers, and idempotent digest behavior

**Files:**
- Modify: `.claude/skills/meditate/tests/test_memory_cycle.py`
- Modify: `.claude/skills/meditate/scripts/optimize_vault.py`

- [ ] **Step 1: Write failing safety and idempotence tests**

Add independent tests for Resource topic and Area ownership scopes, protected anchor/member, anchor collision, invalid source / unresolved source link, ambiguous relationship, oversized unsplittable cluster, conflict retention, and digest idempotence. The tests must assert an explicit blocker rather than merely an empty candidate list.

```python
self.assertEqual("report_only", candidate["action"])
self.assertIn("anchor_protected", candidate["blockers"])
self.assertIn("source_missing", candidate["blockers"])
self.assertEqual([], eligible_after_existing_digest)
self.assertEqual("conflicts", candidate["relations"][0]["kind"])
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_memory_cycle.MemoryCycleTest.test_restructuring_candidates_respect_safety_blockers .claude.skills.meditate.tests.test_memory_cycle.MemoryCycleTest.test_restructuring_digest_is_idempotent_until_source_changes
```

Expected: FAIL until the candidate records contain the required blocker and historical-digest semantics.

- [ ] **Step 3: Complete eligibility and last-digest logic**

Parse existing anchor marker metadata by cluster id. If its source-set digest equals the recomputed digest, omit it from write-eligible candidates. A source-body change or member-set change must produce a new digest and candidate. Preserve `conflicts` as a high-confidence write-eligible relation, but never choose a winner.

```python
def restructuring_marker_digests(text: str) -> dict[str, str]:
    """Map marker cluster id to its recorded source-set digest without trusting body prose."""
    found: dict[str, str] = {}
    for match in KNOWLEDGE_RESTRUCTURING_BEGIN_RE.finditer(text):
        end = text.find(KNOWLEDGE_RESTRUCTURING_END, match.end())
        if end == -1:
            continue
        block = text[match.end():end]
        digest = re.search(r"来源集：(?P<digest>sha256:[0-9a-f]{64})", block)
        if digest:
            found[match.group("cluster_id")] = digest.group("digest")
    return found

def restructuring_blockers(
    anchor_path: str | None,
    member_paths: list[str],
    protected: set[str],
    relation_is_unique: bool,
    source_links_valid: bool,
) -> list[str]:
    blockers: set[str] = set()
    if anchor_path is None:
        blockers.add("anchor_collision")
    if anchor_path in protected:
        blockers.add("anchor_protected")
    if any(path in protected for path in member_paths):
        blockers.add("member_protected")
    if not relation_is_unique:
        blockers.add("relation_ambiguous")
    if not source_links_valid:
        blockers.add("source_missing")
    return sorted(blockers)
```

- [ ] **Step 4: Run the focused safety suite and verify GREEN**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_memory_cycle
```

Expected: PASS, including existing synthesis / restatement behavior.

- [ ] **Step 5: Commit the safety slice**

```bash
git add .claude/skills/meditate/scripts/optimize_vault.py .claude/skills/meditate/tests/test_memory_cycle.py
git commit -m "test(meditate): cover restructuring safety gates"
```

### Task 3: Publish the report, Markdown, and local-log contract

**Files:**
- Modify: `.claude/skills/meditate/tests/test_memory_cycle.py`
- Modify: `.claude/skills/meditate/scripts/optimize_vault.py`

- [ ] **Step 1: Write failing report-contract tests**

Assert that `build_report()` and `refresh_report_findings()` publish `restructuring_candidates` at the top level and under `report_only`, that scan Markdown has an auditable count / blocker section, and that `append_log()` reserves `- 知识重构：0`.

```python
self.assertEqual(report["restructuring_candidates"], report["report_only"]["restructuring_candidates"])
self.assertIn("知识重构候选", optimize_vault.markdown_report(report))
self.assertIn("- 知识重构：0", log_path.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_memory_cycle.MemoryCycleTest.test_restructuring_report_and_log_contract
```

Expected: FAIL until report and log fields exist.

- [ ] **Step 3: Wire candidates through both report paths**

Update `build_report()` and `refresh_report_findings()` to calculate candidates from the current index and expose the same deterministic records in `report_only`. Extend `markdown_report()` to list each cluster id, scope, anchor, member count, action, confidence, and blockers. Extend `append_log()` with a fixed `知识重构` zero line; deterministic apply-safe never changes it.

- [ ] **Step 4: Run the report contract tests and verify GREEN**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_memory_cycle
```

Expected: PASS.

- [ ] **Step 5: Commit the report slice**

```bash
git add .claude/skills/meditate/scripts/optimize_vault.py .claude/skills/meditate/tests/test_memory_cycle.py
git commit -m "feat(meditate): expose restructuring report contract"
```

### Task 4: Add strict marker and source validation to the shared weekly guard

**Files:**
- Modify: `.claude/skills/meditate/tests/test_cadence_guard.py`
- Modify: `.claude/skills/meditate/scripts/cadence_guard.py`

- [ ] **Step 1: Write failing guard tests for allowed targets and malformed output**

Construct a report with two high-confidence write candidates and commits that respectively write the wrong anchor, change anchor text outside the marker, use the wrong digest, point to a non-existent filename stem, and omit one target. Assert that every violation is reported by its exact key.

```python
self.assertEqual(["Projects/other.md"], summary["unauthorized_restructuring_paths"])
self.assertEqual(["Projects/example.md"], summary["marker_boundary_violations"])
self.assertEqual(["Projects/example.md"], summary["digest_mismatches"])
self.assertEqual(["Projects/example.md"], summary["invalid_source_links"])
self.assertEqual(["kr-second"], summary["missing_restructuring_clusters"])
```

- [ ] **Step 2: Run the focused guard tests and verify RED**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_cadence_guard.CadenceGuardTest.test_audit_weekly_restructuring_rejects_invalid_marker_output
```

Expected: FAIL because restructuring audit fields do not yet exist.

- [ ] **Step 3: Implement report target extraction and marker parser**

Add a separate target function and a strict parser that accepts only complete marker blocks with the approved cluster id and source-set digest:

```python
def restructuring_targets_from_report(report: dict) -> list[dict]:
    return sorted(
        [item for item in report.get("restructuring_candidates", [])
         if item.get("action") == "refresh_anchor" and item.get("confidence") == "high"],
        key=lambda item: (item["anchor_path"], item["cluster_id"]),
    )

def parse_restructuring_blocks(text: str) -> list[dict]:
    """Return complete marker blocks and their source wikilinks; reject malformed / duplicate spans."""
    blocks: list[dict] = []
    for match in KNOWLEDGE_RESTRUCTURING_BEGIN_RE.finditer(text):
        end = text.find(KNOWLEDGE_RESTRUCTURING_END, match.end())
        if end == -1:
            return []
        body = text[match.end():end]
        digest = re.search(r"来源集：(?P<digest>sha256:[0-9a-f]{64})", body)
        blocks.append({"cluster_id": match.group("cluster_id"), "digest": digest.group("digest") if digest else None, "body": body})
    return blocks
```

Use the vault's filename-stem index to resolve every `[[target]]`; aliases are allowed only after the stem exists. Check each `K-*` entry has a source; `supersedes` / `conflicts` need at least two. Guard marker changes against a before/after byte-exact outside-marker comparison.

- [ ] **Step 4: Extend staged and committed audit summaries**

Extend `summarize_semantic_changes()` and both audit entrypoints so their JSON has old synthesis/restatement fields plus:

```python
{
    "restructuring_paths": ["Projects/example.md"],
    "unauthorized_restructuring_paths": [],
    "marker_boundary_violations": [],
    "digest_mismatches": [],
    "invalid_source_links": [],
    "invalid_knowledge_entries": [],
    "missing_restructuring_clusters": [],
}
```

Return non-zero if any of these lists is non-empty. Do not impose a numeric cap: every eligible candidate must be present exactly once.

- [ ] **Step 5: Run the full guard suite and verify GREEN**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_cadence_guard
```

Expected: PASS for authorized all-candidate updates and all rejection cases.

- [ ] **Step 6: Commit the guard slice**

```bash
git add .claude/skills/meditate/scripts/cadence_guard.py .claude/skills/meditate/tests/test_cadence_guard.py
git commit -m "feat(meditate): guard weekly restructuring markers"
```

### Task 5: Bind the weekly runtime to every eligible restructuring candidate

**Files:**
- Modify: `.claude/skills/meditate/tests/test_runtime_entry_layout.py`
- Modify: `.claude/meditate.sh`
- Modify: `.claude/bin/safe-git-commit`

- [ ] **Step 1: Write failing runtime-layout tests**

Assert the weekly prompt says `restructuring_candidates` are processed in full, says no candidate cap exists, invokes the shared guard before commit and after commit, and patches a `知识重构` count. Assert it does not retain the obsolete `最多 2` or `最多 3` prose.

```python
self.assertIn("全部高置信、可写 restructuring_candidates", text)
self.assertIn("audit-weekly-staged", text)
self.assertIn("audit-weekly-commit", text)
self.assertNotIn("最多 2 个 synthesis_candidates", text)
self.assertNotIn("最多 3 个 restatement_candidates", text)
```

- [ ] **Step 2: Run the runtime-layout test and verify RED**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_runtime_entry_layout.RuntimeEntryLayoutTest.test_weekly_runtime_requires_all_restructuring_candidates
```

Expected: FAIL until the weekly prompt and audit flow change.

- [ ] **Step 3: Update `cadence_guard.py` prompt and log patch API**

Make `weekly_prompt_from_report()` list allowed restructuring target records (cluster id, anchor, members, digest, relation evidence) in addition to the compatible old fields. Extend `update_latest_log_semantic_fields()` and the `patch-log` command with `--restructuring-count`, preserving old log entries and always writing the latest entry's three semantic counters.

- [ ] **Step 4: Update commit wrapper and zsh cadence**

`safe-git-commit` must reject all restructuring guard violations from staged content. In `.claude/meditate.sh`, calculate the deep trigger from eligible restructuring candidates, always enter the weekly deep stage even when the eligible count is zero, tell the agent to write every candidate or record `无可安全重构项`, audit the commit, and fail if an eligible candidate is missing. Parse guard JSON to patch `语义综合`, `再巩固`, and `知识重构` counts.

```zsh
CADENCE_PROMPT="本次为 weekly 深度周期：必须处理 report 中全部高置信、可写 restructuring_candidates；不得设置数量上限。若没有可安全候选，记录 无可安全重构项 和逐簇 blocker。$WEEKLY_GUARD_PROMPT"
```

Do not run semantic generation in `scan`, `apply-safe`, `nightly`, or normal interactive meditate.

- [ ] **Step 5: Run syntax and runtime-layout tests and verify GREEN**

Run:

```bash
zsh -n .claude/meditate.sh
python3 -m unittest .claude.skills.meditate.tests.test_runtime_entry_layout
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit the cadence slice**

```bash
git add .claude/meditate.sh .claude/bin/safe-git-commit .claude/skills/meditate/scripts/cadence_guard.py .claude/skills/meditate/tests/test_runtime_entry_layout.py
git commit -m "feat(meditate): run weekly restructuring atomically"
```

### Task 6: Document the canonical operating contract

**Files:**
- Modify: `.claude/skills/meditate/SKILL.md`
- Modify: `.claude/skills/meditate/tests/test_runtime_entry_layout.py`

- [ ] **Step 1: Write a failing canonical-documentation assertion**

Add a layout test requiring the skill to state: weekly-only deep restructuring, original notes retained, all eligible candidates processed atomically, exact report / marker boundaries, and concrete blocker reporting.

```python
self.assertIn("知识重构与压缩", text)
self.assertIn("无可安全重构项", text)
self.assertIn("全部高置信、可写候选", text)
self.assertIn("knowledge-restructuring", text)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_runtime_entry_layout.RuntimeEntryLayoutTest.test_canonical_skill_documents_weekly_restructuring_contract
```

Expected: FAIL before the canonical documentation is updated.

- [ ] **Step 3: Update the canonical skill**

Add the report schema, allowed marker block, relation vocabulary, three-layer safety gate, weekly-only cadence, no-cap / no-partial-commit rule, `知识重构` log field, and final-output wording for “无可安全重构项”. Keep `.agents`, `.codex`, and `.copilot` as thin canonical references; do not copy implementation into them.

- [ ] **Step 4: Run the focused documentation test and verify GREEN**

Run:

```bash
python3 -m unittest .claude.skills.meditate.tests.test_runtime_entry_layout.RuntimeEntryLayoutTest.test_canonical_skill_documents_weekly_restructuring_contract
```

Expected: PASS.

- [ ] **Step 5: Commit the documentation slice**

```bash
git add .claude/skills/meditate/SKILL.md .claude/skills/meditate/tests/test_runtime_entry_layout.py
git commit -m "docs(meditate): document weekly knowledge restructuring"
```

### Task 7: Run the final regression and safety verification

**Files:**
- Verify: `.claude/skills/meditate/scripts/optimize_vault.py`
- Verify: `.claude/skills/meditate/scripts/cadence_guard.py`
- Verify: `.claude/bin/safe-git-commit`
- Verify: `.claude/meditate.sh`
- Verify: `.claude/skills/meditate/tests/`

- [ ] **Step 1: Run all automated regressions**

```bash
python3 -m unittest discover -s .claude/skills/meditate/tests
python3 -m py_compile .claude/skills/meditate/scripts/optimize_vault.py .claude/skills/meditate/scripts/cadence_guard.py .claude/bin/safe-git-commit
zsh -n .claude/meditate.sh
git diff --check master...HEAD
```

Expected: every command exits 0.

- [ ] **Step 2: Inspect the final diff and protected-input boundary**

```bash
git diff --name-only master...HEAD
git -C <vault-root> status --short
```

Expected: the implementation branch changes only canonical skill/runtime/test files; the primary checkout still shows only its two original untracked Inbox files and no staged content from this work.

- [ ] **Step 3: Commit any final verification-only corrections**

```bash
git status --short
git add .claude/skills/meditate/scripts/optimize_vault.py .claude/skills/meditate/scripts/cadence_guard.py .claude/bin/safe-git-commit .claude/meditate.sh .claude/skills/meditate/SKILL.md .claude/skills/meditate/tests/test_memory_cycle.py .claude/skills/meditate/tests/test_cadence_guard.py .claude/skills/meditate/tests/test_runtime_entry_layout.py
git commit -m "test(meditate): verify restructuring safety contract"
```

Do not create an empty commit. Report exact branch, commits, verification output, and that merge into `master` remains a separate user decision.
