-- =====================================================================
-- Discovery Gap: when Spotify introduces you to a new artist, does it land
-- less often for small artists, and does genre matter beyond size?
-- Schema for Spotify "Extended streaming history" exports.
--
-- Run:  mysql -u root -p < 01_schema.sql
-- Wipes and rebuilds the database each time.
-- =====================================================================

DROP DATABASE IF EXISTS spotify_discovery;
CREATE DATABASE spotify_discovery CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE spotify_discovery;

-- One row per person whose export you've loaded.
-- Use a nickname or "friend_1" rather than a real name.
CREATE TABLE listeners (
    listener_id INT PRIMARY KEY AUTO_INCREMENT,
    label       VARCHAR(50) NOT NULL UNIQUE,
    is_sample   BOOLEAN     NOT NULL DEFAULT FALSE
);

-- One row per music play from the export (podcasts and audiobooks are filtered out).
-- Spotify's `ts` is when the play ENDED, in UTC. started_at is worked out by the loader.
-- IP addresses in the export are deliberately NOT loaded.
CREATE TABLE plays (
    play_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
    listener_id   INT          NOT NULL,
    started_at    DATETIME     NOT NULL,     -- UTC
    ended_at      DATETIME     NOT NULL,     -- UTC (Spotify's ts)
    ms_played     INT          NOT NULL,
    platform      VARCHAR(255) NULL,
    conn_country  CHAR(2)      NULL,
    track_name    VARCHAR(300) NOT NULL,
    artist_name   VARCHAR(300) NOT NULL,
    album_name    VARCHAR(300) NULL,
    track_uri     VARCHAR(60)  NOT NULL,
    reason_start  VARCHAR(40)  NULL,         -- clickrow, playbtn, trackdone, fwdbtn, backbtn, appload, remote...
    reason_end    VARCHAR(40)  NULL,         -- trackdone, fwdbtn, endplay, backbtn, logout...
    shuffle       BOOLEAN      NULL,
    skipped       BOOLEAN      NULL,         -- Spotify's own flag; before 2023 it often disagrees with the 30s rule (Q8), so play_facts.is_skip is used
    offline       BOOLEAN      NULL,
    incognito     BOOLEAN      NULL,
    FOREIGN KEY (listener_id) REFERENCES listeners(listener_id),
    INDEX idx_listener_time (listener_id, started_at),
    INDEX idx_artist (artist_name(100))
);

-- One row per artist in the data.
--   lastfm_listeners: global listener count on Last.fm (fetch_artist_info.py). NULL if not found.
--   genre:            the artist's MAIN genre: your first tag in artist_genres.csv if you gave one,
--                     otherwise the first genre found in their Last.fm tags. All their genres
--                     are in artist_genre_tags below.
-- Size tiers (small / mid / big) are worked out in 03_build_facts.sql, three ways:
-- Last.fm listeners, Deezer fans, and rank within the artist's own genre.
CREATE TABLE artists (
    artist_name      VARCHAR(300) NOT NULL,
    lastfm_name      VARCHAR(300) NULL,
    lastfm_listeners INT          NULL,
    lastfm_tags      VARCHAR(500) NULL,
    genre            VARCHAR(50)  NULL,
    genre_source     ENUM('manual', 'lastfm') NULL,
    deezer_fans      INT          NULL,     -- Deezer fan count (fetch_deezer_info.py): a second size measure
    PRIMARY KEY (artist_name(191))
);

-- Every genre of every artist (an artist can have several). genre_rank 1 = main genre,
-- the same one as artists.genre. Use this table to ask "how do ALL alté artists do,
-- including those whose main genre is hip-hop?" (Q3b in 04_analysis.sql).
CREATE TABLE artist_genre_tags (
    artist_name  VARCHAR(300) NOT NULL,
    genre        VARCHAR(50)  NOT NULL,
    genre_rank   TINYINT      NOT NULL,
    INDEX idx_agt_artist (artist_name(191)),
    INDEX idx_agt_genre  (genre)
);
