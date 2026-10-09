-- =====================================================================
-- Discovery Gap: the analysis
-- Question: do lesser-known artists get a fair chance on Spotify?
--   1. When Spotify introduces you to an artist you've never heard, is a
--      lesser-known artist skipped more than a big one?  (Q1, Q2, Q6, Q10)
--   2. How do new artists reach people, and who does Spotify introduce?  (Q2b, Q4)
--   3. After that first listen, does the artist get a second chance, and who
--      brings them back: the listener or Spotify?  (Q5, Q5b)
--   Genre is a check, not the question: does the pattern hold within genres? (Q3, Q3b)
--
-- Run all:   mysql -u root -p -t spotify_discovery < 04_analysis.sql
-- Or run one query at a time in PopSQL: highlight it, then Run.
--
-- Key definitions (built in 03_build_facts.sql):
--   size_tier           small / mid / big / unknown, by the measure set in 03_build_facts.sql
--                       (default: rank within the artist's own genre; see artist_tiers there)
--   is_skip             under 30 seconds, or ended by pressing next
--   start_type          chosen (you picked it) / lean_back (carried on from a playlist,
--                       album, radio or autoplay) / navigating (arrived by skipping)
--   is_first_ever_play  first time this listener ever played this artist
--
-- Everything leaves out each listener's first 30 days: at the start of an
-- export, every artist looks "new" even if you've loved them for years.
-- =====================================================================
USE spotify_discovery;


-- ---------------------------------------------------------------------
-- Q0. Data health check: run this first on real data
-- Enough data per person? How often is `skipped` empty? How much has size and genre?
-- ---------------------------------------------------------------------
SELECT
    l.label,
    DATE(MIN(p.started_at))                          AS first_play,
    DATE(MAX(p.started_at))                          AS last_play,
    COUNT(*)                                         AS plays,
    ROUND(SUM(p.ms_played) / 3600000)                AS hours,
    COUNT(DISTINCT p.artist_name)                    AS artists,
    ROUND(100 * AVG(p.skipped IS NULL), 1)           AS pct_skipped_field_empty,
    ROUND(100 * AVG(a.lastfm_listeners IS NOT NULL), 1) AS pct_plays_size_known,
    ROUND(100 * AVG(a.genre IS NOT NULL), 1)         AS pct_plays_genre_known
FROM plays p
JOIN listeners l      ON l.listener_id  = p.listener_id
LEFT JOIN artists a   ON a.artist_name  = p.artist_name
GROUP BY l.listener_id, l.label
ORDER BY plays DESC;


-- ---------------------------------------------------------------------
-- Q0b. How are artists spread across size tiers and genres?
-- Check this before trusting any comparison: a genre with almost no
-- artists in a tier can't be compared in that tier.
-- If the tiers look badly balanced, adjust the cut-offs in 03_build_facts.sql.
-- ---------------------------------------------------------------------
SELECT
    genre,
    COUNT(DISTINCT CASE WHEN size_tier = 'small' THEN artist_name END) AS small_artists,
    COUNT(DISTINCT CASE WHEN size_tier = 'mid'   THEN artist_name END) AS mid_artists,
    COUNT(DISTINCT CASE WHEN size_tier = 'big'   THEN artist_name END) AS big_artists,
    COUNT(DISTINCT CASE WHEN size_tier = 'unknown' THEN artist_name END) AS unknown_size,
    ROUND(AVG(lastfm_listeners))                                        AS avg_listeners_per_play
FROM play_facts
GROUP BY genre
ORDER BY small_artists DESC;


-- ---------------------------------------------------------------------
-- Q0c. Suggested shared time window
-- Everyone's data covers different years. To compare like with like, use a
-- window that every listener's data covers: from the LATEST first play to the
-- EARLIEST last play. Copy the dates into @window_start / @window_end in
-- 03_build_facts.sql and rerun it. (Runs on `plays`, so it always sees full history.)
-- ---------------------------------------------------------------------
SELECT
    DATE(MAX(first_play))                                   AS suggested_window_start,
    DATE(MIN(last_play))                                    AS suggested_window_end,
    TIMESTAMPDIFF(MONTH, MAX(first_play), MIN(last_play))   AS months_shared,
    COUNT(*)                                                AS listeners
FROM (
    SELECT listener_id, MIN(started_at) AS first_play, MAX(started_at) AS last_play
    FROM plays GROUP BY listener_id
) per_listener;
-- If months_shared is long (over ~24), you can start later, e.g. the last 2 years,
-- so the analysis reflects today's Spotify.


-- ---------------------------------------------------------------------
-- Q1. THE HEADLINE: first-play skip rate by artist size
-- A first play is the moment of discovery. How often does it get skipped?
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
)
SELECT
    f.size_tier,
    SUM(f.is_first_ever_play)                                                   AS first_plays,
    ROUND(100 * AVG(CASE WHEN f.is_first_ever_play = 1 THEN f.is_skip END), 1) AS first_play_skip_pct,
    ROUND(100 * AVG(CASE WHEN f.artist_play_number > 20 THEN f.is_skip END), 1) AS established_artist_skip_pct
