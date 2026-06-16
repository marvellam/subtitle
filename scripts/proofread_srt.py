from __future__ import annotations

import argparse
import csv
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}$")
CORRUPT_TEXT_RE = re.compile(r"\?{4,}|�|锟")
FILLER_ONLY = {"啊", "哈", "嗯", "呃", "哎", "唉", "额", "uh", "yeah", "okay", "ok", "hm", "hmm", "hm okay", "hmm okay"}
SENTENCE_FINAL_FILLERS = ("啊", "哈", "嗯", "呃", "哎", "唉")
DISCOURSE_WORDS = ("这个", "那个", "那么", "好不好")
# A类清理：句首/句尾固定清除
SENTENCE_START_REMOVE = ("好的", "好吧", "yeah", "okay", "ok", "uh", "hm", "hmm", "对", "是吧", "你看", "哎", "呃", "嗯", "啊", "哦")
SENTENCE_END_REMOVE = ("你看", "是吧", "好不好", "哦")
SENTENCE_START_FILLER = ("好",)

# 合法叠词白名单（不压缩）
VALID_REDUP = {"慢慢","轻轻","好好","厚厚","重重","紧紧","稳稳","明明",
              "渐渐","茫茫","滚滚","滔滔","熊熊","炯炯","翩翩","天天",
              "年年","人人","处处","时时","字字","句句","方方面面",
              "冷冷","热热","软软","硬硬","粗粗","细细","厚厚","薄薄",
              "长长","短短","远远","高高","低低","深深","浅浅","肥肥","瘦瘦",
              "圆圆","正正","歪歪","直直","弯弯","多多","少少",
              "白白","黑黑","红红","绿绿","蓝蓝","黄黄","紫紫","灰灰",
              "纷纷","洋洋","凉凉","暖暖","爽爽",
              "等等","哈哈","呵呵","嘿嘿","嘻嘻",
              "亲亲","抱抱","瞧瞧","看看","试试","尝尝","想想",
              "谢谢","仅仅",
              "香香","甜甜","苦苦","辣辣","酸酸","咸咸"}



@dataclass(frozen=True)
class LexiconRule:
    wrong: str
    correct: str
    category: str
    confidence: str
    condition: str
    source_lesson: str
    note: str


def read_text(path: Path) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=enc), enc
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Cannot decode {path}")


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
            )
            for r in rows
            if (r.get("wrong") or "").strip()
        ]


def load_blacklist(project: Path) -> list[dict[str, str]]:
    path = project / "blacklist.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f) if (r.get("term") or "").strip()]


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
    for rule in rules:
        if rule.wrong not in current:
            continue
        if rule.confidence == "auto":
            count = current.count(rule.wrong)
            current = current.replace(rule.wrong, rule.correct)
            applied.append({"old": rule.wrong, "new": rule.correct, "count": str(count), "category": rule.category, "risk": "low", "note": rule.note})
        elif rule.confidence == "conditional":
            if condition_met(rule.condition, ctx):
                count = current.count(rule.wrong)
                current = current.replace(rule.wrong, rule.correct)
                applied.append({"old": rule.wrong, "new": rule.correct, "count": str(count), "category": rule.category, "risk": "medium", "note": rule.note})
            else:
                reviews.append({"term": rule.wrong, "suggestion": rule.correct, "category": rule.category, "risk": "medium", "note": f"condition not met: {rule.condition}"})
        else:
            reviews.append({"term": rule.wrong, "suggestion": rule.correct, "category": rule.category, "risk": "medium", "note": rule.note})
    return current, applied, reviews


_SENTENCE_START_PATTERN = re.compile(r"^(好)(?!处|奇|久|像|比|转|在|画)")
_SENTENCE_START_REMOVE = re.compile(r"^(" + "|".join(re.escape(w) for w in SENTENCE_START_REMOVE) + r")\s*")
_SENTENCE_END_REMOVE = re.compile(r"\s*(" + "|".join(re.escape(w) for w in SENTENCE_END_REMOVE) + r")$")

