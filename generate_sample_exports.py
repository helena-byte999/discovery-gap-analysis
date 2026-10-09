"""Creates SAMPLE Spotify Extended Streaming History exports for 6 fictional listeners.

The files match Spotify's real export format field-for-field, so they go through the
same loader as your real data. All artists, tracks and listeners are invented.

Output:
  sample_data/<listener>/Streaming_History_Audio_2025-2026_0.json
  sample_artist_info.csv     (what fetch_artist_info.py would return from Last.fm:
                              invented listener counts and tags)

Standard library only. Run:  python3 generate_sample_exports.py
"""
import csv
import json
import math
import os
import random
import string
from datetime import datetime, timedelta, timezone

random.seed(7)

START = datetime(2025, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc)

# genre -> niche?  (mirrors the genres table in 01_schema.sql)
GENRES = {
    "amapiano": True, "gqom": True, "afro house": True, "alte": True, "uk funky": True,
    "afrobeats": False, "uk garage": False, "uk drill": False, "hip-hop": False,
    "r&b": False, "pop": False, "house": False,
}

# Each listener's taste: genre -> weight
LISTENERS = {
    "sample_ena":    {"amapiano": 5, "gqom": 4, "afro house": 5, "afrobeats": 3, "house": 2, "r&b": 1},
    "sample_tobi":   {"afrobeats": 5, "alte": 3, "r&b": 3, "hip-hop": 2, "amapiano": 2},
    "sample_jess":   {"pop": 5, "r&b": 3, "uk garage": 2, "house": 1},
    "sample_kwame":  {"uk drill": 4, "hip-hop": 5, "uk funky": 2, "afrobeats": 2},
    "sample_lerato": {"amapiano": 4, "afro house": 3, "gqom": 2, "house": 3, "pop": 1},
    "sample_sam":    {"uk garage": 4, "house": 4, "uk funky": 3, "pop": 2, "r&b": 1},
}
PLATFORMS = ["ios", "android", "osx", "windows", "web_player"]

SYL = ["ka", "zo", "mi", "ta", "lu", "ne", "sa", "bo", "ri", "de", "fu", "ya", "no", "ve", "ji", "la",
       "mo", "ze", "ti", "ro", "ba", "ku", "si", "na"]
WORDS = ["Midnight", "Tender", "Lagos", "Signal", "Velvet", "Ghost", "Pressure", "Summer", "Static",
         "Gold", "Drift", "Echo", "Ember", "Slow", "Fever", "Neon", "Paper", "Rhythm", "Window", "Sunday",
         "Loose", "Heavy", "Blue", "Wired", "Distance", "Halo", "Motion", "Salt", "Glass", "Tides"]


def uri():
    return "spotify:track:" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def artist_name(used):
    while True:
        n = "".join(random.choices(SYL, k=random.randint(2, 3))).capitalize()
        r = random.random()
        if r < 0.2:
            n = "DJ " + n
        elif r < 0.35:
            n = n + " " + random.choice(["& The Hours", "Collective", "Sound", "Twins"])
        elif r < 0.6:
            n = n + " " + "".join(random.choices(SYL, k=2)).capitalize()
        if n not in used:
            used.add(n)
            return n


# ---------------------------------------------------------------- catalogue
used = set()
catalogue = {}           # genre -> list of artists
artist_genre = {}
tracks_by_artist = {}
for g in GENRES:
    catalogue[g] = []
    for _ in range(45):
        a = artist_name(used)
        catalogue[g].append(a)
        artist_genre[a] = g
        album = f"{random.choice(WORDS)} {random.choice(WORDS)}"
        tracks_by_artist[a] = [
            {"name": f"{random.choice(WORDS)} {random.choice(WORDS)}" if random.random() < 0.7 else random.choice(WORDS),
             "album": album if random.random() < 0.7 else f"{random.choice(WORDS)} (Single)",
             "uri": uri(),
             "ms": random.randint(150, 400) * 1000}
            for _ in range(random.randint(4, 10))
        ]
# artist popularity within a genre: long tail
artist_pop = {}
for g, arts in catalogue.items():
    for rank, a in enumerate(arts, 1):
        artist_pop[a] = 1 / rank ** 0.8

# Global listener counts (what Last.fm would report). Niche genres are smaller on
# average, but the spread is wide: there are big amapiano acts and tiny pop acts.
# That overlap is what lets the analysis separate artist size from genre.
artist_listeners = {}
for g, arts in catalogue.items():
    median = 60_000 if GENRES[g] else 450_000
    draws = sorted((int(median * math.exp(random.gauss(0, 1.3))) for _ in arts), reverse=True)
    for a, n in zip(arts, draws):          # most popular artist gets the biggest count
        artist_listeners[a] = max(300, n)