FROM play_facts f
JOIN bounds b ON b.listener_id = f.listener_id
WHERE f.started_at >= b.history_start + INTERVAL 30 DAY
  AND f.size_tier <> 'unknown'
GROUP BY f.size_tier
ORDER BY FIELD(f.size_tier, 'small', 'mid', 'big');


-- ---------------------------------------------------------------------
-- Q2. Is it the recommendations, or the artists?
-- Split first plays by how they started. If small artists only do badly when
-- they arrive lean-back (playlists, radio, autoplay), but fine when the listener
-- picked them, that points at how they're recommended, not at the music.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
)
SELECT
    f.start_type,
    SUM(f.size_tier = 'small')                                                  AS small_first_plays,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'small' THEN f.is_skip END), 1)     AS small_skip_pct,
    SUM(f.size_tier = 'mid')                                                    AS mid_first_plays,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'mid'   THEN f.is_skip END), 1)     AS mid_skip_pct,
    SUM(f.size_tier = 'big')                                                    AS big_first_plays,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'big'   THEN f.is_skip END), 1)     AS big_skip_pct
FROM play_facts f
JOIN bounds b ON b.listener_id = f.listener_id
WHERE f.is_first_ever_play = 1
  AND f.started_at >= b.history_start + INTERVAL 30 DAY
  AND f.start_type IN ('chosen', 'lean_back')
GROUP BY f.start_type;


-- ---------------------------------------------------------------------
-- Q2b. How do new artists reach people?  Share of first plays by route
-- For each size: what share of first plays were chosen, lean-back (Spotify
-- carried on), or arrived by skipping (navigating). Plus two checks:
--   navigating_skip_pct         first plays reached by pressing next are mostly skipped
--                               again: that's flicking through, not judging the artist
--   lean_back_skip_pct_no_lofi  lean-back skip rate without lo-fi/study/sleep music,
--                               which people rarely skip because it's background
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
),
fp AS (
    SELECT f.size_tier, f.start_type, f.is_skip, f.genre
    FROM play_facts f
    JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.size_tier <> 'unknown'
)
SELECT
    size_tier,
    COUNT(*)                                                                  AS first_plays,
    ROUND(100 * AVG(start_type = 'chosen'), 1)                                AS pct_chosen,
    ROUND(100 * AVG(start_type = 'lean_back'), 1)                             AS pct_lean_back,
    ROUND(100 * AVG(start_type = 'navigating'), 1)                            AS pct_navigating,
    ROUND(100 * AVG(start_type = 'other'), 1)                                 AS pct_other,
    ROUND(100 * AVG(CASE WHEN start_type = 'navigating' THEN is_skip END), 1) AS navigating_skip_pct,
    ROUND(100 * AVG(CASE WHEN start_type = 'lean_back' AND genre <> 'functional'
                         THEN is_skip END), 1)                                AS lean_back_skip_pct_no_lofi
FROM fp
GROUP BY size_tier
ORDER BY FIELD(size_tier, 'small', 'mid', 'big');


-- ---------------------------------------------------------------------
-- Q3. Does genre matter BEYOND size?
-- Lean-back first plays, genre by genre, within each size tier. Compare down
-- a column: e.g. small amapiano vs small r&b. That comparison holds size
-- (roughly) constant, so a gap there is about genre, not just size.
-- Ignore cells with fewer than ~30 first plays: too few to mean anything.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
)
SELECT
    f.genre,
    SUM(f.size_tier = 'small')                                               AS small_n,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'small' THEN f.is_skip END), 1)  AS small_skip_pct,
    SUM(f.size_tier = 'mid')                                                 AS mid_n,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'mid'   THEN f.is_skip END), 1)  AS mid_skip_pct,
    SUM(f.size_tier = 'big')                                                 AS big_n,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'big'   THEN f.is_skip END), 1)  AS big_skip_pct
FROM play_facts f
JOIN bounds b ON b.listener_id = f.listener_id
WHERE f.is_first_ever_play = 1
  AND f.started_at >= b.history_start + INTERVAL 30 DAY
  AND f.start_type = 'lean_back'
  AND f.genre <> 'untagged'
GROUP BY f.genre
ORDER BY mid_skip_pct DESC;


