# Discovery Gap

**Do lesser-known artists get a fair chance on Spotify?**

A product case study built on real Spotify listening data: the Extended Streaming History exports of 10 friends (about 1.68 million plays), analysed in MySQL, plus four listener interviews.

**Headline:** lesser-known artists get a fair first listen on Spotify, but they don't stick. For all 10 listeners, fewer lesser-known artists were still being played 30–90 days later, and the second chance depends mostly on luck.

- **Read the case study:** [the interactive website](https://helena-byte999.github.io/discovery-gap/), or as text in [`case_study.md`](case_study.md)
- **See the SQL:** [`04_analysis.sql`](04_analysis.sql)
- **How it was checked:** [`REVIEW_LOG.md`](REVIEW_LOG.md)

> An independent case study, not affiliated with or endorsed by Spotify. Artist data from Last.fm and Deezer. Friends appear only as random codes (L01–L10). Raw listening data, interviews and per-person outputs are private and never published (see `.gitignore`). Nor are the artist lists the lookups were run on (`artists.csv`, `artist_info.csv`, `deezer_info.csv`): they name every artist the friends played, with play counts, which would expose individual listening. Only aggregated results are committed.

## A finding about the data itself: open databases undercount African artists

Measuring "lesser-known" turned out to be the hardest part, because the open data sources lean Western.

- **With one global cut-off on Last.fm listeners, 357 of 412 Afrobeats artists and 147 of 148 amapiano artists came out "lesser-known".** Burna Boy, Tems and Wizkid were only "mid"; amapiano star Kabza De Small was "small" ([`results/size_and_catalogue_checks.txt`](results/size_and_catalogue_checks.txt)).
- **A hand check of 30 artists against Spotify monthly listeners found Last.fm undercounts African artists about 3.5× compared with Western ones**, but still ranks them in the right order within each group (rank correlation 0.91, [`results/size_measure_check.txt`](results/size_measure_check.txt)).
- **Deezer, the second measure, puts African genres a size tier higher than Last.fm much more often** (45% of amapiano and 30% of afrobeats artists, against about 10% for hip-hop and pop), which fits the Last.fm undercount.
- **The fix:** rank artists within their own genre instead of using one cut-off. Artists with no genre tag still fall back to the cut-off; see Limitations.

---

## How it works

```
Spotify exports (JSON) ─→ load_history.py ─→ MySQL ─→ 03_build_facts.sql ─→ 04_analysis.sql ─→ case_study.md
Last.fm size + tags ─────→ (fetch_artist_info.py)          │                    05_listener_counts.sql
Hand-checked genres ─────→ artist_genres.csv                │                           │
                                                            └─→ results/raw/ (private) ─→ pseudonymise.py
                                                                                        ─→ bootstrap_ci.py, sizing.py, make_charts.py
```

| File | What it does |
|---|---|
| `01_schema.sql` | Creates the `spotify_discovery` database |
| `load_history.py` | Reads everyone's exports and writes `02_load_data.sql`. Drops podcasts, never loads IP addresses, and merges artist spellings that differ only in capitals or accents. |
| `fetch_artist_info.py` | Looks up each artist on Last.fm (listeners and top tags) and turns the tags into genres |
| `fetch_deezer_info.py` | Deezer fan counts, the second size measure. Each match is confirmed through the artist's most-played track. |
| `artist_genres.csv` | Hand-checked genres for the most-played artists; these win over Last.fm |
| `03_build_facts.sql` | Measures artist size and builds `play_facts`: one row per play, with skip, start type and first-listen fields. The window starts in October 2021. |
| `04_analysis.sql` | The analysis, Q0–Q13 |
| `05_listener_counts.sql` | Per-listener counts behind the headline numbers (charts 1, 2, 3, 5) |
| `06_liked_but_lost.sql` | The liked-but-lost group per listener (chart 4, sizing) |
| `pseudonymise.py` | Swaps listener codes for random public ones (L01–L10). The key stays private. |
| `bootstrap_ci.py` | Pooled *and* within-listener results: bootstrap ranges, sign tests, leave-one-out |
| `sizing.py` | Opportunity funnel and A/B test size (measured ICC, unequal-cluster design effect) |
| `check_size_measure.py` + `spotify_check.csv` | Checks Last.fm against 30 artists' Spotify monthly listeners |
| `make_charts.py` | Draws the five charts in `charts/` straight from the query results, and prints the numbers |
| `make_unwrapped.py` | A private "Unwrapped" recap for each friend, using the same definitions |
| `generate_sample_exports.py` | Makes realistic *fake* exports (fixed seed), so the pipeline can be run without anyone's real data |
| `results/` | Public outputs: confidence ranges, sizing, checks, per-listener counts (codes only) |

## Measuring artist size

"Lesser-known" (`small` in the SQL) is **ranked within the artist's own genre**:

1. Each artist's Last.fm listener count is ranked against artists of the same genre.
2. The bottom third is lesser-known, the top third is big, the rest is mid.
3. Genres with fewer than 50 artists are ranked with related genres (African genres, UK scenes, other small genres).
4. Artists with no genre use fixed cut-offs (under 100k, 100k–1M, 1M+). **That applies to 71% of lesser-known lean-back first listens**, and almost all of these artists are very small.

**Why not one cut-off?** Last.fm's audience leans Western. With fixed cut-offs, 357 of 412 Afrobeats artists came out lesser-known, and Burna Boy was only "mid" (Q12). A hand check of 30 artists against Spotify shows Last.fm undercounts African artists about 3.5× compared with Western ones. It still orders artists correctly within each group (rank correlation 0.91), which is all that ranking within genre needs.

## Definitions

| Term | Definition |
|---|---|
| **Skip** | Played under 30 seconds, or ended by pressing next. (Spotify counts a stream at 30 seconds. The export's own `skipped` flag is unreliable before 2023, Q8.) |
| **Lean-back** | Started with `trackdone`: it played on by itself, from a playlist, album, radio or autoplay. This includes the listener's own playlists. |
| **Chosen** | Started with `clickrow` or `playbtn`, including tapping a song inside a Spotify mix |
| **First listen** | The first play of an artist in a listener's whole export, after a 30-day warm-up |
| **Liked** | A lean-back first listen that wasn't skipped |
| **Lost** | Liked, then no play of the artist from day 1 to day 14 |
| **Stuck** | Played, not skipped, in days 30–90 |
| **Different song** | A non-skipped play of another song by the artist in days 30–90 (the proposed experiment's primary metric) |

## Rerun it

From this folder, in Terminal. Put your Last.fm key in a `.env` file first (copy `.env.example`; `.env` is git-ignored). To try it without real data, run `python3 generate_sample_exports.py` and use `sample_data` in place of `ext_streaming_history`.

```
python3 load_history.py ext_streaming_history
mysql -u root -p < 01_schema.sql
mysql -u root -p spotify_discovery < 02_load_data.sql
mysql -u root -p spotify_discovery < 03_build_facts.sql
mysql -u root -p -t spotify_discovery < 04_analysis.sql > results/04_output.txt     # private: has per-listener tables
mysql -u root -p spotify_discovery < 05_listener_counts.sql > results/raw/listener_counts.tsv
mysql -u root -p spotify_discovery < 06_liked_but_lost.sql  > results/raw/liked_but_lost.tsv
python3 pseudonymise.py
python3 make_charts.py        # draws all five charts and prints the numbers behind them
python3 bootstrap_ci.py      > results/confidence_ranges.txt
python3 sizing.py            > results/sizing_output.txt
python3 check_size_measure.py > results/size_measure_check.txt
```

In PopSQL instead: run `05_listener_counts.sql` and `06_liked_but_lost.sql`, export each result as CSV into `results/raw/` (as `listener_counts.csv` and `liked_but_lost.csv`), then run the Python lines above. `make_charts.py` needs matplotlib (`pip3 install matplotlib`).

## Limitations

- **10 friends, mostly heavy listeners in Nigeria and the UK.** Every gap is therefore checked *within* each listener, not just pooled. One listener has about 27% of the plays, and another supplies over half the lesser-known lean-back first listens.
- **Lean-back mixes autoplay with the listener's own playlists,** and "liked" means only "not skipped".
- **Size is relative** to what these listeners play, and untagged artists fall back to fixed cut-offs, where the Last.fm undercount of African artists isn't corrected.
- **"First listen" means first in the export,** and catalogue sizes aren't known (see Q13).
- **Observational data:** recommendations that weren't played, and discovery off Spotify, can't be seen.