def cleanup_fillers(text: str) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    compact = re.sub(r"\s+", "", text)
    applied: list[dict[str, str]] = []
    reviews: list[dict[str, str]] = []
    if compact in FILLER_ONLY:
        return "", [{"old": text, "new": "", "count": "1", "category": "语气词", "risk": "low", "note": "standalone filler block"}], []
    current = text
    for filler in SENTENCE_FINAL_FILLERS:
        pattern = re.compile(re.escape(filler) + r"([。！？!?，,、\s]*)$")
        if pattern.search(current):
            current = pattern.sub(r"\1", current).rstrip()
            applied.append({"old": filler, "new": "", "count": "1", "category": "语气词", "risk": "low", "note": "sentence-final filler"})
            break
    # 句首固定删除：好吧|对|是吧|你看
    m = _SENTENCE_START_REMOVE.search(current)
    if m:
        current = current[m.end():].lstrip()
        applied.append({"old": m.group(1), "new": "", "count": "1", "category": "句首语气词", "risk": "low", "note": "auto-delete sentence-start filler"})
    # 句尾固定删除：你看|是吧（循环清除多个）
    while True:
        m = _SENTENCE_END_REMOVE.search(current)
        if not m:
            break
        current = current[:m.start()].rstrip()
        applied.append({"old": m.group(1), "new": "", "count": "1", "category": "句尾语气词", "risk": "low", "note": "auto-delete sentence-end filler"})
    for word in DISCOURSE_WORDS:
        if word in current:
            reviews.append({"term": word, "suggestion": "", "category": "口语连接词", "risk": "low", "note": "mark for human review; do not delete automatically"})
    return current, applied, reviews


def cleanup_repeated_chars(text: str) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    """Remove ASR stutter repetitions while preserving legitimate 叠词."""
    applied: list[dict[str, str]] = []
    current = text
    # 3+ consecutive same chars → always reduce to 1
    current = re.sub(r'(.)(\1{2,})', lambda m: m.group(1), current)
    # 2 consecutive same chars → reduce if not in whitelist
    current = re.sub(r'(.)(\1)', lambda m: m.group(0) if m.group(0) in VALID_REDUP else m.group(1), current)
    if current != text:
        applied.append({"old": text, "new": current, "count": "1", "category": "重复字", "risk": "low", "note": "ASR stutter cleanup"})
    return current, applied, []


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


def write_html(path: Path, title: str, summary: dict[str, object], rows: list[dict[str, str]]) -> None:
    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(r.get('index',''))}</td>"
            f"<td>{html.escape(r.get('timestamp',''))}</td>"
            f"<td>{html.escape(r.get('risk',''))}</td>"
            f"<td class='before'>{html.escape(r.get('before',''))}</td>"
            f"<td class='after'>{html.escape(r.get('after',''))}</td>"
            f"<td>{html.escape(r.get('rules',''))}</td>"
            f"<td class='ctx'>{html.escape(r.get('context',''))}</td>"
            "</tr>"
        )
    summary_html = "<br>".join(f"<b>{html.escape(str(k))}</b>: {html.escape(str(v))}" for k, v in summary.items())
    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;background:#f7f3ec;color:#1a1a1a;margin:32px;}}