-- ---------------------------------------------------------------------
-- Q3b. Same as Q3, but counting EVERY genre an artist has, not just their main one.
-- An alté artist whose main genre is hip-hop now also counts under alte.
-- Artists with several genres appear in several rows, so the rows overlap:
-- read each row on its own, and don't add rows together.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
)
SELECT
    t.genre,
    SUM(f.size_tier = 'small')                                               AS small_n,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'small' THEN f.is_skip END), 1)  AS small_skip_pct,
    SUM(f.size_tier = 'mid')                                                 AS mid_n,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'mid'   THEN f.is_skip END), 1)  AS mid_skip_pct,
    SUM(f.size_tier = 'big')                                                 AS big_n,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'big'   THEN f.is_skip END), 1)  AS big_skip_pct
FROM play_facts f
JOIN bounds b            ON b.listener_id = f.listener_id
JOIN artist_genre_tags t ON t.artist_name = f.artist_name
WHERE f.is_first_ever_play = 1
  AND f.started_at >= b.history_start + INTERVAL 30 DAY
  AND f.start_type = 'lean_back'
GROUP BY t.genre
ORDER BY mid_skip_pct DESC;


-- ---------------------------------------------------------------------
-- Q4. Who gets recommended?  Popularity bias
-- Of the new artists people discover, what share are small?
-- Compare discoveries that arrived lean-back (mostly recommendations) with
-- ones people found themselves. If recommendations introduce far fewer small
-- artists, that's popularity bias: the rich get richer.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
)
SELECT
    f.start_type                                           AS how_discovered,
    COUNT(*)                                               AS new_artists,
    ROUND(100 * AVG(f.size_tier = 'small'), 1)             AS pct_small,
    ROUND(100 * AVG(f.size_tier = 'mid'), 1)               AS pct_mid,
    ROUND(100 * AVG(f.size_tier = 'big'), 1)               AS pct_big,
    ROUND(AVG(f.lastfm_listeners))                         AS avg_listeners
FROM play_facts f
JOIN bounds b ON b.listener_id = f.listener_id
WHERE f.is_first_ever_play = 1
  AND f.started_at >= b.history_start + INTERVAL 30 DAY
  AND f.start_type IN ('chosen', 'lean_back')
  AND f.size_tier <> 'unknown'
GROUP BY f.start_type;


-- ---------------------------------------------------------------------
-- Q5. Did the discovery stick?  Artist survival by size
-- Of artists a listener first heard (after their first 30 days, and at least
-- 90 days before their data ends), how many did they come back to?
--   second_listen: played again within 30 days
--   stuck:         played (not skipped) 30-90 days after first hearing
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start, MAX(started_at) AS history_end
    FROM play_facts GROUP BY listener_id
),
discoveries AS (
    SELECT f.listener_id, f.artist_name, f.size_tier, f.start_type AS first_start_type,
           f.artist_first_heard_at AS first_heard
    FROM play_facts f
    JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.started_at <= b.history_end   - INTERVAL 90 DAY
      AND f.size_tier <> 'unknown'
),
followups AS (
    SELECT d.listener_id, d.artist_name,
           MAX(f.started_at >  d.first_heard AND f.started_at <= d.first_heard + INTERVAL 30 DAY)  AS second_listen,
           MAX(f.started_at >  d.first_heard + INTERVAL 30 DAY
               AND f.started_at <= d.first_heard + INTERVAL 90 DAY AND f.is_skip = 0)               AS stuck
    FROM discoveries d
    JOIN play_facts f ON f.listener_id = d.listener_id AND f.artist_name = d.artist_name
    GROUP BY d.listener_id, d.artist_name
)
SELECT
    d.size_tier,
    d.first_start_type,
    COUNT(*)                                   AS artists_discovered,
    ROUND(100 * AVG(fu.second_listen), 1)      AS pct_second_listen_30d,
    ROUND(100 * AVG(fu.stuck), 1)              AS pct_stuck_30_90d
FROM discoveries d
JOIN followups fu ON fu.listener_id = d.listener_id AND fu.artist_name = d.artist_name
WHERE d.first_start_type IN ('chosen', 'lean_back')
GROUP BY d.size_tier, d.first_start_type
ORDER BY FIELD(d.size_tier, 'small', 'mid', 'big'), d.first_start_type;


