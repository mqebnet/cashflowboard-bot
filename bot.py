import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import json
import os
import time
import hmac
import hashlib
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pymongo import MongoClient

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
MONGO_URL = os.environ.get("MONGO_URL", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "") # Your Railway/Vercel URL

# --- CONSTANTS ---
MINING_INTERVAL = 3600
WITHDRAWAL_THRESHOLD = 10000

# --- DATABASE CONNECTION ---
client = MongoClient(MONGO_URL)
db = client["cashflowboard"]
users_col = db["users"]
tasks_col = db["tasks"]
banned_col = db["banned"]

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# --- SECURITY: HMAC VERIFICATION ---
def verify_telegram_data(init_data_str):
    try:
        parsed = {k: unquote(v) for k, v in [part.split('=') for part in init_data_str.split('&')]}
        hash_received = parsed.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        hash_calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return hash_calculated == hash_received, parsed
    except:
        return False, {}

# --- MINING ENGINE ---
def mining_engine():
    while True:
        try:
            now = datetime.now()
            for user in users_col.find({}):
                last_time = datetime.fromisoformat(user.get("last_mining", now.isoformat()))
                diff = (now - last_time).total_seconds()
                if diff >= MINING_INTERVAL:
                    earned = int(diff // MINING_INTERVAL) * user.get("hpower", 10)
                    users_col.update_one({"id": user["id"]}, {"$inc": {"coins": earned}, "$set": {"last_mining": now.isoformat()}})
        except Exception as e:
            print(f"Mining Error: {e}")
        time.sleep(300)

threading.Thread(target=mining_engine, daemon=True).start()

# --- WEBAPP API SERVER ---
class APIHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        init_data = body.get("init_data", "")
        is_valid, tg_data = verify_telegram_data(init_data)
        
        if not is_valid: return self.send_json({"error": "Unauthorized"}, 401)
        
        uid = json.loads(tg_data.get("user")).get("id")
        path = urlparse(self.path).path

        if path == "/api/task/complete":
            tid = body.get("task_id")
            user = users_col.find_one({"id": uid})
            if tid not in user.get("completed_tasks", []):
                task = tasks_col.find_one({"id": tid})
                users_col.update_one({"id": uid}, {"$push": {"completed_tasks": tid}, "$inc": {"hpower": task["hpower"]}})
                return self.send_json({"success": True})
            return self.send_json({"success": False})

        if path == "/api/withdraw":
            user = users_col.find_one({"id": uid})
            if not user.get("wallet_address"): return self.send_json({"error": "WALLET_MISSING"})
            if user["coins"] < WITHDRAWAL_THRESHOLD: return self.send_json({"error": "INSUFFICIENT_FUNDS"})
            users_col.update_one({"id": uid}, {"$set": {"pending_withdrawal": True}})
            bot.send_message(ADMIN_ID, f"Withdraw Alert: {uid}")
            return self.send_json({"success": True})

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        init_data = query.get("init_data", [""])[0]
        is_valid, tg_data = verify_telegram_data(init_data)
        if not is_valid: return self.send_json({"error": "Unauthorized"}, 401)
        
        uid = json.loads(tg_data.get("user")).get("id")
        user = users_col.find_one({"id": uid})

        if "/api/user" in self.path:
            user.pop("_id")
            self.send_json(user)
        elif "/api/tasks" in self.path:
            tasks = list(tasks_col.find({}, {"_id": 0}))
            for t in tasks: t["done"] = t["id"] in user.get("completed_tasks", [])
            self.send_json(tasks)

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    if not users_col.find_one({"id": uid}):
        users_col.insert_one({"id": uid, "first_name": m.from_user.first_name, "coins": 0, "hpower": 10, "completed_tasks": [], "last_mining": datetime.now().isoformat(), "wallet_address": None})
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("Open CashFlow", web_app=WebAppInfo(url=WEBAPP_URL)))
    bot.send_message(m.chat.id, "Welcome to CashFlowBoard!", reply_markup=kb)

@bot.message_handler(commands=['wallet'])
def set_wallet(m):
    msg = bot.send_message(m.chat.id, "Send your USDT TRC20 address:")
    bot.register_next_step_handler(msg, lambda msg: users_col.update_one({"id": m.from_user.id}, {"$set": {"wallet_address": msg.text.strip()}}) or bot.send_message(m.chat.id, "Wallet Saved!"))

@bot.message_handler(commands=['broadcast'])
def broadcast(m):
    if m.from_user.id != ADMIN_ID: return
    msg = bot.send_message(m.chat.id, "Send message:")
    bot.register_next_step_handler(msg, lambda msg: [bot.send_message(u['id'], msg.text) for u in users_col.find({})])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), APIHandler).serve_forever(), daemon=True).start()
    bot.infinity_polling()
