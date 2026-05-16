from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json

app = Flask(__name__)

DATA_FILE = "clients.json"
TIMEOUT = 60  # seconds
THIRTY_DAYS = 30 * 24 * 60 * 60  # seconds

# -------- Load existing data --------
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        raw = json.load(f)
        clients = {
            k: {
                "name": v["name"],
                "login_time": datetime.fromisoformat(v["login_time"]),
                "last_seen": datetime.fromisoformat(v["last_seen"]),
            }
            for k, v in raw.items()
        }
else:
    clients = {}


def save_clients():
    with open(DATA_FILE, "w") as f:
        json.dump({
            k: {
                "name": v["name"],
                "login_time": v["login_time"].isoformat(),
                "last_seen": v["last_seen"].isoformat()
            } for k, v in clients.items()
        }, f)


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
            "last_seen": now
        }
    else:
        clients[device]["last_seen"] = now

    save_clients()
    return jsonify({"ok": True})


@app.route("/clients", methods=["GET"])
def get_clients():
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    result = {}

    # -------- cleanup older than 30 days --------
    to_delete = []
    for device, data in clients.items():
        if (now - data["last_seen"]).total_seconds() > THIRTY_DAYS:
            to_delete.append(device)

    for device in to_delete:
        del clients[device]

    if to_delete:
        save_clients()

    # -------- build response --------
    for device, data in clients.items():
        last_seen = data["last_seen"]
        login_time = data["login_time"]

        diff = (now - last_seen).total_seconds()

        if diff <= TIMEOUT:
            active_minutes = int((now - login_time).total_seconds() // 60)
            status_text = f"online since {login_time.strftime('%H:%M:%S')} ({active_minutes} min)"
        else:
            status_text = f"last active at {last_seen.strftime('%H:%M:%S')}"

        result[device] = {
            "name": data["name"],
            "status": status_text
        }

    return jsonify(result)


@app.route("/")
def home():
    return "Server running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