-- ---------------------------------------------------------------------
-- Q5b. What happens after a liked first listen?  The second chance
-- Lean-back first plays that were NOT skipped (the listener liked it, or at
-- least let it play). Did the artist get played again within 30 days, and how
-- did that next play start?
--   by_listener   = the listener clicked or pressed play on the artist themselves
--   lean_back     = it played on by itself: Spotify's mixes, radio or autoplay, OR the
--                   listener's own saved playlist or Liked Songs (the export can't tell)
--   same_track    = of the lean-back returns, the same song as the first listen playing
--                   again (a playlist replaying it), not a new song by the artist
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start, MAX(started_at) AS history_end
    FROM play_facts GROUP BY listener_id
),
liked_firsts AS (
    SELECT f.listener_id, f.artist_name, f.size_tier, f.started_at AS first_at, f.track_uri AS first_track
    FROM play_facts f
    JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1
      AND f.start_type = 'lean_back'
      AND f.is_skip = 0
      AND f.size_tier <> 'unknown'
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.started_at <= b.history_end   - INTERVAL 30 DAY
),
comebacks AS (
    SELECT l.listener_id, l.artist_name, f.started_at, f.start_type, f.track_uri,
           ROW_NUMBER() OVER (PARTITION BY l.listener_id, l.artist_name ORDER BY f.started_at) AS rn
    FROM liked_firsts l
    JOIN play_facts f ON f.listener_id = l.listener_id AND f.artist_name = l.artist_name
    WHERE f.started_at >= l.first_at + INTERVAL 1 DAY      -- a new session, not the same album carrying on
      AND f.started_at <  l.first_at + INTERVAL 30 DAY
)
SELECT
    l.size_tier,
    COUNT(*)                                                                   AS liked_first_listens,
    ROUND(100 * AVG(c.listener_id IS NOT NULL), 1)                             AS pct_back_within_30d,
    ROUND(100 * AVG(COALESCE(c.start_type = 'chosen', 0)), 1)                  AS pct_back_by_listener,
    ROUND(100 * AVG(COALESCE(c.start_type = 'lean_back', 0)), 1)               AS pct_back_lean_back,
    ROUND(100 * AVG(COALESCE(c.start_type = 'lean_back' AND c.track_uri = l.first_track, 0)), 1)
                                                                               AS pct_back_lean_back_same_track,
    ROUND(100 * AVG(COALESCE(c.start_type NOT IN ('chosen', 'lean_back'), 0)), 1) AS pct_other_route
FROM liked_firsts l
LEFT JOIN comebacks c ON c.listener_id = l.listener_id AND c.artist_name = l.artist_name AND c.rn = 1
GROUP BY l.size_tier
ORDER BY FIELD(l.size_tier, 'small', 'mid', 'big');


-- ---------------------------------------------------------------------
-- Q6. Is it everyone, or one person?  The gap per listener
-- With 5-10 people, one heavy listener can drive the whole result.
-- A finding is much stronger if most listeners show it.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
)
SELECT
    l.label,
    SUM(f.size_tier = 'small')                                               AS small_first_plays,
    SUM(f.size_tier = 'big')                                                 AS big_first_plays,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'small' THEN f.is_skip END), 1)  AS small_skip_pct,
    ROUND(100 * AVG(CASE WHEN f.size_tier = 'big'   THEN f.is_skip END), 1)  AS big_skip_pct,
    CASE
        WHEN SUM(f.size_tier = 'small') < 20 OR SUM(f.size_tier = 'big') < 20 THEN 'too little data'
        WHEN AVG(CASE WHEN f.size_tier = 'small' THEN f.is_skip END)
           > AVG(CASE WHEN f.size_tier = 'big'   THEN f.is_skip END) THEN 'lesser-known skipped more'
        ELSE 'lesser-known skipped less or equal'
    END                                                                      AS verdict
FROM play_facts f
JOIN bounds b    ON b.listener_id = f.listener_id
JOIN listeners l ON l.listener_id = f.listener_id
WHERE f.is_first_ever_play = 1
  AND f.started_at >= b.history_start + INTERVAL 30 DAY
  AND f.start_type = 'lean_back'
GROUP BY l.listener_id, l.label
ORDER BY l.label;


-- ---------------------------------------------------------------------
-- Q7. Discovery diet: how much of each month is new music, and how much is small artists?
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
)
SELECT
    l.label,
    DATE_FORMAT(f.started_at, '%Y-%m')              AS month,
    COUNT(*)                                         AS plays,
    SUM(f.is_first_ever_play)                        AS new_artists,
    ROUND(100 * AVG(f.is_discovery_window), 1)       AS pct_plays_discovery,
    ROUND(100 * AVG(f.size_tier = 'small'), 1)       AS pct_plays_small_artists
FROM play_facts f
JOIN bounds b    ON b.listener_id = f.listener_id
JOIN listeners l ON l.listener_id = f.listener_id
WHERE f.started_at >= b.history_start + INTERVAL 30 DAY
GROUP BY l.listener_id, l.label, month
ORDER BY l.label, month;


