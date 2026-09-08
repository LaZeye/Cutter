"""Trend smoothing and projection maths for Cutter.

Raw scale readings swing several pounds a day on water and gut content alone.
Everything here works off an exponentially weighted moving average instead,
which is the same approach Happy Scale and The Hacker's Diet use.
"""

from datetime import date, timedelta


def _d(iso):
    return date.fromisoformat(iso)


def smooth(entries, alpha=0.10):
    """Gap-aware exponential moving average over weigh-ins.

    A plain EMA assumes evenly spaced samples. Missed days would make it lag,
    so the smoothing factor is compounded across the actual day gap:
    a_effective = 1 - (1 - alpha) ** gap_days.

    entries: list of dicts with 'date' (ISO) and 'weight', oldest first.
    Returns: list of dicts with 'date' and 'trend'.
    """
    if not entries:
        return []

    out = []
    ema = entries[0]["weight"]
    prev = None

    for e in entries:
        current = _d(e["date"])
        if prev is not None:
            gap = max((current - prev).days, 1)
            a = 1 - (1 - alpha) ** gap
            ema = ema + a * (e["weight"] - ema)
        out.append({"date": e["date"], "trend": round(ema, 2)})
        prev = current

    return out


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
    """Extend the recent trend forward to the fight date.

    Returns a two-point series (today and fight day) plus the projected weight.
    """
    if not trend or not fight_date:
        return {"series": [], "projected_weight": None}

    slope = recent_slope(trend, window_days)
    if slope is None:
        return {"series": [], "projected_weight": None}

    last_date = _d(trend[-1]["date"])
    target_date = _d(fight_date)
    days_ahead = (target_date - last_date).days

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


def weekly_rates(trend):
    """Change in the smoothed weight for each calendar week of camp."""
    if len(trend) < 2:
        return []

    buckets = {}
    for t in trend:
        d = _d(t["date"])
        week_start = d - timedelta(days=d.weekday())
        buckets.setdefault(week_start, []).append(t["trend"])

    rates = []
    for week_start in sorted(buckets):
        values = buckets[week_start]
        if len(values) < 2:
            continue
        rates.append({
            "week": week_start.isoformat(),
            "change": round(values[-1] - values[0], 2),
        })

    return rates


def summarise(entries, trend, settings):
    """Headline numbers for the readout panel."""
    stats = {
        "latest_weight": None,
        "latest_date": None,
        "trend_weight": None,
        "seven_day_change": None,
        "total_change": None,
        "daily_rate": None,
        "weekly_rate": None,
        "days_out": None,
        "days_elapsed": None,
        "camp_length": None,
        "to_target": None,
        "projected_weight": None,
        "projected_gap": None,
        "required_weekly_rate": None,
        "entry_count": len(entries),
    }

    if not entries:
        return stats

    stats["latest_weight"] = entries[-1]["weight"]
    stats["latest_date"] = entries[-1]["date"]
    stats["trend_weight"] = trend[-1]["trend"]
    stats["total_change"] = round(trend[-1]["trend"] - trend[0]["trend"], 2)

    last_date = _d(trend[-1]["date"])

    # Trend change over the past week
    week_ago = last_date - timedelta(days=7)
    prior = [t for t in trend if _d(t["date"]) <= week_ago]
    if prior:
        stats["seven_day_change"] = round(trend[-1]["trend"] - prior[-1]["trend"], 2)

    slope = recent_slope(trend)
    if slope is not None:
        stats["daily_rate"] = round(slope, 3)
        stats["weekly_rate"] = round(slope * 7, 2)

    try:
        target_weight = float(settings.get("target_weight") or 0)
    except ValueError:
        target_weight = 0

    if target_weight:
        stats["to_target"] = round(trend[-1]["trend"] - target_weight, 2)

    fight_date = settings.get("fight_date")
    if fight_date:
        today = date.today()
        fight = _d(fight_date)
        stats["days_out"] = (fight - today).days

        camp_start = settings.get("camp_start") or entries[0]["date"]
        start = _d(camp_start)
        stats["camp_length"] = max((fight - start).days, 0)
        stats["days_elapsed"] = max(min((today - start).days, stats["camp_length"]), 0)

        projection = project(trend, fight_date)
        stats["projected_weight"] = projection["projected_weight"]

        if projection["projected_weight"] is not None and target_weight:
            stats["projected_gap"] = round(
                projection["projected_weight"] - target_weight, 2
            )

        if target_weight and stats["days_out"] and stats["days_out"] > 0:
            remaining = trend[-1]["trend"] - target_weight
            stats["required_weekly_rate"] = round(
                remaining / stats["days_out"] * 7, 2
            )

    return stats