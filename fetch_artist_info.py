"""Looks up every artist on Last.fm: global listener count + top tags, and suggests a genre.

Run on your own Mac (it needs the internet):
    put LASTFM_API_KEY=your_key in a .env file in this folder (copy .env.example;
    .env is git-ignored, so the key never reaches GitHub), or export it in Terminal
    python3 fetch_artist_info.py
(--api-key YOUR_KEY also works, but it leaves the key in your Terminal history.)

Get a free API key at https://www.last.fm/api/account/create (you need a Last.fm account;
the "callback URL" field can be left blank).

Input:  artists.csv       (written by load_history.py: every artist in your data)
Output: artist_info.csv   (artist_name, lastfm_name, lastfm_listeners, lastfm_tags, genre, status)

It saves as it goes, so you can stop it (Ctrl+C) and run it again later: it picks up
where it left off. It runs 4 lookups side by side, capped at 4 requests per second
(Last.fm asks for no more than 5), so 10,000 artists takes about 45 minutes.

Standard library only.
"""
import argparse
import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://ws.audioscrobbler.com/2.0/"
FIELDS = ["artist_name", "lastfm_name", "lastfm_listeners", "lastfm_tags", "genre", "status"]

# ---------------------------------------------------------------------
# Tag -> genre. The artist's tags are checked in order (Last.fm lists the
# most-used tag first). The first tag that matches is the artist's MAIN genre;
# every other matching tag becomes an extra genre (an artist can have several).
# Add spellings here if you see common tags going unmatched.
# Deliberately NOT mapped: country tags ("nigeria", "british") and tags like
# "post-punk"/"new wave", which Last.fm often takes from a same-name artist.
# ---------------------------------------------------------------------
TAG_TO_GENRE = {
    "amapiano": "amapiano",
    "gqom": "gqom",
    "afro house": "afro house", "afrohouse": "afro house", "afro-house": "afro house", "afro tech": "afro house",
    "afrobeats": "afrobeats", "afrobeat": "afrobeats", "afropop": "afrobeats", "afro pop": "afrobeats",
    "afro-pop": "afrobeats", "naija": "afrobeats", "afrofusion": "afrobeats", "afro-fusion": "afrobeats",
    "afroswing": "afrobeats", "afro swing": "afrobeats", "street pop": "afrobeats", "street-pop": "afrobeats",
    "highlife": "highlife", "highlife fusion": "highlife",
    "kuduro": "kuduro",
    "lo-fi": "functional", "lofi": "functional", "lo-fi hip hop": "functional", "lofi hip hop": "functional",
    "chillhop": "functional", "chill beats": "functional", "instrumental hip-hop": "functional",
    "instrumental hip hop": "functional", "beats": "functional", "study": "functional", "sleep": "functional",
    "nature sounds": "functional", "meditation": "functional",
    "folk": "folk", "indie folk": "folk", "psychedelic folk": "folk", "folk rock": "folk",
    "soundtrack": "soundtrack", "video game music": "soundtrack", "chiptune": "soundtrack",
    "ambient": "electronic",
    "alte": "alte", "alté": "alte",
    "uk funky": "uk funky",
    "uk garage": "uk garage", "ukg": "uk garage", "2-step": "uk garage",
    "2 step": "uk garage", "2step": "uk garage", "speed garage": "uk garage", "bassline": "uk garage",
    "uk drill": "uk drill", "drill": "uk drill", "grime": "grime",
    "hip-hop": "hip-hop", "hip hop": "hip-hop", "hiphop": "hip-hop", "rap": "hip-hop", "trap": "hip-hop",
    "uk rap": "hip-hop", "uk hip hop": "hip-hop",
    "rnb": "r&b", "r&b": "r&b", "r and b": "r&b", "contemporary r&b": "r&b", "alternative r&b": "r&b",
    "soul": "r&b", "neo-soul": "r&b", "neo soul": "r&b",
    "pop": "pop", "dance-pop": "pop", "dance pop": "pop", "electropop": "pop", "synthpop": "pop",
    "house": "house", "deep house": "house", "tech house": "house", "funky house": "house",
    "electronic": "electronic", "edm": "electronic", "techno": "electronic", "dubstep": "electronic",
    "drum and bass": "electronic", "dnb": "electronic", "electronica": "electronic", "jungle": "electronic",
    "gospel": "gospel", "christian": "gospel", "worship": "gospel", "afrogospel": "gospel",
    "dancehall": "dancehall", "reggae": "dancehall", "bashment": "dancehall",
    "rock": "rock", "alternative rock": "rock", "metal": "rock", "punk": "rock",
    "indie": "indie", "indie rock": "indie", "indie pop": "indie", "alternative": "indie",
    "dream pop": "indie", "bedroom pop": "indie", "shoegaze": "indie",
    "phonk": "hip-hop",
    "k-pop": "k-pop", "kpop": "k-pop",
    "latin": "latin", "reggaeton": "latin",
    "jazz": "jazz", "country": "country", "classical": "classical",
}


