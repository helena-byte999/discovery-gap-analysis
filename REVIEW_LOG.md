# Review log

How the case study was checked before publishing. It covers a code review, then an independent peer review (a reviewer with no context, acting as a Spotify PM hiring manager and a data scientist). I checked every finding against the data before acting on it.

## 1. Code review (30 Sep 2026)

| Severity | File | Issue | Fix |
|---|---|---|---|
| HIGH | `sizing.py` | Per-listener inputs came from a scratch query that wasn't in the repo, so nobody could reproduce them | Added as Q11b (and Q11c) in `04_analysis.sql`. The script now reads `results/liked_but_lost.tsv`. |
| MEDIUM | `04_analysis.sql` Q11b | Eligible months used `@window_start`, which is only set inside `03_build_facts.sql` | Uses each listener's first play in `play_facts` instead |
| MEDIUM | `bootstrap_ci.py` | Read tab-separated files only; a PopSQL export is CSV | Detects the delimiter |
| LOW | `bootstrap_ci.py` | A resample with no cases would produce NaN and skew the percentiles | NaN results are dropped |
| LOW | `03_build_facts.sql` | Error text said "tell Claude" | Now says what to check |
| LOW | `load_history.py` | The data file loads wrongly if the MySQL client isn't set to UTF-8 | The file now starts with `SET NAMES utf8mb4` |

## 2. Peer review evaluation

**21 findings: 18 confirmed and fixed, 2 partly valid, 1 not an issue.**

