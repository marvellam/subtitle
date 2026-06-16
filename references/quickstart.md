# Quickstart

This guide shows the shortest path from installation to the first proofreading run.

## 1. Create a project/profile

A project keeps reusable corrections and review history for one subtitle context.

You do **not** need to fill the lexicon before the first run.

```powershell
python scripts/init_project.py --name art-course-2026
```

This creates:

```text
subtitle-projects/art-course-2026/
├─ project.yml
├─ lexicon.csv
├─ blacklist.csv
├─ style_rules.yml
├─ feedback/
└─ runs/
```

Use a concrete but generic project name, such as:

```text
art-course-2026
museum-interview-series
weekly-talk-show
product-training-videos
history-lecture-audio
```

## 2. Run Phase 1 on an existing SRT

```powershell
python scripts/proofread_srt.py `
  --srt "C:\path\to\raw.srt" `
  --project "subtitle-projects\art-course-2026" `
  --output-in-source
```

Phase 1 preserves SRT structure and produces mechanical review artifacts.

## 3. Ask the agent to run Phase 2

Give the agent the Phase 1 output folder and say:

```text
Please run Phase 2 contextual proofreading for this SRT.
```

The agent should follow `SKILL.md` and `references/workflow.md`.

Phase 2 output:

```text
*_Phase2_待人工校验.srt
*_Phase2_语境修正.csv
*_Phase2_人工复验重点.csv
```

## 4. Human review and feedback

After manually correcting the Phase 2 SRT, save it as a new file, for example:

```text
raw_manual.srt
```

Compare AI output with manual output:

```powershell
python scripts/compare_manual_srt.py `
  --ai-srt "path\to\raw_Phase2_待人工校验.srt" `
  --manual-srt "path\to\raw_manual.srt" `
  --out "subtitle-projects\art-course-2026\feedback\raw_manual_diff.csv"
```

Review the diff CSV. Only merge approved reusable corrections:

```powershell
python scripts/update_lexicon.py `
  --project "subtitle-projects\art-course-2026" `
  --feedback "subtitle-projects\art-course-2026\feedback\approved_feedback.csv"
```