-- ---------------------------------------------------------------------
-- Q8. Can we trust Spotify's own `skipped` field?
-- Why this project defines skips itself: the field is often empty. Where it's
-- filled in, how well does it agree with the 30-second definition?
-- ---------------------------------------------------------------------
SELECT
    YEAR(p.started_at)                                              AS year,
    COUNT(*)                                                        AS plays,
    ROUND(100 * AVG(p.skipped IS NULL), 1)                          AS pct_field_empty,
    ROUND(100 * AVG(CASE WHEN p.skipped IS NOT NULL
                         THEN p.skipped = (p.ms_played < 30000 OR p.reason_end = 'fwdbtn') END), 1)
                                                                    AS pct_agrees_with_our_definition
FROM plays p
GROUP BY year
ORDER BY year;


-- ---------------------------------------------------------------------
-- Q9. Discoveries that stuck: each listener's best finds
-- Artists first heard after the first 30 days, ranked by plays since.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
),
found AS (
    SELECT f.listener_id, f.artist_name, f.genre, f.size_tier, f.lastfm_listeners,
           MIN(f.artist_first_heard_at)                                   AS first_heard,
           MIN(CASE WHEN f.is_first_ever_play = 1 THEN f.start_type END)  AS how_found,
           COUNT(*)                                                       AS plays_since
    FROM play_facts f
    JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.artist_first_heard_at >= b.history_start + INTERVAL 30 DAY
    GROUP BY f.listener_id, f.artist_name, f.genre, f.size_tier, f.lastfm_listeners
),
ranked AS (
    SELECT found.*, ROW_NUMBER() OVER (PARTITION BY listener_id ORDER BY plays_since DESC) AS rn
    FROM found
)
SELECT l.label, r.rn AS rank_, r.artist_name, r.genre, r.size_tier, r.lastfm_listeners,
       DATE(r.first_heard) AS first_heard, r.how_found, r.plays_since
FROM ranked r
JOIN listeners l ON l.listener_id = r.listener_id
WHERE r.rn <= 3
ORDER BY l.label, r.rn;


-- ---------------------------------------------------------------------
-- Q10. Does the headline survive a different ruler?
-- The Q1 skip rates, with artist size measured three ways:
--   rank within the artist's own genre (main) / Last.fm fixed cut-offs / Deezer fans.
-- If lean-back skip rises from lesser-known ('small') to big under all three,
-- the finding doesn't depend on one platform's audience or one way of measuring size.
-- lean_back_skip_pct = first plays that Spotify started on its own (autoplay,
-- radio, playlist carrying on): the recommendation moment itself.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start
    FROM play_facts GROUP BY listener_id
),
first_plays AS (
    SELECT f.size_tier_lastfm, f.size_tier_deezer, f.size_tier_genre, f.is_skip, f.start_type
    FROM play_facts f
    JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
)
SELECT '2 Last.fm listeners (fixed cut-offs)' AS size_measure, size_tier_lastfm AS tier,
       COUNT(*) AS first_plays,
       ROUND(100 * AVG(is_skip), 1) AS first_play_skip_pct,
       ROUND(100 * AVG(CASE WHEN start_type = 'lean_back' THEN is_skip END), 1) AS lean_back_skip_pct
FROM first_plays WHERE size_tier_lastfm <> 'unknown' GROUP BY size_tier_lastfm
UNION ALL
SELECT '3 Deezer fans', size_tier_deezer,
       COUNT(*), ROUND(100 * AVG(is_skip), 1),
       ROUND(100 * AVG(CASE WHEN start_type = 'lean_back' THEN is_skip END), 1)
FROM first_plays WHERE size_tier_deezer <> 'unknown' GROUP BY size_tier_deezer
UNION ALL
SELECT '1 Rank within genre (main)', size_tier_genre,
       COUNT(*), ROUND(100 * AVG(is_skip), 1),
       ROUND(100 * AVG(CASE WHEN start_type = 'lean_back' THEN is_skip END), 1)
FROM first_plays WHERE size_tier_genre <> 'unknown' GROUP BY size_tier_genre
ORDER BY size_measure, FIELD(tier, 'small', 'mid', 'big');


