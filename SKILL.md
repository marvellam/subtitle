---
name: subtitle-proofreader
description: Existing SRT subtitle text proofreading workflow. Use when an agent needs to correct .srt subtitle text while preserving numbering, timestamps, and block count; apply project/profile lexicons; generate review artifacts; compare AI output with a manually corrected SRT; or feed approved human corrections back into reusable project dictionaries.
---

# Subtitle Proofreader

## Purpose

Use this skill to turn existing SRT subtitles into a controlled two-phase text proofreading workflow. The contract is conservative: preserve every SRT index and timestamp, change only subtitle text, and output clear CSV artifacts for human review.

Keep the reusable workflow in this skill. Keep project-specific paths, terms, blacklists, and manual feedback in a separate project folder such as `subtitle-projects/<project-slug>/`.

## Workflow

### Phase 1 — Mechanical Pass

1. Identify the project folder and read `project.yml`, `lexicon.csv`, `blacklist.csv`, and `style_rules.yml`.
2. Parse the input SRT and validate index/timestamp sequence before editing.
3. Apply deterministic lexicon rules first:
   - `auto`: replace directly.
   - `conditional`: replace only when nearby context satisfies the condition.
   - `review`: do not force replace; add to the Phase 1 CSV.
4. Apply speech-cleanup rules conservatively:
   - Remove or blank standalone filler blocks such as `啊`, `哈`, `嗯`, `呃`, `哎`.
   - Remove low-information sentence-final fillers.
   - Mark discourse words such as `这个`, `那个`, `那么`, `是吧`, `好不好` for review unless the project explicitly says to remove them.
5. Output exactly:
   - `<stem>_Phase1_机械校对.srt`
   - `<stem>_Phase1_机械修改与疑点.csv`
   - `<stem>_Phase1_auto_applied.csv` for Class A low-risk automatic changes that are recorded but not sent to Phase 2 review.
   - `<stem>_Phase1_semantic_review.csv` for Class B semantic review items, such as pronouns, risky conditional/review lexicon hits, and context-dependent substitutions.
   - `<stem>_Phase1_anomaly_review.csv` for Class C mandatory anomaly review items, such as Latin leftovers, mixed Latin/CJK fragments, suspicious ASR terms, blacklist-like issues, or non-grammatical lines.
   - `run_status.json`

Phase 1 is an intermediate artifact for Phase 2 and debugging. Do not hand Phase 1 SRT to editing projects as the human-review version.

### Phase 2 — AI Contextual Pass

Run Phase 2 when there are review items, blacklist hits, or known context-dependent issues. For this proofreading workflow, Phase 2 is expected before human review.

1. Export chunks from the Phase 1 SRT, not from the raw SRT:

   ```bash
   python scripts/proofread_srt.py \
     --srt "<run>\第2课_Phase1_机械校对.srt" \
     --project "<project>" \
     --export-ai-chunks "<run>\第2课_ai_chunks.json"
   ```

