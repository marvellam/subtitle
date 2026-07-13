from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced with an actionable message at runtime
    yaml = None


TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$")
CORRUPT_TEXT_RE = re.compile(r"\?{4,}|�|锟")
DEFAULT_STANDALONE_FILLERS = ("啊", "哈", "嗯", "呃", "哎", "唉", "额", "uh", "yeah", "okay", "ok", "hm", "hmm")
DEFAULT_REVIEW_WORDS = ("这个", "那个", "那么", "其实", "就是", "对吧", "是吧", "你看", "好不好")
VALID_PHASE1_DECISIONS = {"accepted", "reverted", "adjusted"}


class SemanticGuardError(ValueError):
    """Raised when clustered high-impact edits look like rewriting, not proofreading."""

    def __init__(self, message: str, review_rows: list[dict[str, object]]):
        super().__init__(message)
        self.review_rows = review_rows


def configure_console_output() -> None:
    """Keep CLI status output safe on legacy Windows console encodings."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")



@dataclass(frozen=True)
class LexiconRule:
    wrong: str
    correct: str
    category: str
    confidence: str
    condition: str
    source_lesson: str
    note: str
    status: str = "active"
    verified_count: str = ""
    last_verified: str = ""


def read_text(path: Path) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=enc), enc
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Cannot decode {path}")


def load_yaml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required to read project.yml/style_rules.yml. Install with: python -m pip install pyyaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def load_project_config(project: Path) -> dict:
    return load_yaml_file(project / "project.yml")


def load_style_rules(project: Path) -> dict:
    return load_yaml_file(project / "style_rules.yml")


def as_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, dict):
        term = str(value.get("term", "")).strip()
        return [term] if term else []
    return []


def timestamp_to_ms(value: str) -> tuple[int, int]:
    numbers = [int(part) for part in re.findall(r"\d+", value)]
    if len(numbers) != 8:
        raise ValueError(f"Invalid timestamp: {value}")
    start = ((numbers[0] * 60 + numbers[1]) * 60 + numbers[2]) * 1000 + numbers[3]
    end = ((numbers[4] * 60 + numbers[5]) * 60 + numbers[6]) * 1000 + numbers[7]
    return start, end


def structural_errors(items: list[dict[str, str]]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    expected = [str(i) for i in range(1, len(items) + 1)]
    actual = [item["index"] for item in items]
    if actual != expected:
        errors.append({"type": "index_sequence_invalid", "value": f"expected 1..{len(items)}"})
    previous_start = -1
    for item in items:
        try:
            start, end = timestamp_to_ms(item["timestamp"])
        except ValueError:
            continue
        if start >= end:
            errors.append({"type": "timestamp_nonpositive", "value": item["timestamp"], "index": item["index"]})
        if start < previous_start:
            errors.append({"type": "timestamp_start_not_monotonic", "value": item["timestamp"], "index": item["index"]})
        previous_start = start
    return errors


def parse_srt(text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff\n ")
    blocks = re.split(r"\n{2,}", normalized)
    items: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for block_no, block in enumerate(blocks, 1):
        if not block.strip():
            continue
        lines = block.split("\n")
        if len(lines) < 2:
            errors.append({"block": str(block_no), "type": "too_few_lines", "value": block[:100]})
            continue
        idx = lines[0].strip()
        timestamp = lines[1].strip() if len(lines) > 1 else ""
        body = "\n".join(lines[2:]) if len(lines) > 2 else ""
        if not idx.isdigit():
            errors.append({"block": str(block_no), "type": "index_not_digit", "value": idx})
        if not TIME_RE.match(timestamp):
            errors.append({"block": str(block_no), "type": "timestamp_invalid", "value": timestamp})
        items.append({"index": idx, "timestamp": timestamp, "text": body})
    return items, errors


def dump_srt(items: list[dict[str, str]]) -> str:
    return "\n\n".join(f"{it['index']}\n{it['timestamp']}\n{it['text']}" for it in items) + "\n"


def items_fingerprint(items: list[dict[str, str]]) -> str:
    return hashlib.sha256(dump_srt(items).encode("utf-8")).hexdigest()


def load_lexicon(project: Path) -> list[LexiconRule]:
    path = project / "lexicon.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f)
        return [
            LexiconRule(
                wrong=(r.get("wrong") or "").strip(),
                correct=(r.get("correct") or "").strip(),
                category=(r.get("category") or "").strip(),
                confidence=(r.get("confidence") or "review").strip().lower(),
                condition=(r.get("condition") or "").strip(),
                source_lesson=(r.get("source_lesson") or "").strip(),
                note=(r.get("note") or "").strip(),
                status=(r.get("status") or "active").strip().lower(),
                verified_count=(r.get("verified_count") or "").strip(),
                last_verified=(r.get("last_verified") or "").strip(),
            )
            for r in rows
            if (r.get("wrong") or "").strip() and (r.get("status") or "active").strip().lower() not in {"disabled", "rejected"}
        ]


def load_blacklist(project: Path) -> list[dict[str, str]]:
    path = project / "blacklist.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f) if (r.get("term") or "").strip()]


def load_protected_terms(project: Path, lexicon: list[LexiconRule] | None = None) -> list[str]:
    terms: list[str] = []
    path = project / "protected_terms.csv"
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                term = (row.get("term") or "").strip()
                if term:
                    terms.append(term)
    for rule in lexicon or load_lexicon(project):
        if rule.wrong == rule.correct:
            terms.append(rule.wrong)
    return list(dict.fromkeys(terms))


def context_text(items: list[dict[str, str]], pos: int, radius: int) -> str:
    start = max(0, pos - radius)
    end = min(len(items), pos + radius + 1)
    return " / ".join(f"{it['index']}:{it['text']}" for it in items[start:end])


def condition_met(condition: str, ctx: str) -> bool:
    if not condition:
        return True
    tokens = [t.strip() for t in re.split(r"[|,，、\s]+", condition) if t.strip()]
    return any(t in ctx for t in tokens)


def apply_lexicon(text: str, ctx: str, rules: list[LexiconRule]) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    current = text
    applied: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    grouped: dict[str, list[LexiconRule]] = {}
    for rule in rules:
        # wrong == correct is a canonical/protected term, not a replacement.
        if rule.wrong == rule.correct or rule.status in {"disabled", "rejected"}:
            continue
        grouped.setdefault(rule.wrong, []).append(rule)

    # Longer source phrases must run before shorter overlapping phrases.
    for wrong in sorted(grouped, key=len, reverse=True):
        if wrong not in current:
            continue
        candidates = grouped[wrong]
        active_corrections = {rule.correct for rule in candidates}
        certified = [rule for rule in candidates if rule.confidence == "auto" and rule.status in {"active", "certified"}]
        certified_corrections = {rule.correct for rule in certified}
        if len(active_corrections) == 1 and len(certified_corrections) == 1:
            chosen = certified[0]
            count = current.count(wrong)
            current = current.replace(wrong, chosen.correct)
            applied.append({
                "old": wrong,
                "new": chosen.correct,
                "count": str(count),
                "category": chosen.category,
                "risk": "low" if chosen.confidence == "auto" else "medium",
                "note": chosen.note,
            })
        elif len(active_corrections) > 1:
            suggestions = " / ".join(sorted(active_corrections))
            reviews.append({
                "term": wrong,
                "suggestion": suggestions,
                "category": "词库冲突",
                "risk": "high",
                "note": "multiple lexicon corrections match this context; do not auto-replace",
            })
        else:
            suggestions = " / ".join(dict.fromkeys(rule.correct for rule in candidates))
            matched_conditions = [rule.condition for rule in candidates if rule.confidence == "conditional" and condition_met(rule.condition, ctx)]
            reviews.append({
                "term": wrong,
                "suggestion": suggestions,
                "category": candidates[0].category,
                "risk": "medium",
                "note": "candidate only; Agent must decide from context" + (f"; matched conditions: {' | '.join(matched_conditions)}" if matched_conditions else ""),
            })
    return current, applied, reviews


def cleanup_fillers(text: str, style_rules: dict | None = None) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    style_rules = style_rules or {}
    speech = style_rules.get("speech_fillers") or {}
    standalone = set(as_string_list(speech.get("standalone_blank")) or DEFAULT_STANDALONE_FILLERS)
    start_review = as_string_list(speech.get("sentence_start_review"))
    end_review = as_string_list(speech.get("sentence_end_review"))
    final_remove = as_string_list(speech.get("sentence_final_remove"))
    compact = re.sub(r"\s+", "", text)
    applied: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    if compact.lower() in {word.lower() for word in standalone}:
        return "", [{"old": text, "new": "", "count": "1", "category": "语气词", "risk": "low", "note": "standalone filler block"}], []
    current = text
    for filler in final_remove:
        pattern = re.compile(re.escape(filler) + r"([。！？!?，,、\s]*)$")
        if pattern.search(current):
            reviews.append({"term": filler, "suggestion": "", "category": "句尾语气词", "risk": "medium", "note": "project-configured candidate; Agent must decide, do not delete mechanically"})
    for word in start_review:
        if current.startswith(word):
            reviews.append({"term": word, "suggestion": "", "category": "句首口语词", "risk": "low", "note": "project-configured review; do not delete automatically"})
    for word in end_review:
        if re.search(re.escape(word) + r"[。！？!?，,、\s]*$", current):
            reviews.append({"term": word, "suggestion": "", "category": "句尾口语词", "risk": "low", "note": "project-configured review; do not delete automatically"})
    if not start_review and not end_review:
        for word in DEFAULT_REVIEW_WORDS:
            if word in current:
                reviews.append({"term": word, "suggestion": "", "category": "口语连接词", "risk": "low", "note": "mark for contextual review; do not delete automatically"})
    return current, applied, reviews


def cleanup_repeated_chars(text: str) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    """Never collapse repeated Chinese characters mechanically.

    Repetition may be a stutter, emphasis, a kinship term, or a legitimate reduplicated
    word. Only long runs are surfaced for contextual review.
    """
    reviews: list[dict[str, str]] = []
    if re.search(r"(.)\1{2,}", text):
        reviews.append({
            "term": text,
            "suggestion": "",
            "category": "重复字",
            "risk": "medium",
            "note": "three-or-more repeated characters; review in context, never auto-collapse",
        })
    return text, [], reviews


_DIGIT_TO_CN = {
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}


def normalize_ordinals(text: str) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    """Normalize short spoken ordinals such as 第2个 -> 第二个."""
    applied: list[dict[str, str]] = []

    def repl(match: re.Match[str]) -> str:
        old = match.group(0)
        new = "第" + _DIGIT_TO_CN[match.group(1)] + match.group(2)
        applied.append({"old": old, "new": new, "count": "1", "category": "数字规范", "risk": "low", "note": "spoken ordinal normalization"})
        return new

    current = re.sub(r"第([1-9])(个|根|组|片|课|节|种|层|次|步)", repl, text)
    return current, applied, []


def scan_blacklist(items: list[dict[str, str]], blacklist: list[dict[str, str]]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for item in items:
        for rule in blacklist:
            term = (rule.get("term") or "").strip()
            if term and term in item["text"]:
                hits.append({
                    "index": item["index"],
                    "timestamp": item["timestamp"],
                    "term": term,
                    "expected": rule.get("expected", ""),
                    "severity": rule.get("severity", "medium"),
                    "note": rule.get("note", ""),
                    "text": item["text"],
                })
    return hits


def phase1_audit_csv_path(src: Path) -> Path:
    stem = re.sub(r"_Phase1_机械校对$", "", src.stem)
    return src.with_name(f"{stem}_Phase1_机械修改与疑点.csv")


def load_phase1_audit(src: Path) -> dict[str, dict[str, str]]:
    path = phase1_audit_csv_path(src)
    if not path.exists():
        return {}
    audit: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            idx = (row.get("index") or "").strip()
            risk = (row.get("risk") or "").strip().lower()
            review_class = (row.get("review_class") or "").strip().upper()
            requires_decision = (row.get("requires_phase2_decision") or row.get("need_human_check") or "").strip().lower() == "true"
            if idx and (risk in {"medium", "high"} or review_class in {"B", "C"} or requires_decision):
                audit[idx] = {
                    "risk": risk,
                    "before": row.get("before", ""),
                    "after": row.get("after", ""),
                    "rules": row.get("rules", ""),
                    "context": row.get("context", ""),
                    "review_class": review_class,
                    "priority": row.get("priority", ""),
                    "need_human_check": row.get("need_human_check", ""),
                    "requires_phase2_decision": row.get("requires_phase2_decision", ""),
                }
    return audit


LATIN_RE = re.compile(r"[A-Za-z]")
MIXED_LATIN_CJK_RE = re.compile(r"(?:[A-Za-z]+[\u4e00-\u9fff]+|[\u4e00-\u9fff]+[A-Za-z]+)")


def detect_phase2_anomaly(item: dict[str, str], ctx: str, style_rules: dict | None = None) -> dict[str, str]:
    """Recall lines that need mandatory Phase 2 review even if Phase 1 made no edit.

    These are not automatic replacements. They are high-priority review signals for
    heavy-accent ASR: Latin leftovers, mixed Latin/CJK fragments, and known
    phonetically plausible but nonsensical terms.
    """
    text_value = item.get("text", "")
    compact = re.sub(r"\s+", "", text_value)
    style_rules = style_rules or {}
    configured_terms = as_string_list(style_rules.get("asr_review_terms"))
    signals: list[str] = []
    mandatory = False
    if LATIN_RE.search(compact):
        signals.append("latin_letters")
    if MIXED_LATIN_CJK_RE.search(compact):
        signals.append("mixed_latin_cjk")
        mandatory = True
    lowered = compact.lower()
    for term in configured_terms:
        if term.lower() in lowered:
            signals.append(f"suspicious_asr:{term}")
            mandatory = True
    if not signals:
        return {}
    return {
        "risk": "high" if mandatory else "medium",
        "before": text_value,
        "after": text_value,
        "rules": ("Phase2 mandatory anomaly review: " if mandatory else "Phase2 contextual review: ") + "; ".join(dict.fromkeys(signals)),
        "context": ctx,
        "requires_phase2_decision": "true" if mandatory else "false",
    }


def merge_phase2_audit(primary: dict[str, str], anomaly: dict[str, str]) -> dict[str, str]:
    if not primary:
        return anomaly
    if not anomaly:
        return primary
    merged = dict(primary)
    merged["risk"] = "high" if "high" in {primary.get("risk"), anomaly.get("risk")} else primary.get("risk", "medium")
    merged["rules"] = "; ".join(part for part in (primary.get("rules", ""), anomaly.get("rules", "")) if part)
    merged["context"] = primary.get("context") or anomaly.get("context", "")
    merged["requires_phase2_decision"] = "true"
    return merged


def classify_phase1_row(row: dict[str, str]) -> tuple[str, str, str]:
    rules = row.get("rules", "")
    risk = (row.get("risk") or "low").lower()
    if "Phase2 mandatory anomaly review:" in rules or row.get("requires_phase2_decision") == "true":
        return "C", "high", "true"
    if risk in {"medium", "high"}:
        return "B", "medium", "true"
    return "A", "low", "false"


def add_review_metadata(row: dict[str, str]) -> dict[str, str]:
    review_class, priority, need_human_check = classify_phase1_row(row)
    enriched = dict(row)
    enriched["review_class"] = review_class
    enriched["priority"] = priority
    enriched["need_human_check"] = need_human_check
    return enriched


def resolve_context_files(project: Path, project_config: dict) -> dict[str, list[str]]:
    configured = as_string_list(project_config.get("context_files")) + as_string_list(project_config.get("materials"))
    project_root = project.resolve()
    inside_project: list[str] = []
    external: list[str] = []
    missing: list[str] = []
    for value in dict.fromkeys(configured):
        path = Path(value)
        if not path.is_absolute():
            path = project / path
        resolved = path.resolve()
        if not path.exists():
            missing.append(str(resolved))
        elif resolved == project_root or resolved.is_relative_to(project_root):
            inside_project.append(str(resolved))
        else:
            external.append(str(resolved))
    return {"inside_project": inside_project, "external_requires_approval": external, "missing": missing}


def export_ai_chunks(
    src: Path,
    items: list[dict[str, str]],
    chunk_size: int,
    context_size: int,
    project: Path,
    project_config: dict,
    style_rules: dict,
    out_path: Path,
    review_mode: str = "deep",
    focused_sample_rate: float = 0.1,
) -> dict:
    """Export items as chunked JSON for agent AI pass."""
    all_chunks = []
    total = len(items)
    phase1_audit = load_phase1_audit(src)
    anomaly_count = 0
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        ck_items = items[start:end]
        ctx_before = context_text(items, start - 1, context_size) if start > 0 else ""
        ctx_after = context_text(items, end, context_size) if end < total else ""
        # Build a simple summary of the previous chunk for continuity
        prev_summary = ""
        if start > 0:
            prev = items[max(0, start - 10):start]
            visible = [it["text"] for it in prev if len(it["text"].strip()) > 5]
            prev_summary = " | ".join(visible[-5:])
        chunk_items = []
        for offset, it in enumerate(ck_items):
            ctx = context_text(items, start + offset, context_size)
            anomaly = detect_phase2_anomaly(it, ctx, style_rules)
            if anomaly:
                anomaly_count += 1
            chunk_items.append({
                "index": it["index"],
                "text": it["text"],
                "phase1_audit": merge_phase2_audit(phase1_audit.get(it["index"], {}), anomaly),
            })
        chunk_data = {
            "chunk_id": start // chunk_size,
            "indices": f"{ck_items[0]['index']}-{ck_items[-1]['index']}",
            "context_before": ctx_before,
            "chunk_items": chunk_items,
            "context_after": ctx_after,
            "previous_chunk_tail": prev_summary,
        }
        all_chunks.append(chunk_data)

    if review_mode == "deep":
        chunks = all_chunks
    elif review_mode == "focused":
        rate = max(0.0, min(1.0, focused_sample_rate))
        sample_every = max(1, round(1 / rate)) if rate > 0 else 0
        chunks = []
        for chunk in all_chunks:
            has_audit = any(bool(item.get("phase1_audit")) for item in chunk["chunk_items"])
            sampled = bool(sample_every and int(chunk["chunk_id"]) % sample_every == 0)
            if has_audit or sampled:
                chunks.append(chunk)
    elif review_mode == "mechanical":
        chunks = []
    else:
        raise ValueError(f"Unsupported review_mode: {review_mode}")

    selected_indices = [item["index"] for chunk in chunks for item in chunk["chunk_items"]]
    payload = {
        "source": str(src),
        "project": str(project),
        "project_title": project_config.get("title", ""),
        "speaker": project_config.get("speaker", ""),
        "domain": project_config.get("domain", ""),
        "profile_isolation": "project",
        "context_files": resolve_context_files(project, project_config),
        "protected_terms": load_protected_terms(project),
        "total_items": total,
        "source_fingerprint": items_fingerprint(items),
        "total_chunks": len(all_chunks),
        "selected_chunk_count": len(chunks),
        "selected_indices": selected_indices,
        "review_mode": review_mode,
        "focused_sample_rate": focused_sample_rate,
        "chunk_size": chunk_size,
        "context_size": context_size,
        "phase2_task": "This project is isolated to its configured speaker/course/domain. Read trusted course context first. Proofread by local substitution only: correct recognition, spelling, punctuation, names, and terminology without reconstructing sentences, moving meaning across cues, adding inferred facts, or making speech more literary. Audit every selected item with phase1_audit and set phase1_decision to accepted, reverted, or adjusted with a concrete reason. Legitimate foreign-language text may be accepted; do not manufacture a change merely to pass a gate. When a correction would replace most of a cue or evidence is insufficient, keep item.text unchanged, set uncertainty, and store the proposal as new_context_fix.suggested_text with new_context_fix.reason instead of forcing it into the SRT.",
        "audit_item_count": len(phase1_audit),
        "phase2_anomaly_count": anomaly_count,
        "selected_audit_item_count": sum(1 for chunk in chunks for item in chunk["chunk_items"] if item.get("phase1_audit")),
        "chunks": chunks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


GUARD_IGNORED_RE = re.compile(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()\[\]【】《》〈〉—…·-]+")


def normalize_guard_text(value: str) -> str:
    """Ignore whitespace and punctuation when measuring semantic edit impact."""
    return GUARD_IGNORED_RE.sub("", value)


def text_change_metrics(before: str, after: str) -> dict[str, object]:
    """Measure edit size without pretending to judge whether the new meaning is true."""
    old = normalize_guard_text(before)
    new = normalize_guard_text(after)
    max_length = max(len(old), len(new), 1)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    edit_units = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
    edit_ratio = edit_units / max_length
    length_delta_ratio = abs(len(old) - len(new)) / max_length
    similarity = matcher.ratio()
    high_impact = bool(old != new) and (
        (max_length >= 3 and similarity <= 0.25)
        or (max_length >= 6 and edit_ratio >= 0.60)
        or (max_length >= 10 and edit_ratio >= 0.45)
        or (max_length >= 8 and length_delta_ratio >= 0.50)
    )
    reasons: list[str] = []
    if high_impact:
        if similarity <= 0.25:
            reasons.append("新旧文本几乎没有共同文字")
        if edit_ratio >= 0.45:
            reasons.append(f"文字改动比例约为 {edit_ratio:.0%}")
        if length_delta_ratio >= 0.50:
            reasons.append(f"长度变化约为 {length_delta_ratio:.0%}")
    return {
        "max_length": max_length,
        "edit_units": edit_units,
        "edit_ratio": round(edit_ratio, 4),
        "length_delta_ratio": round(length_delta_ratio, 4),
        "similarity": round(similarity, 4),
        "high_impact": high_impact,
        "guard_reason": "；".join(reasons) if reasons else "局部文字校正",
    }


def assess_semantic_changes(payload: dict, items: list[dict[str, str]]) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    """Classify individual edits and detect dense rewriting clusters.

    A single high-impact edit is held for human review. A dense cluster blocks the
    Phase 2 delivery because it is more consistent with reconstruction than SRT
    proofreading.
    """
    expected = {item["index"]: item for item in items}
    assessments: dict[str, dict[str, object]] = {}
    for chunk in payload.get("chunks", []):
        for ck_item in chunk.get("chunk_items", []):
            idx = str(ck_item.get("index", ""))
            if idx not in expected or not isinstance(ck_item.get("text"), str):
                continue
            before = expected[idx]["text"]
            proposed = ck_item["text"]
            if before == proposed:
                continue
            metrics = text_change_metrics(before, proposed)
            start_ms, _ = timestamp_to_ms(expected[idx]["timestamp"])
            context_fix = ck_item.get("new_context_fix") or {}
            context_fix_reason = context_fix.get("reason", "") if isinstance(context_fix, dict) else ""
            agent_reason = str(ck_item.get("reason") or ck_item.get("note") or context_fix_reason or "").strip()
            assessments[idx] = {
                "index": idx,
                "timestamp": expected[idx]["timestamp"],
                "source_text": before,
                "proposed_text": proposed,
                "agent_reason": agent_reason,
                "start_ms": start_ms,
                **metrics,
            }

    high_impact = sorted(
        (row for row in assessments.values() if row.get("high_impact")),
        key=lambda row: int(row["start_ms"]),
    )
    clustered: list[dict[str, object]] = []
    for pos, first in enumerate(high_impact):
        window = [
            row for row in high_impact[pos:]
            if int(row["start_ms"]) - int(first["start_ms"]) <= 90_000
        ]
        substantial = sum(1 for row in window if int(row["max_length"]) >= 8)
        edit_units = sum(int(row["edit_units"]) for row in window)
        if len(window) >= 4 and substantial >= 2 and edit_units >= 24:
            clustered = window
            break
    return assessments, clustered


def held_review_row(assessment: dict[str, object], *, blocked: bool = False) -> dict[str, object]:
    source_text = str(assessment.get("source_text", ""))
    return {
        "index": str(assessment.get("index", "")),
        "timestamp": str(assessment.get("timestamp", "")),
        "risk": "high",
        "review_class": "C",
        "priority": "high",
        "need_human_check": "true",
        "requires_phase2_decision": "true",
        "change_type": "blocked_rewrite_cluster" if blocked else "held_high_impact_suggestion",
        "apply_status": "blocked_run" if blocked else "held_for_review",
        "before": source_text,
        "after": source_text,
        "source_text": source_text,
        "current_srt_text": source_text,
        "suggested_change": str(assessment.get("proposed_text", "")),
        "rules": "语义安全门：疑似生成式改写，未写入SRT",
        "reason": str(assessment.get("agent_reason", "")),
        "guard_reason": str(assessment.get("guard_reason", "")),
        "context": "",
        "phase1_before": "",
        "phase1_after": "",
        "phase1_rules": "",
    }


def validate_ai_payload(
    payload: dict,
    items: list[dict[str, str]],
    protected_terms: list[str] | None = None,
    manifest: dict | None = None,
) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("chunks"), list):
        raise ValueError("ai_results.json must preserve the exported top-level object and chunks array")
    if payload.get("source_fingerprint") and payload.get("source_fingerprint") != items_fingerprint(items):
        raise ValueError("AI result quality gate failed: source fingerprint does not match the SRT being applied")
    if manifest is not None:
        for key in ("source_fingerprint", "review_mode", "selected_indices", "total_chunks", "selected_chunk_count"):
            if payload.get(key) != manifest.get(key):
                raise ValueError(f"AI result quality gate failed: selection manifest field changed: {key}")
    elif payload.get("review_mode"):
        raise ValueError("AI result quality gate failed: --ai-chunks-manifest is required for review-mode payloads")

    all_expected = {item["index"]: item for item in items}
    selected = payload.get("selected_indices")
    if isinstance(selected, list):
        unknown_selected = [str(idx) for idx in selected if str(idx) not in all_expected]
        if unknown_selected:
            raise ValueError(f"AI result quality gate failed: selected_indices contains unknown indices: {unknown_selected[:10]}")
        expected = {str(idx): all_expected[str(idx)] for idx in selected}
    else:
        expected = all_expected
    seen: set[str] = set()
    errors: list[str] = []
    for chunk in payload["chunks"]:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("chunk_items"), list):
            errors.append("every chunk must contain a chunk_items array")
            continue
        for ck_item in chunk["chunk_items"]:
            if not isinstance(ck_item, dict):
                errors.append("chunk item is not an object")
                continue
            idx = str(ck_item.get("index", ""))
            if not idx or idx not in expected:
                errors.append(f"unknown or missing index: {idx!r}")
                continue
            if idx in seen:
                errors.append(f"duplicate index: {idx}")
                continue
            seen.add(idx)
            text_value = ck_item.get("text")
            if not isinstance(text_value, str):
                errors.append(f"index {idx}: text must be a string")
                continue
            audit = ck_item.get("phase1_audit") or {}
            decision = str(ck_item.get("phase1_decision") or (audit.get("phase1_decision") if isinstance(audit, dict) else "") or "").strip().lower()
            context_fix = ck_item.get("new_context_fix") or {}
            context_fix_reason = context_fix.get("reason", "") if isinstance(context_fix, dict) else ""
            suggested_text = context_fix.get("suggested_text", "") if isinstance(context_fix, dict) else ""
            reason = str(ck_item.get("reason") or ck_item.get("note") or context_fix_reason or "").strip()
            uncertainty = ck_item.get("uncertainty")
            if audit:
                if decision not in VALID_PHASE1_DECISIONS:
                    errors.append(f"index {idx}: audited item lacks accepted/reverted/adjusted decision")
                if not reason:
                    errors.append(f"index {idx}: audited item lacks a contextual reason")
            if text_value != expected[idx]["text"] and not reason:
                errors.append(f"index {idx}: changed text lacks a reason")
            if uncertainty and not reason:
                errors.append(f"index {idx}: uncertainty lacks a reason")
            if suggested_text and not isinstance(suggested_text, str):
                errors.append(f"index {idx}: new_context_fix.suggested_text must be a string")
            if suggested_text and not reason:
                errors.append(f"index {idx}: suggested change lacks a reason")
            for term in protected_terms or []:
                if term in expected[idx]["text"] and term not in text_value:
                    errors.append(f"index {idx}: protected term was removed or altered: {term}")
            if decision == "adjusted" and text_value == expected[idx]["text"]:
                errors.append(f"index {idx}: adjusted decision did not change text")
    missing = sorted(set(expected) - seen, key=lambda value: int(value))
    if missing:
        errors.append(f"missing {len(missing)} subtitle indices; first: {', '.join(missing[:10])}")
    if errors:
        raise ValueError("AI result quality gate failed: " + "; ".join(errors[:30]))
    _, clustered = assess_semantic_changes(payload, items)
    if clustered:
        indices = ", ".join(str(row["index"]) for row in clustered[:12])
        raise SemanticGuardError(
            "AI result semantic guard failed: clustered high-impact rewrites detected "
            f"within 90 seconds (indices: {indices}). No Phase2 SRT was written.",
            [held_review_row(row, blocked=True) for row in clustered],
        )


def apply_ai_chunks(
    items: list[dict[str, str]],
    ai_results_path: Path,
    src: Path,
    project: Path,
    manifest_path: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Apply AI-processed chunk text back onto items and return Phase 2 changes."""
    payload = json.loads(ai_results_path.read_text(encoding="utf-8-sig"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path else None
    validate_ai_payload(payload, items, load_protected_terms(project), manifest)
    guard_assessments, _ = assess_semantic_changes(payload, items)
    corrupt_hits: list[str] = []
    idx_map: dict[str, str] = {}
    audit_map: dict[str, dict[str, str]] = {}
    reason_map: dict[str, str] = {}
    uncertainty_map: dict[str, bool] = {}
    suggestion_map: dict[str, str] = {}
    for ck in payload.get("chunks", []):
        for ck_item in ck.get("chunk_items", []):
            idx = ck_item.get("index", "")
            txt = ck_item.get("text", "")
            if idx:
                if isinstance(txt, str) and CORRUPT_TEXT_RE.search(txt):
                    corrupt_hits.append(f"index={idx} text={txt!r}")
                context_fix = ck_item.get("new_context_fix") or {}
                context_fix_reason = context_fix.get("reason", "") if isinstance(context_fix, dict) else ""
                reason = ck_item.get("reason") or ck_item.get("note") or context_fix_reason or ""
                if isinstance(reason, str) and CORRUPT_TEXT_RE.search(reason):
                    corrupt_hits.append(f"index={idx} reason={reason!r}")
                idx_map[idx] = txt
                audit = ck_item.get("phase1_audit") or {}
                if isinstance(audit, dict):
                    audit_map[idx] = audit
                reason_map[idx] = reason
                uncertainty_map[idx] = bool(ck_item.get("uncertainty"))
                if isinstance(context_fix, dict) and isinstance(context_fix.get("suggested_text"), str):
                    suggestion_map[idx] = context_fix.get("suggested_text", "")
                if ck_item.get("phase1_decision"):
                    audit_map.setdefault(idx, {})["phase1_decision"] = str(ck_item.get("phase1_decision"))
    if corrupt_hits:
        preview = "; ".join(corrupt_hits[:10])
        raise ValueError(
            "Refusing to apply AI chunks because ai_results contains corrupted text "
            f"({len(corrupt_hits)} hits): {preview}"
        )
    phase2_changes: list[dict[str, str]] = []
    for item in items:
        new_text = idx_map.get(item["index"])
        if new_text is not None and new_text != item["text"]:
            audit = audit_map.get(item["index"], {})
            phase1_before = audit.get("before", "")
            phase1_after = audit.get("after", "")
            phase1_rules = audit.get("rules", "")
            if phase1_before and new_text == phase1_before and item["text"] == phase1_after:
                change_type = "reverted_phase1"
                rules = "撤回Phase1机械修改"
            elif phase1_after and item["text"] == phase1_after:
                change_type = "adjusted_phase1"
                rules = "调整Phase1机械修改"
            else:
                change_type = "new_context_fix"
                rules = "AI语境修正"
            guard = guard_assessments.get(item["index"], {})
            if guard.get("high_impact"):
                phase2_changes.append(held_review_row(guard))
                continue
            phase2_changes.append({
                "index": item["index"],
                "timestamp": item["timestamp"],
                "risk": audit.get("risk", "medium"),
                "review_class": audit.get("review_class", "C" if audit.get("requires_phase2_decision") == "true" else "B"),
                "priority": audit.get("priority", "high" if audit.get("requires_phase2_decision") == "true" else "medium"),
                "need_human_check": audit.get("need_human_check", "true" if audit.get("requires_phase2_decision") == "true" else "false"),
                "requires_phase2_decision": audit.get("requires_phase2_decision", "false"),
                "change_type": change_type,
                "apply_status": "applied",
                "before": item["text"],
                "after": new_text,
                "source_text": item["text"],
                "current_srt_text": new_text,
                "suggested_change": "",
                "rules": rules,
                "reason": reason_map.get(item["index"], ""),
                "guard_reason": "局部文字校正，通过语义安全门",
                "context": audit.get("context", ""),
                "phase1_before": phase1_before,
                "phase1_after": phase1_after,
                "phase1_rules": phase1_rules,
            })
            item["text"] = new_text
        elif new_text is not None:
            audit = audit_map.get(item["index"], {})
            decision = (audit.get("phase1_decision") or "").strip().lower()
            suggested_text = suggestion_map.get(item["index"], "")
            if suggested_text and suggested_text != item["text"]:
                suggestion_metrics = {
                    "index": item["index"],
                    "timestamp": item["timestamp"],
                    "source_text": item["text"],
                    "proposed_text": suggested_text,
                    "agent_reason": reason_map.get(item["index"], ""),
                    **text_change_metrics(item["text"], suggested_text),
                }
                phase2_changes.append(held_review_row(suggestion_metrics))
            elif uncertainty_map.get(item["index"]):
                phase2_changes.append({
                    "index": item["index"],
                    "timestamp": item["timestamp"],
                    "risk": "high",
                    "review_class": "C",
                    "priority": "high",
                    "need_human_check": "true",
                    "requires_phase2_decision": "true",
                    "change_type": "uncertainty",
                    "apply_status": "unchanged_uncertain",
                    "before": item["text"],
                    "after": item["text"],
                    "source_text": item["text"],
                    "current_srt_text": item["text"],
                    "suggested_change": "",
                    "rules": "Agent无法仅凭文本与项目资料确认",
                    "reason": reason_map.get(item["index"], ""),
                    "guard_reason": "证据不足，保留原文",
                    "context": audit.get("context", ""),
                    "phase1_before": audit.get("before", ""),
                    "phase1_after": audit.get("after", ""),
                    "phase1_rules": audit.get("rules", ""),
                })
            elif audit and decision in {"accepted", "accept", "accepted_phase1"}:
                phase2_changes.append({
                    "index": item["index"],
                    "timestamp": item["timestamp"],
                    "risk": audit.get("risk", "medium"),
                    "review_class": audit.get("review_class", "C" if audit.get("requires_phase2_decision") == "true" else "B"),
                    "priority": audit.get("priority", "high" if audit.get("requires_phase2_decision") == "true" else "medium"),
                    "need_human_check": audit.get("need_human_check", "true" if audit.get("requires_phase2_decision") == "true" else "false"),
                    "requires_phase2_decision": audit.get("requires_phase2_decision", "false"),
                    "change_type": "accepted_phase1",
                    "apply_status": "applied_phase1",
                    "before": item["text"],
                    "after": item["text"],
                    "source_text": audit.get("before", item["text"]),
                    "current_srt_text": item["text"],
                    "suggested_change": "",
                    "rules": "确认Phase1机械修改",
                    "reason": reason_map.get(item["index"], ""),
                    "guard_reason": "确认已有机械修改，不新增文本",
                    "context": audit.get("context", ""),
                    "phase1_before": audit.get("before", ""),
                    "phase1_after": audit.get("after", ""),
                    "phase1_rules": audit.get("rules", ""),
                })
    print(json.dumps({
        "applied_changes": sum(1 for row in phase2_changes if row.get("apply_status") in {"applied", "applied_phase1"}),
        "held_for_review": sum(1 for row in phase2_changes if row.get("apply_status") == "held_for_review"),
        "source": str(src),
    }, ensure_ascii=False, indent=2))
    return items, phase2_changes


def write_change_csv(path: Path, rows: list[dict[str, str]]) -> None:
    def csv_safe(value: object) -> object:
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "index",
            "timestamp",
            "risk",
            "review_class",
            "priority",
            "need_human_check",
            "requires_phase2_decision",
            "change_type",
            "apply_status",
            "before",
            "after",
            "source_text",
            "current_srt_text",
            "suggested_change",
            "rules",
            "reason",
            "guard_reason",
            "context",
            "phase1_before",
            "phase1_after",
            "phase1_rules",
        ])
        writer.writeheader()
        writer.writerows({key: csv_safe(value) for key, value in row.items()} for row in rows)


