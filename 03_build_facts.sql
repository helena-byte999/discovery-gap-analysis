-- =====================================================================
-- Builds play_facts: one row per play with everything the analysis needs.
-- Run after every data load:
--   mysql -u root -p spotify_discovery < 03_build_facts.sql
--
-- Size tiers use Last.fm's global listener count. To change the cut-offs,
-- edit the two numbers in the size_tier CASE below and rerun this file.
--
-- TIME WINDOW: compare everyone over the same period.
--   Set @window_start / @window_end below, then rerun this file.
--   NULL = no limit, i.e. each person's full history.
--   Pick the dates with Q0c in 04_analysis.sql (it suggests a shared window).
--   "First play of an artist" is always worked out from each person's FULL
--   history, so an artist someone heard in 2019 never counts as new in 2025.
-- =====================================================================
USE spotify_discovery;

SET @window_start = '2021-10-01';   -- last 5 years: the period all listeners cover, all in the personalised-mix era (NULL = full history)
SET @window_end   = NULL;   -- e.g. '2026-08-31'   (NULL = up to each person's latest play)

-- ---------------------------------------------------------------------
-- artist_tiers: each artist's size, measured three ways.
--   size_tier_genre   MAIN MEASURE. Rank within the artist's own genre (by Last.fm
--                     listeners): bottom third of that genre = small, top third = big.
--                     So an artist is big or lesser-known COMPARED WITH THEIR OWN GENRE:
--                     Burna Boy is big in afrobeats, a new afrobeats act is lesser-known,
--                     whatever Last.fm's users happen to listen to.
--                     - Genres with 50+ artists are ranked on their own.
--                     - Smaller genres are ranked with their family (e.g. alte, highlife,
--                       afro house with the other African genres; uk garage with uk drill).
--                     - Artists with no genre fall back to the Last.fm cut-offs below
--                       (almost all of them are genuinely tiny).
--   size_tier_lastfm  Last.fm listeners, fixed cut-offs (under 100k / 100k-1M / 1M+).
--                     "Global reach" view. Last.fm undercounts some regions, so this
--                     is a second opinion, not the headline.
--   size_tier_deezer  Deezer fans, same share of artists per tier as Last.fm.
-- 'small' in the SQL = lesser-known / long-tail in the write-up.
-- ---------------------------------------------------------------------
SET @size_measure = 'genre';   -- which measure play_facts.size_tier uses: 'genre' | 'lastfm' | 'deezer'

SET @share_small = (SELECT AVG(lastfm_listeners <  100000) FROM artists WHERE lastfm_listeners IS NOT NULL);
SET @share_big   = (SELECT AVG(lastfm_listeners >= 1000000) FROM artists WHERE lastfm_listeners IS NOT NULL);

DROP TABLE IF EXISTS artist_tiers;

CREATE TABLE artist_tiers AS
SELECT
    artist_name, genre, rank_group, lastfm_listeners, deezer_fans,
    size_tier_lastfm,
    CASE
        WHEN deezer_fans IS NULL              THEN 'unknown'
        WHEN deezer_pct <  @share_small       THEN 'small'
        WHEN deezer_pct >= 1 - @share_big     THEN 'big'
        ELSE                                       'mid'
    END                                                             AS size_tier_deezer,
    CASE
        WHEN lastfm_listeners IS NULL         THEN 'unknown'
        WHEN genre IS NULL                    THEN size_tier_lastfm       -- untagged: fixed cut-offs
        WHEN group_artists < 50               THEN 'unknown'              -- too few to rank
        WHEN group_pct <  1/3                 THEN 'small'
        WHEN group_pct >= 2/3                 THEN 'big'
        ELSE                                       'mid'
    END                                                             AS size_tier_genre
FROM (
    SELECT
        g.*,
        PERCENT_RANK() OVER (PARTITION BY (deezer_fans IS NULL) ORDER BY deezer_fans)                   AS deezer_pct,
        PERCENT_RANK() OVER (PARTITION BY rank_group, (lastfm_listeners IS NULL) ORDER BY lastfm_listeners) AS group_pct,
        COUNT(*)       OVER (PARTITION BY rank_group, (lastfm_listeners IS NULL))                        AS group_artists
    FROM (
        SELECT
            c.*,
            -- which artists each artist is ranked against
            CASE
                WHEN genre IS NULL          THEN NULL
                WHEN genre_artists >= 50    THEN genre
                WHEN genre IN ('afrobeats', 'amapiano', 'alte', 'highlife', 'afro house', 'gqom',
                               'fuji', 'soukous', 'kuduro')                    THEN 'family: african'
                WHEN genre IN ('uk drill', 'grime', 'uk garage', 'uk funky')   THEN 'family: uk'
                ELSE                             'family: other small genres'
            END                                                     AS rank_group
        FROM (
            SELECT
                artist_name, genre, lastfm_listeners, deezer_fans,
                CASE
                    WHEN lastfm_listeners IS NULL     THEN 'unknown'
                    WHEN lastfm_listeners <   100000  THEN 'small'
                    WHEN lastfm_listeners <  1000000  THEN 'mid'
                    ELSE                                   'big'
                END                                                 AS size_tier_lastfm,
                SUM(lastfm_listeners IS NOT NULL) OVER (PARTITION BY genre) AS genre_artists
            FROM artists
        ) c
    ) g
) ranked;

