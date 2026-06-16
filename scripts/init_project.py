from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def slugify(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-_.")
    if not value:
        raise ValueError("project name cannot be empty")
    return value


def write_csv_if_missing(path: Path, fieldnames: list[str]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a subtitle proofreading project/profile.")
    parser.add_argument("--name", required=True, help="Project/profile name, e.g. art-course-2026")
    parser.add_argument("--root", default="subtitle-projects", help="Root directory for projects; default: subtitle-projects")
    parser.add_argument("--force", action="store_true", help="Allow using an existing project directory; existing files are not overwritten")
    args = parser.parse_args()

    slug = slugify(args.name)
    root = Path(args.root)
    project = root / slug
    if project.exists() and not args.force:
        raise SystemExit(f"Project already exists: {project}\nUse --force to keep existing files and fill missing templates.")

    project.mkdir(parents=True, exist_ok=True)
    (project / "feedback").mkdir(exist_ok=True)
    (project / "runs").mkdir(exist_ok=True)

    project_yml = project / "project.yml"
    if not project_yml.exists():
        project_yml.write_text(
            "\n".join([
                f"project: {slug}",
                f"title: {args.name.strip()}",
                "description: Existing SRT subtitle proofreading project.",
                "output_dir: runs",
                "default_chunk_size: 100",
                "default_context_size: 10",
                "proofread_mode:",
                "  preserve_index: true",
                "  preserve_timestamp: true",
                "  preserve_block_count: true",
                "notes:",
                "  - Keep project-specific terms and feedback in this folder.",
                "  - The lexicon can start empty; add approved corrections after human review.",
                "",
            ]),
            encoding="utf-8",
        )

    write_csv_if_missing(
        project / "lexicon.csv",
        ["wrong", "correct", "category", "confidence", "condition", "source_lesson", "note"],
    )
    write_csv_if_missing(
        project / "blacklist.csv",
        ["term", "expected", "severity", "note"],
    )

    style_rules = project / "style_rules.yml"
    if not style_rules.exists():
        style_rules.write_text(
            "\n".join([
                "speech_cleanup:",
                "  remove_standalone_fillers: true",
                "  remove_sentence_final_fillers: conservative",
                "  mark_discourse_words_for_review: true",
                "editorial_rules:",
                "  preserve_speaker_meaning: true",
                "  do_not_rewrite_style_aggressively: true",
                "  do_not_change_timestamps: true",
                "",
            ]),
            encoding="utf-8",
        )

    readme = project / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {args.name.strip()}\n\n"
            "This folder stores the project/profile data for subtitle proofreading.\n\n"
            "Start with an empty lexicon. After each human-reviewed subtitle, merge only approved reusable corrections.\n",
            encoding="utf-8",
        )

    print(f"Project initialized: {project}")
    print("Next step: provide an existing .srt file and run proofread_srt.py with --project", project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
