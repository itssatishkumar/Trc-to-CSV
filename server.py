from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)
clients = {}
TIMEOUT = 60

@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    device = data.get("device", "unknown")
    name = data.get("name", device)

    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    clients[device] = {
        "name": name,
        "last_seen": now
    }

    return jsonify({"ok": True})

@app.route("/clients", methods=["GET"])
def get_clients():
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    result = {}

    for device, data in clients.items():
        last_seen = data["last_seen"]
        diff = (now - last_seen).total_seconds()

        if diff <= TIMEOUT:
            status = "online"
        else:
            status = f"last active at {last_seen.strftime('%H:%M:%S')}"

        result[device] = {
            "name": data["name"],
            "status": status
        }

    return jsonify(result)

@app.route("/")
def home():
    return "Server running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
