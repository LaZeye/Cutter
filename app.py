from datetime import date

from flask import Flask, jsonify, render_template, request

from modules import analytics, db

app = Flask(__name__)
db.init_db()


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

    entries = db.list_entries()
    trend = analytics.smooth(entries, alpha)
    projection = analytics.project(trend, settings.get("fight_date"))
    stats = analytics.summarise(entries, trend, settings)

    return jsonify({
        "entries": entries,
        "trend": trend,
        "projection": projection["series"],
        "weekly_rates": analytics.weekly_rates(trend),
        "stats": stats,
        "settings": settings,
        "alpha": alpha,
        "today": date.today().isoformat(),
    })


@app.route("/api/entries", methods=["POST"])
def api_add_entry():
    payload = request.get_json(silent=True) or {}

    entry_date = (payload.get("date") or "").strip()
    raw_weight = payload.get("weight")
    note = (payload.get("note") or "").strip() or None

    if not entry_date:
        return jsonify({"error": "Pick a date for this weigh-in."}), 400

    try:
        date.fromisoformat(entry_date)
    except ValueError:
        return jsonify({"error": "Date must look like 2026-09-08."}), 400

    try:
        weight = round(float(raw_weight), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Enter a weight as a number."}), 400

    if not 40 <= weight <= 700:
        return jsonify({"error": "That weight is outside the range this tracks."}), 400

    db.upsert_entry(entry_date, weight, note)
    return jsonify({"ok": True, "date": entry_date, "weight": weight})


@app.route("/api/entries/<entry_date>", methods=["DELETE"])
def api_delete_entry(entry_date):
    if db.delete_entry(entry_date):
        return jsonify({"ok": True})
    return jsonify({"error": "No weigh-in saved for that date."}), 404


@app.route("/api/settings", methods=["POST"])
def api_settings():
    payload = request.get_json(silent=True) or {}

    for field in ("fight_date", "camp_start"):
        value = (payload.get(field) or "").strip()
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                return jsonify({"error": f"{field} must look like 2026-09-08."}), 400

    if payload.get("target_weight") not in (None, ""):
        try:
            float(payload["target_weight"])
        except (TypeError, ValueError):
            return jsonify({"error": "Target weight must be a number."}), 400

    db.save_settings(payload)
    return jsonify({"ok": True, "settings": db.get_settings()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)