ALTER TABLE artist_tiers ADD INDEX idx_at_artist (artist_name(191));

DROP TABLE IF EXISTS play_facts;

CREATE TABLE play_facts AS
SELECT
    play_id, listener_id, started_at, ms_played, platform, track_name, artist_name, track_uri,
    reason_start, reason_end, shuffle, incognito,
    genre, lastfm_listeners, artist_first_heard_at, artist_play_number, track_play_number,
    listener_history_start,   -- this person's first play in their whole export (for the 30-day warm-up)

    -- Artist size (see artist_tiers above). size_tier = the measure chosen in @size_measure.
    size_tier, size_tier_genre, size_tier_lastfm, size_tier_deezer, deezer_fans,

    -- A skip: under 30 seconds (Spotify's own threshold for counting a stream),
    -- or ended by pressing next. Doesn't rely on the `skipped` field, which is often empty.
    (ms_played < 30000 OR reason_end = 'fwdbtn')                              AS is_skip,

    -- How the play began.
    CASE
        WHEN reason_start IN ('clickrow', 'playbtn')        THEN 'chosen'     -- you picked it
        WHEN reason_start = 'trackdone'                     THEN 'lean_back'  -- carried on from a playlist, album, radio or autoplay
        WHEN reason_start IN ('fwdbtn', 'backbtn')          THEN 'navigating' -- arrived by skipping
        ELSE 'other'
    END                                                                       AS start_type,

    -- Discovery: the first week after this listener first heard the artist.
    -- (04_analysis.sql leaves out each person's first 30 days, where every artist looks new.)
    (started_at < artist_first_heard_at + INTERVAL 7 DAY)                     AS is_discovery_window,
    (artist_play_number = 1)                                                  AS is_first_ever_play
FROM (
    SELECT
        p.*,
        COALESCE(a.genre, 'untagged')      AS genre,
        a.lastfm_listeners,
        COALESCE(CASE @size_measure WHEN 'lastfm' THEN t.size_tier_lastfm
                                    WHEN 'deezer' THEN t.size_tier_deezer
                                    ELSE t.size_tier_genre END, 'unknown') AS size_tier,
        COALESCE(t.size_tier_genre,  'unknown')  AS size_tier_genre,
        COALESCE(t.size_tier_lastfm, 'unknown')  AS size_tier_lastfm,
        COALESCE(t.size_tier_deezer, 'unknown')  AS size_tier_deezer,
        t.deezer_fans,
        af.artist_first_heard_at,
        ROW_NUMBER() OVER (PARTITION BY p.listener_id, p.artist_name ORDER BY p.started_at) AS artist_play_number,
        ROW_NUMBER() OVER (PARTITION BY p.listener_id, p.track_uri   ORDER BY p.started_at) AS track_play_number,
        lh.listener_history_start
    FROM plays p
    LEFT JOIN artists a      ON a.artist_name = p.artist_name
    LEFT JOIN artist_tiers t ON t.artist_name = p.artist_name
    -- first plays worked out with GROUP BY (same result as MIN() OVER, much faster on MariaDB)
    JOIN (SELECT listener_id, artist_name, MIN(started_at) AS artist_first_heard_at
            FROM plays GROUP BY listener_id, artist_name) af
      ON af.listener_id = p.listener_id AND af.artist_name = p.artist_name
    JOIN (SELECT listener_id, MIN(started_at) AS listener_history_start
            FROM plays GROUP BY listener_id) lh
      ON lh.listener_id = p.listener_id
) base
-- Keep only plays inside the chosen window. This runs AFTER the window
-- functions above, so first-play detection still sees the full history.
WHERE (@window_start IS NULL OR started_at >= @window_start)
  AND (@window_end   IS NULL OR started_at <  @window_end + INTERVAL 1 DAY);

ALTER TABLE play_facts
    ADD INDEX idx_pf_listener (listener_id, started_at),
    ADD INDEX idx_pf_artist (listener_id, artist_name(100));

-- Check: one row per play. A mismatch means an artist matched twice in artist_tiers.
SELECT COUNT(*) AS play_facts_rows,
       (SELECT COUNT(*) FROM plays
         WHERE (@window_start IS NULL OR started_at >= @window_start)
           AND (@window_end   IS NULL OR started_at <  @window_end + INTERVAL 1 DAY)) AS plays_in_window,
       CASE WHEN COUNT(*) = (SELECT COUNT(*) FROM plays
                              WHERE (@window_start IS NULL OR started_at >= @window_start)
                                AND (@window_end   IS NULL OR started_at <  @window_end + INTERVAL 1 DAY))
            THEN 'OK' ELSE 'MISMATCH: an artist matches twice in artist_tiers; check artist spellings' END AS row_check,
       COALESCE(@window_start, 'full history') AS window_start,
       COALESCE(@window_end,   'latest play')  AS window_end
FROM play_facts;
