import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import json
import os
import time
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import hmac
import hashlib
from pymongo import MongoClient

# ═══════════════════════════════════════════════════════
#                    CONFIGURATION
# ═══════════════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
BOT_NAME = "CashFlowBoard"
BOT_USERNAME = "CashFlowBoard_bot"
COMPANY = "Phantom MD Technology"
MAINTENANCE_MODE = False

# Security
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
MAX_WITHDRAW_PER_DAY = 3

# WebApp URL — Auto detected or from env
_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
if _domain:
    WEBAPP_URL = os.environ.get("WEBAPP_URL", f"https://{_domain}")
else:
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://abrarali97987.github.io/cashflowboard-bot")

# H-Power Mining Settings
BASE_HPOWER = 0
MINING_INTERVAL = 3600
COINS_PER_HPOWER = 1
TASK_HPOWER_REWARD = 50
REFER_HPOWER_REWARD = 100
WITHDRAWAL_THRESHOLD = 10000
DAILY_CHECKIN_HPOWER = 15
DAILY_CHECKIN_COINS = 50

# MongoDB
MONGO_URL = os.environ.get("MONGO_URL", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set!")
if not MONGO_URL:
    raise ValueError("MONGO_URL not set!")

mongo_client = MongoClient(MONGO_URL)
db = mongo_client["cashflowboard"]
users_col = db["users"]
channels_col = db["channels"]
tasks_col = db["tasks"]
banned_col = db["banned"]

bot = telebot.TeleBot(BOT_TOKEN)

# ═══════════════════════════════════════════════════════
#                    DATABASE
# ═══════════════════════════════════════════════════════
def get_user(user_id, username="", first_name="Miner"):
    uid = int(user_id)
    user = users_col.find_one({"id": uid})
    if not user:
        user = {
            "id": uid,
            "username": username,
            "first_name": first_name,
            "coins": 0,
            "hpower": BASE_HPOWER,
            "joined_channels": [],
            "completed_tasks": [],
            "referrals": 0,
            "referred_by": None,
            "last_mining": datetime.now().isoformat(),
            "last_checkin": "",
            "wallet_address": None,
            "join_date": datetime.now().strftime("%Y-%m-%d"),
            "total_withdrawn": 0,
            "pending_withdrawal": False,
            "withdraw_count_today": 0,
            "withdraw_date": ""
        }
        users_col.insert_one(user)
    user.pop("_id", None)
    return user

def update_user(user_id, data):
    uid = int(user_id)
    users_col.update_one({"id": uid}, {"$set": data})

def is_banned(user_id):
    return banned_col.find_one({"id": int(user_id)}) is not None

def ban_user(user_id):
    uid = int(user_id)
    if not banned_col.find_one({"id": uid}):
        banned_col.insert_one({"id": uid})

def unban_user(user_id):
    banned_col.delete_one({"id": int(user_id)})

def load_channels():
    return list(channels_col.find({}, {"_id": 0}))

def load_tasks():
    return list(tasks_col.find({}, {"_id": 0}))

def load_all_users():
    return list(users_col.find({}, {"_id": 0}))

# ═══════════════════════════════════════════════════════
#              AUTO MINING ENGINE
# ═══════════════════════════════════════════════════════
def mining_engine():
    while True:
        try:
            now = datetime.now()
            all_users = load_all_users()
            for user in all_users:
                last = datetime.fromisoformat(user.get("last_mining", now.isoformat()))
                diff = (now - last).total_seconds()
                if diff >= MINING_INTERVAL:
                    hours = int(diff // MINING_INTERVAL)
                    earned = hours * user.get("hpower", 0) * COINS_PER_HPOWER
                    update_user(user["id"], {
                        "coins": user["coins"] + earned,
                        "last_mining": now.isoformat()
                    })
        except Exception as e:
            print(f"Mining error: {e}")
        time.sleep(300)

threading.Thread(target=mining_engine, daemon=True).start()

# ═══════════════════════════════════════════════════════
#         WEBAPP DATA API SERVER (Port 8080)
# ═══════════════════════════════════════════════════════
def verify_telegram_data(init_data_str):
    """Verify Telegram WebApp initData"""
    try:
        parsed = {}
        for part in init_data_str.split("&"):
            k, v = part.split("=", 1)
            from urllib.parse import unquote
            parsed[k] = unquote(v)

        hash_value = parsed.pop("hash", "")
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return computed == hash_value, parsed
    except:
        return False, {}

# Read index.html content
def get_webapp_html():
    html_path = os.path.join(os.path.dirname(__file__), 'index.html')
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return f.read()
    return "<h1>WebApp not found</h1>"

class WebAppAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Quiet logs

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ── GET / → Serve WebApp ─────────────────────────
        if path == "/" or path == "/index.html":
            html = get_webapp_html()
            # Inject dynamic API URL
            port = int(os.environ.get("PORT", 8080))
            domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", f"localhost:{port}")
            api_url = f"https://{domain}" if not domain.startswith("localhost") else f"http://{domain}"
            html = html.replace(
                "const API_BASE = getApiBase();",
                f"const API_BASE = '{api_url}';"
            )
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # ── GET /api/user?init_data=... ──────────────────
        if path == "/api/user":
            init_data = params.get("init_data", [""])[0]
            valid, data = verify_telegram_data(init_data)
            try:
                user_info = json.loads(data.get("user", "{}"))
                uid = int(user_info.get("id", 0))
            except:
                uid = 0

            if not uid:
                try:
                    uid = int(params.get("uid", [0])[0])
                except:
                    uid = 0
                if not uid:
                    self.send_json({"error": "Unauthorized"}, 401)
                    return

            username = user_info.get("username", "") if user_info else ""
            first_name = user_info.get("first_name", "Miner") if user_info else "Miner"
            user = get_user(uid, username, first_name)
            # Mining status
            last = datetime.fromisoformat(user.get("last_mining", datetime.now().isoformat()))
            diff = (datetime.now() - last).total_seconds()
            next_mine = max(0, MINING_INTERVAL - (diff % MINING_INTERVAL))

            self.send_json({
                "id": str(user["id"]),
                "name": user["first_name"],
                "username": user.get("username", ""),
                "coins": user["coins"],
                "hpower": user["hpower"],
                "referrals": user["referrals"],
                "withdrawn": user.get("total_withdrawn", 0),
                "wallet": user.get("wallet_address"),
                "last_checkin": user.get("last_checkin", ""),
                "last_mining": user.get("last_mining"),
                "next_mine_seconds": int(next_mine),
                "pending_withdrawal": user.get("pending_withdrawal", False),
                "join_date": user.get("join_date", "")
            })

        # ── GET /api/leaderboard ─────────────────────────
        elif path == "/api/leaderboard":
            top = sorted(load_all_users(), key=lambda x: x.get("hpower",0), reverse=True)[:10]
            result = [{"name": u["first_name"], "hpower": u["hpower"]} for u in top]
            self.send_json(result)

        # ── GET /api/tasks?uid=... ───────────────────────
        elif path == "/api/tasks":
            uid = params.get("uid", [0])[0]
            try:
                user = get_user(int(uid)) if uid and int(uid) != 0 else {}
            except:
                user = {}
            tasks = load_tasks()
            completed = user.get("completed_tasks", [])
            result = []
            for t in tasks:
                result.append({
                    "id": t["id"],
                    "name": t["name"],
                    "hpower": t["hpower"],
                    "link": t["link"],
                    "type": t.get("type", "one_time"),
                    "done": t["id"] in completed
                })
            self.send_json(result)

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # ── POST /api/checkin ────────────────────────────
        if path == "/api/checkin":
            uid = body.get("uid")
            if not uid:
                self.send_json({"error": "No uid"}, 400)
                return
            user = get_user(uid)
            today = datetime.now().strftime("%Y-%m-%d")
            if user.get("last_checkin") == today:
                self.send_json({"success": False, "message": "Already checked in today!"})
                return
            update_user(uid, {
                "last_checkin": today,
                "hpower": user["hpower"] + DAILY_CHECKIN_HPOWER,
                "coins": user["coins"] + DAILY_CHECKIN_COINS
            })
            self.send_json({
                "success": True,
                "hpower_gained": DAILY_CHECKIN_HPOWER,
                "coins_gained": DAILY_CHECKIN_COINS
            })

        # ── POST /api/withdraw ───────────────────────────
        elif path == "/api/withdraw":
            uid = body.get("uid")
            if not uid:
                self.send_json({"error": "No uid"}, 400)
                return
            user = get_user(uid)
            if user["coins"] < WITHDRAWAL_THRESHOLD:
                self.send_json({"success": False, "message": "Not enough coins!"})
                return
            if user.get("pending_withdrawal"):
                self.send_json({"success": False, "message": "Pending request exists!"})
                return
            if not user.get("wallet_address"):
                self.send_json({"success": False, "message": "No wallet bound! Use /wallet in bot."})
                return
            usd = user["coins"] // WITHDRAWAL_THRESHOLD
            update_user(uid, {"pending_withdrawal": True})
            try:
                bot.send_message(ADMIN_ID,
                    f"💎 *WITHDRAWAL REQUEST*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 {user['first_name']} | `{uid}`\n"
                    f"🪙 Coins: *{user['coins']:,}*\n"
                    f"💵 Amount: *${usd} USD*\n"
                    f"💳 Wallet: `{user['wallet_address']}`\n\n"
                    f"✅ /approve_{uid}\n❌ /reject_{uid}",
                    parse_mode="Markdown")
            except:
                pass
            self.send_json({"success": True, "amount": usd})

        # ── POST /api/task/complete ──────────────────────
        elif path == "/api/task/complete":
            uid = body.get("uid")
            task_id = body.get("task_id")
            if not uid or not task_id:
                self.send_json({"error": "Missing uid or task_id"}, 400)
                return
            user = get_user(uid)
            completed = user.get("completed_tasks", [])
            if task_id in completed:
                self.send_json({"success": False, "message": "Already completed!"})
                return
            tasks = load_tasks()
            task = next((t for t in tasks if t["id"] == task_id), None)
            if not task:
                self.send_json({"error": "Task not found"}, 404)
                return
            completed.append(task_id)
            new_hpower = user["hpower"] + task["hpower"]
            update_user(uid, {
                "completed_tasks": completed,
                "hpower": new_hpower
            })
            self.send_json({
                "success": True,
                "hpower_gained": task["hpower"],
                "new_hpower": new_hpower
            })

        else:
            self.send_json({"error": "Not found"}, 404)

def start_api_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), WebAppAPIHandler)
    print(f"✅ WebApp API running on port {port}")
    server.serve_forever()

