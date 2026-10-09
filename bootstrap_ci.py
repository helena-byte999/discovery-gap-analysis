"""How sure can we be? Pooled and within-listener views of the headline numbers.

Why two views. With 10 listeners, a POOLED rate (all plays added up) is dominated by
whoever contributes most plays, and listeners differ a lot in how often they skip. If
low-skip listeners also play many lesser-known artists, a pooled gap can appear that no
single listener shows (Simpson's paradox). So every gap is reported both ways:

    pooled          all listeners' plays added up (the number in the SQL output)
    95% range       listener-level bootstrap: draw 10 listeners with replacement,
                    recompute, repeat 10,000 times, keep the middle 95%. It describes
                    variation among listeners like these, not all Spotify users.
    per-listener    the gap computed inside each listener, then the mean and median
                    across the 10 (every listener counts once)
    sign test       how many of the 10 show the gap (a gap within +/-0.5 points is
                    "level" and left out), and the exact two-sided p-value
    without top     pooled, leaving out the listener who contributes the most lesser-known
                    lean-back first listens (found from the data, so no code is hard-wired)
    leave-one-out   pooled, leaving out each listener in turn (lowest and highest result)

Input:  results/listener_counts.tsv: the output of 05_listener_counts.sql, with public codes
        (save the query output to results/raw/listener_counts.tsv, then run pseudonymise.py).
        A CSV export from PopSQL works too:  python3 bootstrap_ci.py path/to/file.csv
Output: printed table and results/confidence_ranges.csv

Standard library only.
"""
import csv
import random
import sys
from collections import defaultdict
from math import comb
from statistics import mean, median

IN_FILE = "results/listener_counts.tsv"
OUT_FILE = "results/confidence_ranges.csv"
REPS = 10_000
SEED = 42          # fixed, so the ranges are the same on every run
LEVEL = 0.5        # a per-listener gap within +/- this many points counts as level


def load(path):
    """{listener: {size_tier: {column: int}}}"""
    data = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as f:
        delimiter = "\t" if "\t" in f.readline() else ","    # mysql client -> tabs; PopSQL export -> commas
        f.seek(0)
        for r in csv.DictReader(f, delimiter=delimiter):
            data[r["listener"]][r["size_tier"]] = {k: int(v) for k, v in r.items()
                                                   if k not in ("listener", "size_tier")}
    return dict(data)


def rate(sample, tier, num, den):
    """Pooled % for one size tier across the listeners in `sample`."""
    n = sum(d[tier][num] for d in sample)
    k = sum(d[tier][den] for d in sample)
    return 100 * n / k if k else float("nan")


def share(sample, tier, col):
    """% of `col` (e.g. lean-back new artists) that fall in `tier`."""
    part = sum(d[tier][col] for d in sample)
    whole = sum(d[t][col] for d in sample for t in ("small", "mid", "big"))
    return 100 * part / whole if whole else float("nan")


# (name, function of a list of listener records -> %, is_gap)
METRICS = [
    ("F1 lean-back first-listen skip: lesser-known", lambda s: rate(s, "small", "lb_first_skipped", "lb_first"), False),
    ("F1 lean-back first-listen skip: big", lambda s: rate(s, "big", "lb_first_skipped", "lb_first"), False),
    ("F1 gap: big minus lesser-known (pts)",
     lambda s: rate(s, "big", "lb_first_skipped", "lb_first") - rate(s, "small", "lb_first_skipped", "lb_first"), True),
    ("F2 lesser-known share: lean-back new artists", lambda s: share(s, "small", "lb_first"), False),
    ("F2 lesser-known share: chosen new artists", lambda s: share(s, "small", "chosen_first"), False),
    ("F2 gap: lean-back minus chosen (pts)",
     lambda s: share(s, "small", "lb_first") - share(s, "small", "chosen_first"), True),
    ("F3 stuck 30-90 days: lesser-known", lambda s: rate(s, "small", "lb_stuck", "lb_disc"), False),
    ("F3 stuck 30-90 days: big", lambda s: rate(s, "big", "lb_stuck", "lb_disc"), False),
    ("F3 gap: big minus lesser-known (pts)",
     lambda s: rate(s, "big", "lb_stuck", "lb_disc") - rate(s, "small", "lb_stuck", "lb_disc"), True),
    ("F4 back within 30d after a liked listen: lesser-known", lambda s: rate(s, "small", "liked_back", "liked"), False),
    ("F4 back within 30d after a liked listen: big", lambda s: rate(s, "big", "liked_back", "liked"), False),
    ("F4 gap: big minus lesser-known (pts)",
     lambda s: rate(s, "big", "liked_back", "liked") - rate(s, "small", "liked_back", "liked"), True),
    ("F4 lean-back return gap: big minus lesser-known (pts)",
     lambda s: rate(s, "big", "liked_back_lean_back", "liked") - rate(s, "small", "liked_back_lean_back", "liked"), True),
    ("F4 listener clicked back: lesser-known", lambda s: rate(s, "small", "liked_back_clicked", "liked"), False),
    ("F4 listener clicked back: big", lambda s: rate(s, "big", "liked_back_clicked", "liked"), False),
]


