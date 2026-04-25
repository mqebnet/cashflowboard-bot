import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import json
import os
import time
import threading
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

# ═══════════════════════════════════════════════════════
#                    CONFIGURATION
# ═══════════════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7454509508:AAGdqEQ3K4B4fS0eByfW9xVfVs6bJ7QgGZ4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7848264205"))
BOT_NAME = "CashFlowBoard"
BOT_USERNAME = "CashFlowBoard_bot"
COMPANY = "Phantom MD Technology"
MAINTENANCE_MODE = False

# WebApp URL — GitHub Pages
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://abrarali97987.github.io/cashflowboard-bot")

# Mining Settings
BASE_HPOWER = 10
MINING_INTERVAL = 3600
COINS_PER_HPOWER = 1
TASK_HPOWER_REWARD = 50
REFER_HPOWER_REWARD = 100
WITHDRAWAL_THRESHOLD = 10000
DAILY_CHECKIN_HPOWER = 15
DAILY_CHECKIN_COINS = 50

# Files
USERS_FILE = "users.json"
CHANNELS_FILE = "channels.json"
TASKS_FILE = "tasks.json"
BANNED_FILE = "banned.json"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
CORS(app) # For WebApp Data Loading

# ═══════════════════════════════════════════════════════
#                    DATABASE HANDLERS
# ═══════════════════════════════════════════════════════
def load_data(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except: return {} if filename == USERS_FILE else []
    return {} if filename == USERS_FILE else []

def save_data(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def get_user(user_id, username="", first_name="User"):
    users = load_data(USERS_FILE)
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "id": user_id, "username": username, "first_name": first_name,
            "coins": 0, "hpower": BASE_HPOWER, "referrals": 0,
            "last_mining": datetime.now().isoformat(), "last_checkin": "",
            "wallet_address": None, "total_withdrawn": 0, "pending_withdrawal": False,
            "completed_tasks": [], "join_date": datetime.now().strftime("%Y-%m-%d"),
            "referred_by": None
        }
        save_data(USERS_FILE, users)
    return users[uid]

def update_user(user_id, data):
    users = load_data(USERS_FILE)
    uid = str(user_id)
    if uid in users:
        users[uid].update(data)
        save_data(USERS_FILE, users)

# ═══════════════════════════════════════════════════════
#              WEB API FOR GITHUB PAGES
# ═══════════════════════════════════════════════════════
@app.route('/api/user', methods=['GET'])
def get_user_api():
    uid = request.args.get('uid')
    if not uid: return jsonify({"error": "Unauthorized"}), 401
    user = get_user(uid)
    return jsonify({
        "id": user["id"], "name": user["first_name"], "coins": user["coins"],
        "hpower": user["hpower"], "referrals": user["referrals"],
        "wallet": user.get("wallet_address"), "withdrawn": user.get("total_withdrawn", 0)
    })

@app.route('/api/tasks', methods=['GET'])
def get_tasks_api():
    return jsonify(load_data(TASKS_FILE))

@app.route('/')
def health(): return "Server Alive"

# ═══════════════════════════════════════════════════════
#              MINING ENGINE (Runs in Background)
# ═══════════════════════════════════════════════════════
def mining_engine():
    while True:
        try:
            users = load_data(USERS_FILE)
            now = datetime.now()
            for uid, user in users.items():
                last = datetime.fromisoformat(user.get("last_mining", now.isoformat()))
                diff = (now - last).total_seconds()
                if diff >= MINING_INTERVAL:
                    hours = int(diff // MINING_INTERVAL)
                    users[uid]["coins"] += hours * user["hpower"]
                    users[uid]["last_mining"] = now.isoformat()
            save_data(USERS_FILE, users)
        except: pass
        time.sleep(300)

# ═══════════════════════════════════════════════════════
#              BOT COMMANDS & LOGIC
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    args = message.text.split()
    user = get_user(user_id, message.from_user.username, message.from_user.first_name)
    
    # Referral Logic
    if len(args) > 1 and not user.get("referred_by"):
        try:
            ref_id = int(args[1])
            if ref_id != user_id:
                update_user(user_id, {"referred_by": ref_id})
                ref_user = get_user(ref_id)
                update_user(ref_id, {"referrals": ref_user["referrals"] + 1, "hpower": ref_user["hpower"] + REFER_HPOWER_REWARD})
                bot.send_message(ref_id, f"🎉 New Referral! +{REFER_HPOWER_REWARD} H-Power Added!")
        except: pass

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🎮 Open Mining App", web_app=WebAppInfo(url=WEBAPP_URL)))
    kb.add(InlineKeyboardButton("⚡ Dashboard", callback_data="dashboard"),
           InlineKeyboardButton("📋 Tasks", callback_data="tasks"),
           InlineKeyboardButton("👥 Referral", callback_data="referral"),
           InlineKeyboardButton("💎 Withdraw", callback_data="withdraw"),
           InlineKeyboardButton("💳 My Wallet", callback_data="my_wallet"),
           InlineKeyboardButton("🎁 Daily Check-in", callback_data="daily_checkin"))
    
    bot.send_message(message.chat.id, f"⛏️ *{BOT_NAME} MINING*\n\nWelcome {user['first_name']}\nBalance: {user['coins']:,} Coins\nSpeed: {user['hpower']} H/hr", 
                     parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    users = load_data(USERS_FILE)
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
           InlineKeyboardButton("📊 Analytics", callback_data="admin_analytics"),
           InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"))
    bot.send_message(message.chat.id, f"👑 *ADMIN PANEL*\nUsers: {len(users)}", reply_markup=kb)

@bot.message_handler(commands=['wallet'])
def wallet_cmd(message):
    bot.send_message(message.chat.id, "💳 Send your USDT TRC20 address:")
    bot.register_next_step_handler(message, process_wallet_bind)

def process_wallet_bind(message):
    address = message.text.strip()
    if len(address) < 30 or not address.startswith("T"):
        bot.send_message(message.chat.id, "❌ Invalid TRC20 Address!")
        return
    update_user(message.from_user.id, {"wallet_address": address})
    bot.send_message(message.chat.id, f"✅ Wallet Saved: `{address}`", parse_mode="Markdown")

# --- CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user = get_user(call.from_user.id)
    if call.data == "dashboard":
        bot.edit_message_text(f"⚡ *DASHBOARD*\nH-Power: {user['hpower']} H/hr\nCoins: {user['coins']:,}", 
                              call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    elif call.data == "daily_checkin":
        today = datetime.now().strftime("%Y-%m-%d")
        if user.get("last_checkin") == today:
            bot.answer_callback_query(call.id, "Already claimed!")
        else:
            update_user(call.from_user.id, {"last_checkin": today, "coins": user["coins"] + DAILY_CHECKIN_COINS})
            bot.answer_callback_query(call.id, f"🎁 +{DAILY_CHECKIN_COINS} Coins!")
    elif call.data == "referral":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={call.from_user.id}"
        bot.send_message(call.message.chat.id, f"👥 *Referral Program*\n\nLink: `{ref_link}`\nReward: +{REFER_HPOWER_REWARD} HP", parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
#              RUN SERVER & BOT
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    # Start Mining Engine
    threading.Thread(target=mining_engine, daemon=True).start()
    # Start Bot Polling
    threading.Thread(target=lambda: bot.polling(none_stop=True), daemon=True).start()
    # Run API Server on Railway Port
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
