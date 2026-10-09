"""Unwrapped: a personal discovery recap for each listener, the data behind the story cards.

Run from the spotify-discovery folder (needs artist_info.csv from fetch_artist_info.py):
    python3 make_unwrapped.py ext_streaming_history

Writes:
    unwrapped/unwrapped_data.json   one entry per listener, grouped by card (easiest to read)
    unwrapped/unwrapped_data.csv    one row per listener, one column per field (for design tools)

Same definitions as the case study, so the two never disagree:
    skip           played under 30 seconds, or ended by pressing next
    lesser-known   in the bottom third of their own genre by Last.fm listeners (the same
                   "rank within genre" rule as 03_build_facts.sql). Artists with no genre use the
                   fixed cut-off (under 100,000); artists with no Last.fm match are left out.
    discovery      the first time a listener ever played an artist, ignoring each person's first
                   30 days (at the start of an export every artist looks new)
    found by you   the first play started from a click (clickrow / playbtn)
    found for you  the first play carried on by itself (trackdone): autoplay, radio, or a playlist
                   or album playing on
It covers 2016 onward (the year Spotify Wrapped started; change with --since), the same
window as the case study. First plays are still judged against each person's whole history.

Checking "lesser-known":
    - not_lesser_known.csv (optional, one column: artist_name): artists you know aren't
      lesser-known. They never appear on the lesser-known cards.
    - Each run writes unwrapped/review_lesser_known.csv: every artist shown on a lesser-known card,
      biggest first. Copy any that aren't lesser-known into not_lesser_known.csv and run again.

Privacy: each listener's entry holds only their own data. Group comparisons are ranks only
("#2 of 7"). IP addresses are never read. Artist names come from the listener's own history.

Standard library only; reuses the reading rules in load_history.py.
"""
import argparse
import csv
import json
import os
import statistics
from bisect import bisect_left
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import load_history as lh
from fetch_artist_info import tags_to_genres

LESSER_KNOWN = 100_000      # fixed cut-off, used only for artists with no genre
MIN_GROUP = 50              # a genre needs this many artists to be ranked on its own
FAMILIES = {                # smaller genres are ranked with their family (as in 03_build_facts.sql)
    "family: african": {"afrobeats", "amapiano", "alte", "highlife", "afro house", "gqom",
                        "fuji", "soukous", "kuduro"},
    "family: uk": {"uk drill", "grime", "uk garage", "uk funky"},
}
WARMUP_DAYS = 30
REGULAR_PLAYS = 10          # a hidden gem you "kept" has at least this many plays
SECOND_CHANCE_PLAYS = 20    # skipped first, then played at least this many times
NEVER_SKIP_MIN_PLAYS = 50   # the artist you never skip needs at least this many plays

# Local time for the listening clock, by the country Spotify recorded for each play.
TIMEZONES = {
    "NG": "Africa/Lagos", "GB": "Europe/London", "GH": "Africa/Accra", "ZA": "Africa/Johannesburg",
    "KE": "Africa/Nairobi", "IE": "Europe/Dublin", "FR": "Europe/Paris", "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam", "ES": "Europe/Madrid", "IT": "Europe/Rome", "PT": "Europe/Lisbon",
    "US": "America/New_York", "CA": "America/Toronto", "AE": "Asia/Dubai",
}
COUNTRY_NAMES = {
    "NG": "Nigeria", "GB": "the UK", "GH": "Ghana", "ZA": "South Africa", "KE": "Kenya",
    "IE": "Ireland", "FR": "France", "DE": "Germany", "NL": "the Netherlands", "ES": "Spain",
    "IT": "Italy", "PT": "Portugal", "US": "the US", "CA": "Canada", "AE": "the UAE",
}
CLOCK = [(0, 6, "after midnight"), (6, 12, "in the morning"), (12, 18, "in the afternoon"),
         (18, 24, "in the evening")]


