-- =====================================================================
-- The "liked but lost" group per listener and size (the same as Q11b in 04_analysis.sql).
-- Feeds chart 4 (make_charts.py) and sizing.py. Run after 03_build_facts.sql and save the
-- result in results/raw/ (it holds the private listener codes):
--   mysql -u root -p spotify_discovery < 06_liked_but_lost.sql > results/raw/liked_but_lost.tsv
-- or in PopSQL: run it, export as CSV, save as results/raw/liked_but_lost.csv
--   lost          liked (lean-back, not skipped), then no play of the artist on days 1-14
--   *_stuck       any non-skipped play of the artist in days 30-90
--   *_new_song    a non-skipped play of a DIFFERENT song by the artist in days 30-90
--   trigger_*     only first listens that meet the proposed trigger rules (played to the
--                 end; a tagged, non-functional artist)
-- =====================================================================
USE spotify_discovery;

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
