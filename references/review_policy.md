# Review Policy

## Automatic replacement

Use `auto` only when one wrong form maps to one correction, has no reasonable valid reading in the isolated project, and has `status=active` or `status=certified`. Never auto-apply conflicting mappings.

Rows where `wrong == correct` are canonical terms, not replacement events.

## Conditional replacement

Use `conditional` when the wrong form may be valid elsewhere. Do not modify it mechanically; generate an Agent candidate with matched context. If multiple corrections exist, create a high-risk review item.

## Contextual review

Use `review` for plausible names, foreign-language examples, pronouns, grammar particles, titles, or terms requiring subject expertise or listening.

An Agent may accept the source text when evidence supports it. Quality is measured by complete, reasoned review—not by forcing a minimum number of changes.

## Speech and repetition

Blank only a whole subtitle block that exactly matches a configured standalone filler. Do not mechanically delete sentence-start discourse words. Do not mechanically collapse repeated Chinese characters.
