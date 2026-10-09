"""Sizing for the case study: how big is the "liked but lost" problem, what could a fix
be worth, and how large would the A/B test need to be.

Inputs are MEASURED from this data (results/liked_but_lost.tsv, the output of Q11b in
04_analysis.sql) or ASSUMED (marked below; change them and rerun). Nothing is a Spotify figure.

Definitions (per listener and artist size):
    liked     a lean-back first listen that wasn't skipped (at least 90 days before the data ends)
    lost      liked, then no play of the artist from day 1 to day 14: the proposed trigger
    new_song  in days 30-90 the listener played (not skipped) a DIFFERENT song by the artist.
              This is the experiment's primary metric: it means they met more of the artist,
              not just the same song replaying from a playlist.
    stuck     any non-skipped play in days 30-90 (secondary; weaker)

Why one listener is left out: the biggest contributor plays artist radio while falling
asleep, so many of their "liked" listens may not be real engagement, and they alone supply
58% of liked-but-lost lesser-known artists. Pooled rates without them are the main figures;
the with-everyone figures are printed for comparison. The listener is found from the data.

Sizing and the test size use TRIGGER columns: liked-but-lost first listens that also meet
the proposed trigger rules (played to the end; a tagged, non-functional artist).

    python3 sizing.py

Standard library only.
"""
import csv
from math import ceil, sqrt
from statistics import NormalDist, mean, median, pstdev

IN_FILE = "results/liked_but_lost.tsv"

# ---------------------------------------------------------------- assumptions (change these)
CAP_PER_MONTH = 8                    # at most 2 re-introductions a week per listener
EXPOSURE = {"low": 0.3, "high": 0.7}  # share of triggered re-introductions the listener actually hears
REL_LIFT = {"low": 0.25, "high": 1.0}  # relative rise in the primary metric among those who hear it
ALPHA, POWER = 0.05, 0.80            # two-sided test
ENROL_MONTHS = 1
ICC_FLOOR = 0.02                     # plan with at least this much clustering: 9 listeners can't pin the ICC down