-- ---------------------------------------------------------------------
-- Q10b. Where do Last.fm and Deezer disagree?  (per genre)
-- For artists found on both, how often Deezer puts them in a BIGGER tier than
-- Last.fm does, and how often a smaller one. A genre where Deezer is often
-- "bigger" is one Last.fm undercounts. Worth a line in the case study
-- (e.g. if it's Afrobeats or amapiano).
-- ---------------------------------------------------------------------
SELECT
    genre,
    COUNT(*)                                                                    AS artists_on_both,
    ROUND(100 * AVG(size_tier_deezer = size_tier_lastfm), 1)                           AS pct_same_tier,
    ROUND(100 * AVG(FIELD(size_tier_deezer, 'small', 'mid', 'big')
                  > FIELD(size_tier_lastfm, 'small', 'mid', 'big')), 1)         AS pct_bigger_on_deezer,
    ROUND(100 * AVG(FIELD(size_tier_deezer, 'small', 'mid', 'big')
                  < FIELD(size_tier_lastfm, 'small', 'mid', 'big')), 1)         AS pct_smaller_on_deezer
FROM artist_tiers
WHERE size_tier_lastfm <> 'unknown' AND size_tier_deezer <> 'unknown' AND genre IS NOT NULL
GROUP BY genre
HAVING COUNT(*) >= 20
ORDER BY pct_bigger_on_deezer DESC;


-- ---------------------------------------------------------------------
-- Q11. Sizing the opportunity: the "liked but lost" group
-- Liked (not skipped) lean-back first listens, at least 90 days before the data ends.
--   lost_2wk            no play of the artist from day 1 to day 14: the proposed trigger
--   stuck_pct_if_lost   of those, the share still played (not skipped) 30-90 days later:
--                       the baseline the A/B test would try to raise
--   stuck_pct_if_back   the same for artists that did come back within 2 weeks
-- The last two columns repeat it without Listener_3c (the heavy sleep-music listener).
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start, MAX(started_at) AS history_end
    FROM play_facts GROUP BY listener_id
),
liked AS (
    SELECT f.listener_id, f.artist_name, f.size_tier, f.started_at AS first_at
    FROM play_facts f JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1 AND f.start_type = 'lean_back' AND f.is_skip = 0
      AND f.size_tier <> 'unknown'
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.started_at <= b.history_end - INTERVAL 90 DAY
),
follow AS (
    SELECT l.listener_id, l.artist_name,
           MAX(f.started_at >= l.first_at + INTERVAL 1 DAY AND f.started_at < l.first_at + INTERVAL 14 DAY) AS back_2wk,
           MAX(f.started_at >  l.first_at + INTERVAL 30 DAY AND f.started_at <= l.first_at + INTERVAL 90 DAY AND f.is_skip = 0) AS stuck
    FROM liked l JOIN play_facts f ON f.listener_id = l.listener_id AND f.artist_name = l.artist_name
    GROUP BY l.listener_id, l.artist_name
)
SELECT l.size_tier, COUNT(*) AS liked, SUM(fo.back_2wk=0) AS lost_2wk,
       ROUND(100*AVG(fo.back_2wk=0),1) AS pct_lost,
       ROUND(100*AVG(CASE WHEN fo.back_2wk=0 THEN fo.stuck END),1) AS stuck_pct_if_lost,
       ROUND(100*AVG(CASE WHEN fo.back_2wk=1 THEN fo.stuck END),1) AS stuck_pct_if_back,
       SUM(fo.back_2wk=0 AND l.listener_id<>(SELECT listener_id FROM listeners WHERE label='Listener_3c')) AS lost_excl_3c,
       ROUND(100*AVG(CASE WHEN fo.back_2wk=0 AND l.listener_id<>(SELECT listener_id FROM listeners WHERE label='Listener_3c') THEN fo.stuck END),1) AS stuck_if_lost_excl_3c
FROM liked l JOIN follow fo ON fo.listener_id=l.listener_id AND fo.artist_name=l.artist_name
GROUP BY l.size_tier ORDER BY FIELD(l.size_tier,'small','mid','big');


