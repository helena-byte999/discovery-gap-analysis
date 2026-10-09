"""Turns Spotify Extended Streaming History exports into a SQL file you can load into MySQL.

Folder layout: one sub-folder per person, holding that person's unzipped export:

    my_data/
        ena/        Streaming_History_Audio_2023-2024_0.json, ...
        friend_1/   Streaming_History_Audio_2024_1.json, ...

Run:
    python3 load_history.py my_data
    mysql -u root -p spotify_discovery < 02_load_data.sql

It also reads, if they exist:
    artist_info.csv     Last.fm listener counts + suggested genres (from fetch_artist_info.py)
    deezer_info.csv     Deezer fan counts, a second size measure (from fetch_deezer_info.py)
    artist_genres.csv   your own genre fixes: artist_name,genre  (these win over Last.fm).
                        An artist can have several: "alte; hip-hop". The first is their MAIN genre.
and writes:
    artists.csv         every artist in the data, most-played first (input for fetch_artist_info.py)
    artists_to_tag.csv  artists with no genre yet, most-played first

Privacy: IP addresses and usernames in the export are never read into the output.
Standard library only.
"""
import argparse
import csv
import json
import os
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta


def match_key(name):
    """How MySQL compares names (utf8mb4_unicode_ci): ignores capitals, accents and trailing
    spaces. So 'OMAH LAY' and 'Omah Lay' are one artist to the database, and must be one here."""
    s = unicodedata.normalize("NFKD", name.rstrip())
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def sql(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def cut(v, n):
    """Trim text to fit its database column (e.g. a 103-character phone model name)."""
    return v[:n] if isinstance(v, str) and v else v


def boolish(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1")


def find_export_files(folder):
    out = []
    for root, _, files in os.walk(folder):
        for f in files:
            lf = f.lower()
            # current exports: Streaming_History_Audio_*.json ; older ones: endsong_*.json
            if lf.endswith(".json") and ("streaming_history_audio" in lf or lf.startswith("endsong")):
                out.append(os.path.join(root, f))
    return sorted(out)


def split_genres(text):
    """'Alte; hip-hop' -> ['alte', 'hip-hop']: lower case, no repeats, first = main genre."""
    out = []
    for g in (text or "").replace(",", ";").split(";"):
        g = g.strip().lower()
        if g and g not in out:
            out.append(g)
    return out


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", help="folder containing one sub-folder per listener")
    ap.add_argument("--info", default="artist_info.csv", help="Last.fm results from fetch_artist_info.py")
    ap.add_argument("--deezer", default="deezer_info.csv", help="Deezer results from fetch_deezer_info.py")
    ap.add_argument("--genres", default="artist_genres.csv", help="your own genre fixes: artist_name,genre")
    ap.add_argument("--sample", action="store_true", help="mark these listeners as sample data")
    ap.add_argument("--out", default="02_load_data.sql")
    args = ap.parse_args()

    if not os.path.isdir(args.data_dir):
        sys.exit(f"Folder not found: {args.data_dir}")
    listeners = sorted(d for d in os.listdir(args.data_dir) if os.path.isdir(os.path.join(args.data_dir, d)))
    if not listeners:
        sys.exit(f"No listener folders found inside {args.data_dir}")
    # Short labels: "Listener_1eSpotify Extended Streaming History" -> "Listener_1e"
    def label(folder):
        return folder.replace("Spotify Extended Streaming History", "").strip(" _-") or folder

    all_rows = []
    stats = Counter()
    artist_plays, artist_people = Counter(), {}
    for lid, name in enumerate(listeners, 1):
        files = find_export_files(os.path.join(args.data_dir, name))
        if not files:
            print(f"  ! {name}: no Streaming_History_Audio_*.json files found, skipped")
            continue
        seen = set()
        n = 0
        for path in files:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for r in data:
                track_uri = r.get("spotify_track_uri")
                artist = r.get("master_metadata_album_artist_name")
                track = r.get("master_metadata_track_name")
                if not track_uri or not artist or not track:
                    stats["non_music_dropped"] += 1        # podcasts, audiobooks, local files
                    continue
                ms = int(r.get("ms_played") or 0)
                if ms <= 0:
                    stats["zero_ms_dropped"] += 1
                    continue
                key = (r["ts"], track_uri, ms)
                if key in seen:
                    stats["duplicates_dropped"] += 1
                    continue
                seen.add(key)
                ended = datetime.strptime(r["ts"].replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S")
                started = ended - timedelta(milliseconds=ms)
                artist = artist[:300]
                all_rows.append((lid, started, ended, ms, cut(r.get("platform"), 255), cut(r.get("conn_country"), 2),
                                 track[:300], artist, (r.get("master_metadata_album_album_name") or "")[:300] or None,
                                 track_uri[:60], cut(r.get("reason_start"), 40), cut(r.get("reason_end"), 40),
                                 boolish(r.get("shuffle")), boolish(r.get("skipped")),
                                 boolish(r.get("offline")), boolish(r.get("incognito_mode"))))
                artist_plays[artist] += 1
                artist_people.setdefault(artist, set()).add(name)
                n += 1
        print(f"  {label(name)}: {n:,} music plays from {len(files)} file(s)")

    # ---------------------------------------------------------------- one spelling per artist
    # Spotify sometimes changes how a name is written ('OMAH LAY' vs 'Omah Lay'). Keep the
    # most-played spelling, so a new spelling never looks like discovering a new artist.
    spelling = {}
    for a, _ in artist_plays.most_common():
        spelling.setdefault(match_key(a), a)
    canon = {a: spelling[match_key(a)] for a in artist_plays}
    renamed = [a for a in canon if canon[a] != a]
    if renamed:
        all_rows = [r[:7] + (canon[r[7]],) + r[8:] for r in all_rows]
        plays2, people2 = Counter(), {}
        for a, c in artist_plays.items():
            plays2[canon[a]] += c
            people2.setdefault(canon[a], set()).update(artist_people[a])
        artist_plays, artist_people = plays2, people2
        ex = renamed[0]
        print(f"  Merged {len(renamed)} artist spelling(s) that differ only in capitals/accents "
              f"(e.g. '{ex}' -> '{canon[ex]}').")

    # ---------------------------------------------------------------- artist info
    info = {r["artist_name"]: r for r in read_csv(args.info) if r.get("artist_name")}
    deezer_rows = read_csv(args.deezer)
    deezer = {}
    for r in deezer_rows:
        if r.get("status") == "ok" and str(r.get("deezer_fans", "")).isdigit():
            deezer[r["artist_name"]] = int(r["deezer_fans"])
    if deezer_rows and not deezer:
        print(f"  ! {args.deezer} has no usable fan counts: check it with fetch_deezer_info.py --test")

    # Each artist's most-played track: fetch_deezer_info.py uses it to confirm it found
    # the right artist (not a more famous one with the same name).
    track_plays = Counter((r[7], r[6]) for r in all_rows)
    top_track = {}
    for (a, t), _ in track_plays.most_common():
        top_track.setdefault(a, t)
    # Genres: an artist can have several. The first one is their main genre (used where each
    # artist must count once); all of them go into the artist_genre_tags table.
    manual = {}
    for r in read_csv(args.genres):
        a, gs = (r.get("artist_name") or "").strip(), split_genres(r.get("genre"))
        if a and gs:
            manual[match_key(a)] = gs
    try:                                   # genres from Last.fm tags, with the latest tag list
        from fetch_artist_info import tags_to_genres
    except ImportError:
        tags_to_genres = None
    if not info:
        print(f"  (no {args.info} yet: run fetch_artist_info.py to get artist sizes and genres)")

    artist_rows, artist_genres = [], {}
    for a in artist_plays:
        i = info.get(a, {})
        try:
            listeners_n = int(i.get("lastfm_listeners") or "") if i.get("status") == "ok" else None
        except ValueError:
            listeners_n = None
        if match_key(a) in manual:
            genres, source = manual[match_key(a)], "manual"
        elif i.get("status") == "ok" and tags_to_genres and i.get("lastfm_tags"):
            genres, source = tags_to_genres(i["lastfm_tags"].split(";")), "lastfm"
        else:
            genres, source = split_genres(i.get("genre")), "lastfm"
        if not genres:
            source = None
        artist_genres[a] = genres
        artist_rows.append((a, i.get("lastfm_name") or None, listeners_n,
                            (i.get("lastfm_tags") or "")[:500] or None, genres[0] if genres else None,
                            source, deezer.get(a)))
    by_artist = {r[0]: r for r in artist_rows}
    tag_rows = [(a, g, rank) for a, gs in artist_genres.items() for rank, g in enumerate(gs, 1)]

    with open("artists.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["artist_name", "plays", "listeners_in_your_data", "top_track"])
        for a, c in artist_plays.most_common():
            w.writerow([a, c, len(artist_people[a]), top_track.get(a, "")])
    with open("artists_to_tag.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["artist_name", "genre", "plays", "lastfm_tags"])
        for a, c in artist_plays.most_common():
            if not by_artist[a][4]:
                w.writerow([a, "", c, by_artist[a][3] or ""])

    # ---------------------------------------------------------------- write SQL
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("-- Generated by load_history.py. Load with:\n")
        f.write("--   mysql -u root -p spotify_discovery < " + args.out + "\n")
        f.write("USE spotify_discovery;\nSET NAMES utf8mb4;\nSET autocommit = 0;\n")
        f.write("DELETE FROM artist_genre_tags;\nDELETE FROM artists;\nDELETE FROM plays;\nDELETE FROM listeners;\n")
        f.write("INSERT INTO listeners (listener_id, label, is_sample) VALUES\n")
        f.write(",\n".join(f"({i}, {sql(label(n))}, {sql(args.sample)})" for i, n in enumerate(listeners, 1)) + ";\n")
        cols = ("listener_id, started_at, ended_at, ms_played, platform, conn_country, track_name, artist_name, "
                "album_name, track_uri, reason_start, reason_end, shuffle, skipped, offline, incognito")
        for i in range(0, len(all_rows), 1000):
            f.write(f"INSERT INTO plays ({cols}) VALUES\n")
            f.write(",\n".join("(" + ", ".join(sql(v) for v in r) + ")" for r in all_rows[i:i + 1000]) + ";\n")
        for i in range(0, len(artist_rows), 1000):
            f.write("INSERT INTO artists (artist_name, lastfm_name, lastfm_listeners, lastfm_tags, genre, genre_source, deezer_fans) VALUES\n")
            f.write(",\n".join("(" + ", ".join(sql(v) for v in r) + ")" for r in artist_rows[i:i + 1000]) + ";\n")
        for i in range(0, len(tag_rows), 1000):
            f.write("INSERT INTO artist_genre_tags (artist_name, genre, genre_rank) VALUES\n")
            f.write(",\n".join("(" + ", ".join(sql(v) for v in r) + ")" for r in tag_rows[i:i + 1000]) + ";\n")
        f.write("COMMIT;\n")

    total = sum(artist_plays.values()) or 1
    with_size = sum(c for a, c in artist_plays.items() if by_artist[a][2] is not None)
    with_genre = sum(c for a, c in artist_plays.items() if by_artist[a][4])
    print(f"\nWrote {args.out}: {len(all_rows):,} plays, {len(artist_plays):,} artists.")
    print(f"Dropped: {stats['non_music_dropped']:,} podcast/audiobook rows, "
          f"{stats['zero_ms_dropped']:,} zero-length plays, {stats['duplicates_dropped']:,} duplicates.")
    with_deezer = sum(c for a, c in artist_plays.items() if by_artist[a][6] is not None)
    multi = sum(1 for gs in artist_genres.values() if len(gs) > 1)
    print(f"Artist size known for {100 * with_size / total:.0f}% of plays; genre known for {100 * with_genre / total:.0f}%"
          f" ({multi:,} artists have more than one genre).")
    if deezer:
        print(f"Deezer fan count known for {100 * with_deezer / total:.0f}% of plays.")
    if with_size / total < 0.8:
        print("  -> Run fetch_artist_info.py (or rerun it to retry failures), then run this again.")
    if with_genre / total < 0.8:
        print("  -> Add genres for the top artists in artists_to_tag.csv to artist_genres.csv, then run this again.")


if __name__ == "__main__":
    main()