def find_corrupt_output_rows(items: list[dict[str, str]], rows: list[dict[str, str]]) -> list[str]:
    hits: list[str] = []
    for item in items:
        text = item.get("text", "")
        if CORRUPT_TEXT_RE.search(text):
            hits.append(f"srt index={item.get('index')} text={text!r}")
    for row in rows:
        for field in ("before", "after", "source_text", "current_srt_text", "suggested_change", "reason", "guard_reason", "context", "phase1_before", "phase1_after", "phase1_rules"):
            value = row.get(field, "")
            if value and CORRUPT_TEXT_RE.search(value):
                hits.append(f"csv index={row.get('index')} field={field} value={value!r}")
    return hits


def write_queue_csvs(out_dir: Path, stem: str, rows: list[dict[str, str]]) -> dict[str, str]:
    queues = {
        "auto_applied": [r for r in rows if r.get("review_class") == "A"],
        "semantic_review": [r for r in rows if r.get("review_class") == "B"],
        "anomaly_review": [r for r in rows if r.get("review_class") == "C"],
    }
    outputs: dict[str, str] = {}
    for name, queue_rows in queues.items():
        path = out_dir / f"{stem}_Phase1_{name}.csv"
        write_change_csv(path, queue_rows)
        outputs[name] = str(path)
    return outputs


