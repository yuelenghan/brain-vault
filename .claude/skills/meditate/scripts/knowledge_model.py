#!/usr/bin/env python3
"""Pure knowledge-model helpers for deterministic meditate understanding."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


MIN_OWNERSHIP_AREA_CONCEPTS = 3
WIKILINK_RE = re.compile(r"!?(?<!\!)\[\[([^\]]+)\]\]")

CONCEPT_STOPWORDS = {
    "about",
    "across",
    "after",
    "agent",
    "agents",
    "also",
    "always",
    "analysis",
    "anything",
    "actual",
    "answer",
    "auth",
    "back",
    "because",
    "before",
    "being",
    "between",
    "build",
    "change",
    "complete",
    "course",
    "current",
    "could",
    "data",
    "does",
    "driven",
    "each",
    "every",
    "else",
    "flag",
    "from",
    "give",
    "gets",
    "have",
    "help",
    "into",
    "know",
    "like",
    "long",
    "look",
    "lose",
    "make",
    "more",
    "most",
    "note",
    "notes",
    "once",
    "only",
    "over",
    "part",
    "pattern",
    "people",
    "preserve",
    "preserves",
    "read",
    "real",
    "reference",
    "rather",
    "running",
    "session",
    "sessions",
    "should",
    "single",
    "stay",
    "stays",
    "system",
    "that",
    "than",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "those",
    "this",
    "through",
    "turn",
    "uses",
    "using",
    "weak",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "work",
    "works",
    "would",
    "push",
    "your",
}

GENERIC_CONCEPT_PHRASES = {
    "actually get",
    "actually gets",
    "actually think",
    "annual conference",
    "annual meeting",
    "arxiv preprint",
    "become context",
    "become useful",
    "best ways",
    "better input",
    "computational linguistic",
    "create four",
    "different place",
    "embedding ragmem0",
    "emoosryoa s-mem",
    "first time",
    "first week",
    "independent rater",
    "information processing",
    "international conference",
    "neural information",
    "next step",
    "obsidian vault",
    "preprint arxiv",
    "processing system",
    "project folder",
    "prompt claude",
    "replication package",
    "return config",
    "rough idea",
    "simplemem memoryo",
    "three days",
    "three phase",
    "vegetarian restaurant",
    "what changed",
    "week four",
}

GENERIC_TOPIC_RELATION_PHRASES = {
    "language model",
}


@dataclass
class ModelNote:
    path: str
    title: str
    aliases: list[str]
    body: str
    kind: str


@dataclass
class TopicProfile:
    topic: str
    dir: str
    names: list[str] = field(default_factory=list)
    material_count: int = 0
    has_readme: bool = False
    concept_counts: Counter[str] = field(default_factory=Counter)


@dataclass
class OwnershipProfile:
    path: str
    title: str
    aliases: list[str]
    body: str
    concept_counts: Counter[str] = field(default_factory=Counter)

    def __post_init__(self) -> None:
        if not self.concept_counts:
            text = f"{Path(self.path).stem}\n{self.title}\n{self.body}"
            self.concept_counts = concept_counts_for_text(text)


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", Path(name).stem.strip()).lower()


def text_mentions_name(text: str, name: str) -> bool:
    if not name:
        return False

    def accepted(start: int, end: int) -> bool:
        window = text[max(0, start - 96) : min(len(text), end + 96)]
        negative_patterns = (
            r"不直接关联",
            r"不关联",
            r"无关",
            r"not\s+directly\s+related",
            r"not\s+related",
        )
        return not any(re.search(pattern, window, flags=re.IGNORECASE) for pattern in negative_patterns)

    if re.fullmatch(r"[A-Za-z0-9 _.-]+", name):
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
        return any(accepted(match.start(), match.end()) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    lowered_text = text.lower()
    lowered_name = name.lower()
    start = 0
    while True:
        idx = lowered_text.find(lowered_name, start)
        if idx < 0:
            return False
        if accepted(idx, idx + len(name)):
            return True
        start = idx + len(name)


def normalize_concept_token(token: str) -> str:
    token = token.lower().strip("-_")
    if token.endswith("ies") and len(token) > 5:
        token = token[:-3] + "y"
    elif token.endswith(("ches", "shes", "sses", "xes", "zes")) and len(token) > 5:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 4 and not token.endswith(("sis", "ss", "us", "ys")):
        token = token[:-1]
    return token


def meaningful_concept_token(token: str) -> bool:
    if len(token) < 4:
        return False
    if token in CONCEPT_STOPWORDS:
        return False
    if token.isdigit():
        return False
    if len(token) > 32:
        return False
    if re.search(r"\d{2,}", token):
        return False
    if re.search(r"\d+(?:st|nd|rd|th)$", token):
        return False
    return True


CJK_GENERATED_MARKERS = (
    "资料索引",
    "主题来源",
    "主题定位",
    "概念画像",
    "适用范围",
    "核心概念",
    "资料数量",
    "下一步",
    "自动承接",
    "分化概念",
    "上级承接",
    "稳定主题",
    "形成稳定知识簇",
    "重新理解",
    "长期复用",
    "持续由",
    "更新画像",
    "重构边界",
    "优化",
)

CJK_GENERIC_FRAGMENT_MARKERS = (
    "当前判断",
    "提供了一个",
    "都应",
    "也要",
    "应该",
    "是否",
    "持续积累",
    "需要同时",
    "关键不是",
    "本质是",
    "价值在于",
    "更快转成",
    "负责生成",
    "实际工作中",
    "不只是",
    "先判断",
    "先转换",
    "不属于现有",
    "而不是",
    "不是一个",
    "而是",
    "变成",
    "很重要",
    "如果未来",
    "待补充",
)


def normalize_cjk_concept(phrase: str) -> str:
    phrase = phrase.strip()
    strip_prefixes = ("一个典型的", "还应该包括", "价值在于降低", "以及", "并且", "同时", "的", "一个", "再提炼", "先定义")
    changed = True
    while changed:
        changed = False
        for prefix in strip_prefixes:
            if phrase.startswith(prefix) and len(phrase) > len(prefix) + 3:
                phrase = phrase[len(prefix) :]
                changed = True
                break
    return phrase


def meaningful_cjk_concept(phrase: str) -> bool:
    if len(phrase) < 4:
        return False
    if any(marker in phrase for marker in CJK_GENERATED_MARKERS):
        return False
    if any(marker in phrase for marker in CJK_GENERIC_FRAGMENT_MARKERS):
        return False
    if phrase.startswith("当前"):
        return False
    if phrase.startswith("在") and phrase.endswith("中"):
        return False
    if phrase.endswith(("和", "与", "或")):
        return False
    if len(phrase) > 18 and any(marker in phrase for marker in ("应该", "需要", "可以", "如果", "而不是")):
        return False
    return True


def concept_counts_for_text(text: str) -> Counter[str]:
    text = WIKILINK_RE.sub(" ", text)
    counts: Counter[str] = Counter()
    chunks = re.findall(r"[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[A-Za-z][A-Za-z0-9-]*)*", text)
    for chunk in chunks:
        segment: list[str] = []
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9-]*", chunk):
            token = normalize_concept_token(raw)
            if not meaningful_concept_token(token):
                for first, second in zip(segment, segment[1:]):
                    if first != second:
                        counts[f"{first} {second}"] += 2
                segment = []
                continue
            counts[token] += 1
            segment.append(token)
        for first, second in zip(segment, segment[1:]):
            if first != second:
                counts[f"{first} {second}"] += 2
    for cjk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        concept = normalize_cjk_concept(cjk)
        if meaningful_cjk_concept(concept):
            counts[concept] += 1
    return counts


def note_concept_counts(note: ModelNote) -> Counter[str]:
    text = f"{Path(note.path).stem}\n{note.title}\n{note.body}"
    return concept_counts_for_text(text)


def concept_can_drive_structure(term: str) -> bool:
    if term in GENERIC_CONCEPT_PHRASES:
        return False
    if " " in term:
        return True
    return bool(re.search(r"[\u4e00-\u9fff]", term)) and len(term) >= 4


def concept_can_drive_topic_relation(term: str) -> bool:
    if term in GENERIC_TOPIC_RELATION_PHRASES:
        return False
    return concept_can_drive_structure(term)


def top_concepts_from_counts(counts: Counter[str], limit: int = 12) -> list[str]:
    items = [
        (term, count)
        for term, count in counts.items()
        if count > 0 and concept_can_drive_structure(term)
    ]
    items.sort(key=lambda item: (-item[1], -len(item[0].split()), item[0]))
    return [term for term, _count in items[:limit]]


def top_concepts(profile: TopicProfile, limit: int = 12) -> list[str]:
    return top_concepts_from_counts(profile.concept_counts, limit)


def concept_topic_frequency(profiles: dict[str, TopicProfile]) -> Counter[str]:
    frequency: Counter[str] = Counter()
    for profile in profiles.values():
        for term in set(top_concepts(profile, limit=24)):
            frequency[term] += 1
    return frequency


def topic_relation_candidates(
    profiles: dict[str, TopicProfile],
    min_shared_concepts: int = 3,
    min_topic_materials: int = 3,
    max_concept_topic_frequency: int = 3,
) -> list[dict]:
    frequency = concept_topic_frequency(profiles)
    candidates: list[dict] = []
    sorted_profiles = sorted(
        (profile for profile in profiles.values() if profile.material_count >= min_topic_materials),
        key=lambda profile: profile.topic,
    )
    for left_index, left in enumerate(sorted_profiles):
        left_terms = {
            term
            for term in top_concepts(left, limit=24)
            if concept_can_drive_topic_relation(term)
            and 1 < frequency.get(term, 0) <= max_concept_topic_frequency
        }
        for right in sorted_profiles[left_index + 1 :]:
            right_terms = {
                term
                for term in top_concepts(right, limit=24)
                if concept_can_drive_topic_relation(term)
                and 1 < frequency.get(term, 0) <= max_concept_topic_frequency
            }
            exact_pair_terms = {
                term
                for term in left_terms & right_terms
                if frequency.get(term, 0) == 2
            }
            small_cluster_terms = {
                term
                for term in left_terms & right_terms
                if 2 < frequency.get(term, 0) <= max_concept_topic_frequency
            }
            shared = exact_pair_terms
            if len(small_cluster_terms) >= min_shared_concepts:
                shared = shared | small_cluster_terms
            shared = sorted(shared)
            if len(shared) < min_shared_concepts:
                continue
            candidates.append(
                {
                    "source_topic": left.topic,
                    "target_topic": right.topic,
                    "source_dir": left.dir,
                    "target_dir": right.dir,
                    "concepts": shared[:8],
                    "score": len(shared),
                    "reason": "resource topics share distinctive stable concepts",
                }
            )
    candidates.sort(key=lambda item: (-item["score"], item["source_topic"], item["target_topic"]))
    return candidates


def ownership_concept_frequency(profiles: dict[str, OwnershipProfile]) -> Counter[str]:
    frequency: Counter[str] = Counter()
    for profile in profiles.values():
        for term in set(top_concepts_from_counts(profile.concept_counts, limit=24)):
            frequency[term] += 1
    return frequency


def stable_topic_concepts(notes: list[ModelNote], topic: str, limit: int = 12) -> list[str]:
    counts: Counter[str] = Counter()
    doc_frequency: Counter[str] = Counter()
    topic_prefix = f"Resources/{topic}/"
    for note in notes:
        if not note.path.startswith(topic_prefix) or note.kind not in {"reference", "archive"}:
            continue
        note_counts = note_concept_counts(note)
        for term, count in note_counts.items():
            if not concept_can_drive_structure(term):
                continue
            counts[term] += count
            doc_frequency[term] += 1
    items = [
        (term, count)
        for term, count in counts.items()
        if doc_frequency[term] >= 2
    ]
    items.sort(key=lambda item: (-item[1], -len(item[0].split()), item[0]))
    return [term for term, _count in items[:limit]]


def title_starts_with_concept(note: ModelNote, concept: str) -> bool:
    concept_key = normalize_name(concept)
    if not concept_key:
        return False
    for name in (Path(note.path).stem, note.title):
        key = normalize_name(name)
        if re.fullmatch(r"[a-z0-9 ._-]+", concept_key):
            if key == concept_key or key.startswith(f"{concept_key} "):
                return True
        elif key.startswith(concept_key):
            return True
    return False


def title_mentions_concept(note: ModelNote, concept: str) -> bool:
    concept_key = normalize_name(concept)
    if not concept_key:
        return False
    for name in (Path(note.path).stem, note.title):
        key = normalize_name(name)
        if key == concept_key or text_mentions_name(name, concept):
            return True
    return False


def scored_resource_subclusters(
    material_notes: list[ModelNote],
    topic_key: str,
    min_cluster_materials: int,
    title_matcher,
) -> list[tuple[int, int, str, list[ModelNote]]]:
    concept_notes: dict[str, list[ModelNote]] = defaultdict(list)
    concept_counts: Counter[str] = Counter()
    for note in material_notes:
        counts = note_concept_counts(note)
        for term, count in counts.items():
            if not concept_can_drive_structure(term):
                continue
            if normalize_name(term) == topic_key:
                continue
            if not title_matcher(note, term):
                continue
            concept_notes[term].append(note)
            concept_counts[term] += count

    scored: list[tuple[int, int, str, list[ModelNote]]] = []
    for term, grouped_notes in concept_notes.items():
        unique_notes = sorted({note.path: note for note in grouped_notes}.values(), key=lambda item: item.path)
        if len(unique_notes) < min_cluster_materials:
            continue
        scored.append((len(unique_notes), concept_counts[term], term, unique_notes))
    scored.sort(key=lambda item: (item[0], item[1], len(item[2].split()), item[2]), reverse=True)
    return scored


def resource_topic_split_decision(
    notes: list[ModelNote],
    topic: str,
    min_topic_materials: int = 5,
    min_cluster_materials: int = 3,
) -> dict:
    material_notes = [
        note
        for note in notes
        if note.path.startswith(f"Resources/{topic}/") and note.kind in {"reference", "archive"}
    ]
    base = {
        "topic": topic,
        "topic_dir": f"Resources/{topic}",
        "topic_material_count": len(material_notes),
        "material_count": len(material_notes),
        "concept": "",
        "note_paths": [],
        "evidence_count": 0,
    }
    if len(material_notes) < min_topic_materials:
        return {
            **base,
            "status": "insufficient_topic_materials",
            "reason": "resource topic has too few material notes for a safe split",
        }

    topic_key = normalize_name(topic)
    scored = scored_resource_subclusters(
        material_notes,
        topic_key,
        min_cluster_materials,
        title_starts_with_concept,
    )
    reason = "stable title-leading subcluster inside a broad resource topic"
    if not scored:
        scored = scored_resource_subclusters(
            material_notes,
            topic_key,
            min_cluster_materials,
            title_mentions_concept,
        )
        reason = "stable title-contained concept subcluster inside a broad resource topic"
        if not scored:
            return {
                **base,
                "status": "no_title_leading_subcluster",
                "reason": "no stable title-leading or title-contained subcluster reached the safe split threshold",
            }

    best_doc_count, best_count, concept, cluster_notes = scored[0]
    tied = [item for item in scored if item[0] == best_doc_count and item[1] == best_count]
    decision = {
        **base,
        "material_count": best_doc_count,
        "concept": concept,
        "note_paths": [note.path for note in cluster_notes],
        "evidence_count": best_count,
    }
    if len(tied) > 1:
        return {
            **decision,
            "status": "ambiguous",
            "reason": "multiple resource subclusters have the same evidence score",
        }
    if best_doc_count >= len(material_notes):
        whole_topic_reason = "all material notes share a more specific title-leading topic"
        if reason.startswith("stable title-contained"):
            whole_topic_reason = "all material notes share a more specific title-contained concept topic"
        return {
            **decision,
            "status": "whole_topic_rename",
            "reason": whole_topic_reason,
        }
    return {
        **decision,
        "status": "split_candidate",
        "reason": reason,
    }


def ownership_concept_match_score(
    note: ModelNote,
    profile: OwnershipProfile,
    concept_frequency: Counter[str],
) -> tuple[int, list[str]]:
    note_terms = {
        term
        for term in note_concept_counts(note)
        if concept_can_drive_structure(term)
    }
    owner_terms = {
        term
        for term in top_concepts_from_counts(profile.concept_counts, limit=20)
        if concept_frequency.get(term, 0) == 1
    }
    matched = sorted(note_terms & owner_terms)
    if len(matched) < MIN_OWNERSHIP_AREA_CONCEPTS:
        return 0, []
    return len(matched), matched


def topic_equivalence_keys(profile: TopicProfile) -> set[str]:
    keys: set[str] = set()
    for name in profile.names:
        normalized = normalize_name(name)
        if not normalized:
            continue
        keys.add(normalized)
        if re.fullmatch(r"[a-z0-9 ._-]+", normalized):
            words = normalized.split()
            if words and words[-1].endswith("s") and len(words[-1]) > 3:
                words[-1] = words[-1][:-1]
                keys.add(" ".join(words))
    return keys


def canonical_topic_for_equivalent_group(group: list[TopicProfile]) -> TopicProfile:
    return sorted(
        group,
        key=lambda profile: (
            profile.has_readme,
            profile.material_count,
            profile.topic.endswith("s"),
            len(profile.topic),
            profile.topic,
        ),
        reverse=True,
    )[0]


def equivalent_topic_canonical_map(profiles: dict[str, TopicProfile]) -> dict[str, str]:
    by_key: dict[str, list[TopicProfile]] = defaultdict(list)
    for profile in profiles.values():
        for key in topic_equivalence_keys(profile):
            by_key[key].append(profile)
    canonical: dict[str, str] = {}
    for group in by_key.values():
        unique = {profile.topic: profile for profile in group}
        if len(unique) < 2:
            continue
        winner = canonical_topic_for_equivalent_group(list(unique.values()))
        for topic in unique:
            if topic != winner.topic:
                current = canonical.get(topic)
                if current is None:
                    canonical[topic] = winner.topic
                else:
                    current_profile = profiles[current]
                    canonical[topic] = canonical_topic_for_equivalent_group([current_profile, winner]).topic
    return canonical


def topic_match_score(note: ModelNote, profile: TopicProfile) -> tuple[int, list[str]]:
    title_text = f"{Path(note.path).stem}\n{note.title}"
    body = note.body
    score = 0
    matched: list[str] = []
    seen: set[str] = set()
    for name in profile.names:
        key = normalize_name(name)
        if key in seen:
            continue
        title_match = text_mentions_name(title_text, name)
        body_match = text_mentions_name(body, name)
        if not title_match and not body_match:
            continue
        seen.add(key)
        matched.append(name)
        if title_match:
            score += 4
        if body_match:
            score += 1
    return score, matched


def topic_concept_match_score(
    note: ModelNote,
    profile: TopicProfile,
    concept_frequency: Counter[str] | None = None,
) -> tuple[int, list[str]]:
    if profile.material_count < 2:
        return 0, []
    note_terms = {
        term
        for term in note_concept_counts(note)
        if concept_can_drive_structure(term)
    }
    profile_terms = set(top_concepts(profile, limit=16))
    if concept_frequency is not None:
        profile_terms = {term for term in profile_terms if concept_frequency.get(term, 0) == 1}
    matched = sorted(note_terms & profile_terms)
    if len(matched) < MIN_OWNERSHIP_AREA_CONCEPTS:
        return 0, []
    return len(matched), matched
