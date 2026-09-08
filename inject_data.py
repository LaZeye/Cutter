"""Seed Cutter with fifteen months of weigh-ins across several camps.

One-off developer utility. Builds a fighter's history from June 2025 to
September 2026: 225 lb down to 178, with three six-week camps at 205, 190 and
182, and the weight rebound that follows each one.

    python seed_data.py --clear
    python seed_data.py --clear --seed 42      # reproducible
    python seed_data.py --clear --no-active    # no camp currently running

Weigh-ins land in the general log regardless of whether a camp was running.
Camps are stored as named date ranges, so camp views are derived by filtering
that one log rather than keeping a second copy of the same numbers.
"""

import argparse
import random
import sys
from datetime import date, timedelta

from modules import db

# Each leg of the fifteen months: dates, the weight at each end, and whether
# it is a camp (named, with a target) or ordinary living between camps.
#
# kind: 'camp' shapes the loss like a real cut — slow first week, hardest in
# the middle, sharpening at the end. 'drift' and 'rebound' move linearly with
# looser logging discipline.
LEGS = [
    ("drift",   "2025-06-01", "2025-07-20", 225.0, 218.0, None),
    ("camp",    "2025-07-21", "2025-09-01", 218.0, 204.0, {
        "name": "NAGA Houston", "target": 205.0}),
    ("rebound", "2025-09-02", "2025-10-19", 204.0, 214.0, None),
    ("drift",   "2025-10-20", "2026-01-04", 214.0, 202.0, None),
    ("camp",    "2026-01-05", "2026-02-16", 202.0, 189.0, {
        "name": "Fury FC 88", "target": 190.0}),
    ("rebound", "2026-02-17", "2026-03-29", 189.0, 199.0, None),
    ("drift",   "2026-03-30", "2026-05-03", 199.0, 194.0, None),
    ("camp",    "2026-05-04", "2026-06-15", 194.0, 181.5, {
        "name": "Legacy FC Dallas", "target": 182.0}),
    ("rebound", "2026-06-16", "2026-07-19", 181.5, 189.0, None),
    ("drift",   "2026-07-20", "2026-09-08", 189.0, 178.0, None),
]

# A camp still running as of the last weigh-in, so both dashboard views have
# something to show. Skip it with --no-active.
ACTIVE_CAMP = {
    "name": "Grappling Industries Houston",
    "start_date": "2026-08-04",
    "fight_date": "2026-10-10",
    "target_weight": 170.0,
}

# Shape of a camp's loss across its length: fraction of the way through
# mapped to a relative rate. Normalised later so the leg lands where it should.
CAMP_SHAPE = [(0.00, 0.65), (0.20, 1.15), (0.55, 0.95), (0.80, 1.40)]

NOTES = [
    (0.030, "Travel — ate out all weekend"),
    (0.030, "Slept badly"),
    (0.025, "Hard sparring session"),
    (0.020, "Rest day"),
    (0.020, "Salty dinner"),
    (0.020, "Long run, felt light"),
    (0.015, "Sick, appetite off"),
]


def camp_rate(progress):
    rate = CAMP_SHAPE[0][1]
    for at, value in CAMP_SHAPE:
        if progress >= at:
            rate = value
    return rate


def leg_schedule(kind, days, change, rng):
    """Per-day weight movement for one leg, summing exactly to `change`.

    Plateaus have to be decided before the normalising, not after: damping a
    day's movement once the scale factor is fixed makes the leg undershoot.
    """
    shape = []
    plateau = 0

    for i in range(days):
        progress = i / days if days else 0
        rate = camp_rate(progress) if kind == "camp" else 1.0

        if plateau > 0:
            rate *= 0.15
            plateau -= 1
        elif kind != "rebound" and rng.random() < 0.025:
            plateau = rng.randint(4, 9)

        shape.append(rate)

    total = sum(shape)
    scale = change / total if total else 0.0
    return [s * scale for s in shape]


