# Changelog

## 0.2.1 - 2026-07-13

### Changed

- Limited Phase 2 to local corrections and added an explicit proposal path for large replacements.
- Simplified the editor-facing review sheet to source text, current SRT text, suggested change, reason, and handling status.
- Replaced the misleading `production_ready` flag with internal structure, semantic-guard, and delivery-status fields.
- Changed feedback learning to compare the Phase 1/source baseline with the manual final SRT instead of trusting Phase 2 as ground truth.

### Fixed

- Prevented isolated high-impact rewrites from being silently written into the SRT.
- Blocked Phase 2 delivery when high-impact edits cluster within one passage.
- Added a regression check modeled on the multi-cue reconstruction pattern found in production use.

## 0.2.0 - 2026-07-11

### Changed

- Renamed the public Skill and repository to `subtitle` for a shorter, platform-neutral identity.
- Reframed the default workflow around preserving mature Jianying/CapCut timing while improving text accuracy.
- Added isolated speaker/course/domain profiles for multi-lecturer content organizations.
- Added `deep`, `focused`, and explicit `mechanical` review modes with coverage reporting.
- Limited mechanical changes to certified project-local rules; conditional rules now remain Agent candidates.
- Made `project.yml` and `style_rules.yml` active runtime configuration.
- Added trusted project context files, external-path approval boundaries, and protected terminology.
- Replaced forced-change Phase 2 checks with coverage-, reason-, and schema-based quality gates.
- Added cue-independent terminology candidates for feedback from manually resegmented subtitles.
- Required explicit approval before long-term lexicon updates.

### Fixed

- Removed unsafe repeated-character collapsing such as `刚刚 → 刚`.
- Removed unsafe sentence-prefix deletion such as `对照 → 照`.
- Prevented conflicting lexicon rules from being applied by file order.
- Stopped output generation when source SRT structure is invalid.
- Added UTF-8 and spreadsheet-formula safety checks.

### Added

- Python 3.10+ / PyYAML dependency declaration.
- Public sample project with course materials and protected terms.
- Cross-platform automated tests for Windows, macOS, and Ubuntu.
- Detailed Chinese working-principles documentation.

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
