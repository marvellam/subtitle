# Changelog

## 0.1.0 - 2026-06-16

### Added

- Initial public packaging as `subtitle-proofreader`.
- Conservative SRT text proofreading workflow:
  - preserve index sequence
  - preserve timestamps
  - preserve subtitle block count
  - edit subtitle body text only
- Project/profile onboarding via `scripts/init_project.py`.
- Empty-first lexicon flow: users create a project container first; reusable terms are learned from approved human corrections later.
- Phase 1 mechanical pass with review CSVs.
- Phase 2 contextual proofreading bridge for agents.
- Manual review comparison and lexicon update tools.
- Quickstart guide and generic project naming examples.

### Scope

This tool proofreads existing `.srt` files. It does not generate subtitles from audio/video and does not retime, merge, or split subtitle blocks.
