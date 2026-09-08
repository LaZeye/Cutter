"""Seed Cutter with six months of plausible weigh-in history.

One-off developer utility. Generates a realistic cut from ~200 lb with the
texture real scale data has: weekend water retention, plateau stretches,
travel bumps, missed days and daily noise.

    python seed_data.py                 # seed, keeping existing rows
    python seed_data.py --clear         # wipe entries first
    python seed_data.py --days 120      # different span
    python seed_data.py --seed 42       # reproducible output
"""

import argparse
import random
import sys
from datetime import date, timedelta

from modules import db

# Weekly rate of loss for each phase of camp, as a fraction of the span.
# Slow start, steady middle, sharper as fight week approaches.
PHASES = [
    (0.00, 0.20, 0.55),   # settling in
    (0.20, 0.55, 1.10),   # main block
    (0.55, 0.80, 0.90),   # plateau-prone stretch
    (0.80, 1.00, 1.45),   # sharpening up
]

NOTES = [
    (0.03, "Travel — ate out all weekend"),
    (0.03, "Slept badly"),
    (0.02, "Hard sparring session"),
    (0.02, "Rest day"),
    (0.02, "Salty dinner"),
    (0.02, "Long run, felt light"),
    (0.02, "Sick, appetite off"),
]


def weekly_rate(progress):
    for start, end, rate in PHASES:
        if start <= progress < end:
            return rate
    return PHASES[-1][2]


def generate(days, start_weight, end_weight, rng):
    """Build a list of (date, weight, note) tuples, oldest first."""
    today = date.today()
    first_day = today - timedelta(days=days - 1)

    # Scale the phase rates so the run actually lands near end_weight.
    raw_total = sum(
        weekly_rate(i / days) / 7.0 for i in range(days)
    )
    wanted_total = start_weight - end_weight
    scale = wanted_total / raw_total if raw_total else 1.0

    entries = []
    true_weight = start_weight

    plateau_days = 0
    bump_days = 0
    bump_size = 0.0

    for i in range(days):
        day = first_day + timedelta(days=i)
        progress = i / days

        # --- underlying trend movement ---
        daily_loss = (weekly_rate(progress) / 7.0) * scale

        # Plateaus: a few stretches where the scale simply stops moving.
        if plateau_days > 0:
            daily_loss *= 0.12
            plateau_days -= 1
        elif rng.random() < 0.012:
            plateau_days = rng.randint(5, 11)

        true_weight -= daily_loss

        # --- transient water weight ---
        # Travel or a heavy weekend puts a few pounds on for several days.
        if bump_days > 0:
            bump_days -= 1
        elif rng.random() < 0.020:
            bump_days = rng.randint(2, 5)
            bump_size = rng.uniform(1.6, 3.8)

        bump = bump_size * (bump_days / 5.0) if bump_days > 0 else 0.0

        # Weekends read heavier: more sodium, more carbs, later meals.
        weekend = 0.9 if day.weekday() >= 5 else 0.0

        # Ordinary day-to-day scale noise.
        noise = rng.gauss(0, 0.65)

        reading = round(true_weight + bump + weekend + noise, 1)

        # --- missed weigh-ins ---
        # Skip more often on weekends, and occasionally a whole trip.
        skip_chance = 0.22 if day.weekday() >= 5 else 0.08
        if rng.random() < skip_chance:
            continue

        note = None
        for chance, text in NOTES:
            if rng.random() < chance:
                note = text
                break

        entries.append((day.isoformat(), reading, note))

    return entries


def main():
    parser = argparse.ArgumentParser(description="Seed Cutter with sample history.")
    parser.add_argument("--days", type=int, default=182, help="days of history (default 182)")
    parser.add_argument("--start", type=float, default=200.0, help="starting weight")
    parser.add_argument("--end", type=float, default=172.0, help="approximate weight today")
    parser.add_argument("--clear", action="store_true", help="delete existing entries first")
    parser.add_argument("--seed", type=int, help="random seed for reproducible data")
    args = parser.parse_args()

    if args.end >= args.start:
        sys.exit("End weight must be below start weight.")

    rng = random.Random(args.seed)

    db.init_db()

    if args.clear:
        with db.get_connection() as conn:
            removed = conn.execute("DELETE FROM entries").rowcount
        print(f"Cleared {removed} existing entries.")

    entries = generate(args.days, args.start, args.end, rng)

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

    print(f"Inserted {len(entries)} weigh-ins across {args.days} days "
          f"({len(entries) / args.days:.0%} of days logged).")
    print(f"First: {entries[0][0]} at {entries[0][1]} lb")
    print(f"Last:  {entries[-1][0]} at {entries[-1][1]} lb")
    print(f"Database: {db.DB_PATH}")


if __name__ == "__main__":
    main()