# Specific scene/regional genres win over broad ones when choosing the MAIN genre:
# Burna Boy is tagged "rap" before "afrobeats", but afrobeats is the more telling label.
SPECIFIC = {"afrobeats", "amapiano", "alte", "highlife", "afro house", "gqom", "fuji", "soukous", "kuduro",
            "uk drill", "grime", "uk garage", "uk funky", "dancehall", "k-pop", "latin", "gospel"}
# "functional" (lo-fi, study, sleep) is deliberately NOT here: it is the main genre only when it is
# the artist's FIRST matching tag. Otherwise a stray "lo-fi" tag filed TV Girl and Joji as lo-fi.


def tags_to_genres(tags):
    """Every genre the tags point to, no repeats. First = main genre: specific genres
    (afrobeats, uk drill...) come before broad ones (hip-hop, r&b, pop), otherwise tag order."""
    out = []
    plain_lofi_only = True     # was "functional" matched only by the bare "lo-fi" tag?
    for t in tags:
        tag = t.strip().lower()
        g = TAG_TO_GENRE.get(tag)
        if g == "functional" and tag not in AMBIGUOUS_LOFI:
            plain_lofi_only = False
        if g and g not in out:
            out.append(g)
    # A bare "lo-fi" tag also means lo-fi-sounding indie (Mac DeMarco, TV Girl): if the artist
    # also has an indie/rock/folk/r&b tag, it is that, not study/sleep music.
    if "functional" in out and plain_lofi_only and any(g in out for g in ("indie", "rock", "folk", "r&b")):
        out.remove("functional")
    return [g for g in out if g in SPECIFIC] + [g for g in out if g not in SPECIFIC]


AMBIGUOUS_LOFI = {"lo-fi", "lofi"}


def tags_to_genre(tags):
    for t in tags:
        g = TAG_TO_GENRE.get(t.strip().lower())
        if g:
            return g
    return ""


class RateLimiter:
    """Shared by all workers: lets at most `rate` requests start per second."""
    def __init__(self, rate):
        self.interval = 1.0 / rate
        self.next_at = time.monotonic()
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.interval
        time.sleep(max(0.0, start - now))

    def pause(self, seconds):
        """Last.fm said slow down: hold every worker back."""
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + seconds)


class BadKey(Exception):
    pass


