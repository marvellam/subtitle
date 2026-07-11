from __future__ import annotations

import argparse
import csv
from pathlib import Path


FIELDS = ["wrong", "correct", "category", "confidence", "condition", "source_lesson", "note", "status", "verified_count", "last_verified"]
DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows: list[dict[str, str]] = []
        for raw in csv.DictReader(f):
            row = {(k or "").lstrip("\ufeff").strip(): (v or "") for k, v in raw.items()}
            rows.append(row)
        return rows


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--feedback", required=True, help="CSV with wrong/correct/category/confidence/condition/source_lesson/note. A row is merged only when merge_decision/decision is explicitly approved.")
    args = parser.parse_args()
    project = Path(args.project)
    lexicon_path = project / "lexicon.csv"
    existing = read_rows(lexicon_path)
    seen = {(r.get("wrong", ""), r.get("correct", "")) for r in existing}
    added = 0
    skipped_unsafe = 0
    for row in read_rows(Path(args.feedback)):
        decision = (row.get("merge_decision") or row.get("decision") or "").strip().lower()
        if decision not in ("approved", "yes", "y", "merge"):
            continue
        wrong = (row.get("wrong") or row.get("candidate_wrong") or "").strip()
        correct = (row.get("correct") or row.get("candidate_correct") or "").strip()
        if not wrong or not correct or wrong == correct:
            continue
        if wrong.startswith(DANGEROUS_CSV_PREFIXES) or correct.startswith(DANGEROUS_CSV_PREFIXES):
            skipped_unsafe += 1
            continue
        key = (wrong, correct)
        if key in seen:
            continue
        existing.append({
            "wrong": wrong,
            "correct": correct,
            "category": row.get("category", "人工反馈"),
            "confidence": row.get("confidence", "review"),
            "condition": row.get("condition", ""),
            "source_lesson": row.get("source_lesson", ""),
            "note": row.get("note", "manual feedback"),
            "status": row.get("status", "candidate"),
            "verified_count": row.get("verified_count", "1"),
            "last_verified": row.get("last_verified", ""),
        })
        seen.add(key)
        added += 1
    write_rows(lexicon_path, existing)
    print(f"merged {added} rows into {lexicon_path}; skipped_unsafe={skipped_unsafe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
