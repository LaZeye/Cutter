"""Trend smoothing, camp analytics and projection maths for Cutter.

Raw scale readings swing several pounds a day on water and gut content alone,
so everything here works off a smoothed series rather than the raw numbers.
"""

from datetime import date, timedelta

# How far a weekly average may sit from the plan line and still count as
# on track, in whatever unit weights are recorded in.
PACE_TOLERANCE = 1.0

# Readings averaged to prime each smoothing pass, which keeps the first and
# last points from being yanked around by a single noisy weigh-in.
WARMUP = 5

# Windows offered by the all-time view.
RANGES = {
    "2w": 14,
    "1m": 30,
    "3m": 91,
    "6m": 182,
    "1y": 365,
    "all": None,
}


def _d(iso):
    return date.fromisoformat(iso)


# --- smoothing -------------------------------------------------------------

def _ema_pass(dates, weights, alpha, warmup=WARMUP):
    """One gap-aware EMA sweep in the order given.

    A plain EMA assumes evenly spaced samples. Missed days would make it lag
    further, so the factor is compounded across the real day gap:
    a_effective = 1 - (1 - alpha) ** gap_days.
    """
    n = len(weights)
    if n == 0:
        return []

    k = min(warmup, n)
    ema = sum(weights[:k]) / k

    out = []
    prev = None

    for d, w in zip(dates, weights):
        if prev is not None:
            gap = max(abs((d - prev).days), 1)
            a = 1 - (1 - alpha) ** gap
            ema = ema + a * (w - ema)
        out.append(ema)
        prev = d

    return out


def smooth(entries, alpha=0.10, centered=True):
    """Smoothed weight series.

    A forward-only EMA is a lagging filter: every value it reports is a
    weighted average of older readings, so during a cut the line rides above
    the data by roughly (1 - alpha) / alpha days' worth of loss. Running the
    filter both ways and averaging cancels that lag and puts the line through
    the middle of the points.

    The result is non-causal — each value is informed by later readings too.
    That is the right trade for reviewing a trend, and it makes the final
    value a better estimate of current weight than a lagging one.
    """
    if not entries:
        return []

    dates = [_d(e["date"]) for e in entries]
    weights = [e["weight"] for e in entries]

    forward = _ema_pass(dates, weights, alpha)

    if not centered:
        return [
            {"date": e["date"], "trend": round(v, 2)}
            for e, v in zip(entries, forward)
        ]

    backward = _ema_pass(dates[::-1], weights[::-1], alpha)[::-1]

    return [
        {"date": e["date"], "trend": round((f + b) / 2, 2)}
        for e, f, b in zip(entries, forward, backward)
    ]


# --- slicing ---------------------------------------------------------------

def slice_by_date(rows, start=None, end=None, key="date"):
    """Rows falling inside an inclusive date window."""
    out = rows
    if start:
        out = [r for r in out if r[key] >= start]
    if end:
        out = [r for r in out if r[key] <= end]
    return list(out)


def range_window(range_key, entries):
    """Start and end dates for one of the all-time view's zoom levels."""
    if not entries:
        return {"start": None, "end": None}

    end = entries[-1]["date"]
    days = RANGES.get(range_key, None)

    if days is None:
        return {"start": entries[0]["date"], "end": end}

    start = (_d(end) - timedelta(days=days)).isoformat()
    return {"start": max(start, entries[0]["date"]), "end": end}


# --- fitting and projection ------------------------------------------------

def linear_fit(points):
    """Ordinary least squares. points: list of (x, y). Returns (slope, intercept)."""
    n = len(points)
    if n < 2:
        return None

    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)

    denom = n * sxx - sx * sx
    if denom == 0:
        return None

    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def recent_slope(trend, window_days=14):
    """Pounds per day through the recent smoothed values. Negative means losing."""
    if len(trend) < 2:
        return None

    last = _d(trend[-1]["date"])
    cutoff = last - timedelta(days=window_days)
    window = [t for t in trend if _d(t["date"]) >= cutoff]

    if len(window) < 2:
        window = trend[-2:]

    origin = _d(window[0]["date"])
    points = [((_d(t["date"]) - origin).days, t["trend"]) for t in window]

    fit = linear_fit(points)
    return fit[0] if fit else None