2. The agent reads each chunk with project-specific knowledge and applies context-aware fixes.

   **CRITICAL — How to execute this step (correct pattern from verified GPT execution):**

   a. Read `ai_chunks.json` into memory.
   b. For each chunk, read its `context_before`, `chunk_items`, and `context_after` together as a coherent passage.
   c. For each `chunk_item` that has a `phase1_audit` block, evaluate whether the Phase 1 change is correct in this specific context. Do not assume correctness — audit every item individually.
   d. Set `phase1_decision` on each audited item: `accepted` (Phase 1 was right), `reverted` (Phase 1 was wrong, restore original), or `adjusted` (Phase 2 provides a different correction).
   e. When adjusting, update `item.text` to the corrected text.
   f. Add a `reason` field for every audited item explaining the contextual judgment.
   g. After reviewing all audit items, look for issues Phase 1 missed (pronouns like 他/它 confusion, missed terminology, remaining Latin/English artifacts, sentence fragments that should connect) and add `new_context_fix` entries for them.
   h. Write the modified structure back as `ai_results.json`. **The ai_results.json must have the same top-level keys and nested structure as ai_chunks.json** — do not invent a new format.

   **FORBIDDEN EXECUTION PATTERNS (will produce invalid output):**
   - ❌ Writing a Python script with `write` tool to batch-process chunks with rule-based keyword matching
   - ❌ Setting every item to `accepted` without reading context
   - ❌ Inventing a new JSON structure (e.g., a top-level `changes` array) instead of preserving the chunks/chunk_items structure

   Specific contextual checks to perform (in addition to auditing Phase 1 decisions):
   - **Pronouns**: In course context about objects (paintings, leaves, colors, tools), `他` should be `它`. Only keep `他` when clearly referring to a person (the teacher, the artist, the ancients).
   - **Terminology disambiguation**: When a multi-meaning word appears, verify the Phase 1 choice against surrounding sentences.
   - **ASR accent errors**: Listen for Hunan-accent patterns — `硬笔→用笔`, `光系/光细→关系`, `忍/人→染`, `圆→染`, `卷→转/绢`, `蹭→衬/蹭`, `发→画/花`.
   - **Anomaly items** (`requires_phase2_decision: true`): Latin leftovers like `3D`, `OK`, `um`, `yeah`, `so` must be replaced with Chinese equivalents. `OK→可以/好了`, `3D→三维`, English fillers → blank or Chinese equivalent.
   - **Sentence fragments**: When two consecutive items form one complete sentence, consider whether the break is artificial and adjust phrasing for readability.
   - **Reduplication/restored text**: When Phase 1 deleted a repeated word that was intentional (e.g., `去要去调锋` → `要去调锋`), restore if the reduplication carries instructional emphasis.

3. Apply the AI results back to the Phase 1 SRT. **Must use `--out-dir` to write Phase 2 output into the SAME directory as Phase 1** (NOT `--output-in-source`, which creates a new directory):

   ```bash
   python scripts/proofread_srt.py \
     --srt "<run>\第2课_Phase1_机械校对.srt" \
     --project "<project>" \
     --apply-ai-chunks "<run>\第2课_ai_results.json" \
     --out-dir "<run>"
   ```

   Where `<run>` is the Phase 1 output directory (e.g., `第2课_字幕校对_20260520_1815`). This ensures all Phase 1 and Phase 2 outputs live in ONE folder — Phase1 SRT, Phase2 SRT, CSV files, chunks, and results all together.

4. Output exactly:
   - `<stem>_Phase2_待人工校验.srt`
   - `<stem>_Phase2_语境修正.csv`, including `accepted_phase1`, `reverted_phase1`, `adjusted_phase1`, and `new_context_fix` rows when available
   - `<stem>_Phase2_人工复验重点.csv`, containing only human-review navigation rows: Class C anomaly rows and rows changed/reverted/adjusted by Phase 2. Class B rows accepted unchanged should remain in the full Phase2 CSV but should not crowd the human focus file.
   - `run_status.json` with `phase2_done: true` and `ai_changes_count`

Phase 2 is the version to hand to human subtitle review. The SRT is the main deliverable; `Phase2_人工复验重点.csv` is the review navigation file for humans and should stay focused.

### Phase 2 — Quality Gate (MANDATORY self-check before claiming completion)

**After generating ai_results.json, BEFORE running --apply-ai-chunks, you MUST run this self-check:**

```bash
python -c "
import json
with open('<run>/ai_results.json', 'r', encoding='utf-8-sig') as f:
    d = json.load(f)
non_acc = 0
total_audited = d.get('audit_item_count', 0)
for c in d['chunks']:
    for item in c['chunk_items']:
        pd = item.get('phase1_decision', '')
        if pd and pd != 'accepted':
            non_acc += 1
print(f'audit_items={total_audited} non_accepted={non_acc}')
if total_audited > 0 and non_acc == 0:
    print('FAIL: All audit items are accepted. Phase 2 did not perform real contextual work.')
    exit(1)
else:
    print('PASS')
"
```

**Gate rules:**
- If `audit_item_count > 0` AND `non_accepted == 0` → **FAIL**. Stop immediately. Do NOT run `--apply-ai-chunks`. Delete the broken ai_results.json and redo Phase 2 step 2 properly.
- If there are anomaly items (`phase2_anomaly_count > 0`) AND no anomaly was `adjusted` → **FAIL**. Every anomaly must be resolved.
- If the Phase 2 CSV contains only `accepted_phase1` rows with zero `new_context_fix` / `adjusted_phase1` / `reverted_phase1` → **FAIL**.