threading.Thread(target=start_api_server, daemon=True).start()

# ═══════════════════════════════════════════════════════
#              FORCE JOIN CHECK
# ═══════════════════════════════════════════════════════
def check_force_join(user_id):
    channels = load_channels()
    if not channels:
        return True, []
    not_joined = []
    for ch in channels:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ["left", "kicked", "banned"]:
                not_joined.append(ch["username"])
        except:
            not_joined.append(ch["username"])
    return len(not_joined) == 0, not_joined

def force_join_keyboard(not_joined):
    kb = InlineKeyboardMarkup(row_width=1)
    for ch in not_joined:
        kb.add(InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.replace('@', '')}"))
    kb.add(InlineKeyboardButton("✅ I Joined — Verify Now", callback_data="verify_force_join"))
    return kb

# ═══════════════════════════════════════════════════════
#              MINING STATUS
# ═══════════════════════════════════════════════════════
def get_mining_status(user):
    last = datetime.fromisoformat(user.get("last_mining", datetime.now().isoformat()))
    now = datetime.now()
    diff = (now - last).total_seconds()
    next_mine = max(0, MINING_INTERVAL - diff)
    hours_mined = int(diff // MINING_INTERVAL)
    pending = hours_mined * user["hpower"] * COINS_PER_HPOWER
    mins = int(next_mine // 60)
    secs = int(next_mine % 60)
    return pending, f"{mins}m {secs}s", hours_mined

def get_miner_rank(hpower):
    if hpower >= 5000:
        return "💎 Diamond"
    elif hpower >= 2000:
        return "🥇 Gold"
    elif hpower >= 500:
        return "🥈 Silver"
    else:
        return "🥉 Bronze"

# ═══════════════════════════════════════════════════════
#              KEYBOARDS
# ═══════════════════════════════════════════════════════
def main_menu_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton(
        "⛏️ OPEN CASHFLOWBOARD APP",
        web_app=WebAppInfo(url=WEBAPP_URL)
    ))
    kb.add(
        InlineKeyboardButton("💳 My Wallet", callback_data="my_wallet"),
        InlineKeyboardButton("💎 Withdraw", callback_data="withdraw"),
        InlineKeyboardButton("ℹ️ Help", callback_data="help")
    )
    return kb

def admin_menu_kb():
    m_status = "🔴 Maintenance ON" if MAINTENANCE_MODE else "🟢 Maintenance OFF"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Add Channel", callback_data="admin_add_ch"),
        InlineKeyboardButton("➖ Remove Channel", callback_data="admin_rem_ch"),
        InlineKeyboardButton("📋 Channels List", callback_data="admin_list_ch"),
        InlineKeyboardButton("👥 All Users", callback_data="admin_users"),
        InlineKeyboardButton("⚡ Adjust H-Power", callback_data="admin_hpower"),
        InlineKeyboardButton("💎 Withdrawals", callback_data="admin_withdrawals"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("📣 Post to Channels", callback_data="admin_post_channels"),
        InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
        InlineKeyboardButton("✅ Unban User", callback_data="admin_unban"),
        InlineKeyboardButton("📊 Analytics", callback_data="admin_analytics"),
        InlineKeyboardButton(f"{m_status}", callback_data="toggle_maintenance"),
    )
    return kb

# ═══════════════════════════════════════════════════════
#              /start COMMAND
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=['start'])
def start(message):
    global MAINTENANCE_MODE
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or "Miner"

    if is_banned(user_id):
        bot.send_message(message.chat.id,
            f"🚫 *Account Suspended*\n\nContact support.\n\n— *{COMPANY}*",
            parse_mode="Markdown")
        return

    if MAINTENANCE_MODE and user_id != ADMIN_ID:
        bot.send_message(message.chat.id,
            f"🔧 *{BOT_NAME} — Maintenance Mode*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"We are currently upgrading our systems.\n\n"
            f"⏳ Please check back shortly.\n"
            f"🚀 Something bigger is coming!\n\n"
            f"— *{COMPANY}*",
            parse_mode="Markdown")
        return

    args = message.text.split()
    referred_by = None
    if len(args) > 1:
        try:
            referred_by = int(args[1])
        except:
            pass

    user = get_user(user_id, username, first_name)

    if referred_by and referred_by != user_id and not user.get("referred_by"):
        update_user(user_id, {"referred_by": referred_by})
        ref = get_user(referred_by)
        update_user(referred_by, {
            "hpower": ref["hpower"] + REFER_HPOWER_REWARD,
            "referrals": ref["referrals"] + 1
        })
        try:
            bot.send_message(referred_by,
                f"🎉 *New Referral!*\n\n"
                f"👤 {first_name} joined using your link!\n"
                f"⚡ +{REFER_HPOWER_REWARD} H-Power added!",
                parse_mode="Markdown")
        except:
            pass

    joined, not_joined = check_force_join(user_id)
    if not joined:
        bot.send_message(message.chat.id,
            f"⛔ *Join Required*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Please join our channel(s) to access *{BOT_NAME}*.\n\n"
            f"📋 Join {len(not_joined)} channel(s) below 👇",
            parse_mode="Markdown",
            reply_markup=force_join_keyboard(not_joined))
        return

    rank = get_miner_rank(user['hpower'])
    bot.send_message(message.chat.id,
        f"⛏️ *{BOT_NAME}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👋 Welcome, *{first_name}*! {rank}\n\n"
        f"⚡ H-Power: *{user['hpower']} H/hr*\n"
        f"🪙 Coins: *{user['coins']:,}*\n\n"
        f"👇 *Open the app to mine & earn!*\n\n"
        f"— *{COMPANY}*",
        parse_mode="Markdown",
        reply_markup=main_menu_kb())

