from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

TIMEOUT = 60
THIRTY_DAYS = 30 * 24 * 60 * 60

# -------- Google Sheets setup --------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

creds = Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_CREDS"]),
    scopes=SCOPES
)

client = gspread.authorize(creds)
sheet = client.open_by_url(
    "https://docs.google.com/spreadsheets/d/1nDkL93epR1RQfFvCrzAVeiu5a9TpaU2484sOaVkQAQw/edit#gid=974404348"
).get_worksheet(5)

# -------- Load existing data --------
clients = {}

def load_clients():
    global clients
    clients = {}
    try:
        rows = sheet.get_all_records()
        for row in rows:
            device = row["DEVISE NAME"]
            clients[device] = {
                "name": row["USER INFO"],
                "login_time": datetime.fromisoformat(row["LOGIN"]),
                "last_seen": datetime.fromisoformat(row["LOGOUT"]),
            }
    except:
        clients = {}

load_clients()

# -------- Save (update or append) --------
def save_clients():
    rows = sheet.get_all_records()
    row_map = {row["DEVISE NAME"]: idx + 2 for idx, row in enumerate(rows)}

    for device, v in clients.items():
        row_data = [
            device,
            v["name"],
            v["login_time"].isoformat(),
            v["last_seen"].isoformat()
        ]

        if device in row_map:
            sheet.update(f"A{row_map[device]}:D{row_map[device]}", [row_data])
        else:
            sheet.append_row(row_data)

# -------- Routes --------
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

    to_delete = []
    for device, data in clients.items():
        if (now - data["last_seen"]).total_seconds() > THIRTY_DAYS:
            to_delete.append(device)

    for device in to_delete:
        del clients[device]

    if to_delete:
        save_clients()

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