-- ---------------------------------------------------------------------
-- Q11b. The "liked but lost" group per listener and size: the input for sizing.py
-- Save the output as results/liked_but_lost.tsv:
--   run this block on its own and save the result as a tab-separated file
--   lost          liked, then no play of the artist from day 1 to day 14 (the trigger)
--   *_stuck       any non-skipped play of the artist in days 30-90
--   *_new_song    a non-skipped play of a DIFFERENT song by the artist in days 30-90
--                 (the experiment's primary metric)
--   trigger_*     the same, keeping only first listens that meet the proposed trigger rules:
--                 played to the end, and a tagged, non-functional artist (a stand-in for
--                 'verified, not background music')
--   eligible_months  the stretch of data where a first listen can be counted
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start, MAX(started_at) AS history_end,
           MIN(started_at) AS window_first
    FROM play_facts GROUP BY listener_id
),
liked AS (
    SELECT f.listener_id, f.artist_name, f.size_tier, f.started_at AS first_at, f.track_uri AS first_track,
           (f.reason_end = 'trackdone' AND f.genre NOT IN ('untagged', 'functional')) AS meets_trigger_rules
    FROM play_facts f JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1 AND f.start_type = 'lean_back' AND f.is_skip = 0
      AND f.size_tier <> 'unknown'
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.started_at <= b.history_end   - INTERVAL 90 DAY
),
follow AS (
    SELECT l.listener_id, l.artist_name, l.size_tier, l.meets_trigger_rules,
           MAX(f.started_at >= l.first_at + INTERVAL 1 DAY AND f.started_at < l.first_at + INTERVAL 14 DAY) AS back_2wk,
           MAX(f.started_at >  l.first_at + INTERVAL 30 DAY AND f.started_at <= l.first_at + INTERVAL 90 DAY
               AND f.is_skip = 0) AS stuck,
           MAX(f.started_at >  l.first_at + INTERVAL 30 DAY AND f.started_at <= l.first_at + INTERVAL 90 DAY
               AND f.is_skip = 0 AND f.track_uri <> l.first_track) AS new_song
    FROM liked l JOIN play_facts f ON f.listener_id = l.listener_id AND f.artist_name = l.artist_name
    GROUP BY l.listener_id, l.artist_name, l.size_tier, l.meets_trigger_rules
)
SELECT lst.label AS listener, fo.size_tier,
       COUNT(*) AS liked, SUM(fo.back_2wk=0) AS lost,
       SUM(fo.back_2wk=0 AND fo.stuck=1) AS lost_stuck, SUM(fo.back_2wk=0 AND fo.new_song=1) AS lost_new_song,
       SUM(fo.back_2wk=1) AS back, SUM(fo.back_2wk=1 AND fo.stuck=1) AS back_stuck, SUM(fo.back_2wk=1 AND fo.new_song=1) AS back_new_song,
       SUM(fo.back_2wk=0 AND fo.meets_trigger_rules=1) AS trigger_lost,
       SUM(fo.back_2wk=0 AND fo.meets_trigger_rules=1 AND fo.new_song=1) AS trigger_lost_new_song,
       ROUND(DATEDIFF(b.history_end - INTERVAL 90 DAY, GREATEST(b.history_start + INTERVAL 30 DAY, b.window_first)) / 30.44, 1) AS eligible_months
FROM follow fo JOIN bounds b ON b.listener_id = fo.listener_id JOIN listeners lst ON lst.listener_id = fo.listener_id
GROUP BY lst.label, fo.size_tier, b.history_start, b.history_end, b.window_first
ORDER BY lst.label, FIELD(fo.size_tier,'small','mid','big');


-- ---------------------------------------------------------------------
-- Q11c. What is a lasting listener worth?  Streams after a liked-but-lost artist sticks
-- For liked-but-lost artists that still stuck, the average number of streams (30s+) of
-- that artist from day 30 to day 365. Introductions late in someone's data have less
-- than a year to count, so this slightly understates it.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start, MAX(started_at) AS history_end
    FROM play_facts GROUP BY listener_id
),
liked AS (
    SELECT f.listener_id, f.artist_name, f.size_tier, f.started_at AS first_at
    FROM play_facts f JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1 AND f.start_type = 'lean_back' AND f.is_skip = 0
      AND f.size_tier <> 'unknown'
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.started_at <= b.history_end   - INTERVAL 90 DAY
),
follow AS (
    SELECT l.listener_id, l.size_tier,
           MAX(f.started_at >= l.first_at + INTERVAL 1 DAY AND f.started_at < l.first_at + INTERVAL 14 DAY) AS back_2wk,
           MAX(f.started_at >  l.first_at + INTERVAL 30 DAY AND f.started_at <= l.first_at + INTERVAL 90 DAY
               AND f.is_skip = 0)                                                                         AS stuck,
           SUM(f.started_at >  l.first_at + INTERVAL 30 DAY AND f.started_at <= l.first_at + INTERVAL 365 DAY
               AND f.ms_played >= 30000)                                                                  AS streams_30_365
    FROM liked l JOIN play_facts f ON f.listener_id = l.listener_id AND f.artist_name = l.artist_name
    GROUP BY l.listener_id, l.artist_name, l.size_tier
)
SELECT size_tier, COUNT(*) AS lost_then_stuck, ROUND(AVG(streams_30_365), 1) AS avg_streams_day30_to_365
FROM follow
WHERE back_2wk = 0 AND stuck = 1
GROUP BY size_tier
ORDER BY FIELD(size_tier, 'small', 'mid', 'big');


-- ---------------------------------------------------------------------
-- Q12. Why rank within genre?  One fixed cut-off, genre by genre
-- Under the fixed Last.fm cut-offs (under 100k / 100k-1M / 1M+), how are each genre's
-- artists split? A genre where almost everyone is "small" is one Last.fm undercounts.
-- The second part shows where well-known acts land under each measure.
-- ---------------------------------------------------------------------
SELECT genre,
       COUNT(*)                          AS artists,
       SUM(size_tier_lastfm = 'small')   AS small_fixed,
       SUM(size_tier_lastfm = 'mid')     AS mid_fixed,
       SUM(size_tier_lastfm = 'big')     AS big_fixed