def phase2_focus_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    focus: list[dict[str, str]] = []
    for row in rows:
        if row.get("review_class") == "C" or row.get("change_type") != "accepted_phase1":
            focus.append(row)
    return focus


def write_human_focus_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Write the editor-facing sheet with decision columns first and no debug noise."""
    fieldnames = ["index", "timestamp", "原字幕", "当前SRT", "建议修改", "人工复验原因", "处理状态"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            source_text = str(row.get("source_text") or row.get("before") or "")
            current_text = str(row.get("current_srt_text") or row.get("after") or source_text)
            suggestion = str(row.get("suggested_change") or "")
            reason_parts = [str(row.get("guard_reason") or "").strip(), str(row.get("reason") or "").strip()]
            writer.writerow({
                "index": row.get("index", ""),
                "timestamp": row.get("timestamp", ""),
                "原字幕": source_text,
                "当前SRT": current_text,
                "建议修改": suggestion,
                "人工复验原因": "；".join(part for part in reason_parts if part),
                "处理状态": row.get("apply_status", ""),
            })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--srt", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--lesson", default="")
    parser.add_argument("--out-dir")
    parser.add_argument("--output-in-source", action="store_true", help="Place output in source file's parent as {src_stem}_字幕校对_{timestamp}")
    parser.add_argument("--chunk-size", type=int)
    parser.add_argument("--context-size", type=int)
    parser.add_argument("--review-mode", choices=("deep", "focused", "mechanical"), help="Phase 2 coverage mode; defaults to project.yml or deep")
    parser.add_argument("--focused-sample-rate", type=float, help="Deterministic sampling rate for otherwise unflagged chunks in focused mode")
    parser.add_argument("--export-ai-chunks", help="Export chunked JSON for AI pass instead of running full pipeline")
    parser.add_argument("--apply-ai-chunks", help="Apply AI-processed chunk JSON and generate artifacts")
    parser.add_argument("--ai-chunks-manifest", help="Original immutable ai_chunks.json used to verify review selection and coverage")
    args = parser.parse_args()

    src = Path(args.srt)
    project = Path(args.project)
    project_config = load_project_config(project)
    style_rules = load_style_rules(project)
    chunk_size = args.chunk_size or int(project_config.get("default_chunk_size", 100))
    context_size = args.context_size or int(project_config.get("default_context_size", 10))
    review_mode = args.review_mode or str(project_config.get("review_mode", "deep")).strip().lower()
    focused_sample_rate = args.focused_sample_rate if args.focused_sample_rate is not None else float(project_config.get("focused_sample_rate", 0.1))
    raw, source_encoding = read_text(src)
    items, parse_errors = parse_srt(raw)
    parse_errors.extend(structural_errors(items))

    lesson_label = args.lesson or src.stem
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    stem = src.stem
    for suffix in (
        "_Phase1_机械校对",
        "_Phase2_待人工校验",
        "_AI校对_保时轴",
    ):
        stem = re.sub(re.escape(suffix) + r"$", "", stem)
    if args.out_dir:
        out_dir = Path(args.out_dir)
    elif args.output_in_source:
        out_dir = src.parent / f"{stem}_字幕校对_{stamp}"
    else:
        out_dir = project / "runs" / f"{stem}_{stamp}"

    if parse_errors:
        if args.export_ai_chunks:
            raise ValueError(f"Source SRT validation failed with {len(parse_errors)} errors: {parse_errors[:10]}")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_status = out_dir / "run_status.json"
        status = {
            "validation": {
                "source": str(src),
                "source_encoding": source_encoding,
                "source_items": len(items),
                "parse_errors_source": len(parse_errors),
                "errors": parse_errors,
                "structure_valid": False,
                "semantic_guard_passed": None,
                "delivery_status": "blocked",
            },
            "outputs": {"status": str(out_status)},
        }
        out_status.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2

    # --- AI chunk export mode ---
    if args.export_ai_chunks:
        export_ai_chunks(
            src,
            items,
            chunk_size,
            context_size,
            project,
            project_config,
            style_rules,
            Path(args.export_ai_chunks),
            review_mode=review_mode,
            focused_sample_rate=focused_sample_rate,
        )
        return 0

    lexicon = load_lexicon(project)
    blacklist = load_blacklist(project)

    is_phase2 = bool(args.apply_ai_chunks)

    corrected: list[dict[str, str]] = []
    changes: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []

    for pos, item in enumerate(items):
        if is_phase2:
            # Phase 2: input is already Phase-1-cleaned, skip lexicon/filler/ordinal re-application
            corrected.append(dict(item))
            continue
        ctx = context_text(items, pos, context_size)
        new_text, applied, reviews = apply_lexicon(item["text"], ctx, lexicon)
        new_text, filler_applied, filler_reviews = cleanup_fillers(new_text, style_rules)
        applied.extend(filler_applied)
        reviews.extend(filler_reviews)
        new_text, repeat_applied, repeat_reviews = cleanup_repeated_chars(new_text)
        applied.extend(repeat_applied)
        reviews.extend(repeat_reviews)
        new_text, ordinal_applied, ordinal_reviews = normalize_ordinals(new_text)
        applied.extend(ordinal_applied)
        reviews.extend(ordinal_reviews)
        out_item = dict(item)
        out_item["text"] = new_text
        corrected.append(out_item)
        if applied or reviews or new_text != item["text"]:
            risk_values = [a.get("risk", "low") for a in applied] + [r.get("risk", "medium") for r in reviews]
            risk = "high" if "high" in risk_values else "medium" if "medium" in risk_values else "low"
            rule_text = "; ".join(f"{a['old']} -> {a['new']} ({a['category']}: {a['note']})" for a in applied)
            review_text = "; ".join(f"复核 {r['term']} -> {r.get('suggestion','')} ({r['category']}: {r['note']})" for r in reviews)
            combined = "; ".join(x for x in (rule_text, review_text) if x)
            row = {
                "index": item["index"],
                "timestamp": item["timestamp"],
                "risk": risk,
                "before": item["text"],
                "after": new_text,
                "rules": combined,
                "context": ctx,
            }
            anomaly = detect_phase2_anomaly(out_item, ctx, style_rules)
            if anomaly:
                row["risk"] = "high"
                row["rules"] = "; ".join(x for x in (row.get("rules", ""), anomaly.get("rules", "")) if x)
                row["requires_phase2_decision"] = "true"
            row = add_review_metadata(row)
            changes.append(row)
            if reviews or row["review_class"] in {"B", "C"}:
                review_rows.append(row)
        else:
            anomaly = detect_phase2_anomaly(out_item, ctx, style_rules)
            if anomaly:
                row = add_review_metadata({
                    "index": item["index"],
                    "timestamp": item["timestamp"],
                    "risk": "high",
                    "before": item["text"],
                    "after": new_text,
                    "rules": anomaly.get("rules", ""),
                    "context": ctx,
                    "requires_phase2_decision": "true",
                })
                changes.append(row)
                review_rows.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    if is_phase2:
        out_srt = out_dir / f"{stem}_Phase2_待人工校验.srt"
        out_csv = out_dir / f"{stem}_Phase2_语境修正.csv"
        out_focus_csv = out_dir / f"{stem}_Phase2_人工复验重点.csv"
    else:
        out_srt = out_dir / f"{stem}_Phase1_机械校对.srt"
        out_csv = out_dir / f"{stem}_Phase1_机械修改与疑点.csv"
        out_focus_csv = None
    out_status = out_dir / "run_status.json"

    # --- Apply AI chunk corrections before final output ---
    phase2_changes: list[dict[str, str]] = []
    ai_payload_meta: dict = {}
    if args.apply_ai_chunks:
        ai_payload_meta = json.loads(Path(args.apply_ai_chunks).read_text(encoding="utf-8-sig"))
        try:
            corrected, phase2_changes = apply_ai_chunks(
                corrected,
                Path(args.apply_ai_chunks),
                src,
                project,
                Path(args.ai_chunks_manifest) if args.ai_chunks_manifest else None,
            )
        except SemanticGuardError as exc:
            write_human_focus_csv(out_focus_csv, exc.review_rows)
            blocked_status = {
                "validation": {
                    "source": str(src),
                    "project": str(project),
                    "source_items": len(items),
                    "structure_valid": True,
                    "semantic_guard_passed": False,
                    "delivery_status": "blocked",
                    "blocked_reason": str(exc),
                    "blocked_review_items": len(exc.review_rows),
                    "review_mode": ai_payload_meta.get("review_mode", review_mode),
                },
                "outputs": {
                    "human_review_focus_csv": str(out_focus_csv),
                    "status": str(out_status),
                },
            }
            out_status.write_text(json.dumps(blocked_status, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(blocked_status, ensure_ascii=False, indent=2))
            return 3
        corrupt_hits = find_corrupt_output_rows(corrected, phase2_changes)
        if corrupt_hits:
            preview = "; ".join(corrupt_hits[:10])
            raise ValueError(
                "Refusing to write Phase2 outputs because corrupted text was detected "
                f"({len(corrupt_hits)} hits): {preview}"
            )

    out_srt.write_text(dump_srt(corrected), encoding="utf-8-sig")
    blacklist_hits = scan_blacklist(corrected, blacklist)
    if not is_phase2 and blacklist_hits:
        existing_by_index = {row.get("index"): row for row in changes}
        corrected_pos = {item["index"]: pos for pos, item in enumerate(corrected)}
        for hit in blacklist_hits:
            idx = hit.get("index", "")
            rule = f"blacklist_hit: {hit.get('term','')} -> {hit.get('expected','')} ({hit.get('note','')})"
            if idx in existing_by_index:
                row = existing_by_index[idx]
                row["risk"] = "high"
                row["rules"] = "; ".join(x for x in (row.get("rules", ""), rule) if x)
                row["requires_phase2_decision"] = "true"
                row.update(add_review_metadata(row))
            else:
                pos = corrected_pos.get(idx, 0)
                changes.append(add_review_metadata({
                    "index": idx,
                    "timestamp": hit.get("timestamp", ""),
                    "risk": "high",
                    "before": hit.get("text", ""),
                    "after": hit.get("text", ""),
                    "rules": rule,
                    "context": context_text(corrected, pos, context_size),
                    "requires_phase2_decision": "true",
                }))
    out_raw, _ = read_text(out_srt)
    out_items, out_errors = parse_srt(out_raw)
    validation = {
        "source": str(src),
        "source_encoding": source_encoding,
        "project": str(project),
        "speaker": project_config.get("speaker", ""),
        "domain": project_config.get("domain", ""),
        "profile_isolation": "project",
        "lesson": lesson_label,
        "source_items": len(items),
        "output_items": len(out_items),
        "parse_errors_source": len(parse_errors),
        "parse_errors_output": len(out_errors),
        "index_sequence_same": [it["index"] for it in items] == [it["index"] for it in out_items],
        "timestamp_sequence_same": [it["timestamp"] for it in items] == [it["timestamp"] for it in out_items],
        "changed_or_review_items": len(changes),
        "review_items": len(review_rows),
        "blacklist_hits": len(blacklist_hits),
        "chunk_size": chunk_size,
        "context_size": context_size,
        "phase": "phase2" if is_phase2 else "phase1",
        "phase1_done": True,
        "phase2_done": is_phase2,
        "ai_pass_applied": is_phase2,
        "ai_changes_count": sum(1 for row in phase2_changes if row.get("apply_status") in {"applied", "applied_phase1"}),
        "ai_held_for_review_count": sum(1 for row in phase2_changes if row.get("apply_status") == "held_for_review"),
        "structure_valid": not parse_errors and not out_errors,
        "semantic_guard_passed": True if is_phase2 else None,
        "delivery_status": "ready_for_human_review" if is_phase2 else "phase1_debug",
        "project_config_loaded": bool(project_config),
        "style_rules_loaded": bool(style_rules),
        "review_mode": ai_payload_meta.get("review_mode", review_mode) if is_phase2 else review_mode,
        "selected_chunk_count": ai_payload_meta.get("selected_chunk_count", 0) if is_phase2 else 0,
        "total_chunks": ai_payload_meta.get("total_chunks", 0) if is_phase2 else 0,
        "review_coverage": (
            round(ai_payload_meta.get("selected_chunk_count", 0) / ai_payload_meta.get("total_chunks", 1), 4)
            if is_phase2 and ai_payload_meta.get("total_chunks", 0)
            else (0.0 if is_phase2 else None)
        ),
    }

    if is_phase2:
        write_change_csv(out_csv, phase2_changes)
        focus_rows = phase2_focus_rows(phase2_changes)
        write_human_focus_csv(out_focus_csv, focus_rows)
        queue_outputs = {}
    else:
        write_change_csv(out_csv, changes)
        queue_outputs = write_queue_csvs(out_dir, stem, changes)
        focus_rows = []
    status = {
        "validation": validation,
        "outputs": {
            "srt": str(out_srt),
            "csv": str(out_csv),
            "status": str(out_status),
        },
        "blacklist_hits": blacklist_hits,
    }
    if is_phase2 and out_focus_csv is not None:
        status["outputs"]["human_review_focus_csv"] = str(out_focus_csv)
        status["validation"]["human_review_focus_items"] = len(focus_rows)
    if queue_outputs:
        status["outputs"].update(queue_outputs)
        status["validation"]["phase1_auto_applied_items"] = sum(1 for r in changes if r.get("review_class") == "A")
        status["validation"]["phase1_semantic_review_items"] = sum(1 for r in changes if r.get("review_class") == "B")
        status["validation"]["phase1_anomaly_review_items"] = sum(1 for r in changes if r.get("review_class") == "C")
    out_status.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    configure_console_output()
    raise SystemExit(main())
