-- =====================================================================
-- Per-listener counts behind the headline numbers, for confidence ranges.
-- One row per listener and artist size. bootstrap_ci.py reads the result
-- (save it as results/listener_counts.csv) and resamples LISTENERS: with
-- 10 people, the person is what varies, not the individual play.
--
-- Uses exactly the same rules as 04_analysis.sql:
--   lean-back first listens   Q2 (and Q4 for the share of new artists)
--   stuck 30-90 days          Q5
--   after a liked first listen  Q5b
-- Run after 03_build_facts.sql:
--   mysql -u root -p spotify_discovery < 05_listener_counts.sql > results/raw/listener_counts.tsv
-- or in PopSQL: run it, export as CSV, save as results/raw/listener_counts.csv
-- Then run pseudonymise.py, which writes the public copy that the scripts read.
-- =====================================================================
USE spotify_discovery;

WITH bounds AS (
    SELECT listener_id, MIN(listener_history_start) AS history_start, MAX(started_at) AS history_end
    FROM play_facts GROUP BY listener_id
),
-- Every first listen after the 30-day warm-up (Q2 / Q4)
firsts AS (
    SELECT f.listener_id, f.artist_name, f.size_tier, f.start_type, f.is_skip,
           f.started_at, f.track_uri, b.history_end
    FROM play_facts f
    JOIN bounds b ON b.listener_id = f.listener_id
    WHERE f.is_first_ever_play = 1
      AND f.started_at >= b.history_start + INTERVAL 30 DAY
      AND f.size_tier <> 'unknown'
),
first_counts AS (
    SELECT listener_id, size_tier,
           SUM(start_type = 'lean_back')                  AS lb_first,
           SUM(start_type = 'lean_back' AND is_skip = 1)  AS lb_first_skipped,
           SUM(start_type = 'chosen')                     AS chosen_first
    FROM firsts GROUP BY listener_id, size_tier
),
-- Q5: lean-back discoveries at least 90 days before the data ends; stuck = played, not skipped, 30-90 days on
disc AS (
    SELECT listener_id, artist_name, size_tier, started_at AS first_at
    FROM firsts
    WHERE start_type = 'lean_back' AND started_at <= history_end - INTERVAL 90 DAY
),
disc_counts AS (
    SELECT d.listener_id, d.size_tier, COUNT(*) AS lb_disc, SUM(s.stuck) AS lb_stuck
    FROM disc d
    JOIN (
        SELECT d2.listener_id, d2.artist_name,
               MAX(f.started_at > d2.first_at + INTERVAL 30 DAY
                   AND f.started_at <= d2.first_at + INTERVAL 90 DAY AND f.is_skip = 0) AS stuck
        FROM disc d2
        JOIN play_facts f ON f.listener_id = d2.listener_id AND f.artist_name = d2.artist_name
        GROUP BY d2.listener_id, d2.artist_name
    ) s ON s.listener_id = d.listener_id AND s.artist_name = d.artist_name
    GROUP BY d.listener_id, d.size_tier
),
-- Q5b: liked (not skipped) lean-back first listens, at least 30 days before the data ends
liked AS (
    SELECT listener_id, artist_name, size_tier, started_at AS first_at
    FROM firsts
    WHERE start_type = 'lean_back' AND is_skip = 0 AND started_at <= history_end - INTERVAL 30 DAY
),
comebacks AS (
    SELECT l.listener_id, l.artist_name, f.start_type,
           ROW_NUMBER() OVER (PARTITION BY l.listener_id, l.artist_name ORDER BY f.started_at) AS rn
    FROM liked l
    JOIN play_facts f ON f.listener_id = l.listener_id AND f.artist_name = l.artist_name
    WHERE f.started_at >= l.first_at + INTERVAL 1 DAY
      AND f.started_at <  l.first_at + INTERVAL 30 DAY
),
liked_counts AS (
    SELECT l.listener_id, l.size_tier,
           COUNT(*)                                  AS liked,
           SUM(c.listener_id IS NOT NULL)            AS liked_back,
           SUM(COALESCE(c.start_type = 'chosen', 0)) AS liked_back_clicked,
           SUM(COALESCE(c.start_type = 'lean_back', 0)) AS liked_back_lean_back
    FROM liked l
    LEFT JOIN comebacks c ON c.listener_id = l.listener_id AND c.artist_name = l.artist_name AND c.rn = 1
    GROUP BY l.listener_id, l.size_tier
)
SELECT lst.label AS listener, fc.size_tier,
       fc.lb_first, fc.lb_first_skipped, fc.chosen_first,
       COALESCE(dc.lb_disc, 0)            AS lb_disc,
       COALESCE(dc.lb_stuck, 0)           AS lb_stuck,
       COALESCE(lc.liked, 0)              AS liked,
       COALESCE(lc.liked_back, 0)         AS liked_back,
       COALESCE(lc.liked_back_clicked, 0) AS liked_back_clicked,
       COALESCE(lc.liked_back_lean_back, 0) AS liked_back_lean_back
FROM first_counts fc
JOIN listeners lst       ON lst.listener_id = fc.listener_id
LEFT JOIN disc_counts dc  ON dc.listener_id = fc.listener_id AND dc.size_tier = fc.size_tier
LEFT JOIN liked_counts lc ON lc.listener_id = fc.listener_id AND lc.size_tier = fc.size_tier
ORDER BY lst.label, FIELD(fc.size_tier, 'small', 'mid', 'big');
