# Review Policy

## Automatic replacement

Use `auto` only when one wrong form maps to one correction, has no reasonable valid reading in the isolated project, and has `status=active` or `status=certified`. Never auto-apply conflicting mappings.

Rows where `wrong == correct` are canonical terms, not replacement events.

## Conditional replacement

Use `conditional` when the wrong form may be valid elsewhere. Do not modify it mechanically; generate an Agent candidate with matched context. If multiple corrections exist, create a high-risk review item.

## Contextual review

Use `review` for plausible names, foreign-language examples, pronouns, grammar particles, titles, or terms requiring subject expertise or listening.

An Agent may accept the source text when evidence supports it. Quality is measured by complete, reasoned review—not by forcing a minimum number of changes.

Apply contextual corrections as local substitutions only. Do not reconstruct neighboring cues, move meaning across timestamps, add inferred relationships, or improve the speaker's argument. Store a large replacement as `new_context_fix.suggested_text` while keeping `item.text` unchanged.

The deterministic semantic guard must hold an isolated high-impact replacement for human review and block Phase 2 when several high-impact replacements cluster in one passage.

## Speech and repetition

Blank only a whole subtitle block that exactly matches a configured standalone filler. Do not mechanically delete sentence-start discourse words. Do not mechanically collapse repeated Chinese characters.