def fetch_one(artist, api_key, limiter):
    row = {"artist_name": artist, "lastfm_name": "", "lastfm_listeners": "", "lastfm_tags": "",
           "genre": "", "status": ""}
    for attempt in range(3):
        limiter.wait()
        try:
            data = lookup(artist, api_key)
            if "error" in data:
                if data["error"] == 6:
                    row["status"] = "not_found"
                elif data["error"] in (10, 26):
                    raise BadKey(data.get("message"))
                elif data["error"] == 29:
                    row["status"] = "error_rate_limited"
                    limiter.pause(10 * (attempt + 1))   # rate limited: everyone backs off, then retry
                    continue
                else:
                    row["status"] = f"error_{data['error']}"
            else:
                a = data.get("artist", {})
                tags = a.get("tags", {}).get("tag", []) if isinstance(a.get("tags"), dict) else []
                if isinstance(tags, dict):
                    tags = [tags]
                names = [t.get("name", "") for t in tags][:5]
                row.update({"lastfm_name": a.get("name", ""),
                            "lastfm_listeners": a.get("stats", {}).get("listeners", ""),
                            "lastfm_tags": "; ".join(names),
                            "genre": tags_to_genre(names),
                            "status": "ok"})
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError):
            row["status"] = "error_network"
            time.sleep(3 * (attempt + 1))
    return row


def lookup(artist, api_key):
    q = urllib.parse.urlencode({"method": "artist.getinfo", "artist": artist, "api_key": api_key,
                                "autocorrect": 1, "format": "json"})
    req = urllib.request.Request(API + "?" + q, headers={"User-Agent": "discovery-gap-case-study/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def load_dotenv(path=".env"):
    """Reads KEY=value lines from .env into the environment (an existing export wins)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("LASTFM_API_KEY"))
    ap.add_argument("--artists", default="artists.csv")
    ap.add_argument("--out", default="artist_info.csv")
    ap.add_argument("--workers", type=int, default=4, help="lookups running side by side")
    ap.add_argument("--rate", type=float, default=4.0,
                    help="max requests per second in total (Last.fm asks for 5 or fewer)")
    args = ap.parse_args()
    args.rate = min(args.rate, 5.0)
    if not args.api_key:
        sys.exit("Add your Last.fm key first: copy .env.example to .env and put your key in it,\n"
                 "or run  export LASTFM_API_KEY=your_key  in this Terminal window. Then run this again.")
    if not os.path.exists(args.artists):
        sys.exit(f"{args.artists} not found. Run load_history.py first: it writes this file.")

    with open(args.artists, newline="", encoding="utf-8") as f:
        artists = [r["artist_name"] for r in csv.DictReader(f)]

    done = {}
    if os.path.exists(args.out):
        with open(args.out, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("status") in ("ok", "not_found"):
                    done[r["artist_name"]] = r
    todo = [a for a in artists if a not in done]
    print(f"{len(artists):,} artists, {len(done):,} already looked up, {len(todo):,} to go.")

    # rewrite the file with finished rows only, then append as we go
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in done.values():
            w.writerow({k: r.get(k, "") for k in FIELDS})

    if todo:
        mins = len(todo) / args.rate / 60
        print(f"About {mins:.0f} minutes at {args.rate:g} lookups/second. Ctrl+C to stop; rerun to resume.")

    errors = 0
    limiter = RateLimiter(args.rate)
    pool = ThreadPoolExecutor(max_workers=max(1, args.workers))
    started = time.monotonic()
    try:
        with open(args.out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            futures = [pool.submit(fetch_one, a, args.api_key, limiter) for a in todo]
            for i, fut in enumerate(as_completed(futures), 1):
                row = fut.result()
                if row["status"].startswith("error"):
                    errors += 1
                w.writerow(row)
                f.flush()
                if i % 100 == 0 or i == len(todo):
                    left = (len(todo) - i) * (time.monotonic() - started) / i / 60
                    print(f"  {i:,}/{len(todo):,} done  (~{left:.0f} min left)")
    except BadKey as e:
        pool.shutdown(wait=False, cancel_futures=True)
        sys.exit(f"Last.fm says the API key is invalid or suspended: {e}")
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        sys.exit("\nStopped. Everything looked up so far is saved; run the same command to carry on.")
    pool.shutdown(wait=True)

    print(f"\nSaved {args.out}.", f"{errors} lookups failed; run again to retry them." if errors else "")
    print("Next: python3 load_history.py <your data folder>   (it reads artist_info.csv automatically)")


if __name__ == "__main__":
    main()