Do not proceed past this gate until it passes. Do not report completion to the user with a failing gate.

### Phase 2 Encoding Gate (MANDATORY)

When generating `ai_results.json` on Windows, do not pipe Python source containing Chinese literals through PowerShell stdin. PowerShell may replace non-ASCII characters with question marks, which corrupts `ai_results.json` and then propagates into the Phase 2 SRT/CSV.

Safe patterns:
- Write UTF-8 source/data through a real UTF-8 file, then run it.
- Or use JSON/data that was read from UTF-8 files, not typed as Chinese literals into a PowerShell pipeline.

Before and after applying AI chunks, scan `ai_results.json`, the Phase 2 SRT, and both Phase 2 CSV files for:
- `????`
- replacement characters such as `�`
- mojibake markers such as `锟`

If any are found, stop immediately, regenerate `ai_results.json` from a UTF-8-safe path, and rerun `--apply-ai-chunks`. The script now refuses to apply or write Phase 2 outputs when these corruption markers appear.

### Human Review & Feedback Loop

After human review, compare the Phase 2 SRT with the manual SRT:

```bash
python scripts/compare_manual_srt.py \
  --ai-srt "<run>\第2课_Phase2_待人工校验.srt" \
  --manual-srt "X:\path\人工校对.srt" \
  --out "<project>\feedback\第2课_manual_diff.csv"
```

Review the diff CSV, mark `merge_decision` as `approved` or `reject`, then merge authorized corrections:

```bash
python scripts/update_lexicon.py \
  --project "<project>" \
  --feedback "<project>\feedback\第2课_approved_terms.csv"
```

Only merge reviewed rows. Do not auto-merge noisy diff rows.

## Scripts

Run scripts from the skill directory or pass absolute paths.

### Phase 1 Mechanical Pass

```powershell
python scripts/proofread_srt.py `
  --srt "X:\path\第2课.srt" `
  --project "C:\Users\37617\.openclaw\workspace\subtitle-projects\zhaochunheng-songhua" `
  --lesson "初阶课-第2课" `
  --output-in-source
```

Output location rules:
1. `--out-dir <path>`: explicit output directory.
2. `--output-in-source`: creates `{source_parent}/{srt_name}_字幕校对_{YYYYMMDD_HHMM}\` next to the source SRT.
3. Default: `{project}/runs/{srt_name}_{stamp}\`.

Optional flags:
- `--chunk-size 100`
- `--context-size 10`

## Project File Rules

`lexicon.csv` fields: `wrong`, `correct`, `category`, `confidence`, `condition`, `source_lesson`, `note`.

`blacklist.csv` fields: `term`, `expected`, `severity`, `note`.

`style_rules.yml` records project-level editorial choices. Keep it concise and human-readable.

## Safety Rules

- Never overwrite the source SRT.
- Never silently change timestamps or block counts in the proofread SRT.
- If parsing errors exist, write `run_status.json` and stop before claiming the output is production-ready.
- If a term is uncertain, mark it for review instead of forcing a correction.
- Keep project-specific knowledge out of `SKILL.md`; put it in the project folder.
- Never rename or copy Phase 1 output as a human-review deliverable.
- Phase 2 must have its own CSV. If no `<stem>_Phase2_语境修正.csv` exists, do not claim the AI contextual pass ran.
- Phase 2 must not assume Phase 1 is correct. Medium/high Phase 1 changes are hypotheses to audit, not facts.
- **Single output folder**: Phase 1 and Phase 2 outputs MUST all be in ONE folder (`_字幕校对_*`). Do NOT use `--output-in-source` for the Phase 2 apply step — use `--out-dir <phase1_dir>` instead. Never produce two separate folders for the same lesson.
- **No script-wrapper anti-pattern**: Phase 2 step 2 (contextual analysis) must be performed by the agent reading chunk data and making decisions through AI reasoning. Do NOT write a Python script via the `write` tool to programmatically generate ai_results.json. The only Python scripts allowed are `proofread_srt.py` (for export/apply) and the quality gate self-check (one-liner).
