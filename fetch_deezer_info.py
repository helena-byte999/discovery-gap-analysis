"""Looks up every artist on Deezer and saves their fan count: a second measure of artist size.

Why a second measure: Last.fm's users lean Western and towards rock/indie, so some genres
(Afrobeats, amapiano, UK rap...) can look smaller there than they really are. Deezer has a
different audience. If both measures tell the same story, the finding doesn't depend on
one platform's bias.

Run on your own Mac (it needs the internet). No account or key needed.
    python3 fetch_deezer_info.py --test    # 20 most-played artists, prints results, saves nothing
    python3 fetch_deezer_info.py           # everyone (about 2 hours; stop and resume any time)

Input:  artists.csv       (written by load_history.py; needs its top_track column)
Output: deezer_info.csv   (artist_name, deezer_id, deezer_name, deezer_fans, status)

How an artist is matched (so a lesser-known artist is never given a famous namesake's fans):
  1. Search Deezer for the name; keep results whose name matches (ignoring capitals/accents).
  2. Search Deezer for "<artist> <their most-played track in YOUR data>" (then, if needed, the
     track title alone) and accept the candidate that actually has that track.
     (Deezer's artist:"..." track:"..." search syntax returns nothing, so plain search is used.)
Statuses: ok = confirmed | unverified = a same-name artist exists but the track didn't confirm
it (not used) | not_found = no artist with that name. Only 'ok' rows are used by the loader.

Deezer allows 50 requests per 5 seconds; this uses 8 per second, two or three requests per artist.

Standard library only.
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://api.deezer.com"
FIELDS = ["artist_name", "deezer_id", "deezer_name", "deezer_fans", "status", "check"]
CHECK = "v2"   # rows marked unverified by an older check are looked up again


def match_key(name):
    """Same rule the loader uses: ignore capitals, accents and trailing spaces."""
    s = unicodedata.normalize("NFKD", name.rstrip())
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def loose_key(name):
    """Looser still: letters and digits only ('A$AP Rocky' = 'ASAP Rocky')."""
    return re.sub(r"[^0-9a-z]", "", match_key(name).replace("$", "s"))


def clean_title(title):
    """'Essence (feat. Tems) - Remix' -> 'Essence': extras that Deezer often writes differently."""
    t = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", title)
    return t.split(" - ")[0].strip() or title


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
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + seconds)


class RateLimited(Exception):
    pass


def get(path, params):
    req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "discovery-gap-case-study/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def search_artists(name):
    return get("/search/artist", {"q": name, "limit": 10})


def search_track(name, title):
    """Plain search for the artist and track; 'name' can be empty to search the title alone."""
    q = f"{name} {clean_title(title)}".strip()
    return get("/search", {"q": q, "limit": 25 if name else 50})


def call(limiter, fn, *args):
    """One request through the shared limiter. Deezer's 'quota exceeded' (code 4) -> RateLimited."""
    limiter.wait()
    data = fn(*args)
    if isinstance(data, dict) and "error" in data:
        if data["error"].get("code") == 4:
            raise RateLimited()
        raise ValueError(f"deezer error {data['error'].get('code')}")
    return data


def candidates(artist, results):
    """Same-name results, exact matches first, in Deezer's order."""
    out = []
    for key in (match_key, loose_key):
        want = key(artist)
        if want:
            out += [a for a in results if key(a.get("name", "")) == want and a not in out]
    return out


def fetch_one(artist, top_track, limiter):
    row = {"artist_name": artist, "deezer_id": "", "deezer_name": "", "deezer_fans": "", "status": "", "check": CHECK}
    for attempt in range(4):
        try:
            cands = candidates(artist, call(limiter, search_artists, artist).get("data", []))
            if not cands:
                row["status"] = "not_found"
                break
            hit = None
            if top_track:
                for query_name in (artist, ""):           # artist + track first, then the track alone
                    ids = {(t.get("artist") or {}).get("id")
                           for t in call(limiter, search_track, query_name, top_track).get("data", [])}
                    hit = next((c for c in cands if c.get("id") in ids), None)
                    if hit:
                        break
            if hit is None:
                c = cands[0]                      # kept for inspection only; not used
                row.update({"deezer_id": c.get("id", ""), "deezer_name": c.get("name", ""),
                            "deezer_fans": c.get("nb_fan", ""), "status": "unverified"})
            else:
                row.update({"deezer_id": hit.get("id", ""), "deezer_name": hit.get("name", ""),
                            "deezer_fans": hit.get("nb_fan", ""), "status": "ok"})
            break
        except RateLimited:
            row["status"] = "error_rate_limited"
            limiter.pause(5 * (attempt + 1))      # everyone backs off, then retry
        except ValueError as e:
            row["status"] = "error_" + str(e).split()[-1]
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError):
            row["status"] = "error_network"
            time.sleep(3 * (attempt + 1))
    return row