def project(trend, fight_date, window_days=14):
    """Extend the recent trend forward to the fight date."""
    if not trend or not fight_date:
        return {"series": [], "projected_weight": None}

    slope = recent_slope(trend, window_days)
    if slope is None:
        return {"series": [], "projected_weight": None}

    last_date = _d(trend[-1]["date"])
    days_ahead = (_d(fight_date) - last_date).days

    if days_ahead <= 0:
        return {"series": [], "projected_weight": None}

    start = trend[-1]["trend"]
    end = round(start + slope * days_ahead, 2)

    return {
        "series": [
            {"date": trend[-1]["date"], "value": start},
            {"date": fight_date, "value": end},
        ],
        "projected_weight": end,
    }


# --- plan line -------------------------------------------------------------

def plan_line(camp_trend, camp):
    """Straight line from camp-start weight to target weight on fight day."""
    empty = {"series": [], "weight_today": None, "start_weight": None}

    if not camp or not camp_trend:
        return empty

    start = _d(camp["start_date"])
    fight = _d(camp["fight_date"])
    span = (fight - start).days

    if span <= 0:
        return empty

    target = float(camp["target_weight"])
    start_weight = camp_trend[0]["trend"]

    series = [
        {"date": camp["start_date"], "value": round(start_weight, 2)},
        {"date": camp["fight_date"], "value": round(target, 2)},
    ]

    # For a finished camp the meaningful "now" is the last day of the camp.
    reference = camp.get("ended_on") or date.today().isoformat()

    return {
        "series": series,
        "weight_today": plan_value_on(series, reference),
        "start_weight": round(start_weight, 2),
    }


def plan_value_on(series, iso):
    """Where the plan line sits on a given date, clamped to the camp window."""
    if not series or len(series) < 2:
        return None

    start, end = _d(series[0]["date"]), _d(series[1]["date"])
    span = (end - start).days
    if span <= 0:
        return None

    fraction = min(max((_d(iso) - start).days / span, 0.0), 1.0)
    v0, v1 = series[0]["value"], series[1]["value"]
    return round(v0 + (v1 - v0) * fraction, 2)


def classify(delta, tolerance=PACE_TOLERANCE):
    """Ahead, on track, or behind, given a weight minus its plan value."""
    if delta is None:
        return None
    if abs(delta) <= tolerance:
        return "on_track"
    return "ahead" if delta < 0 else "behind"


# --- weekly aggregation ----------------------------------------------------

def weekly_averages(entries, plan_series=None):
    """Mean scale weight for each calendar week, judged against the plan.

    Averaging a week's readings cancels most of the day-to-day water noise
    without the lag a moving average carries, which makes these the honest
    points to grade pace on. Each point sits at the mean date of that week's
    weigh-ins so it lands where the data actually is.
    """
    if not entries:
        return []

    buckets = {}
    for e in entries:
        d = _d(e["date"])
        week_start = d - timedelta(days=d.weekday())
        buckets.setdefault(week_start, []).append((d, e["weight"]))

    out = []
    for week_start in sorted(buckets):
        rows = buckets[week_start]
        average = sum(w for _, w in rows) / len(rows)
        mid_ordinal = round(sum(d.toordinal() for d, _ in rows) / len(rows))
        mid_date = date.fromordinal(mid_ordinal).isoformat()

        expected = plan_value_on(plan_series, mid_date) if plan_series else None
        delta = round(average - expected, 2) if expected is not None else None

        out.append({
            "date": mid_date,
            "week": week_start.isoformat(),
            "average": round(average, 2),
            "count": len(rows),
            "expected": expected,
            "delta": delta,
            "status": classify(delta),
        })

    return out


