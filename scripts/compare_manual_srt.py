from __future__ import annotations

import argparse
import csv
import difflib
import re
from pathlib import Path


TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})$")


def read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Cannot decode {path}")


def ms_from_groups(groups: tuple[str, ...]) -> tuple[int, int]:
    a = (int(groups[0]) * 3600 + int(groups[1]) * 60 + int(groups[2])) * 1000 + int(groups[3])
    b = (int(groups[4]) * 3600 + int(groups[5]) * 60 + int(groups[6])) * 1000 + int(groups[7])
    return a, b


def parse_srt(text: str) -> list[dict[str, object]]:
    blocks = re.split(r"\n{2,}", text.replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff\n "))
    items: list[dict[str, object]] = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        match = TIME_RE.match(lines[1].strip())
        if not match:
            continue
        start, end = ms_from_groups(match.groups())
        text_body = "\n".join(lines[2:]).strip()
        items.append({"index": lines[0].strip(), "timestamp": lines[1].strip(), "start": start, "end": end, "text": text_body})
    return items


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def align(ai: list[dict[str, object]], manual: list[dict[str, object]], window: int = 10) -> tuple[list[tuple[dict[str, object], dict[str, object]]], list[dict[str, object]], list[dict[str, object]]]:
    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    ai_only: list[dict[str, object]] = []
    used: set[int] = set()
    j = 0
    for a in ai:
        best = None
        for k in range(j, min(len(manual), j + window)):
            if k in used:
                continue
            m = manual[k]
            start_diff = abs(int(a["start"]) - int(m["start"]))
            overlap = max(0, min(int(a["end"]), int(m["end"])) - max(int(a["start"]), int(m["start"])))
            text_score = difflib.SequenceMatcher(None, norm(str(a["text"])), norm(str(m["text"]))).ratio()
            if start_diff <= 1200 or overlap > 0 or text_score > 0.45:
                score = start_diff - overlap - int(text_score * 500)
                if best is None or score < best[0]:
                    best = (score, k, m)
        if best is None:
            ai_only.append(a)
        else:
            _, k, m = best
            used.add(k)
            j = max(j, k + 1)
            pairs.append((a, m))
    manual_only = [m for k, m in enumerate(manual) if k not in used]
    return pairs, ai_only, manual_only


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-srt", required=True)
    parser.add_argument("--manual-srt", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    ai = parse_srt(read_text(Path(args.ai_srt)))
    manual = parse_srt(read_text(Path(args.manual_srt)))
    pairs, ai_only, manual_only = align(ai, manual)
    rows: list[dict[str, str]] = []
    for a, m in pairs:
        if str(a["text"]) == str(m["text"]):
            continue
        rows.append({
            "ai_index": str(a["index"]),
            "manual_index": str(m["index"]),
            "ai_timestamp": str(a["timestamp"]),
            "manual_timestamp": str(m["timestamp"]),
            "ai_text": str(a["text"]),
            "manual_text": str(m["text"]),
            "type": "changed",
            "candidate_wrong": str(a["text"]),
            "candidate_correct": str(m["text"]),
            "merge_decision": "",
            "note": "",
        })
    for a in ai_only:
        rows.append({"ai_index": str(a["index"]), "manual_index": "", "ai_timestamp": str(a["timestamp"]), "manual_timestamp": "", "ai_text": str(a["text"]), "manual_text": "", "type": "ai_only", "candidate_wrong": "", "candidate_correct": "", "merge_decision": "", "note": ""})
    for m in manual_only:
        rows.append({"ai_index": "", "manual_index": str(m["index"]), "ai_timestamp": "", "manual_timestamp": str(m["timestamp"]), "ai_text": "", "manual_text": str(m["text"]), "type": "manual_only", "candidate_wrong": "", "candidate_correct": "", "merge_decision": "", "note": ""})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ai_index", "manual_index", "ai_timestamp", "manual_timestamp", "ai_text", "manual_text", "type", "candidate_wrong", "candidate_correct", "merge_decision", "note"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out} rows={len(rows)} pairs={len(pairs)} ai_only={len(ai_only)} manual_only={len(manual_only)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