def percentile(sorted_vals, q):
    i = (len(sorted_vals) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


def sign_test(gaps):
    """Exact two-sided sign test, level gaps left out. Returns (positive, non-level, p)."""
    pos = sum(g > LEVEL for g in gaps)
    n = sum(abs(g) > LEVEL for g in gaps)
    k = min(pos, n - pos)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n) if n else float("nan")
    return pos, n, p


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else IN_FILE
    try:
        data = load(path)
    except FileNotFoundError:
        sys.exit(f"{path} not found. Run 05_listener_counts.sql first (see the top of that file).")
    names = sorted(data)
    people = [data[k] for k in names]
    if any(set(p) != {"small", "mid", "big"} for p in people):
        sys.exit("Every listener needs a small, mid and big row. Check the query output.")
    top = max(names, key=lambda k: data[k]["small"]["lb_first"])     # the biggest contributor
    others = [data[k] for k in names if k != top]
    rng = random.Random(SEED)
    rows = []
    print(f"{len(people)} listeners, {REPS:,} resamples. Gaps in percentage points. "
          f"'w/o top' leaves out {top}.\n")
    print(f"{'metric':55} {'pooled':>6} {'95% range':>14} {'w/o top':>7} {'leave-1-out':>11}| {'mean':>5} {'median':>6} "
          f"{'shows it':>8} {'sign p':>6}")
    for name, fn, is_gap in METRICS:
        value = fn(people)
        boots = [fn([rng.choice(people) for _ in people]) for _ in range(REPS)]
        boots = sorted(b for b in boots if b == b)          # drop NaN (a resample with no cases)
        lo, hi = percentile(boots, 0.025), percentile(boots, 0.975)
        loo = [fn(people[:i] + people[i + 1:]) for i in range(len(people))]
        row = {"metric": name, "pooled": round(value, 1), "ci95_low": round(lo, 1), "ci95_high": round(hi, 1),
               "pooled_without_top": round(fn(others), 1),
               "leave_one_out_min": round(min(loo), 1), "leave_one_out_max": round(max(loo), 1)}
        line = f"{name:55} {value:6.1f} {lo:6.1f} to {hi:5.1f} {fn(others):7.1f} {min(loo):5.1f}-{max(loo):<5.1f}|"
        if is_gap:
            gaps = [fn([p]) for p in people]
            pos, n, p = sign_test(gaps)
            row.update(per_listener_mean=round(mean(gaps), 1), per_listener_median=round(median(gaps), 1),
                       listeners_showing=f"{pos} of {len(gaps)} ({len(gaps) - n} level)", sign_test_p=round(p, 3))
            line += f" {mean(gaps):5.1f} {median(gaps):6.1f} {pos:>3}/{n:<2}{len(gaps) - n:>2}= {p:6.3f}"
        print(line)
        rows.append(row)
    fields = ["metric", "pooled", "ci95_low", "ci95_high", "pooled_without_top", "leave_one_out_min",
              "leave_one_out_max", "per_listener_mean",
              "per_listener_median", "listeners_showing", "sign_test_p"]
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\n'shows it' = listeners with the gap / listeners not level, then how many are level (within {LEVEL}).")
    print(f"Saved {OUT_FILE}")


if __name__ == "__main__":
    main()
