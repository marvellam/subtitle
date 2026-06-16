# SRT Rules

## Proofread Mode

Proofread mode must preserve:

- Index sequence.
- Timestamp sequence.
- Subtitle block count.

It may change only subtitle body text.

## Edit Mode Boundary

If a user asks to merge blocks, delete blocks, or adjust timings, treat it as a separate "edit mode" request. Do not mix it with proofread mode.

## Validation

Every run should report:

- Source item count.
- Output item count.
- Parse errors.
- Index sequence equality.
- Timestamp sequence equality.
- Changed item count.
- Review item count.
- Blacklist residues.

If any structural invariant fails, the output is not production-ready.