def load(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        delimiter = "\t" if "\t" in f.readline() else ","
        f.seek(0)
        return [dict(r, **{k: float(v) for k, v in r.items() if k not in ("listener", "size_tier")})
                for r in csv.DictReader(f, delimiter=delimiter)]


def pooled(rows, num, den):
    return sum(r[num] for r in rows) / sum(r[den] for r in rows)


def icc_anova(rows, num, den):
    """One-way ANOVA estimate of the intra-class correlation of a 0/1 outcome across listeners."""
    n = [r[den] for r in rows]
    p = [r[num] / r[den] for r in rows]
    N, k = sum(n), len(n)
    p_bar = sum(ni * pi for ni, pi in zip(n, p)) / N
    msb = sum(ni * (pi - p_bar) ** 2 for ni, pi in zip(n, p)) / (k - 1)
    msw = sum(ni * pi * (1 - pi) for ni, pi in zip(n, p)) / (N - k)
    n0 = (N - sum(ni ** 2 for ni in n) / N) / (k - 1)
    return max(0.0, (msb - msw) / (msb + (n0 - 1) * msw))


def n_per_arm(p1, p2):
    """Re-introductions needed per arm to tell p1 from p2 (two-proportion z-test)."""
    z_a, z_b = NormalDist().inv_cdf(1 - ALPHA / 2), NormalDist().inv_cdf(POWER)
    p_bar = (p1 + p2) / 2
    num = z_a * sqrt(2 * p_bar * (1 - p_bar)) + z_b * sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return ceil((num / (p2 - p1)) ** 2)


def main():
    rows = load(IN_FILE)
    small = [r for r in rows if r["size_tier"] == "small"]
    big = [r for r in rows if r["size_tier"] == "big"]
    top = max(small, key=lambda r: r["lost"])["listener"]            # the biggest contributor
    small_x, big_x = [r for r in small if r["listener"] != top], [r for r in big if r["listener"] != top]

    print(f"THE PROBLEM (measured; 'without top' leaves out {top})")
    print(f"  Liked lesser-known artists not heard again within 2 weeks: {100 * pooled(small_x, 'lost', 'liked'):.0f}% "
          f"without top, {100 * pooled(small, 'lost', 'liked'):.0f}% with (big artists: "
          f"{100 * pooled(big_x, 'lost', 'liked'):.0f}% / {100 * pooled(big, 'lost', 'liked'):.0f}%)")
    per_month = [r["lost"] / r["eligible_months"] for r in small]
    print(f"  Per listener per month: median {median(per_month):.1f} (range {min(per_month):.1f} to {max(per_month):.1f})")
    print("  Of the lost ones, share reaching each outcome in days 30-90:")
    print(f"  {'':34}{'lesser-known':>13}{'big':>7}   (without top; with everyone in brackets)")
    for label, col in (("a different song", "lost_new_song"), ("any play (stuck)", "lost_stuck")):
        print(f"  {label:34}{100 * pooled(small_x, col, 'lost'):12.1f}%{100 * pooled(big_x, col, 'lost'):6.1f}%"
              f"   ({100 * pooled(small, col, 'lost'):.1f}% / {100 * pooled(big, col, 'lost'):.1f}%)")
    back_rate = pooled(small_x, "back_new_song", "back")
    print(f"  For comparison, lesser-known artists that DID come back within 2 weeks: {100 * back_rate:.1f}% "
          f"reach a different song (correlation, not proof that a return causes it)")
    within = [100 * (b["lost_new_song"] / b["lost"] - s["lost_new_song"] / s["lost"]) for s, b in zip(small, big)]
    print(f"  Within each listener, big minus lesser-known on 'a different song': median {median(within):.1f} pts, "
          f"{sum(w > 0.5 for w in within)} of {len(within)} listeners")

    print(f"  Meeting the trigger rules: {100 * pooled(small_x, 'trigger_lost', 'lost'):.0f}% of lost lesser-known "
          f"artists; of those, {100 * pooled(small_x, 'trigger_lost_new_song', 'trigger_lost'):.1f}% reach a different "
          f"song (big: {100 * pooled(big_x, 'trigger_lost_new_song', 'trigger_lost'):.1f}%)")

    base = pooled(small_x, "trigger_lost_new_song", "trigger_lost")
    icc_measured = icc_anova(small_x, "trigger_lost_new_song", "trigger_lost")
    icc = max(icc_measured, ICC_FLOOR)
    triggers = [min(r["trigger_lost"] / r["eligible_months"], CAP_PER_MONTH) * ENROL_MONTHS for r in small]
    m_bar, cv = mean(triggers), pstdev(triggers) / mean(triggers)
    deff = 1 + ((cv ** 2 + 1) * m_bar - 1) * icc          # design effect for unequal cluster sizes
    med_triggers = median(triggers)

    print(f"\nWHAT A FIX COULD BE WORTH (baseline {100 * base:.1f}%, per 1 million listeners like the median one, per month)")
    print(f"  Funnel: {med_triggers:.1f} triggers a month (cap {CAP_PER_MONTH}) x share heard x baseline x relative lift")
    for case in ("low", "high"):
        extra = 1_000_000 * med_triggers * EXPOSURE[case] * base * REL_LIFT[case]
        print(f"  {case:4}: {EXPOSURE[case]:.0%} heard, +{REL_LIFT[case]:.0%} relative lift -> "
              f"{extra:,.0f} more listener-artist connections that reach a second song")

    print(f"\nA/B TEST SIZE (intention-to-treat: every triggered artist counts, heard or not)")
    print(f"  ICC measured {icc_measured:.3f}, planned with {icc:.2f}; triggers per listener: mean {m_bar:.1f}, "
          f"CV {cv:.1f}; design effect {deff:.2f}")
    for case in ("low", "high"):
        p2 = base * (1 + EXPOSURE[case] * REL_LIFT[case])        # the lift is diluted by who never hears it
        n = n_per_arm(base, p2)
        print(f"  {case:4}: {100 * base:.2f}% -> {100 * p2:.2f}%: {n:,} re-introductions per arm, "
              f"about {ceil(n * deff / m_bar):,} listeners per arm")
    print("\n  Randomise by listener; log a 'would have triggered' flag in control too, so the triggered")
    print("  groups can be compared directly; analyse with listener-clustered standard errors.")
    print("  What limits the test is TIME: the primary metric needs 90 days after each re-introduction.")


if __name__ == "__main__":
    main()