FROM artist_tiers
WHERE genre IN ('afrobeats', 'amapiano', 'hip-hop', 'r&b', 'pop', 'indie', 'rock', 'electronic')
GROUP BY genre
ORDER BY SUM(size_tier_lastfm = 'small') / COUNT(*) DESC;

SELECT artist_name, genre, lastfm_listeners, size_tier_lastfm AS fixed_cutoffs, size_tier_genre AS rank_within_genre
FROM artist_tiers
WHERE artist_name IN ('Burna Boy', 'Wizkid', 'Davido', 'Asake', 'Tems', 'Kabza De Small')
ORDER BY lastfm_listeners DESC;


-- ---------------------------------------------------------------------
-- Q13. Sensitivity: does catalogue size explain the "different song" gap?
-- A tiny artist may have only one song, so it can't reach "a different song". The export
-- has no catalogue sizes, so this uses songs seen anywhere in the data as a floor. That
-- floor is biased: for tiny artists the other songs seen are often this listener's own
-- returns. Read it as a warning sign, not an answer. Leaves out Listener_3c, as sizing.py does.
-- Rules build up: A all liked-but-lost; B played to the end; C tagged, not functional
-- (the trigger rules); D also 3+ songs seen in the data.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS artist_catalogue;
CREATE TABLE artist_catalogue AS
SELECT artist_name, COUNT(DISTINCT track_uri) AS songs_seen FROM play_facts GROUP BY artist_name;
ALTER TABLE artist_catalogue ADD INDEX idx_ac_artist (artist_name(191));

WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start, MAX(started_at) AS history_end
    FROM play_facts GROUP BY listener_id
),
liked AS (
    SELECT f.listener_id, f.artist_name, f.size_tier, f.started_at AS first_at, f.track_uri AS first_track,
           f.reason_end, f.genre, c.songs_seen
    FROM play_facts f
    JOIN bounds b           ON b.listener_id = f.listener_id
    JOIN artist_catalogue c ON c.artist_name = f.artist_name
    WHERE f.is_first_ever_play = 1 AND f.start_type = 'lean_back' AND f.is_skip = 0
      AND f.size_tier IN ('small', 'big')
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.started_at <= b.history_end   - INTERVAL 90 DAY
      AND f.listener_id <> (SELECT listener_id FROM listeners WHERE label = 'Listener_3c')
),
follow AS (
    SELECT l.listener_id, l.artist_name, l.size_tier, l.reason_end, l.genre, l.songs_seen,
           MAX(f.started_at >= l.first_at + INTERVAL 1 DAY AND f.started_at < l.first_at + INTERVAL 14 DAY) AS back_2wk,
           MAX(f.started_at >  l.first_at + INTERVAL 30 DAY AND f.started_at <= l.first_at + INTERVAL 90 DAY
               AND f.is_skip = 0 AND f.track_uri <> l.first_track)                                        AS new_song
    FROM liked l JOIN play_facts f ON f.listener_id = l.listener_id AND f.artist_name = l.artist_name
    GROUP BY l.listener_id, l.artist_name, l.size_tier, l.reason_end, l.genre, l.songs_seen
)
SELECT 'A all liked but lost' AS rule_set, size_tier, SUM(back_2wk = 0) AS lost,
       ROUND(100 * AVG(CASE WHEN back_2wk = 0 THEN new_song END), 1) AS pct_different_song
FROM follow GROUP BY size_tier
UNION ALL
SELECT 'B + played to the end', size_tier, SUM(back_2wk = 0),
       ROUND(100 * AVG(CASE WHEN back_2wk = 0 THEN new_song END), 1)
FROM follow WHERE reason_end = 'trackdone' GROUP BY size_tier
UNION ALL
SELECT 'C + tagged, not functional (trigger rules)', size_tier, SUM(back_2wk = 0),
       ROUND(100 * AVG(CASE WHEN back_2wk = 0 THEN new_song END), 1)
FROM follow WHERE reason_end = 'trackdone' AND genre NOT IN ('untagged', 'functional') GROUP BY size_tier
UNION ALL
SELECT 'D + 3 or more songs seen', size_tier, SUM(back_2wk = 0),
       ROUND(100 * AVG(CASE WHEN back_2wk = 0 THEN new_song END), 1)
FROM follow WHERE reason_end = 'trackdone' AND genre NOT IN ('untagged', 'functional') AND songs_seen >= 3
GROUP BY size_tier
ORDER BY 1, 2 DESC;

DROP TABLE IF EXISTS artist_catalogue;