# ═══════════════════════════════════════════════════════
#              /admin COMMAND
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Access Denied!")
        return
    parts = message.text.strip().split()
    if len(parts) < 2 or parts[1] != ADMIN_SECRET:
        bot.send_message(message.chat.id,
            "🔐 Usage: `/admin <secret_key>`", parse_mode="Markdown")
        return
    all_users = load_all_users()
    channels = load_channels()
    total_coins = sum(u.get("coins",0) for u in all_users)
    total_hpower = sum(u.get("hpower",0) for u in all_users)
    m_status = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
    bot.send_message(message.chat.id,
        f"👑 *ADMIN DASHBOARD*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: *{len(all_users)}*\n"
        f"📺 Active Channels: *{len(channels)}*\n"
        f"🪙 Total Coins: *{total_coins:,}*\n"
        f"⚡ Total H-Power: *{total_hpower:,}*\n"
        f"🔧 Maintenance: *{m_status}*\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=admin_menu_kb())

# ═══════════════════════════════════════════════════════
#              ADMIN COMMANDS
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=['addchannel'])
def add_channel(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.send_message(message.chat.id,
        "📺 Send channel username:\nExample: `@MyChannel`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_add_channel)

def process_add_channel(message):
    if message.from_user.id != ADMIN_ID:
        return
    username = message.text.strip()
    if not username.startswith("@"):
        username = "@" + username
    channels = load_channels()
    for ch in channels:
        if ch["username"] == username:
            bot.send_message(message.chat.id, f"⚠️ {username} already exists!")
            return
    channels_col.insert_one({"username": username, "added": datetime.now().strftime("%Y-%m-%d")})
    bot.send_message(message.chat.id,
        f"✅ *Channel Added!*\n📺 {username}", parse_mode="Markdown")

@bot.message_handler(commands=['removechannel'])
def remove_channel(message):
    if message.from_user.id != ADMIN_ID:
        return
    channels = load_channels()
    text = "📋 *Send username to remove:*\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch['username']}\n"
    msg = bot.send_message(message.chat.id, text, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_remove_channel)

def process_remove_channel(message):
    if message.from_user.id != ADMIN_ID:
        return
    username = message.text.strip()
    if not username.startswith("@"):
        username = "@" + username
    channels_col.delete_one({"username": username})
    bot.send_message(message.chat.id, f"✅ *{username} removed!*", parse_mode="Markdown")

@bot.message_handler(commands=['addtask'])
def add_task_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.send_message(message.chat.id,
        "📋 *Add Task*\nFormat: `NAME | LINK | HPOWER`\n\nExample:\n`Join Channel | https://t.me/xyz | 50`",
        parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_add_task)

def process_add_task(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.strip().split("|")
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Format: NAME | LINK | HPOWER")
            return
        name = parts[0].strip()
        link = parts[1].strip()
        hpower = int(parts[2].strip())
        tasks = load_tasks()
        task_id = f"task_{len(tasks)+1}_{int(time.time())}"
        tasks_col.insert_one({
            "id": task_id, "name": name, "link": link, "hpower": hpower,
            "type": "daily" if link == "daily" else "one_time",
            "added": datetime.now().strftime("%Y-%m-%d")
        })
        bot.send_message(message.chat.id,
            f"✅ *Task Added!*\n📋 {name}\n⚡ +{hpower} H-Power", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(commands=['removetask'])
def remove_task_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    tasks = load_tasks()
    text = "📋 *Send number to remove:*\n\n"
    for i, t in enumerate(tasks, 1):
        text += f"{i}. {t['name']} (+{t['hpower']} HP)\n"
    msg = bot.send_message(message.chat.id, text, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_remove_task)

def process_remove_task(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        idx = int(message.text.strip()) - 1
        tasks = load_tasks()
        if idx < 0 or idx >= len(tasks):
            bot.send_message(message.chat.id, "❌ Invalid number!")
            return
        removed = tasks[idx]
        tasks_col.delete_one({"id": removed["id"]})
        bot.send_message(message.chat.id, f"✅ Removed: {removed['name']}")
    except:
        bot.send_message(message.chat.id, "❌ Invalid!")

@bot.message_handler(commands=['sethpower'])
def set_hpower(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.send_message(message.chat.id,
        "⚡ Send: `USER_ID HPOWER`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_set_hpower)

def process_set_hpower(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.strip().split()
        target_id = int(parts[0])
        hpower = int(parts[1])
        update_user(target_id, {"hpower": hpower})
        bot.send_message(message.chat.id, f"✅ User {target_id} → {hpower} H-Power!")
        try:
            bot.send_message(target_id,
                f"⚡ *H-Power Updated!*\n\nNew H-Power: *{hpower} H/hr*\nMining speed boosted! 🚀",
                parse_mode="Markdown")
        except:
            pass
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.send_message(message.chat.id, "📢 Send broadcast message:")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return
    all_users = load_all_users()
    channels = load_channels()
    text = f"📢 *{BOT_NAME}:*\n\n{message.text}"
    success = 0
    failed = 0
    for ch in channels:
        try:
            bot.send_message(ch["username"], text, parse_mode="Markdown")
            time.sleep(0.3)
        except:
            pass
    for u in all_users:
        try:
            bot.send_message(u["id"], text, parse_mode="Markdown")
            success += 1
            time.sleep(0.05)
        except:
            failed += 1
    bot.send_message(message.chat.id,
        f"✅ *Broadcast Done!*\n✅ {success} | ❌ {failed}", parse_mode="Markdown")

@bot.message_handler(commands=['ban'])
def ban_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /ban USER_ID")
        return
    try:
        target = int(parts[1])
        ban_user(target)
        bot.send_message(message.chat.id, f"🚫 User {target} banned.")
        try:
            bot.send_message(target,
                f"🚫 *Account Suspended.*\n\n— *{COMPANY}*", parse_mode="Markdown")
        except:
            pass
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(commands=['unban'])
def unban_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /unban USER_ID")
        return
    try:
        target = int(parts[1])
        unban_user(target)
        bot.send_message(message.chat.id, f"✅ User {target} unbanned.")
        try:
            bot.send_message(target,
                f"✅ *Account Reinstated!*\nKeep mining! ⚡\n\n— *{COMPANY}*",
                parse_mode="Markdown")
        except:
            pass
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(commands=['wallet'])
def wallet_cmd(message):
    user = get_user(message.from_user.id)
    wallet = user.get("wallet_address")
    if wallet:
        text = (f"💳 *MY WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ Wallet Bound!\n\n📍 Address:\n`{wallet}`\n\n🌐 Network: USDT/TRC20\n\n"
                f"Send new address to update:")
    else:
        text = (f"💳 *BIND WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"❌ No wallet bound yet!\n\nSend your *USDT TRC20* address:\n\n⚠️ TRC20 only!")
    kb = InlineKeyboardMarkup()
    if wallet:
        kb.add(InlineKeyboardButton("🔄 Change Wallet", callback_data="change_wallet"))
    kb.add(InlineKeyboardButton("🔙 Menu", callback_data="back_main"))
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=kb)
    if not wallet:
        bot.register_next_step_handler(message, process_wallet_bind)

def process_wallet_bind(message):
    address = message.text.strip()
    if not address.startswith("T") or len(address) != 34:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔄 Try Again", callback_data="bind_wallet"))
        kb.add(InlineKeyboardButton("🔙 Menu", callback_data="back_main"))
        bot.send_message(message.chat.id,
            "❌ *Invalid TRC20 Address!*\n\n• Must start with *T*\n• Must be *34 characters*",
            parse_mode="Markdown", reply_markup=kb)
        return
    update_user(message.from_user.id, {"wallet_address": address})
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💎 Withdraw", callback_data="withdraw"))
    kb.add(InlineKeyboardButton("🔙 Menu", callback_data="back_main"))
    bot.send_message(message.chat.id,
        f"✅ *Wallet Bound!*\n\n💳 `{address}`\n\n🌐 Network: USDT/TRC20",
        parse_mode="Markdown", reply_markup=kb)

# Withdrawal approve/reject commands
@bot.message_handler(func=lambda m: m.text and m.text.startswith('/approve_') and m.from_user.id == ADMIN_ID)
def approve_withdrawal(message):
    try:
        target_id = int(message.text.split('_')[1])
        user = get_user(target_id)
        usd = user["coins"] // WITHDRAWAL_THRESHOLD
        remaining = user["coins"] % WITHDRAWAL_THRESHOLD
        update_user(target_id, {
            "coins": remaining, "pending_withdrawal": False,
            "total_withdrawn": user["total_withdrawn"] + usd
        })
        bot.send_message(target_id,
            f"✅ *Withdrawal Approved!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 Amount: *${usd} USD*\n🪙 Remaining: *{remaining:,}*\n\n"
            f"USDT credited shortly! 🚀\n\n— *{COMPANY}*", parse_mode="Markdown")
        bot.send_message(message.chat.id, f"✅ ${usd} approved for {target_id}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(func=lambda m: m.text and m.text.startswith('/reject_') and m.from_user.id == ADMIN_ID)
def reject_withdrawal(message):
    try:
        target_id = int(message.text.split('_')[1])
        update_user(target_id, {"pending_withdrawal": False})
        bot.send_message(target_id,
            f"❌ *Withdrawal Rejected*\n\nContact support.\n\n— *{COMPANY}*",
            parse_mode="Markdown")
        bot.send_message(message.chat.id, f"✅ Rejected for {target_id}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

# ═══════════════════════════════════════════════════════
#              CALLBACK HANDLER
# ═══════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global MAINTENANCE_MODE
    user_id = call.from_user.id

    if is_banned(user_id):
        bot.answer_callback_query(call.id, "🚫 Account suspended.")
        return

    user = get_user(user_id, call.from_user.username or "", call.from_user.first_name or "Miner")

    if MAINTENANCE_MODE and user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🔧 Under maintenance!")
        return

    if call.data == "verify_force_join":
        joined, not_joined = check_force_join(user_id)
        if joined:
            bot.answer_callback_query(call.id, "✅ Verified! Welcome!")
            pending, next_mine, _ = get_mining_status(user)
            rank = get_miner_rank(user['hpower'])
            bot.edit_message_text(
                f"⛏️ *{BOT_NAME} MINING*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ Access Granted! {rank}\n\n"
                f"⚡ H-Power: *{user['hpower']} H/hr*\n"
                f"🪙 Coins: *{user['coins']:,}*\n\n"
                f"🎮 Open the app to start mining! 🔥",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=main_menu_kb())
        else:
            bot.answer_callback_query(call.id, f"❌ Still need to join {len(not_joined)} channel(s)!")

    elif call.data == "dashboard":
        pending, next_mine, _ = get_mining_status(user)
        rank = get_miner_rank(user['hpower'])
        coins_per_day = user["hpower"] * 24
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📋 Tasks", callback_data="tasks"),
            InlineKeyboardButton("🔄 Refresh", callback_data="dashboard"),
            InlineKeyboardButton("🎮 Open App", web_app=WebAppInfo(url=WEBAPP_URL)),
            InlineKeyboardButton("🔙 Menu", callback_data="back_main")
        )
        bot.edit_message_text(
            f"⚡ *MINING DASHBOARD*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{rank}\n"
            f"⚡ H-Power: *{user['hpower']} H/hr*\n"
            f"🪙 Coins: *{user['coins']:,}*\n"
            f"📅 Daily Earn: *{coins_per_day:,}*\n"
            f"⏳ Next Mine: *{next_mine}*\n\n"
            f"🎯 Goal: {user['coins']:,} / {WITHDRAWAL_THRESHOLD:,} Coins\n"
            f"📊 Progress: {min(100, user['coins']*100//WITHDRAWAL_THRESHOLD)}%",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb)

    elif call.data == "tasks":
        tasks = load_tasks()
        completed = user.get("completed_tasks", [])
        if not tasks:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_main"))
            bot.edit_message_text("📋 *No tasks yet!*\nAdmin will add tasks soon.",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=kb)
            return
        text = "📋 *TASK CENTER*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        kb = InlineKeyboardMarkup(row_width=1)
        for t in tasks:
            done = t["id"] in completed
            status = "✅" if done else "🔲"
            text += f"{status} *{t['name']}*\n⚡ +{t['hpower']} H-Power\n\n"
            if not done and t["link"] != "daily":
                kb.add(InlineKeyboardButton(f"🔗 {t['name']}", url=t["link"]))
        kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb)

    elif call.data == "referral":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={ref_link}&text=Join%20CashFlowBoard%20Mining!"))
        kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_main"))
        bot.edit_message_text(
            f"👥 *REFERRAL PROGRAM*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Your Referrals: *{user['referrals']}*\n"
            f"⚡ H-Power Earned: *+{user['referrals'] * REFER_HPOWER_REWARD}*\n\n"
            f"📎 *Your Link:*\n`{ref_link}`\n\n"
            f"Per referral: +{REFER_HPOWER_REWARD} H-Power ⚡",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb)

    elif call.data == "daily_checkin":
        today = datetime.now().strftime("%Y-%m-%d")
        if user.get("last_checkin") == today:
            bot.answer_callback_query(call.id, "✅ Already checked in today! Come back tomorrow.")
            return
        update_user(user_id, {
            "last_checkin": today,
            "hpower": user["hpower"] + DAILY_CHECKIN_HPOWER,
            "coins": user["coins"] + DAILY_CHECKIN_COINS
        })
        bot.answer_callback_query(call.id, f"🎁 +{DAILY_CHECKIN_HPOWER} H-Power & +{DAILY_CHECKIN_COINS} Coins!")
        user = get_user(user_id)
        pending, next_mine, _ = get_mining_status(user)
        rank = get_miner_rank(user['hpower'])
        bot.edit_message_text(
            f"🎁 *Daily Check-in Claimed!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ +{DAILY_CHECKIN_HPOWER} H-Power\n🪙 +{DAILY_CHECKIN_COINS} Coins\n\n"
            f"Current H-Power: *{user['hpower']} H/hr* {rank}\n"
            f"Total Coins: *{user['coins']:,}*\n\n"
            f"Come back tomorrow! 🌙",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

    elif call.data == "withdraw":
        coins = user["coins"]
        wallet = user.get("wallet_address")
        usd = coins // WITHDRAWAL_THRESHOLD
        needed = max(0, WITHDRAWAL_THRESHOLD - coins)
        if coins < WITHDRAWAL_THRESHOLD:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📋 Tasks", callback_data="tasks"),
                InlineKeyboardButton("👥 Refer", callback_data="referral"),
                InlineKeyboardButton("🔙 Back", callback_data="back_main"))
            bot.edit_message_text(
                f"💎 *WITHDRAWAL*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"❌ Insufficient Coins!\n\n"
                f"🪙 Your Coins: *{coins:,}*\n"
                f"🎯 Required: *{WITHDRAWAL_THRESHOLD:,}*\n"
                f"📊 Still Need: *{needed:,} Coins*\n\n"
                f"Complete tasks & refer friends to earn faster! ⚡",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=kb)
        elif user.get("pending_withdrawal"):
            bot.answer_callback_query(call.id, "⚠️ You have a pending withdrawal!")
        elif not wallet:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💳 Bind Wallet", callback_data="bind_wallet"))
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_main"))
            bot.edit_message_text(
                f"💎 *WITHDRAWAL*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚠️ No wallet bound!\n\n🪙 Coins: *{coins:,}*\n"
                f"💵 Withdrawable: *${usd} USD*\n\nPlease bind your USDT TRC20 wallet first.",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=kb)
        else:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💰 Cash Out Now", callback_data="confirm_withdraw"))
            kb.add(InlineKeyboardButton("🔄 Change Wallet", callback_data="change_wallet"))
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_main"))
            bot.edit_message_text(
                f"💎 *WITHDRAWAL AVAILABLE!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 Coins: *{coins:,}*\n💵 Amount: *${usd} USD*\n"
                f"💳 Wallet: `{wallet[:10]}...{wallet[-6:]}`\n🌐 USDT/TRC20\n\n"
                f"Press *Cash Out Now* to submit!",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=kb)

    elif call.data == "confirm_withdraw":
        coins = user["coins"]
        usd = coins // WITHDRAWAL_THRESHOLD
        wallet = user.get("wallet_address", "NOT SET")
        update_user(user_id, {"pending_withdrawal": True})
        try:
            bot.send_message(ADMIN_ID,
                f"💎 *WITHDRAWAL REQUEST*\n━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 {call.from_user.first_name} | `{user_id}`\n"
                f"🪙 Coins: *{coins:,}* | 💵 *${usd} USD*\n"
                f"💳 `{wallet}`\n\n✅ /approve_{user_id}\n❌ /reject_{user_id}",
                parse_mode="Markdown")
        except:
            pass
        bot.edit_message_text(
            f"✅ *Request Submitted!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 Amount: *${usd} USD*\n💳 To: `{wallet[:10]}...{wallet[-6:]}`\n"
            f"⏳ Processing: 24 hours\n\nYou'll be notified once done! 🚀\n\n— *{COMPANY}*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

    elif call.data == "my_wallet":
        wallet = user.get("wallet_address")
        if wallet:
            text = (f"💳 *MY WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n✅ Wallet Bound!\n\n"
                    f"📍 Address:\n`{wallet}`\n\n🌐 Network: USDT/TRC20\n"
                    f"💵 Total Withdrawn: *${user.get('total_withdrawn', 0)} USD*")
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔄 Change Wallet", callback_data="change_wallet"))
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_main"))
        else:
            text = (f"💳 *MY WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n❌ No wallet bound!\n\n"
                    f"Use /wallet or tap below.")
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💳 Bind Wallet", callback_data="bind_wallet"))
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="back_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb)

    elif call.data == "bind_wallet":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "💳 Send your USDT TRC20 wallet address:\n\n⚠️ TRC20 network only!")
        bot.register_next_step_handler(msg, process_wallet_bind)

    elif call.data == "change_wallet":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "💳 Send your new USDT TRC20 address:")
        bot.register_next_step_handler(msg, process_wallet_bind)

    elif call.data == "leaderboard":
        top = sorted(load_all_users(), key=lambda x: x.get("hpower",0), reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"]
        text = "🏆 *TOP MINERS*\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, u in enumerate(top):
            m = medals[i] if i < 3 else f"{i+1}."
            rank = get_miner_rank(u['hpower'])
            text += f"{m} {u['first_name'][:12]}: ⚡{u['hpower']} H/hr {rank}\n"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

    elif call.data == "help":
        bot.edit_message_text(
            f"ℹ️ *HOW IT WORKS*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ *H-Power* = Mining speed\n"
            f"🔋 *Auto Mining* runs 24/7\n"
            f"Formula: H-Power × Hours = Coins\n\n"
            f"🏅 *Ranks*\n"
            f"🥉 Bronze: 0–499 H/hr\n"
            f"🥈 Silver: 500–1999 H/hr\n"
            f"🥇 Gold: 2000–4999 H/hr\n"
            f"💎 Diamond: 5000+ H/hr\n\n"
            f"📋 *Boost H-Power*\n"
            f"• Tasks: +{TASK_HPOWER_REWARD} H-Power\n"
            f"• Referral: +{REFER_HPOWER_REWARD} H-Power\n"
            f"• Daily check-in: +{DAILY_CHECKIN_HPOWER} H-Power\n\n"
            f"💎 *Withdrawal*\n"
            f"10,000 Coins = $1 USD (USDT TRC20)\n\n"
            f"📞 Support: @PakEarnPros\n\n"
            f"— *{COMPANY}*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

    # ── ADMIN CALLBACKS ────────────────────────────────
    elif call.data == "toggle_maintenance":
        if user_id != ADMIN_ID:
            return
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        status = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
        bot.answer_callback_query(call.id, f"Maintenance: {status}")

    elif call.data == "admin_analytics":
        if user_id != ADMIN_ID:
            return
        all_users = load_all_users()
        total_coins = sum(u.get("coins",0) for u in all_users)
        total_hpower = sum(u.get("hpower",0) for u in all_users)
        pending_w = sum(1 for u in all_users if u.get("pending_withdrawal"))
        total_withdrawn = sum(u.get("total_withdrawn", 0) for u in all_users)
        today = datetime.now().strftime("%Y-%m-%d")
        new_today = sum(1 for u in all_users if u.get("join_date") == today)
        bot.edit_message_text(
            f"📊 *ANALYTICS*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Total Users: *{len(users)}*\n"
            f"🆕 Joined Today: *{new_today}*\n"
            f"🪙 Total Coins: *{total_coins:,}*\n"
            f"⚡ Total H-Power: *{total_hpower:,}*\n"
            f"💎 Pending Withdrawals: *{pending_w}*\n"
            f"💵 Total Paid Out: *${total_withdrawn} USD*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=admin_menu_kb())

    elif call.data == "admin_list_ch":
        if user_id != ADMIN_ID:
            return
        channels = load_channels()
        text = "📋 *Channels List:*\n\n"
        for i, ch in enumerate(channels, 1):
            text += f"{i}. {ch['username']}\n"
        if not channels:
            text += "No channels added yet."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=admin_menu_kb())

    elif call.data == "admin_withdrawals":
        if user_id != ADMIN_ID:
            return
        pending = [u for u in load_all_users() if u.get("pending_withdrawal")]
        text = f"💎 *Pending Withdrawals: {len(pending)}*\n\n"
        for u in pending:
            usd = u["coins"] // WITHDRAWAL_THRESHOLD
            text += f"👤 {u['first_name']} | `{u['id']}` | ${usd}\n"
            text += f"   /approve_{u['id']}  /reject_{u['id']}\n\n"
        if not pending:
            text += "No pending withdrawals."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=admin_menu_kb())

    elif call.data == "admin_add_ch":
        if user_id != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "📺 Send channel username:\nExample: `@MyChannel`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_channel)

    elif call.data == "admin_rem_ch":
        if user_id != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        channels = load_channels()
        text = "📋 *Send username to remove:*\n\n"
        for i, ch in enumerate(channels, 1):
            text += f"{i}. {ch['username']}\n"
        msg = bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_remove_channel)

    elif call.data == "admin_hpower":
        if user_id != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "⚡ Send: `USER_ID HPOWER`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_set_hpower)

    elif call.data == "admin_broadcast":
        if user_id != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "📢 Send broadcast message:")
        bot.register_next_step_handler(msg, process_broadcast)

    elif call.data == "admin_post_channels":
        if user_id != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "📣 Send message to post in ALL channels:")
        bot.register_next_step_handler(msg, process_post_to_channels)

    elif call.data == "admin_ban":
        if user_id != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🚫 Send USER_ID to ban:")
        bot.register_next_step_handler(msg, lambda m: ban_from_panel(m))

    elif call.data == "admin_unban":
        if user_id != ADMIN_ID:
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "✅ Send USER_ID to unban:")
        bot.register_next_step_handler(msg, lambda m: unban_from_panel(m))

    elif call.data == "admin_users":
        if user_id != ADMIN_ID:
            return
        total = users_col.count_documents({})
        bot.answer_callback_query(call.id, f"👥 Total Users: {total}")

    elif call.data == "back_main":
        pending, next_mine, _ = get_mining_status(user)
        rank = get_miner_rank(user['hpower'])
        bot.edit_message_text(
            f"⛏️ *{BOT_NAME} MINING*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ H-Power: *{user['hpower']} H/hr* {rank}\n"
            f"🪙 Coins: *{user['coins']:,}*\n"
            f"⏳ Next Mine: *{next_mine}*\n\n"
            f"Select an option below 👇",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

def process_post_to_channels(message):
    if message.from_user.id != ADMIN_ID:
        return
    channels = load_channels()
    success = 0
    failed = 0
    for ch in channels:
        try:
            bot.send_message(ch["username"], message.text, parse_mode="Markdown")
            success += 1
            time.sleep(0.3)
        except:
            failed += 1
    bot.send_message(message.chat.id,
        f"📣 *Posted!*\n✅ {success} | ❌ {failed}", parse_mode="Markdown")

def ban_from_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target = int(message.text.strip())
        ban_user(target)
        bot.send_message(message.chat.id, f"🚫 User {target} banned.")
        try:
            bot.send_message(target,
                f"🚫 *Account Suspended.*\n\n— *{COMPANY}*", parse_mode="Markdown")
        except:
            pass
    except:
        bot.send_message(message.chat.id, "❌ Invalid USER_ID!")

def unban_from_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target = int(message.text.strip())
        unban_user(target)
        bot.send_message(message.chat.id, f"✅ User {target} unbanned.")
    except:
        bot.send_message(message.chat.id, "❌ Invalid USER_ID!")

# ═══════════════════════════════════════════════════════
#              START BOT
# ═══════════════════════════════════════════════════════
API_PUBLIC_URL = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
if API_PUBLIC_URL:
    API_PUBLIC_URL = f"https://{API_PUBLIC_URL}"
else:
    API_PUBLIC_URL = os.environ.get("API_URL", "")

print(f"✅ {BOT_NAME} — WebApp Mining Bot is LIVE!")
print(f"— {COMPANY}")
print(f"🌐 WebApp: {WEBAPP_URL}")
print(f"🔗 API URL: {API_PUBLIC_URL}")
import sys

def start_polling():
    while True:
        try:
            print("Starting bot polling...")
            bot.delete_webhook(drop_pending_updates=True)
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)

start_polling()
