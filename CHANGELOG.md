# Changelog

## Unreleased (30 Sep 2026)

### Changed
- **The case study is now a full PM case study:** why it matters, what Spotify already does, hypotheses, options with impact and confidence, the proposal, metrics and experiment, sizing, risks, rollout and a reflection. Method details moved to an appendix.
- **The headline moved** from "skipped less on a first listen" (a pooling effect) to "they stick less" (10 of 10 listeners, p = 0.002).
- **Every gap is reported pooled *and* within listeners** (`bootstrap_ci.py`).
- **The experiment's primary metric** is now a *different* song by the artist in days 30–90, excluding the re-introduced song.
- **Sizing is a funnel** built on the actual trigger rules (`sizing.py`).
- **Charts:** 1 and 5 are per-listener dumbbells; 4 uses the new metric; the "lean-back" wording is fixed.
- **Genres:** "lo-fi" only counts as functional music when it's an artist's first tag and no indie, rock, folk or R&B tag is present (664 artists refiled, e.g. TV Girl, Joji).
- **Unwrapped:** "lesser-known" uses the same rank-within-genre rule as the SQL.
- **`03_build_facts.sql`:** the window is set to October 2021 in the repo copy, and the error message is clearer.

### Added
- `05_listener_counts.sql`, `bootstrap_ci.py`, `sizing.py`, `pseudonymise.py`, `check_size_measure.py`, `spotify_check.csv`
- Q2b, Q5b (same-song column), Q11–Q11c (liked but lost), Q12 (fixed cut-offs by genre), Q13 (catalogue sensitivity)
- `REVIEW_LOG.md` (code review and two peer-review rounds), `ISSUES.md`, `LEARNING.md`, `.gitignore`

### Security
- Listener codes are replaced by random public codes. The key, raw outputs, interviews and transcripts stay private.
- The case study no longer names any friend.

### Fixed
- `02_load_data.sql` starts with `SET NAMES utf8mb4`, so track names with unusual symbols load on any client.
