from __future__ import annotations

import argparse
import csv
from pathlib import Path


FIELDS = ["wrong", "correct", "category", "confidence", "condition", "source_lesson", "note"]


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
    parser.add_argument("--feedback", required=True, help="CSV with wrong/correct/category/confidence/condition/source_lesson/note. Rows are merged only when merge_decision is empty or approved.")
    args = parser.parse_args()
    project = Path(args.project)
    lexicon_path = project / "lexicon.csv"
    existing = read_rows(lexicon_path)
    seen = {(r.get("wrong", ""), r.get("correct", "")) for r in existing}
    added = 0
    for row in read_rows(Path(args.feedback)):
        decision = (row.get("merge_decision") or row.get("decision") or "approved").strip().lower()
        if decision not in ("approved", "yes", "y", "merge", ""):
            continue
        wrong = (row.get("wrong") or row.get("candidate_wrong") or "").strip()
        correct = (row.get("correct") or row.get("candidate_correct") or "").strip()
        if not wrong or not correct or wrong == correct:
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
        })
        seen.add(key)
        added += 1
    write_rows(lexicon_path, existing)
    print(f"merged {added} rows into {lexicon_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
