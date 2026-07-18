from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
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


def parse_count(value: str) -> int:
    try:
        return int(str(value).strip() or "0")
    except (TypeError, ValueError):
        return 0


def write_promotion_review(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["wrong", "correct", "category", "verified_count", "last_verified", "status", "promote_decision", "note"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--feedback", help="CSV with wrong/correct/category/confidence/condition/source_lesson/note. A row is merged only when merge_decision/decision is explicitly approved.")
    parser.add_argument(
        "--promote-threshold",
        type=int,
        default=0,
        help="When set (>0), candidates whose verified_count reaches this value are written to promotion_review.csv for a human to certify. Nothing is auto-certified.",
    )
    args = parser.parse_args()
    project = Path(args.project)
    lexicon_path = project / "lexicon.csv"
    existing = read_rows(lexicon_path)
    index = {(r.get("wrong", ""), r.get("correct", "")): r for r in existing}
    added = 0
    bumped = 0
    skipped_unsafe = 0
    if args.feedback:
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
            today = datetime.now().strftime("%Y-%m-%d")
            match = index.get(key)
            if match is not None:
                match["verified_count"] = str(parse_count(match.get("verified_count", "0")) + 1)
                match["last_verified"] = today
                bumped += 1
                continue
            new_row = {
                "wrong": wrong,
                "correct": correct,
                "category": row.get("category", "人工反馈"),
                "confidence": row.get("confidence", "review"),
                "condition": row.get("condition", ""),
                "source_lesson": row.get("source_lesson", ""),
                "note": row.get("note", "manual feedback"),
                "status": row.get("status", "candidate"),
                "verified_count": row.get("verified_count", "1"),
                "last_verified": row.get("last_verified", today),
            }
            existing.append(new_row)
            index[key] = new_row
            added += 1
    write_rows(lexicon_path, existing)
    message = f"merged {added} rows, bumped {bumped} verified_count into {lexicon_path}; skipped_unsafe={skipped_unsafe}"

    if args.promote_threshold and args.promote_threshold > 0:
        ready = [
            r for r in existing
            if (r.get("status", "").strip().lower() in ("", "candidate", "active"))
            and (r.get("confidence", "").strip().lower() != "auto")
            and parse_count(r.get("verified_count", "0")) >= args.promote_threshold
        ]
        review_path = project / "feedback" / "promotion_review.csv"
        write_promotion_review(review_path, ready)
        message += f"; promotion_candidates={len(ready)} -> {review_path} (human certifies, nothing auto-promoted)"

    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