class Play:
    __slots__ = ("start", "ms", "artist", "track", "uri", "rs", "re", "shuffle", "platform", "country")

    def __init__(self, *v):
        for k, x in zip(self.__slots__, v):
            setattr(self, k, x)

    @property
    def skip(self):
        return self.ms < 30000 or self.re == "fwdbtn"

    @property
    def found(self):
        if self.rs in ("clickrow", "playbtn"):
            return "you"
        if self.rs == "trackdone":
            return "autoplay"
        return "other"


def read_listener(folder):
    """Music plays from one export, same filters as load_history.py."""
    plays, seen = [], set()
    for path in lh.find_export_files(folder):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for r in data:
            uri, artist, track = (r.get("spotify_track_uri"), r.get("master_metadata_album_artist_name"),
                                  r.get("master_metadata_track_name"))
            ms = int(r.get("ms_played") or 0)
            if not uri or not artist or not track or ms <= 0:
                continue
            key = (r["ts"], uri, ms)
            if key in seen:
                continue
            seen.add(key)
            ended = datetime.strptime(r["ts"].replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S")
            plays.append(Play(ended - timedelta(milliseconds=ms), ms, artist[:300], track, uri,
                              r.get("reason_start"), r.get("reason_end"), lh.boolish(r.get("shuffle")),
                              (r.get("platform") or "").lower(), r.get("conn_country") or ""))
    plays.sort(key=lambda p: p.start)
    return plays


def local(p):
    """The play's local time, from the country it was played in (UTC if unknown)."""
    tz = TIMEZONES.get(p.country)
    utc = p.start.replace(tzinfo=timezone.utc)
    return utc.astimezone(ZoneInfo(tz)) if tz else utc


def device(platform):
    if platform in ("", "not_applicable"):
        return "unknown"
    if "tv" in platform or any(w in platform for w in ("cast", "sonos", "echo", "alexa", "amazon", "google_home",
                                                       "ps4", "ps5", "playstation", "xbox", "partner", "bose",
                                                       "speaker", "car")):
        return "speaker, TV or console"
    if any(w in platform for w in ("ios", "iphone", "ipad", "android")):
        return "phone"
    if any(w in platform for w in ("windows", "os x", "osx", "macos", "mac", "linux", "web", "desktop")):
        return "computer"
    return "other"


def label(folder):
    """Folder name -> nickname, the same way load_history.py labels listeners."""
    return folder.replace("Spotify Extended Streaming History", "").strip(" _-") or folder


def hour_label(h):
    return {0: "midnight", 12: "midday"}.get(h, f"{h % 12}{'am' if h < 12 else 'pm'}")


def pct(a, b, digits=0):
    return round(100 * a / b, digits) if b else None


def size_tiers(size, genre):
    """Each artist's size, exactly as artist_tiers.size_tier_genre in 03_build_facts.sql:
    their rank among artists of the same genre (or genre family) by Last.fm listeners.
    Bottom third = small (lesser-known), top third = big."""
    genre_artists = Counter(genre.get(a) for a in size)
    def group(a):
        g = genre.get(a)
        if g is None:
            return None
        if genre_artists[g] >= MIN_GROUP:
            return g
        return next((f for f, members in FAMILIES.items() if g in members), "family: other small genres")
    members = defaultdict(list)
    for a in size:
        if group(a) is not None:
            members[group(a)].append(size[a])
    for v in members.values():
        v.sort()
    tier = {}
    for a, n in size.items():
        g = group(a)
        if g is None:                                   # no genre: fixed cut-offs
            tier[a] = "small" if n < 100_000 else "mid" if n < 1_000_000 else "big"
            continue
        v = members[g]
        if len(v) < MIN_GROUP:
            tier[a] = "unknown"
            continue
        below = bisect_left(v, n)                       # PERCENT_RANK = (rank - 1) / (rows - 1)
        p = below / (len(v) - 1)
        tier[a] = "small" if p < 1 / 3 else "big" if p >= 2 / 3 else "mid"
    return tier


def lesser_known_rule(tier, not_lesser):
    """Lesser-known = 'small' within their genre, and not on your not_lesser_known list."""
    return lambda a: a not in not_lesser and tier.get(a) == "small"


def recap(all_plays, size, lesser, since):
    """Every card's numbers for one listener, counting plays from `since` onward.
    'First time you heard an artist' still looks at the whole history, so an artist heard
    in 2015 never counts as a 2016 discovery."""
    first = {}
    for p in all_plays:
        first.setdefault(p.artist, p)
    plays = [p for p in all_plays if p.start >= since] or all_plays
    count, skips = Counter(), Counter()
    for p in plays:
        count[p.artist] += 1
        skips[p.artist] += p.skip
    start, end = plays[0].start, plays[-1].start
    warm = max(all_plays[0].start + timedelta(days=WARMUP_DAYS), since)
    found = {a: p for a, p in first.items() if p.start >= warm}          # discoveries
    top_rank = {a: i for i, (a, _) in enumerate(count.most_common(), 1)}
    out = {}

    out["intro"] = {"years": f"{start.year}–{end.year}" if start.year != end.year else str(start.year),
                    "hours": round(sum(p.ms for p in plays) / 3.6e6), "plays": len(plays),
                    "artists": len(count)}

    skipped = [p for p in plays if p.skip]
    out["minutes_skipped"] = {
        "skips": len(skipped), "pct_of_plays": pct(len(skipped), len(plays)),
        "seconds_before_skip": round(statistics.median(p.ms for p in skipped) / 1000) if skipped else None,
        "minutes_on_skipped": round(sum(p.ms for p in skipped) / 60000),
        "hours_on_skipped": round(sum(p.ms for p in skipped) / 3.6e6)}

    months = max(1.0, (end - warm).days / 30.44)
    out["explorer_or_loyalist"] = {"plays_per_artist": round(len(plays) / len(count), 1),
                                   "new_per_month": round(len(found) / months),
                                   "listener_type": None, "rank": None, "group_size": None}  # filled in later

    by = Counter(p.found for p in found.values())
    chosen, auto = by["you"], by["autoplay"]
    out["who_finds_your_music"] = {"pct_found_by_you": pct(chosen, chosen + auto),
                                   "pct_found_by_spotify": pct(auto, chosen + auto),
                                   "note": "'by spotify' = the first play carried on by itself: autoplay, radio, "
                                           "or a playlist/album playing on"}

    # Skipped within 30 seconds (not just "pressed next"), since the card says "you gave them seconds".
    got_away = [p for a, p in found.items()
                if lesser(a) and p.found == "autoplay" and p.ms < 30000 and count[a] == 1]
    got_away.sort(key=lambda p: p.start, reverse=True)
    out["ones_that_got_away"] = {"count": len(got_away), "artists": [
        {"artist": p.artist, "seconds_played": max(1, round(p.ms / 1000)), "date": p.start.date().isoformat()}
        for p in got_away[:5]]}

    gems = sorted((a for a in found if lesser(a) and count[a] >= REGULAR_PLAYS), key=lambda a: -count[a])
    out["hidden_gems"] = {"count": len(gems), "artists": [
        {"artist": a, "plays": count[a], "found_by": found[a].found, "year_found": found[a].start.year,
         "lastfm_listeners": size[a]} for a in gems[:5]]}

    chances = sorted((a for a, p in found.items() if p.skip and count[a] >= SECOND_CHANCE_PLAYS),
                     key=lambda a: -count[a])
    out["second_chances"] = {"count": len(chances), "artists": [
        {"artist": a, "first_skip_date": found[a].start.date().isoformat(), "plays_since": count[a] - 1,
         "artist_rank": top_rank[a]} for a in chances[:3]]}

    sized = [p for p in plays if size.get(p.artist) is not None]
    out["backing_lesser_known"] = {"pct_lesser_known": pct(sum(lesser(p.artist) for p in sized), len(sized), 1),
                                   "rank": None, "group_size": None}

    songs = Counter(p.uri for p in plays)
    uri, total = songs.most_common(1)[0]
    days = Counter(local(p).date() for p in plays if p.uri == uri)
    day, n = days.most_common(1)[0]
    song = next(p for p in plays if p.uri == uri)
    out["your_obsession"] = {"song": song.track, "artist": song.artist, "total_plays": total,
                             "record_date": day.isoformat(), "plays_that_day": n}

    per_year = defaultdict(list)
    for a, p in found.items():
        per_year[p.start.year].append(a)
    out["year_by_year"] = [{"year": y, "artist": max(per_year[y], key=lambda a: count[a]),
                            "plays": count[max(per_year[y], key=lambda a: count[a])]}
                           for y in sorted(per_year)[-6:]]

    steady = [a for a in count if count[a] >= NEVER_SKIP_MIN_PLAYS]
    if steady:
        a = min(steady, key=lambda a: (skips[a] / count[a], -count[a]))
        out["never_skip"] = {"artist": a, "skip_pct": pct(skips[a], count[a], 1), "plays": count[a]}
    else:
        out["never_skip"] = None

    hours = Counter(local(p).hour for p in found.values())
    buckets = Counter()
    for h, c in hours.items():
        buckets[next(label for lo, hi, label in CLOCK if lo <= h < hi)] += c
    if buckets:
        label, c = buckets.most_common(1)[0]
        out["listening_clock"] = {"discoveries_happen": label, "pct": pct(c, sum(buckets.values())),
                                  "peak_hour": hour_label(hours.most_common(1)[0][0])}
    else:
        out["listening_clock"] = None

    kinds = Counter(device(p.platform) for p in plays)
    known = sum(c for k, c in kinds.items() if k != "unknown")
    shuffled = [p.shuffle for p in plays if p.shuffle is not None]
    places = Counter(p.country for p in plays if p.country and p.country != "ZZ")   # ZZ = unknown
    out["where_and_how"] = {
        "devices_pct": {k: pct(c, known) for k, c in kinds.most_common() if k != "unknown"},
        "top_device": next((k for k, _ in kinds.most_common() if k != "unknown"), None),
        "pct_device_unknown": pct(kinds["unknown"], len(plays)),
        "shuffle_pct": pct(sum(shuffled), len(shuffled)),
        "countries": [{"country": COUNTRY_NAMES.get(c, c), "pct": pct(n, sum(places.values()))}
                      for c, n in places.most_common(3) if n / sum(places.values()) >= 0.01]}
    return out


def add_group_ranks(recaps):
    """Anonymous comparisons: each person only ever sees their own rank."""
    n = len(recaps)
    third = max(1, n // 3)
    order = sorted(recaps, key=lambda k: recaps[k]["explorer_or_loyalist"]["plays_per_artist"])
    for rank, k in enumerate(order, 1):
        e = recaps[k]["explorer_or_loyalist"]
        e.update(rank=rank, group_size=n,
                 listener_type="Explorer" if rank <= third else "Loyalist" if rank > n - third else "In-between")
    order = sorted(recaps, key=lambda k: -(recaps[k]["backing_lesser_known"]["pct_lesser_known"] or 0))
    for rank, k in enumerate(order, 1):
        recaps[k]["backing_lesser_known"].update(rank=rank, group_size=n)


def flatten(d, prefix=""):
    """{'a': {'b': 1}, 'l': [{'x': 2}]} -> {'a_b': 1, 'l_1_x': 2}: one column per field."""
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}{k}_"))
    elif isinstance(d, list):
        for i, v in enumerate(d, 1):
            out.update(flatten(v, f"{prefix}{i}_"))
    else:
        out[prefix.rstrip("_")] = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", help="folder with one sub-folder per listener (e.g. ext_streaming_history)")
    ap.add_argument("--info", default="artist_info.csv", help="Last.fm results from fetch_artist_info.py")
    ap.add_argument("--genres", default="artist_genres.csv", help="your own genre fixes (win over Last.fm)")
    ap.add_argument("--not-lesser", default="not_lesser_known.csv", help="artists you know aren't lesser-known")
    ap.add_argument("--since", default="2016-01-01", help="first day counted (default: Wrapped's first year)")
    ap.add_argument("--out", default="unwrapped")
    args = ap.parse_args()

    folders = sorted(d for d in os.listdir(args.data_dir) if os.path.isdir(os.path.join(args.data_dir, d)))
    everyone = {}
    for name in folders:
        plays = read_listener(os.path.join(args.data_dir, name))
        if plays:
            everyone[label(name)] = plays
            print(f"  {label(name)}: {len(plays):,} plays")
    if not everyone:
        sys.exit(f"No listening data found in {args.data_dir}")

    # One spelling per artist across everyone, exactly as load_history.py does.
    totals = Counter(p.artist for plays in everyone.values() for p in plays)
    spelling = {}
    for a, _ in totals.most_common():
        spelling.setdefault(lh.match_key(a), a)
    for plays in everyone.values():
        for p in plays:
            p.artist = spelling[lh.match_key(p.artist)]

    # Size and main genre for every artist in anyone's history, exactly as load_history.py
    # builds the artists table (so the ranking uses the same set of artists as the SQL).
    info = {r["artist_name"]: r for r in lh.read_csv(args.info) if r.get("artist_name")}
    manual = {lh.match_key(r["artist_name"]): lh.split_genres(r.get("genre"))
              for r in lh.read_csv(args.genres) if (r.get("artist_name") or "").strip()}
    size, genre = {}, {}
    for a in totals:
        a = spelling[lh.match_key(a)]
        i = info.get(a, {})
        if i.get("status") == "ok" and str(i.get("lastfm_listeners", "")).isdigit():
            size[a] = int(i["lastfm_listeners"])
        if manual.get(lh.match_key(a)):
            gs = manual[lh.match_key(a)]
        elif i.get("status") == "ok" and i.get("lastfm_tags"):
            gs = tags_to_genres(i["lastfm_tags"].split(";"))
        else:
            gs = lh.split_genres(i.get("genre"))
        if gs:
            genre[a] = gs[0]
    if not size:
        sys.exit(f"No artist sizes in {args.info}: run fetch_artist_info.py first.")
    tier = size_tiers(size, genre)
    not_lesser = {lh.match_key(r["artist_name"]) for r in lh.read_csv(args.not_lesser) if r.get("artist_name")}
    not_lesser = {spelling[k] for k in not_lesser if k in spelling}
    lesser = lesser_known_rule(tier, not_lesser)
    print(f"Lesser-known = bottom third of their genre ({sum(t == 'small' for t in tier.values()):,} artists)"
          f"{f', {len(not_lesser)} excluded by you' if not_lesser else ''}.")

    since = datetime.strptime(args.since, "%Y-%m-%d")
    recaps = {who: recap(plays, size, lesser, since) for who, plays in everyone.items()}
    add_group_ranks(recaps)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "unwrapped_data.json"), "w", encoding="utf-8") as f:
        json.dump(recaps, f, ensure_ascii=False, indent=2)
    rows = [{"listener": who, **flatten(r)} for who, r in recaps.items()]
    cols = ["listener"] + sorted({c for r in rows for c in r} - {"listener"})
    with open(os.path.join(args.out, "unwrapped_data.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    # Every artist shown on a lesser-known card, biggest first: the ones most worth a second look.
    shown = Counter()
    for r in recaps.values():
        for card in ("hidden_gems", "ones_that_got_away"):
            for a in r[card]["artists"]:
                shown[a["artist"]] += 1
    with open(os.path.join(args.out, "review_lesser_known.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["artist_name", "genre", "lastfm_listeners", "on_how_many_unwrappeds"])
        for a in sorted(shown, key=lambda a: -size[a]):
            w.writerow([a, genre.get(a, ""), size[a], shown[a]])
    print(f"\nWrote {args.out}/unwrapped_data.json and .csv for {len(recaps)} listeners.")
    print(f"Check {args.out}/review_lesser_known.csv: copy any artist who isn't lesser-known into "
          f"{args.not_lesser} (column: artist_name) and run this again.")


if __name__ == "__main__":
    main()
