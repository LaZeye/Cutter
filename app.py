"""Cutter — weigh-in tracking, camp analytics and trend projection."""

from datetime import date

from flask import Flask, jsonify, render_template, request

from modules import analytics, db

app = Flask(__name__)
db.init_db()


def parse_iso(value, label):
    """Returns (date, error_response). Blank values are an error."""
    value = (value or "").strip()
    if not value:
        return None, (jsonify({"error": f"{label} is required."}), 400)
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, (jsonify({"error": f"{label} must look like 2026-09-08."}), 400)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    """Everything the dashboard needs, in one round trip."""
    settings = db.get_settings()

    try:
        alpha = float(request.args.get("alpha", settings.get("alpha", 0.10)))
    except (TypeError, ValueError):
        alpha = 0.10
    alpha = min(max(alpha, 0.01), 0.9)

    range_key = request.args.get("range", "3m")
    if range_key not in analytics.RANGES:
        range_key = "3m"

    entries = db.list_entries()

    # Smoothing runs across the whole history, then views slice it. Smoothing
    # per-window instead would restart the filter at each edge and show a
    # different trend for the same day at every zoom level.
    trend = analytics.smooth(entries, alpha)

    camps = db.list_camps()
    active = db.active_camp()

    window = analytics.range_window(range_key, entries)
    overall_entries = analytics.slice_by_date(entries, window["start"], window["end"])
    overall_trend = analytics.slice_by_date(trend, window["start"], window["end"])

    return jsonify({
        "entries": entries,
        "settings": settings,
        "alpha": alpha,
        "today": date.today().isoformat(),
        "tolerance": analytics.PACE_TOLERANCE,
        "active_camp": analytics.camp_detail(entries, active, alpha),
        "camps": [analytics.camp_summary(entries, c, alpha) for c in camps],
        "overall": {
            "range": range_key,
            "window": window,
            "entries": overall_entries,
            "trend": overall_trend,
            "weekly_averages": analytics.weekly_averages(overall_entries),
            "stats": analytics.overall_stats(entries, trend),
        },
    })


# --- weigh-ins -------------------------------------------------------------

@app.route("/api/entries", methods=["POST"])
def api_add_entry():
    payload = request.get_json(silent=True) or {}

    entry_date, err = parse_iso(payload.get("date"), "Date")
    if err:
        return err

    try:
        weight = round(float(payload.get("weight")), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Enter a weight as a number."}), 400

    if not 40 <= weight <= 700:
        return jsonify({"error": "That weight is outside the range this tracks."}), 400

    note = (payload.get("note") or "").strip() or None
    db.upsert_entry(entry_date.isoformat(), weight, note)
    return jsonify({"ok": True, "date": entry_date.isoformat(), "weight": weight})


@app.route("/api/entries/<entry_date>", methods=["DELETE"])
def api_delete_entry(entry_date):
    if db.delete_entry(entry_date):
        return jsonify({"ok": True})
    return jsonify({"error": "No weigh-in saved for that date."}), 404


# --- camps -----------------------------------------------------------------

def validate_camp(payload):
    """Shared checks for creating and editing a camp."""
    name = (payload.get("name") or "").strip()
    if not name:
        return None, (jsonify({"error": "Give the camp a name."}), 400)

    start, err = parse_iso(payload.get("start_date"), "Camp start")
    if err:
        return None, err

    fight, err = parse_iso(payload.get("fight_date"), "Fight date")
    if err:
        return None, err

    if fight <= start:
        return None, (jsonify({"error": "Fight date must fall after camp start."}), 400)

    try:
        target = round(float(payload.get("target_weight")), 2)
    except (TypeError, ValueError):
        return None, (jsonify({"error": "Target weight must be a number."}), 400)

    if not 40 <= target <= 700:
        return None, (jsonify({"error": "That target is outside the range this tracks."}), 400)

    return {
        "name": name[:80],
        "start_date": start.isoformat(),
        "fight_date": fight.isoformat(),
        "target_weight": target,
    }, None


@app.route("/api/camps", methods=["POST"])
def api_create_camp():
    payload = request.get_json(silent=True) or {}

    if db.active_camp():
        return jsonify({"error": "A camp is already running. End it before starting another."}), 409

    fields, err = validate_camp(payload)
    if err:
        return err

    camp_id = db.create_camp(**fields)
    return jsonify({"ok": True, "id": camp_id})


@app.route("/api/camps/<int:camp_id>", methods=["PUT"])
def api_update_camp(camp_id):
    payload = request.get_json(silent=True) or {}

    if not db.get_camp(camp_id):
        return jsonify({"error": "That camp no longer exists."}), 404

    fields, err = validate_camp(payload)
    if err:
        return err

    db.update_camp(camp_id, **fields)
    return jsonify({"ok": True})


@app.route("/api/camps/<int:camp_id>/end", methods=["POST"])
def api_end_camp(camp_id):
    payload = request.get_json(silent=True) or {}

    camp = db.get_camp(camp_id)
    if not camp:
        return jsonify({"error": "That camp no longer exists."}), 404
    if camp["ended_on"]:
        return jsonify({"error": "That camp has already ended."}), 409

    ended_on, err = parse_iso(payload.get("ended_on"), "End date")
    if err:
        return err

    if ended_on.isoformat() < camp["start_date"]:
        return jsonify({"error": "A camp cannot end before it started."}), 400

    db.end_camp(camp_id, ended_on.isoformat())
    return jsonify({"ok": True})


@app.route("/api/camps/<int:camp_id>/reopen", methods=["POST"])
def api_reopen_camp(camp_id):
    if not db.get_camp(camp_id):
        return jsonify({"error": "That camp no longer exists."}), 404
    if db.active_camp():
        return jsonify({"error": "End the running camp first."}), 409

    db.reopen_camp(camp_id)
    return jsonify({"ok": True})


@app.route("/api/camps/<int:camp_id>", methods=["GET"])
def api_camp_detail(camp_id):
    camp = db.get_camp(camp_id)
    if not camp:
        return jsonify({"error": "That camp no longer exists."}), 404

    settings = db.get_settings()
    try:
        alpha = float(request.args.get("alpha", settings.get("alpha", 0.10)))
    except (TypeError, ValueError):
        alpha = 0.10

    entries = db.list_entries()
    alpha = min(max(alpha, 0.01), 0.9)

    return jsonify(analytics.camp_detail(entries, camp, alpha))


@app.route("/api/camps/<int:camp_id>", methods=["DELETE"])
def api_delete_camp(camp_id):
    if db.delete_camp(camp_id):
        return jsonify({"ok": True})
    return jsonify({"error": "That camp no longer exists."}), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)