def pace_status(weekly, min_count=3):
    """Overall pace, from the most recent week with enough weigh-ins.

    A week with one or two readings can swing several pounds on water alone,
    so those are skipped when a fuller week is available.
    """
    blank = {"status": None, "delta": None, "average": None, "expected": None, "week": None}

    graded = [w for w in weekly if w["delta"] is not None]
    if not graded:
        return blank

    solid = [w for w in graded if w["count"] >= min_count]
    chosen = solid[-1] if solid else graded[-1]

    return {
        "status": chosen["status"],
        "delta": chosen["delta"],
        "average": chosen["average"],
        "expected": chosen["expected"],
        "week": chosen["week"],
    }


# --- camp analytics --------------------------------------------------------

def camp_window(camp):
    """The date span a camp's chart covers."""
    end = camp.get("ended_on") or camp["fight_date"]
    # A camp closed early still shows the full plan through fight day.
    if end < camp["fight_date"] and camp.get("ended_on"):
        end = camp["fight_date"]
    return {"start": camp["start_date"], "end": end}


def camp_detail(entries, camp, alpha=0.10):
    """Everything one camp's view needs: trend, plan, pace and headline stats.

    The trend here is smoothed over the camp's own weigh-ins rather than
    sliced out of the full history. Centered smoothing looks both ways, so a
    globally smoothed series lets the rebound that follows a fight bleed
    backwards into fight week — enough to report a made cut as a missed one.
    """
    if not camp:
        return None

    window = camp_window(camp)
    is_active = camp.get("ended_on") is None
    last_day = camp.get("ended_on") or date.today().isoformat()

    camp_entries = slice_by_date(entries, camp["start_date"], last_day)
    camp_trend = smooth(camp_entries, alpha)

    plan = plan_line(camp_trend, camp)
    weekly = weekly_averages(camp_entries, plan["series"])
    pace = pace_status(weekly)

    projection = (project(camp_trend, camp["fight_date"])
                  if is_active else {"series": [], "projected_weight": None})

    target = float(camp["target_weight"])
    stats = {
        "entry_count": len(camp_entries),
        "start_weight": camp_trend[0]["trend"] if camp_trend else None,
        "current_weight": camp_trend[-1]["trend"] if camp_trend else None,
        "latest_scale": camp_entries[-1]["weight"] if camp_entries else None,
        "latest_date": camp_entries[-1]["date"] if camp_entries else None,
        "final_scale": final_scale(camp_entries),
        "target_weight": target,
        "total_change": None,
        "seven_day_change": None,
        "weekly_rate": None,
        "to_target": None,
        "plan_weight_today": plan["weight_today"],
        "projected_weight": projection["projected_weight"],
        "projected_gap": None,
        "required_weekly_rate": None,
        "days_out": None,
        "days_elapsed": None,
        "camp_length": (_d(camp["fight_date"]) - _d(camp["start_date"])).days,
        "pace_status": pace["status"],
        "pace_delta": pace["delta"],
        "pace_average": pace["average"],
        "made_weight": None,
        "is_active": is_active,
    }

    if camp_trend:
        stats["total_change"] = round(camp_trend[-1]["trend"] - camp_trend[0]["trend"], 2)
        stats["to_target"] = round(camp_trend[-1]["trend"] - target, 2)

        week_ago = (_d(camp_trend[-1]["date"]) - timedelta(days=7)).isoformat()
        prior = [t for t in camp_trend if t["date"] <= week_ago]
        if prior:
            stats["seven_day_change"] = round(
                camp_trend[-1]["trend"] - prior[-1]["trend"], 2
            )

        slope = recent_slope(camp_trend)
        if slope is not None:
            stats["weekly_rate"] = round(slope * 7, 2)

    if stats["final_scale"] is not None and not is_active:
        stats["made_weight"] = stats["final_scale"] <= target

    if projection["projected_weight"] is not None:
        stats["projected_gap"] = round(projection["projected_weight"] - target, 2)

    reference = _d(last_day)
    stats["days_out"] = (_d(camp["fight_date"]) - reference).days
    stats["days_elapsed"] = max(
        min((reference - _d(camp["start_date"])).days, stats["camp_length"]), 0
    )

    if is_active and stats["days_out"] > 0 and camp_trend:
        remaining = camp_trend[-1]["trend"] - target
        stats["required_weekly_rate"] = round(remaining / stats["days_out"] * 7, 2)

    return {
        "camp": camp,
        "window": window,
        "entries": camp_entries,
        "trend": camp_trend,
        "plan": plan["series"],
        "projection": projection["series"],
        "weekly_averages": weekly,
        "stats": stats,
    }