def generate(rng):
    """Build (date, weight, note) tuples across every leg, oldest first."""
    entries = []
    bump_days = 0
    bump_size = 0.0

    for kind, start_iso, end_iso, start_w, end_w, _camp in LEGS:
        start = date.fromisoformat(start_iso)
        end = date.fromisoformat(end_iso)
        days = (end - start).days + 1

        schedule = leg_schedule(kind, days, start_w - end_w, rng)
        weight = start_w

        # Logging discipline is much better inside a camp.
        skip_weekday = 0.06 if kind == "camp" else 0.20
        skip_weekend = 0.16 if kind == "camp" else 0.38

        for i in range(days):
            day = start + timedelta(days=i)
            weight -= schedule[i]

            # Transient water weight from travel or a heavy weekend.
            if bump_days > 0:
                bump_days -= 1
            elif rng.random() < (0.030 if kind == "camp" else 0.050):
                bump_days = rng.randint(2, 5)
                bump_size = rng.uniform(1.5, 3.6)

            bump = bump_size * (bump_days / 5.0) if bump_days > 0 else 0.0

            # Weekends read heavier: more sodium, more carbs, later meals.
            weekend = 0.9 if day.weekday() >= 5 else 0.0
            noise = rng.gauss(0, 0.7)

            reading = round(weight + bump + weekend + noise, 1)

            skip = skip_weekend if day.weekday() >= 5 else skip_weekday
            if rng.random() < skip:
                continue

            note = None
            for chance, text in NOTES:
                if rng.random() < chance:
                    note = text
                    break

            entries.append((day.isoformat(), reading, note))

    return entries


def camp_rows():
    """Completed camps, taken straight from the leg definitions."""
    rows = []
    for kind, start_iso, end_iso, _sw, _ew, camp in LEGS:
        if kind != "camp":
            continue
        rows.append({
            "name": camp["name"],
            "start_date": start_iso,
            "fight_date": end_iso,
            "target_weight": camp["target"],
            "ended_on": end_iso,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Seed Cutter with sample history.")
    parser.add_argument("--clear", action="store_true",
                        help="delete existing weigh-ins and camps first")
    parser.add_argument("--no-active", action="store_true",
                        help="don't leave a camp running")
    parser.add_argument("--seed", type=int, help="random seed for reproducible data")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    db.init_db()

    if args.clear:
        with db.get_connection() as conn:
            gone_entries = conn.execute("DELETE FROM entries").rowcount
            gone_camps = conn.execute("DELETE FROM camps").rowcount
        print(f"Cleared {gone_entries} weigh-ins and {gone_camps} camps.")

    entries = generate(rng)
    if not entries:
        sys.exit("Generated no entries.")

    with db.get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO entries (date, weight, note) VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                weight = excluded.weight,
                note   = excluded.note
            """,
            entries,
        )

        for row in camp_rows():
            conn.execute(
                """
                INSERT INTO camps (name, start_date, fight_date, target_weight, ended_on)
                VALUES (:name, :start_date, :fight_date, :target_weight, :ended_on)
                """,
                row,
            )

        if not args.no_active:
            conn.execute(
                """
                INSERT INTO camps (name, start_date, fight_date, target_weight)
                VALUES (:name, :start_date, :fight_date, :target_weight)
                """,
                ACTIVE_CAMP,
            )

    span_days = (date.fromisoformat(entries[-1][0]) - date.fromisoformat(entries[0][0])).days + 1

    print(f"Inserted {len(entries)} weigh-ins across {span_days} days "
          f"({len(entries) / span_days:.0%} of days logged).")
    print(f"  {entries[0][0]} at {entries[0][1]} lb  →  {entries[-1][0]} at {entries[-1][1]} lb")
    print()
    print("Camps:")
    for row in camp_rows():
        print(f"  {row['name']:<28} {row['start_date']} → {row['ended_on']}  target {row['target_weight']:.0f} lb")
    if not args.no_active:
        print(f"  {ACTIVE_CAMP['name']:<28} {ACTIVE_CAMP['start_date']} → "
              f"{ACTIVE_CAMP['fight_date']}  target {ACTIVE_CAMP['target_weight']:.0f} lb  (running)")
    print()
    print(f"Database: {db.DB_PATH}")


if __name__ == "__main__":
    main()