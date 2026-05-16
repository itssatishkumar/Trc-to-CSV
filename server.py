from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

clients = {}
TIMEOUT = 60  # seconds


@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    device = data.get("device", "unknown")
    name = data.get("name", device)

    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    if device not in clients:
        clients[device] = {
            "name": name,
            "login_time": now,
            "last_seen": now,
            "history": []
        }
    else:
        clients[device]["last_seen"] = now
        clients[device].pop("saved", None)

    return jsonify({"ok": True})


@app.route("/clients", methods=["GET"])
def get_clients():
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    result = {}

    for device, data in clients.items():
        last_seen = data["last_seen"]
        login_time = data["login_time"]

        diff = (now - last_seen).total_seconds()

        if diff <= TIMEOUT:
            active_minutes = int((now - login_time).total_seconds() // 60)
            status_text = f"online since {login_time.strftime('%H:%M:%S')} ({active_minutes} min)"
        else:
            if "saved" not in data:
                data["history"].append({
                    "login": login_time.strftime('%H:%M:%S'),
                    "logout": last_seen.strftime('%H:%M:%S')
                })
                data["saved"] = True

            status_text = f"last active at {last_seen.strftime('%H:%M:%S')}"

        result[device] = {
            "name": data["name"],
            "status": status_text,
            "history": data["history"]
        }

    return jsonify(result)


@app.route("/")
def home():
    return "Server running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
