"""Draws the five case-study charts, straight from the two query results.

    python3 make_charts.py

Reads (public codes, written by pseudonymise.py):
    results/listener_counts.tsv   05_listener_counts.sql   -> charts 1, 2, 3 and 5
    results/liked_but_lost.tsv    06_liked_but_lost.sql    -> chart 4
Writes the PNGs to charts/, prints every number it plotted, and saves them in
charts/chart_data.json so you can check them. Nothing is typed in by hand.
Needs matplotlib (pip3 install matplotlib).
"""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "charts")

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
RAMP = {"Lesser-known": "#104281", "Mid": "#2a78d6", "Big": "#86b6ef"}   # ordinal: darkest = the focus
TIERS = ["Lesser-known", "Mid", "Big"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "text.color": INK,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def frame(ax, title, subtitle):
    fig = ax.figure
    fig.text(0.015, 0.955, title, fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.015, 0.885, subtitle, fontsize=10.5, color=INK2, va="top")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)


def source(fig, text):
    fig.text(0.01, 0.01, text, fontsize=8.5, color=INK2)


def read_rows(path):
    """Rows of a tab- or comma-separated file (mysql client output or a PopSQL CSV export)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        delimiter = "\t" if "\t" in f.readline() else ","
        f.seek(0)
        return list(csv.DictReader(f, delimiter=delimiter))


def per_listener(path):
    """{listener code: {tier: {column: int}}} from results/listener_counts.tsv."""
    out = {}
    if True:
        for r in read_rows(path):
            code = r["listener"].replace("Listener_", "")
            out.setdefault(code, {})[r["size_tier"]] = {k: int(v) for k, v in r.items()
                                                        if k not in ("listener", "size_tier")}
    return out


def dumbbell(rows, title, subtitle, note, xmax, filename):
    """One row per listener: a dot for lesser-known, a dot for big, joined by a line."""
    rows = sorted(rows, key=lambda r: r[2] - r[1])          # by gap, largest at the top after invert
    fig, ax = plt.subplots(figsize=(8, 5.2))
    for i, (code, small, big) in enumerate(rows):
        ax.plot([small, big], [i, i], color=GRID, lw=2.5, zorder=1, solid_capstyle="round")
        ax.scatter([small], [i], s=70, color=RAMP["Lesser-known"], zorder=3,
                   label="Lesser-known" if i == 0 else None)
        ax.scatter([big], [i], s=70, color=RAMP["Big"], edgecolor=INK2, linewidth=0.8, zorder=3,
                   label="Big" if i == 0 else None)
        ax.text(max(small, big) + xmax * 0.015, i, f"{big - small:+.1f} pts", va="center", fontsize=9, color=INK2)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.set_xlim(0, xmax)
    ax.xaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ticks = [t for t in range(0, int(xmax) + 1, 10 if xmax <= 60 else 20)]
    ax.set_xticks(ticks, [f"{t}%" for t in ticks])
    ax.spines["bottom"].set_visible(False)
    ax.legend(frameon=False, loc="lower left", fontsize=10, ncol=2, bbox_to_anchor=(0, 1.0), borderaxespad=0.2)
    frame(ax, title, subtitle)
    source(fig, note)
    fig.tight_layout(rect=(0, 0.04, 1, 0.83))
    fig.savefig(os.path.join(OUT, filename), dpi=200)
    plt.close(fig)


def chart_first_listen(people):
    """Per listener: share of lean-back first listens skipped, lesser-known vs big."""
    rows = [(k, 100 * v["small"]["lb_first_skipped"] / v["small"]["lb_first"],
             100 * v["big"]["lb_first_skipped"] / v["big"]["lb_first"]) for k, v in people.items()]
    dumbbell(rows, "No penalty for being lesser-known on a first listen",
             "Lean-back first listens that were skipped, per listener: the gaps are small and go both ways",
             "10 listeners, Oct 2021 onward. Labels = big minus lesser-known. Skip = under 30s or pressed next.",
             60, "1_first_listen_skip.png")


def chart_stick(people):
    """Per listener: share of lean-back discoveries still played 30-90 days later, lesser-known vs big."""
    rows = [(k, 100 * v["small"]["lb_stuck"] / v["small"]["lb_disc"],
             100 * v["big"]["lb_stuck"] / v["big"]["lb_disc"]) for k, v in people.items()]
    dumbbell(rows, "Lesser-known artists stick less, for all 10 listeners",
             "New artists first heard lean-back: share still played (not skipped) 30-90 days later, per listener",
             "10 listeners, Oct 2021 onward. Labels = big minus lesser-known. Pooled: 12% vs 19%.",
             40, "5_stick_per_listener.png")


def chart_how_found(d):
    """100% stacked horizontal bars: size mix of new artists, by how they were found."""
    fig, ax = plt.subplots(figsize=(8, 3.4))
    rows = [("Played on by itself\n(lean-back)", d["lean_back"]), ("Listener chose\nthem", d["chosen"])]
    for r, (label, mix) in enumerate(rows):
        left = 0
        for tier in TIERS:
            v = mix[tier]
            ax.barh(r, v - 0.4, left=left + 0.2, color=RAMP[tier], height=0.56, zorder=2)   # 0.4 gap
            ink = "#ffffff" if tier != "Big" else INK
            ax.text(left + v / 2, r, f"{tier}\n{v:.0f}%", ha="center", va="center", fontsize=9.5, color=ink)
            left += v
    ax.set_yticks([0, 1], [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    frame(ax, "How new artists were found (pooled across listeners)",
          "Size mix of the new artists each listener discovered, by how they first heard them")
    source(fig, f"{d['listeners']} listeners, Oct 2021 onward. {d['n_lean_back']:,} artists discovered "
                f"lean-back, {d['n_chosen']:,} chosen.")
    fig.tight_layout(rect=(0, 0.06, 1, 0.80))
    fig.savefig(os.path.join(OUT, "2_how_found.png"), dpi=200)
    plt.close(fig)


def chart_second_chance(d):
    """Stacked bars: after a liked first listen, back within 30 days, split by who brought them back."""
    fig, ax = plt.subplots(figsize=(8, 4.6))
    parts = [("Played on by itself (lean-back)", "spotify", BLUE),
             ("Listener clicked to play", "listener", ORANGE),
             ("Other route", "other", AQUA)]
    x = list(range(len(TIERS)))
    bottom = [0.0] * len(TIERS)
    for label, key, color in parts:
        vals = [d[t][key] for t in TIERS]
        ax.bar(x, [max(v - 0.15, 0.05) for v in vals], 0.52, bottom=[b + 0.075 for b in bottom],
               color=color, label=label, zorder=2)
        bottom = [b + v for b, v in zip(bottom, vals)]
    for i, t in enumerate(TIERS):
        s, l, o = d[t]["spotify"], d[t]["listener"], d[t]["other"]
        ax.text(i, bottom[i] + 0.8, f"{bottom[i]:.0f}% came back", ha="center", fontsize=10.5,
                fontweight="bold", color=INK)
        ax.text(i, s / 2, f"{s:.0f}%\nplayed on", ha="center", va="center", fontsize=9.5, color="#ffffff")
        ax.text(i + 0.3, s + (l + o) / 2, f"+{l + o:.1f} pts", ha="left", va="center", fontsize=9.5, color=INK2)
    ax.set_xticks(x, TIERS)
    ax.set_xlim(-0.5, 2.6)
    ax.set_ylim(0, 33)
    ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_yticks([0, 10, 20, 30], ["0%", "10%", "20%", "30%"])
    ax.legend(frameon=False, loc="lower left", fontsize=10, ncol=3, bbox_to_anchor=(0, 1.0), borderaxespad=0.2)
    frame(ax, "After a liked first listen, fewer lesser-known artists come back",
          "Artists first heard lean-back and not skipped: share played again within 30 days, by what started that play")
    source(fig, f"{d['listeners']} listeners, Oct 2021 onward. 'Played on by itself' includes the listener's "
                "own playlists; most are the same song again.")
    fig.tight_layout(rect=(0, 0.04, 1, 0.83))
    fig.savefig(os.path.join(OUT, "3_second_chance.png"), dpi=200)
    plt.close(fig)


def chart_liked_but_lost(d):
    """Grouped bars: share still played 30-90 days later, split by whether the artist came back within 2 weeks."""
    fig, ax = plt.subplots(figsize=(8, 4.6))
    groups = [("Came back within 2 weeks", "back"), ("Didn't come back (\"liked but lost\")", "lost")]
    sizes = [("Lesser-known", RAMP["Lesser-known"]), ("Big", RAMP["Big"])]
    w = 0.34
    for j, (tier, color) in enumerate(sizes):
        off = (j - 0.5) * (w + 0.02)
        vals = [d[tier][key] for _, key in groups]
        bars = ax.bar([i + off for i in range(len(groups))], vals, w, color=color, label=tier, zorder=2)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}%", ha="center", va="bottom",
                    fontsize=10.5, color=INK)
    ax.set_xticks(range(len(groups)), [g for g, _ in groups])
    for i, (_, key) in enumerate(groups):
        share = d["Lesser-known"]["share_" + key]
        ax.text(i, -5.3, f"{share:.0f}% of liked lesser-known first listens", ha="center", fontsize=9, color=INK2)
    ax.set_ylim(0, 30)
    ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_yticks([0, 10, 20, 30], ["0%", "10%", "20%", "30%"])
    ax.legend(frameon=False, loc="lower left", fontsize=10, ncol=2, bbox_to_anchor=(0, 1.0), borderaxespad=0.2)
    frame(ax, "Liked but lost: few lesser-known artists reach a second song",
          "Liked lean-back first listens: share where the listener played a different song by the artist in days 30-90")
    source(fig, f"{d['listeners']} listeners (the largest contributor left out), Oct 2021 onward. 'Came back' = "
                "played again from day 1 to day 14 (Q11b). Correlation, not cause.")
    fig.tight_layout(rect=(0, 0.07, 1, 0.83))
    fig.savefig(os.path.join(OUT, "4_liked_but_lost.png"), dpi=200)
    plt.close(fig)


def how_found_numbers(people):
    """Chart 2: size mix of new artists, lean-back vs chosen (the same as Q4)."""
    def mix(col):
        total = sum(v[t][col] for v in people.values() for t in ("small", "mid", "big"))
        return {label: round(100 * sum(v[t][col] for v in people.values()) / total, 1)
                for label, t in zip(TIERS, ("small", "mid", "big"))}, total
    lean, n_lean = mix("lb_first")
    chosen, n_chosen = mix("chosen_first")
    return {"listeners": len(people), "n_lean_back": n_lean, "n_chosen": n_chosen, "lean_back": lean, "chosen": chosen}


def second_chance_numbers(people):
    """Chart 3: after a liked first listen, back within 30 days, by what started that play (the same as Q5b)."""
    out = {"listeners": len(people)}
    for label, t in zip(TIERS, ("small", "mid", "big")):
        s = lambda col: sum(v[t][col] for v in people.values())
        liked = s("liked")
        out[label] = {"spotify": round(100 * s("liked_back_lean_back") / liked, 1),
                      "listener": round(100 * s("liked_back_clicked") / liked, 1),
                      "other": round(100 * (s("liked_back") - s("liked_back_clicked") - s("liked_back_lean_back")) / liked, 1)}
    return out


def liked_but_lost_numbers(rows):
    """Chart 4: without the biggest contributor, share reaching a different song (Q11b / 06)."""
    small = [r for r in rows if r["size_tier"] == "small"]
    top = max(small, key=lambda r: float(r["lost"]))["listener"]
    keep = [r for r in rows if r["listener"] != top]
    out = {"listeners": len({r["listener"] for r in keep}), "left_out": top}
    for label, t in (("Lesser-known", "small"), ("Big", "big")):
        s = lambda col: sum(float(r[col]) for r in keep if r["size_tier"] == t)
        out[label] = {"back": round(100 * s("back_new_song") / s("back"), 1),
                      "lost": round(100 * s("lost_new_song") / s("lost"), 1),
                      "share_back": round(100 * s("back") / s("liked"), 1),
                      "share_lost": round(100 * s("lost") / s("liked"), 1)}
    return out


def report(people, data):
    """Print what each chart shows, so the numbers can be checked or quoted."""
    rate = lambda t, a, b: 100 * sum(v[t][a] for v in people.values()) / sum(v[t][b] for v in people.values())
    print("1  First-listen skip, pooled: lesser-known {:.1f}%  big {:.1f}%  (per listener: see chart)".format(
        rate("small", "lb_first_skipped", "lb_first"), rate("big", "lb_first_skipped", "lb_first")))
    h = data["how_found"]
    print(f"2  Lean-back new artists: {h['lean_back']}   Chosen: {h['chosen']}")
    for t in TIERS:
        c = data["second_chance"][t]
        print(f"3  {t:12} back within 30 days {c['spotify'] + c['listener'] + c['other']:.1f}% "
              f"(played on {c['spotify']}%, clicked {c['listener']}%, other {c['other']}%)")
    l = data["liked_but_lost"]
    print(f"4  Liked but lost (without {l['left_out']}): different song lesser-known {l['Lesser-known']['lost']}% "
          f"vs big {l['Big']['lost']}%; came back: {l['Lesser-known']['back']}% vs {l['Big']['back']}%")
    print("5  Still played 30-90 days, pooled: lesser-known {:.1f}%  big {:.1f}%".format(
        rate("small", "lb_stuck", "lb_disc"), rate("big", "lb_stuck", "lb_disc")))


if __name__ == "__main__":
    people = per_listener(os.path.join(HERE, "results", "listener_counts.tsv"))
    data = {"how_found": how_found_numbers(people), "second_chance": second_chance_numbers(people),
            "liked_but_lost": liked_but_lost_numbers(read_rows(os.path.join(HERE, "results", "liked_but_lost.tsv")))}
    with open(os.path.join(OUT, "chart_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    chart_first_listen(people)
    chart_how_found(data["how_found"])
    chart_second_chance(data["second_chance"])
    chart_liked_but_lost(data["liked_but_lost"])
    chart_stick(people)
    report(people, data)
    print("\nWrote charts/1_first_listen_skip.png to 5_stick_per_listener.png, and charts/chart_data.json")
