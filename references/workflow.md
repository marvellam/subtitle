# Course Subtitle Proofreader Workflow

## Operating Model

The skill is split into two layers:

- **Reusable skill**: parsing, validation, chunking strategy, output contracts, comparison tools, AI-pass bridge.
- **Project folder**: course paths, lexicon, blacklist, style rules, manual feedback, run outputs.

Each lesson run has two production stages only. Phase 1 is intermediate. Phase 2 is the human-review version.

## Two-Phase Run

### Phase 1 — Deterministic Mechanical Pass

1. Confirm the source SRT and project folder.
2. Parse and validate SRT structure: index sequence, timestamp format, block count.
3. Run deterministic proofreading with the project lexicon:
   - `auto`: direct replacement.
   - `conditional`: replacement only when nearby context contains trigger tokens.
   - `review`: mark for review, do not force change.
4. Apply speech filler cleanup.
5. Scan output against `blacklist.csv`.
6. Generate Phase 1 files:

   ```bash
   python scripts/proofread_srt.py --srt <raw.srt> --project <project> --output-in-source
   ```

   Outputs:
   - `<stem>_Phase1_机械校对.srt`
   - `<stem>_Phase1_机械修改与疑点.csv`
   - `run_status.json`

Phase 1 must not be placed into editing projects as the human-review subtitle.

### Phase 2 — AI Contextual Pass

1. Export the Phase 1 SRT as chunked JSON:

   ```bash
   python scripts/proofread_srt.py --srt <stem>_Phase1_机械校对.srt --project <project> --export-ai-chunks <ai_chunks.json>
   ```

2. Agent processes each chunk, applying:
   - audit of every `phase1_audit` item before making new fixes
   - `phase1_decision`: `accepted`, `reverted`, or `adjusted`
   - rollback of Phase 1 over-corrections when the original text fits context better
   - context-aware term disambiguation
   - pronoun correction
   - accent/ASR error correction
   - sentence-level fixes when meaning is clear

3. Apply the AI corrections back to the Phase 1 SRT:

   ```bash
   python scripts/proofread_srt.py --srt <stem>_Phase1_机械校对.srt --project <project> --apply-ai-chunks <ai_results.json>
   ```

   Outputs:
   - `<stem>_Phase2_待人工校验.srt`
   - `<stem>_Phase2_语境修正.csv` with audit categories: `accepted_phase1`, `reverted_phase1`, `adjusted_phase1`, `new_context_fix`
   - `run_status.json` with `phase2_done: true`

Phase 2 is the file to give to human subtitle review. There is no separate Step 3 delivery copy.

## Feedback Loop

After human review, compare the Phase 2 SRT with the manual SRT using approximate time alignment:

```bash
python scripts/compare_manual_srt.py --ai-srt <phase2.srt> --manual-srt <manual.srt> --out <feedback.csv>
```

Classify reusable corrections before merging:

| Type | Action |
|------|--------|
| Reusable term correction | Add to `lexicon.csv` |
| Dangerous residue | Add to `blacklist.csv` |
| One-off stylistic edit | Keep in feedback only |
| Timing/block split change | Keep outside the lexicon |

Merge approved corrections:

```bash
python scripts/update_lexicon.py --project <project> --feedback <approved_feedback.csv>
```

## Chunking Rules

- Default: 100 subtitles per chunk, 10 context lines per side.
- AI pass edits are bounded to the target chunk. Context is read-only.
- A running tail summary is carried between chunks for topic/pronoun continuity.
- The script's `--chunk-size` and `--context-size` flags override defaults.
- For courses with very short subtitles, increase chunk size to 200.
- Chunk items may include `phase1_audit` with Phase 1 original text, revised text, risk, rule, and context. Treat medium/high Phase 1 changes as hypotheses, not facts.

## Session Continuity Note

When the agent processes Phase 2, carry a `course_context` summary across sessions:
- course: 赵春恒宋代花鸟画
- speaker: 赵春恒 (湖南口音)
- key terminology: 芙蓉(花), 木本植物, 花托, 花蕊, 骨法用笔, 随类赋彩, 宿墨
- common ASR errors: 圣代→宋代, 方言化→花鸟画, 湖人/壶人/无人→芙蓉