def tier(a):
    n = artist_listeners[a]
    return "small" if n < 100_000 else "mid" if n < 1_000_000 else "big"


def pick_new_artist(taste, known, mode):
    """Discovery. Lean-back sessions (autoplay/radio/algorithmic) wander further from your taste."""
    genres = list(taste)
    weights = [taste[g] for g in genres]
    if mode == "lean_back" and random.random() < 0.25:
        genres = list(GENRES)          # recommendation outside your usual genres
        weights = [1] * len(genres)
    for _ in range(20):
        g = random.choices(genres, weights=weights)[0]
        pool = [a for a in catalogue[g] if a not in known]
        if pool:
            # recommendations lean towards already-popular artists (popularity bias);
            # when you go looking yourself, you're more likely to land on someone small
            power = 1.8 if mode == "lean_back" else 0.5
            return random.choices(pool, weights=[artist_pop[a] ** power for a in pool])[0]
    return None


def row(ts_end, ms, platform, track, artist, reason_start, reason_end, shuffle, skipped, incognito):
    return {
        "ts": ts_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": platform,
        "ms_played": ms,
        "conn_country": random.choices(["GB", "NG", "ZA", "FR"], weights=[90, 5, 3, 2])[0],
        "ip_addr": f"81.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(0,255)}",
        "master_metadata_track_name": track["name"] if track else None,
        "master_metadata_album_artist_name": artist,
        "master_metadata_album_album_name": track["album"] if track else None,
        "spotify_track_uri": track["uri"] if track else None,
        "episode_name": None, "episode_show_name": None, "spotify_episode_uri": None,
        "audiobook_title": None, "audiobook_uri": None,
        "audiobook_chapter_uri": None, "audiobook_chapter_title": None,
        "reason_start": reason_start, "reason_end": reason_end,
        "shuffle": shuffle, "skipped": skipped,
        "offline": random.random() < 0.05, "offline_timestamp": None,
        "incognito_mode": incognito,
    }


