"""Replaces the listener codes in the per-listener results with random public codes (L01-L10).

The folder codes (Listener_3c, ...) can hint at who a friend is, so nothing public uses them.
The key that links the two lives in results/raw/code_key.csv, which is private (.gitignore)
and is created once, then reused so the public codes stay the same between runs.

    python3 pseudonymise.py

Reads:  results/raw/listener_counts.tsv (or .csv), results/raw/liked_but_lost.tsv (or .csv)
        (private query outputs: from the mysql command, or a PopSQL CSV export)
Writes: results/listener_counts.tsv,     results/liked_but_lost.tsv      (public)

Standard library only.
"""
import csv
import os
import random

RAW, PUBLIC = "results/raw", "results"
KEY = os.path.join(RAW, "code_key.csv")
FILES = ["listener_counts", "liked_but_lost"]      # each read from .tsv or .csv, written as .tsv


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        delimiter = "\t" if "\t" in f.readline() else ","
        f.seek(0)
        return list(csv.DictReader(f, delimiter=delimiter))


def find_raw(name):
    for ext in (".tsv", ".csv"):
        path = os.path.join(RAW, name + ext)
        if os.path.exists(path):
            return path
    return None


def load_key(listeners):
    key = {}
    if os.path.exists(KEY):
        with open(KEY, newline="", encoding="utf-8") as f:
            key = {r["listener"]: r["public_code"] for r in csv.DictReader(f)}
    new = sorted(set(listeners) - set(key))
    if new:
        free = [f"L{i:02d}" for i in range(1, len(key) + len(new) + 1) if f"L{i:02d}" not in key.values()]
        random.SystemRandom().shuffle(free)          # not reproducible on purpose: the key is the secret
        key.update(zip(new, free))
        with open(KEY, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["listener", "public_code"])
            w.writerows(sorted(key.items()))
    return key


def main():
    tables = {name: read(find_raw(name)) for name in FILES if find_raw(name)}
    if not tables:
        raise SystemExit(f"No query results in {RAW}/. Save 05_listener_counts.sql and 06_liked_but_lost.sql output there first.")
    key = load_key(r["listener"] for rows in tables.values() for r in rows)
    for name, rows in tables.items():
        for r in rows:
            r["listener"] = key[r["listener"]]
        rows.sort(key=lambda r: (r["listener"], ["small", "mid", "big"].index(r["size_tier"])))
        with open(os.path.join(PUBLIC, name + ".tsv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {PUBLIC}/{name}.tsv ({len(rows)} rows, public codes)")


if __name__ == "__main__":
    main()