def run_test(artists, limiter):
    """Look up the 20 most-played artists and print what Deezer returns. Saves nothing."""
    print(f"{'artist':30} {'deezer name':30} {'fans':>12}  status")
    rows = [fetch_one(a, t, limiter) for a, t in artists[:20]]
    for r in rows:
        print(f"{r['artist_name'][:30]:30} {r['deezer_name'][:30]:30} {str(r['deezer_fans']):>12}  {r['status']}")
    ok = [r for r in rows if r["status"] == "ok"]
    if ok and not any(str(r["deezer_fans"]).isdigit() for r in ok):
        sys.exit("\n! Deezer found the artists but returned no fan counts. Don't run the full lookup; "
                 "tell Claude what you see above.")
    print(f"\n{len(ok)} of {len(rows)} confirmed with a fan count. Looks right? "
          "Run it without --test for everyone.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artists", default="artists.csv")
    ap.add_argument("--out", default="deezer_info.csv")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rate", type=float, default=8.0, help="requests per second (Deezer allows 10)")
    ap.add_argument("--test", action="store_true", help="try the 20 most-played artists; save nothing")
    args = ap.parse_args()
    args.rate = min(args.rate, 9.0)
    if not os.path.exists(args.artists):
        sys.exit(f"{args.artists} not found. Run load_history.py first: it writes this file.")

    with open(args.artists, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "top_track" not in (reader.fieldnames or []):
            sys.exit(f"{args.artists} has no top_track column. Run the new load_history.py first.")
        artists = [(r["artist_name"], r.get("top_track", "")) for r in reader]

    limiter = RateLimiter(args.rate)
    if args.test:
        run_test(artists, limiter)
        return

    done = {}
    if os.path.exists(args.out):
        with open(args.out, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("status") in ("ok", "not_found") or (r.get("status") == "unverified"
                                                               and r.get("check") == CHECK):
                    done[r["artist_name"]] = r
    todo = [(a, t) for a, t in artists if a not in done]
    print(f"{len(artists):,} artists, {len(done):,} already looked up, {len(todo):,} to go.")
    if todo:
        print(f"About {2.2 * len(todo) / args.rate / 60:.0f} minutes. Ctrl+C to stop; rerun to resume.")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in done.values():
            w.writerow({k: r.get(k, "") for k in FIELDS})

    errors = 0
    pool = ThreadPoolExecutor(max_workers=max(1, args.workers))
    started = time.monotonic()
    try:
        with open(args.out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            futures = [pool.submit(fetch_one, a, t, limiter) for a, t in todo]
            for i, fut in enumerate(as_completed(futures), 1):
                row = fut.result()
                if row["status"].startswith("error"):
                    errors += 1
                w.writerow(row)
                f.flush()
                if i % 250 == 0 or i == len(todo):
                    left = (len(todo) - i) * (time.monotonic() - started) / i / 60
                    print(f"  {i:,}/{len(todo):,} done  (~{left:.0f} min left)")
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        sys.exit("\nStopped. Everything looked up so far is saved; run the same command to carry on.")
    pool.shutdown(wait=True)

    with open(args.out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    count = lambda s: sum(r["status"] == s for r in rows)
    print(f"\nSaved {args.out}: {count('ok'):,} confirmed, {count('unverified'):,} unverified "
          f"(same name, track didn't match), {count('not_found'):,} not on Deezer.",
          f"{errors} lookups failed; run again to retry them." if errors else "")
    print("Next: python3 load_history.py ext_streaming_history   (it reads deezer_info.csv automatically)")


if __name__ == "__main__":
    main()