h1{{font-family:Georgia,"Times New Roman",serif;color:#8a6a32;}}
.summary{{background:white;padding:16px 20px;border-left:4px solid #c9a96e;margin-bottom:20px;}}
table{{border-collapse:collapse;width:100%;background:white;font-size:14px;}}
th,td{{border:1px solid #e5ded2;padding:8px;vertical-align:top;}}
th{{background:#1a1a1a;color:white;position:sticky;top:0;}}
.before{{color:#8a1f11;white-space:pre-wrap;}}
.after{{color:#11613a;white-space:pre-wrap;font-weight:600;}}
.ctx{{font-size:12px;color:#666;}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="summary">{summary_html}</div>
<table><thead><tr><th>编号</th><th>时间轴</th><th>风险</th><th>原文</th><th>校对后</th><th>规则/疑点</th><th>上下文</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody></table>
</body></html>"""
    path.write_text(doc, encoding="utf-8")


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
SUSPICIOUS_ASR_TERMS = (
    "yeah",
    "okay",
    "ok",
    "hm",
    "hmm",
    "input",
    "hold",
    "go around",
    "how",
    "b档",
    "B档",
    "防棉",
    "翳墨",
    "笔录",
    "光系",
    "影帝",
    "硬币",
    "硬笔",
)


def detect_phase2_anomaly(item: dict[str, str], ctx: str) -> dict[str, str]:
    """Recall lines that need mandatory Phase 2 review even if Phase 1 made no edit.

    These are not automatic replacements. They are high-priority review signals for
    heavy-accent ASR: Latin leftovers, mixed Latin/CJK fragments, and known
    phonetically plausible but nonsensical terms.
    """
    text_value = item.get("text", "")
    compact = re.sub(r"\s+", "", text_value)
    signals: list[str] = []
    if LATIN_RE.search(compact):
        signals.append("latin_letters")
    if MIXED_LATIN_CJK_RE.search(compact):
        signals.append("mixed_latin_cjk")
    lowered = compact.lower()
    for term in SUSPICIOUS_ASR_TERMS:
        if term.lower() in lowered:
            signals.append(f"suspicious_asr:{term}")
    if not signals:
        return {}
    return {
        "risk": "high",
        "before": text_value,
        "after": text_value,
        "rules": "Phase2 mandatory anomaly review: " + "; ".join(dict.fromkeys(signals)),
        "context": ctx,
        "requires_phase2_decision": "true",
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


def export_ai_chunks(src: Path, items: list[dict[str, str]], chunk_size: int, context_size: int, project: str, out_path: Path) -> dict:
    """Export items as chunked JSON for agent AI pass."""
    chunks = []
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
            anomaly = detect_phase2_anomaly(it, ctx)
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
        chunks.append(chunk_data)
    payload = {
        "source": str(src),
        "project": project,
        "total_items": total,
        "chunk_size": chunk_size,
        "context_size": context_size,
        "phase2_task": "Audit medium/high risk Phase 1 changes first. Then audit every high-risk anomaly item marked requires_phase2_decision=true (Latin leftovers, mixed Latin/CJK, suspicious ASR terms). For every item with phase1_audit, set phase1_decision to accepted, reverted, or adjusted. Do not mark anomaly items accepted until the whole sentence is grammatical and semantically valid in context. Revert over-corrections when the original text is correct in context; then fix additional contextual errors.",
        "audit_item_count": len(phase1_audit),
        "phase2_anomaly_count": anomaly_count,
        "chunks": chunks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def apply_ai_chunks(
    items: list[dict[str, str]],
    ai_results_path: Path,
    src: Path,
    project: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Apply AI-processed chunk text back onto items and return Phase 2 changes."""
    payload = json.loads(ai_results_path.read_text(encoding="utf-8-sig"))
    corrupt_hits: list[str] = []
    idx_map: dict[str, str] = {}
    audit_map: dict[str, dict[str, str]] = {}
    reason_map: dict[str, str] = {}
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
            phase2_changes.append({
                "index": item["index"],
                "timestamp": item["timestamp"],
                "risk": audit.get("risk", "medium"),
                "review_class": audit.get("review_class", "C" if audit.get("requires_phase2_decision") == "true" else "B"),
                "priority": audit.get("priority", "high" if audit.get("requires_phase2_decision") == "true" else "medium"),
                "need_human_check": audit.get("need_human_check", "true" if audit.get("requires_phase2_decision") == "true" else "false"),
                "change_type": change_type,
                "before": item["text"],
                "after": new_text,
                "rules": rules,
                "reason": reason_map.get(item["index"], ""),
                "context": audit.get("context", ""),
                "phase1_before": phase1_before,
                "phase1_after": phase1_after,
                "phase1_rules": phase1_rules,
            })
            item["text"] = new_text
        elif new_text is not None:
            audit = audit_map.get(item["index"], {})
            decision = (audit.get("phase1_decision") or "").strip().lower()
            if audit and decision in {"accepted", "accept", "accepted_phase1"}:
                phase2_changes.append({
                    "index": item["index"],
                    "timestamp": item["timestamp"],
                    "risk": audit.get("risk", "medium"),
                    "review_class": audit.get("review_class", "C" if audit.get("requires_phase2_decision") == "true" else "B"),
                    "priority": audit.get("priority", "high" if audit.get("requires_phase2_decision") == "true" else "medium"),
                    "need_human_check": audit.get("need_human_check", "true" if audit.get("requires_phase2_decision") == "true" else "false"),
                    "change_type": "accepted_phase1",
                    "before": item["text"],
                    "after": item["text"],
                    "rules": "确认Phase1机械修改",
                    "reason": reason_map.get(item["index"], ""),
                    "context": audit.get("context", ""),
                    "phase1_before": audit.get("before", ""),
                    "phase1_after": audit.get("after", ""),
                    "phase1_rules": audit.get("rules", ""),
                })
    print(json.dumps({"applied_changes": len(phase2_changes), "source": str(src)}, ensure_ascii=False, indent=2))
    return items, phase2_changes


def write_change_csv(path: Path, rows: list[dict[str, str]]) -> None:
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
            "before",
            "after",
            "rules",
            "reason",
            "context",
            "phase1_before",
            "phase1_after",
            "phase1_rules",
        ])
        writer.writeheader()
        writer.writerows(rows)


def find_corrupt_output_rows(items: list[dict[str, str]], rows: list[dict[str, str]]) -> list[str]:
    hits: list[str] = []
    for item in items:
        text = item.get("text", "")
        if CORRUPT_TEXT_RE.search(text):
            hits.append(f"srt index={item.get('index')} text={text!r}")
    for row in rows:
        for field in ("before", "after", "reason", "context", "phase1_before", "phase1_after", "phase1_rules"):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--srt", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--lesson", default="")
    parser.add_argument("--out-dir")
    parser.add_argument("--output-in-source", action="store_true", help="Place output in source file's parent as {src_stem}_字幕校对_{timestamp}")
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--context-size", type=int, default=10)
    parser.add_argument("--export-ai-chunks", help="Export chunked JSON for AI pass instead of running full pipeline")
    parser.add_argument("--apply-ai-chunks", help="Apply AI-processed chunk JSON and generate artifacts")
    args = parser.parse_args()

    src = Path(args.srt)
    project = Path(args.project)
    raw, source_encoding = read_text(src)
    items, parse_errors = parse_srt(raw)

    # --- AI chunk export mode ---
    if args.export_ai_chunks:
        export_ai_chunks(src, items, args.chunk_size, args.context_size, str(project), Path(args.export_ai_chunks))
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
        ctx = context_text(items, pos, args.context_size)
        new_text, applied, reviews = apply_lexicon(item["text"], ctx, lexicon)
        new_text, filler_applied, filler_reviews = cleanup_fillers(new_text)
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
            anomaly = detect_phase2_anomaly(out_item, ctx)
            if anomaly:
                row["risk"] = "high"
                row["rules"] = "; ".join(x for x in (row.get("rules", ""), anomaly.get("rules", "")) if x)
                row["requires_phase2_decision"] = "true"
            row = add_review_metadata(row)
            changes.append(row)
            if reviews or row["review_class"] in {"B", "C"}:
                review_rows.append(row)
        else:
            anomaly = detect_phase2_anomaly(out_item, ctx)
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

    lesson_label = args.lesson or src.stem
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    # Clean stem: strip previous generated suffixes if re-processing.
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
    if args.apply_ai_chunks:
        corrected, phase2_changes = apply_ai_chunks(corrected, Path(args.apply_ai_chunks), src, project)
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
                    "context": context_text(corrected, pos, args.context_size),
                    "requires_phase2_decision": "true",
                }))
    out_raw, _ = read_text(out_srt)
    out_items, out_errors = parse_srt(out_raw)
    validation = {
        "source": str(src),
        "source_encoding": source_encoding,
        "project": str(project),
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
        "chunk_size": args.chunk_size,
        "context_size": args.context_size,
        "phase": "phase2" if is_phase2 else "phase1",
        "phase1_done": True,
        "phase2_done": is_phase2,
        "ai_pass_applied": is_phase2,
        "ai_changes_count": len(phase2_changes),
    }

    if is_phase2:
        write_change_csv(out_csv, phase2_changes)
        focus_rows = phase2_focus_rows(phase2_changes)
        write_change_csv(out_focus_csv, focus_rows)
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
    raise SystemExit(main())
