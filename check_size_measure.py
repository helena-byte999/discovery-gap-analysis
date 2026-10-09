"""Checks the Last.fm size measure against Spotify for 30 hand-checked artists.

spotify_check.csv holds each artist's Last.fm listeners and their Spotify monthly
listeners (looked up by hand). Two questions:
    1. Does Last.fm undercount some groups? Compare the median Spotify-per-Last.fm ratio.
    2. Does it still ORDER artists correctly within a group? Spearman rank correlation.
Ranking within genre only needs (2).

    python3 check_size_measure.py

Standard library only.
"""
import csv
from statistics import median


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    r = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1          # average rank for ties
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return cov / (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5


def main():
    with open("spotify_check.csv", newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["lastfm_listeners"] and r["spotify_monthly_listeners"]]
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append((float(r["lastfm_listeners"]), float(r["spotify_monthly_listeners"])))
    ratios = {}
    for g, pairs in sorted(groups.items()):
        ratios[g] = median(s / l for l, s in pairs)
        rho = spearman([l for l, _ in pairs], [s for _, s in pairs])
        print(f"{g:8} {len(pairs):2} artists  median Spotify/Last.fm ratio {ratios[g]:5.1f}  rank correlation {rho:.2f}")
    if {"African", "Western"} <= set(ratios):
        print(f"Undercount of African vs Western artists on Last.fm: {ratios['African'] / ratios['Western']:.1f}x")


if __name__ == "__main__":
    main()