| # | Finding | Verdict | What changed |
|---|---|---|---|
| 1 | The first-listen gap (7.9% vs 17.8%) is mostly a pooling effect (Simpson's paradox) | **Confirmed.** Within listeners the median gap is 2.0 points, 7 of 10 show it, p = 0.34. | The headline moved to "they stick less" (10 of 10, p = 0.002). Finding 1 is now "no penalty". Every gap is reported pooled *and* within listeners. |
| 2 | Real first names, and interviewees linked to listener codes | **Confirmed** | The case study uses no names. The synthesis, transcripts and raw per-listener output are private (`.gitignore`). Still to do: each friend's OK (ISSUES.md). |
| 3 | "Nothing acts after the first listen" is wrong: paid campaigns target "programmed listeners" | **Confirmed** on Spotify's help page | Added a "what exists today" table; the claim is narrowed to *organic*, *two weeks after a liked listen*; cannibalisation added to risks |
| 4 | Lean-back returns are size-neutral, so the gap isn't about Spotify's follow-up | **Partly valid.** Pooled, yes, but that's 3c again. Within listeners, lean-back returns also lean big (8 of 10, median 5 points, p = 0.11). | Reframed: returns depend on luck and are mostly the same song; off-platform routes named as an explanation |
| 5 | "Liked = not skipped" fails for sleep listening, and 3c dominates the sizing | **Confirmed.** 3c supplies 58% of liked-but-lost lesser-known artists. | Sizing uses without-3c as the main baseline; the trigger needs a play to the end and excludes sleep and functional contexts |
| 6 | Most lesser-known first listens aren't ranked within genre | **Confirmed.** 71% are untagged, fixed cut-off. | Disclosed in A1 (tagged-only: 9.6% vs 17.8%); verified-profile rule and spam risk added |
| 7 | "Nobody goes back" contradicts the interviews | **Confirmed** | Now "rarely click back". H4 says returns via saved playlists can't be separated. |
| 8 | Sizing doesn't match the proposal; three different baselines | **Confirmed** | A funnel (triggers × cap × share heard × lift) with low and high cases; one baseline (2.3%, without 3c), with the reason |
| 9 | Weak primary metric, no ghost triggers, no dilution, design effect assumed | **Confirmed** | Primary = a *different* song in days 30–90. Adds ghost triggers, intention-to-treat, clustered standard errors, a measured ICC (0.00, planned with 0.02) and an unequal-cluster design effect. Margins defined. |
| 10 | Interview counts overstated (3 of 4, two DJs); a prompted quote used as evidence | **Confirmed** | Counts corrected; the prompted quote is marked "a lead, not evidence" |
| 11 | "Top five songs" isn't verbatim | **Confirmed** | Paraphrased without quote marks |
| 12 | Some numbers can't be traced; `@window_start` NULL in the repo copy; Burna Boy line wrong | **Mostly confirmed.** `spotify_check.csv` is in the project folder, the reviewer's copy just lacked it. | Window set to October 2021; full `04` rerun saved; Burna Boy line corrected (fixed cut-offs made him *mid*; 357 of 412 Afrobeats artists lesser-known) |
| 13 | Bootstrap ranges are shaky with 10 listeners | **Confirmed** | Within-listener mean and median, sign tests and leave-one-out added; ranges labelled "listeners like these" |
| 14 | A first listen is only the first *in the export* | **Confirmed** | Added to limits; sensitivity check logged as an issue |
| 15 | "Lean-back" described as "Spotify" | **Confirmed** | Wording and chart legends now say "played on by itself" |
| 16 | Prioritisation has no impact column; surface choice | **Confirmed** | Impact and confidence columns; v1 in radio, autoplay and mixes (where the first listen happened), with no new UI; Discover Weekly moved to v2 |
| 17 | No business case or stakeholders | **Confirmed** | Pro-rata royalties, retention, paid products and stakeholders added |
| 18 | Leading with the lawsuit reads as adversarial | **Confirmed** | Moved to risks, stated neutrally |
| 19 | Too long; add a mock-up | **Partly accepted** | Method and A2 moved to an appendix. The experiment and risks stay in the main body because a panel will ask about them. **No mock-up:** the project deliberately excludes UI. |
| 20 | Wording and charts ("never heard again", "+2.9%") | **Confirmed** | Fixed |
| 21 | Housekeeping; cite Spotify for the 30% | **Confirmed** | Spotify's page cited; stray text fixed; `__pycache__` in `.gitignore` |

### Round 2: the same reviewer checked the revision

The reviewer **withdrew #4** after the within-listener check and raised 10 more points. All were valid, and all are fixed:

| # | Finding | What changed |
|---|---|---|
| 1 | Listener codes echo nicknames; interview details link people to codes | Every listener gets a random public code (L01–L10, `pseudonymise.py`), with the key kept private. The "largest contributor" is found from the data, not hard-coded. Identifying details are removed from the text. |
| 2 | The re-introduced song could count as its own success | The primary excludes the re-introduced song (and the "would-have-been" song in control). The leading metric is now a return the listener starts, a save or a follow. |
| 3 | Catalogue size confounds "a different song" | New sensitivity check (Q13). Artists with 3+ songs seen close the gap (8.7% vs 8.9%), but that filter is biased. Disclosed; the trigger now requires several released songs. |
| 4 | Wrong denominator for "clicked back" | Fixed: 1.0% of liked first listens, about 1 in 25 returns |
| 5 | TL;DR mixed bases; big artists are lost almost as often | Bases labelled; "most artists of any size are lost; the gap is what comes next" |
| 6 | Size-check numbers untraceable | `spotify_check.csv` and `check_size_measure.py` added (reproduces 3.5× and 0.91); Afrobeats split added as Q12 |
| 7 | The baseline didn't use the trigger rules | Q11b has trigger columns; the baseline is now 3.3% and the sizing uses trigger volumes |
| 8 | A quote from a leading question was used without a flag | Flagged as a lead, not evidence |
| 9 | Two claims about Spotify couldn't be supported | Now "no public feature…" and "reaching these listeners is valued" |
| 10 | Wording and chart titles | Fixed |

**Biggest lesson:** check every pooled comparison within individuals before headlining it. The original headline number was real, but it described *who* listens, not how artists are treated.