tag_rows = {}
for name, taste in LISTENERS.items():
    rows = []
    known = {}           # artist -> {"aff": float, "last": datetime}
    base_skip = random.uniform(0.12, 0.2)
    shuffle_p = random.uniform(0.2, 0.7)
    main_platform = random.choice(["ios", "android"])
    # seed with a few artists you already love
    for g, w in taste.items():
        for a in random.sample(catalogue[g][:10], k=min(10, w * 2)):
            known[a] = {"aff": random.uniform(3, 10), "last": START - timedelta(days=random.randint(1, 60))}

    day = START
    while day < END:
        for _ in range(max(0, int(random.gauss(2.2, 1.2)))):
            hour = random.choices(range(24), weights=[3, 2, 1, 1, 1, 1, 3, 6, 7, 5, 4, 4, 5, 5, 4, 4, 5, 6, 7, 8, 8, 7, 6, 4])[0]
            t = day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))
            mode = "lean_back" if random.random() < 0.45 else "chosen"
            shuffle = random.random() < shuffle_p
            platform = main_platform if random.random() < 0.8 else random.choice(PLATFORMS)
            incognito = random.random() < 0.02
            prev_end = None
            for i in range(random.randint(3, 20)):
                if i == 0:
                    reason_start = random.choices(["clickrow", "playbtn", "appload"], weights=[60, 30, 10])[0]
                else:
                    reason_start = prev_end if prev_end in ("fwdbtn", "backbtn") else "trackdone"
                    if mode == "chosen" and random.random() < 0.08:
                        reason_start = "clickrow"
                picked = reason_start in ("clickrow", "playbtn")
                if mode == "lean_back":
                    # radio/autoplay sessions start from something you already know
                    p_new = 0.0 if i == 0 else 0.30
                else:
                    # you sometimes search for someone new (a friend's tip); albums mostly familiar
                    p_new = 0.18 if picked else 0.04
                new = random.random() < p_new
                artist = pick_new_artist(taste, known, mode) if new else None
                if artist is None:
                    new = False
                    now = t
                    arts = list(known)
                    w = [known[a]["aff"] ** 1.3 * math.exp(-max(0, (now - known[a]["last"]).days) / 75) + 0.01 for a in arts]
                    artist = random.choices(arts, weights=w)[0]
                track = random.choice(tracks_by_artist[artist])
                g = artist_genre[artist]
                niche = GENRES[g]
                in_taste = g in taste

                # --- skip model (this is the pattern the sample is built to show)
                p_skip = base_skip + (0.05 if shuffle else 0)
                if new:
                    if mode == "lean_back":
                        # recommended small artists land worst; niche genres a little worse on top
                        p_skip += {"small": 0.26, "mid": 0.16, "big": 0.08}[tier(artist)]
                        p_skip += 0.06 if niche else 0
                        if not in_taste:
                            p_skip += 0.15
                    else:
                        p_skip += 0.05                          # you chose it: you usually give it a chance
                elif artist in known:
                    p_skip -= min(0.1, known[artist]["aff"] / 100)
                p_skip = max(0.03, min(0.9, p_skip))

                if random.random() < p_skip:
                    ms = random.randint(800, 29000) if random.random() < 0.85 else random.randint(30000, track["ms"] // 2)
                    reason_end, skipped = "fwdbtn", True
                elif random.random() < 0.9:
                    ms, reason_end, skipped = track["ms"], "trackdone", False
                else:
                    ms = random.randint(30000, track["ms"])
                    reason_end, skipped = random.choice(["endplay", "logout", "unexpected-exit"]), False

                # older exports often leave `skipped` empty
                if t < datetime(2025, 7, 1, tzinfo=timezone.utc) and random.random() < 0.6:
                    skipped = None

                t_end = t + timedelta(milliseconds=ms)
                rows.append(row(t_end, ms, platform, track, artist, reason_start, reason_end, shuffle, skipped, incognito))
                if artist not in known:
                    # a first listen that lands can turn into a new favourite
                    liked = reason_end != "fwdbtn"
                    known[artist] = {"aff": random.uniform(1.5, 6) if liked and random.random() < 0.5 else 0.2, "last": t}
                k = known[artist]
                k["aff"] = min(12, max(0.1, k["aff"] + (-0.6 if reason_end == "fwdbtn" else 0.6)))
                k["last"] = t
                prev_end = reason_end
                t = t_end + timedelta(seconds=random.randint(0, 3))
                if reason_end in ("endplay", "logout", "unexpected-exit"):
                    break
        # the odd podcast, which the loader should filter out
        if random.random() < 0.1:
            r = row(day.replace(hour=8) + timedelta(minutes=40), random.randint(300000, 2400000), main_platform,
                    None, None, "clickrow", "endplay", False, False, False)
            r.update({"episode_name": "Episode " + str(random.randint(1, 300)), "episode_show_name": "The Culture Hour",
                      "spotify_episode_uri": "spotify:episode:" + "".join(random.choices(string.ascii_letters, k=22))})
            rows.append(r)
        day += timedelta(days=1)

    rows.sort(key=lambda r: r["ts"])
    out_dir = os.path.join("sample_data", name)
    os.makedirs(out_dir, exist_ok=True)
    # Spotify splits exports into files of roughly 15-20k rows
    for n, i in enumerate(range(0, len(rows), 15000)):
        with open(os.path.join(out_dir, f"Streaming_History_Audio_2025-2026_{n}.json"), "w") as f:
            json.dump(rows[i:i + 15000], f, indent=1)
    for a in known:
        tag_rows[a] = artist_genre[a]
    print(f"{name}: {len(rows):,} rows")

# ---------------------------------------------------------------- Last.fm-style artist info
from fetch_artist_info import FIELDS, tags_to_genre

TAG_SPELLINGS = {
    "amapiano": ["amapiano"], "gqom": ["gqom"], "afro house": ["afro house", "afrohouse"],
    "alte": ["alte"], "uk funky": ["uk funky"], "afrobeats": ["afrobeats", "afropop", "afrobeat"],
    "uk garage": ["uk garage", "2-step"], "uk drill": ["uk drill", "drill"], "hip-hop": ["hip-hop", "rap"],
    "r&b": ["rnb", "r&b"], "pop": ["pop"], "house": ["house", "deep house"],
}
NOISE = ["seen live", "female vocalists", "male vocalists", "british", "south african", "nigerian"]
with open("sample_artist_info.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    for a in sorted(tag_rows):
        if random.random() < 0.03:       # a few artists Last.fm can't find
            w.writerow({"artist_name": a, "lastfm_name": "", "lastfm_listeners": "", "lastfm_tags": "",
                        "genre": "", "status": "not_found"})
            continue
        g = artist_genre[a]
        tags = [random.choice(TAG_SPELLINGS[g])] + random.sample(NOISE, 2)
        if random.random() < 0.25:       # sometimes a junk tag comes first
            tags.insert(0, tags.pop())
        w.writerow({"artist_name": a, "lastfm_name": a, "lastfm_listeners": artist_listeners[a],
                    "lastfm_tags": "; ".join(tags), "genre": tags_to_genre(tags), "status": "ok"})
print(f"artists in sample_artist_info.csv: {len(tag_rows)}")