def final_scale(camp_entries, window_days=3):
    """Lowest scale reading in the closing days of a camp.

    Making weight is judged on the official weigh-in, not on a smoothed line,
    and a fighter is at their lightest right at the end.
    """
    if not camp_entries:
        return None

    last = _d(camp_entries[-1]["date"])
    cutoff = (last - timedelta(days=window_days)).isoformat()
    tail = [e["weight"] for e in camp_entries if e["date"] >= cutoff]
    return min(tail) if tail else camp_entries[-1]["weight"]


def camp_summary(entries, camp, alpha=0.10):
    """Compact figures for a camp tile."""
    last_day = camp.get("ended_on") or date.today().isoformat()
    camp_entries = slice_by_date(entries, camp["start_date"], last_day)
    camp_trend = smooth(camp_entries, alpha)

    target = float(camp["target_weight"])
    start_weight = camp_trend[0]["trend"] if camp_trend else None
    end_weight = camp_trend[-1]["trend"] if camp_trend else None
    closing = final_scale(camp_entries)

    days = (_d(last_day) - _d(camp["start_date"])).days
    # Negative means weight came off, matching every other rate on the page.
    change = round(end_weight - start_weight, 2) if camp_trend else None

    return {
        "id": camp["id"],
        "name": camp["name"],
        "start_date": camp["start_date"],
        "fight_date": camp["fight_date"],
        "ended_on": camp.get("ended_on"),
        "is_active": camp.get("ended_on") is None,
        "target_weight": target,
        "start_weight": start_weight,
        "end_weight": end_weight,
        "final_scale": closing,
        "change": change,
        "days": days,
        "weeks": round(days / 7, 1) if days else 0,
        "weekly_rate": round(change / days * 7, 2) if change is not None and days else None,
        "to_target": round(closing - target, 2) if closing is not None else None,
        "made_weight": (closing <= target) if closing is not None else None,
        "entry_count": len(camp_entries),
    }


# --- general (non-camp) stats ----------------------------------------------

def overall_stats(entries, trend):
    """Headline numbers for the readout when no camp is running."""
    stats = {
        "entry_count": len(entries),
        "latest_scale": None,
        "latest_date": None,
        "trend_weight": None,
        "seven_day_change": None,
        "thirty_day_change": None,
        "weekly_rate": None,
        "lightest": None,
        "heaviest": None,
    }

    if not entries:
        return stats

    stats["latest_scale"] = entries[-1]["weight"]
    stats["latest_date"] = entries[-1]["date"]
    stats["trend_weight"] = trend[-1]["trend"]
    stats["lightest"] = min(t["trend"] for t in trend)
    stats["heaviest"] = max(t["trend"] for t in trend)

    last = _d(trend[-1]["date"])

    for days, key in ((7, "seven_day_change"), (30, "thirty_day_change")):
        cutoff = (last - timedelta(days=days)).isoformat()
        prior = [t for t in trend if t["date"] <= cutoff]
        if prior:
            stats[key] = round(trend[-1]["trend"] - prior[-1]["trend"], 2)

    slope = recent_slope(trend)
    if slope is not None:
        stats["weekly_rate"] = round(slope * 7, 2)

    return stats