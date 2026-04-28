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

# ═══════════════════════════════════════════════════════
#                    CONFIGURATION
# ═══════════════════════════════════════════════════════
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "8348643466:AAEuYJEhxjyY-NrIY6oNask_UwdlK_EI6zY")
ADMIN_ID    = int(os.environ.get("ADMIN_ID", "8065948352"))
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "phantommd2024")
MONGO_URL   = os.environ.get("MONGO_URL", "")

BOT_NAME     = "CashFlowBoard"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "CashFlowBoard_bot")
COMPANY      = "Phantom MD Technology"
MAINTENANCE_MODE = False

# ── Dynamic WebApp URL (Railway / any host) ──────────
_rail_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
if _rail_domain:
    WEBAPP_URL = f"https://{_rail_domain}"
else:
    WEBAPP_URL = os.environ.get("WEBAPP_URL",
                 "https://abrarali97987.github.io/cashflowboard-bot")

# ── Mining Constants ──────────────────────────────────
BASE_HPOWER            = 0
MINING_INTERVAL        = 3600       # seconds
COINS_PER_HPOWER       = 1
TASK_HPOWER_REWARD     = 50
REFER_HPOWER_REWARD    = 100
WITHDRAWAL_THRESHOLD   = 10000
DAILY_CHECKIN_HPOWER   = 15
DAILY_CHECKIN_COINS    = 50

# ── Startup validation ────────────────────────────────
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable not set!")
if not MONGO_URL:
    raise ValueError("❌ MONGO_URL environment variable not set!")

# ── MongoDB ───────────────────────────────────────────
try:
    mongo_client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
    mongo_client.server_info()
    db          = mongo_client["cashflowboard"]
    users_col   = db["users"]
    channels_col = db["channels"]
    tasks_col   = db["tasks"]
    banned_col  = db["banned"]
    print("✅ MongoDB connected!")
except Exception as e:
    raise ConnectionError(f"❌ MongoDB connection failed: {e}")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# ═══════════════════════════════════════════════════════
#                    DATABASE HELPERS
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
        }
        users_col.insert_one(user)
    user.pop("_id", None)
    return user

def update_user(user_id, data):
    users_col.update_one({"id": int(user_id)}, {"$set": data}, upsert=True)

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
            for user in load_all_users():
                try:
                    last = datetime.fromisoformat(user.get("last_mining", now.isoformat()))
                    diff = (now - last).total_seconds()
                    if diff >= MINING_INTERVAL:
                        hours  = int(diff // MINING_INTERVAL)
                        earned = hours * user.get("hpower", 0) * COINS_PER_HPOWER
                        if earned > 0:
                            update_user(user["id"], {
                                "coins":       user["coins"] + earned,
                                "last_mining": now.isoformat()
                            })
                except Exception as ue:
                    print(f"Mining error for user {user.get('id')}: {ue}")
        except Exception as e:
            print(f"Mining engine error: {e}")
        time.sleep(300)

threading.Thread(target=mining_engine, daemon=True).start()

# ═══════════════════════════════════════════════════════
#              TELEGRAM INITDATA VERIFICATION (FIXED)
# ═══════════════════════════════════════════════════════
def verify_telegram_data(init_data_str):
    try:
        parsed = {}
        for part in init_data_str.split("&"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            parsed[k] = unquote(v)

        hash_value = parsed.pop("hash", "")
        if not hash_value:
            return False, {}

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )
        # ✅ FIXED: was hmac.new (wrong), now hmac.new → hmac.HMAC correctly
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed   = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return computed == hash_value, parsed
    except Exception as e:
        print(f"Verify error: {e}")
        return False, {}

# ═══════════════════════════════════════════════════════
#              WEBAPP API SERVER
# ═══════════════════════════════════════════════════════
def get_webapp_html():
    for path in [
        os.path.join(os.path.dirname(__file__), "index.html"),
        "/app/index.html",
        "index.html"
    ]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return "<h1>WebApp file not found</h1>"

class WebAppAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence request logs

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)

    def _get_uid_from_params(self, params, init_data_str=""):
        """Try to extract user ID from initData or fallback uid param."""
        if init_data_str:
            valid, data = verify_telegram_data(init_data_str)
            try:
                user_info = json.loads(data.get("user", "{}"))
                uid = int(user_info.get("id", 0))
                if uid:
                    return uid, user_info
            except:
                pass
        try:
            uid = int(params.get("uid", [0])[0])
            if uid:
                return uid, {}
        except:
            pass
        return 0, {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)

        # ── Serve WebApp HTML ──────────────────────────────
        if path in ("/", "/index.html"):
            html = get_webapp_html()
            # ✅ Dynamic API URL injection — never hardcoded
            port = int(os.environ.get("PORT", 8080))
            domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
            if domain:
                api_url = f"https://{domain}"
            else:
                api_url = os.environ.get("API_URL", f"http://localhost:{port}")
            html = html.replace("__API_BASE_PLACEHOLDER__", api_url)
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # ── GET /api/user ──────────────────────────────────
        if path == "/api/user":
            init_data = params.get("init_data", [""])[0]
            uid, user_info = self._get_uid_from_params(params, init_data)
            if not uid:
                self.send_json({"error": "Unauthorized"}, 401)
                return
            username   = user_info.get("username", "")
            first_name = user_info.get("first_name", "Miner")
            user = get_user(uid, username, first_name)
            last = datetime.fromisoformat(user.get("last_mining", datetime.now().isoformat()))
            diff = (datetime.now() - last).total_seconds()
            next_mine = max(0, MINING_INTERVAL - (diff % MINING_INTERVAL))
            self.send_json({
                "id":                 str(user["id"]),
                "name":               user["first_name"],
                "username":           user.get("username", ""),
                "coins":              user["coins"],
                "hpower":             user["hpower"],
                "referrals":          user["referrals"],
                "withdrawn":          user.get("total_withdrawn", 0),
                "wallet":             user.get("wallet_address"),
                "last_checkin":       user.get("last_checkin", ""),
                "last_mining":        user.get("last_mining"),
                "next_mine_seconds":  int(next_mine),
                "pending_withdrawal": user.get("pending_withdrawal", False),
                "join_date":          user.get("join_date", "")
            })
            return

        # ── GET /api/leaderboard ───────────────────────────
        if path == "/api/leaderboard":
            top = sorted(load_all_users(), key=lambda x: x.get("hpower", 0), reverse=True)[:10]
            self.send_json([{"name": u["first_name"], "hpower": u["hpower"]} for u in top])
            return

        # ── GET /api/tasks ─────────────────────────────────
        if path == "/api/tasks":
            uid, _ = self._get_uid_from_params(params)
            user = get_user(uid) if uid else {}
            completed = user.get("completed_tasks", []) if user else []
            tasks = load_tasks()
            today = datetime.now().strftime("%Y-%m-%d")
            result = []
            for t in tasks:
                if t.get("type") == "daily":
                    done = f"{t['id']}_{today}" in completed
                else:
                    done = t["id"] in completed
                result.append({
                    "id":    t["id"],
                    "name":  t["name"],
                    "hpower": t["hpower"],
                    "link":  t["link"],
                    "type":  t.get("type", "one_time"),
                    "done":  done
                })
            self.send_json(result)
            return

        # ── GET /health ────────────────────────────────────
        if path == "/health":
            self.send_json({"status": "ok", "bot": BOT_NAME, "company": COMPANY})
            return

        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length)) if length else {}
        except:
            body = {}

        uid = body.get("uid")

        # ── POST /api/checkin ──────────────────────────────
        if path == "/api/checkin":
            if not uid:
                self.send_json({"error": "No uid"}, 400); return
            user  = get_user(uid)
            today = datetime.now().strftime("%Y-%m-%d")
            if user.get("last_checkin") == today:
                self.send_json({"success": False, "message": "Already checked in today!"}); return
            update_user(uid, {
                "last_checkin": today,
                "hpower":       user["hpower"] + DAILY_CHECKIN_HPOWER,
                "coins":        user["coins"]  + DAILY_CHECKIN_COINS
            })
            self.send_json({"success": True, "hpower_gained": DAILY_CHECKIN_HPOWER, "coins_gained": DAILY_CHECKIN_COINS})
            return

        # ── POST /api/withdraw ─────────────────────────────
        if path == "/api/withdraw":
            if not uid:
                self.send_json({"error": "No uid"}, 400); return
            user = get_user(uid)
            if user["coins"] < WITHDRAWAL_THRESHOLD:
                self.send_json({"success": False, "message": "Not enough coins!"}); return
            if user.get("pending_withdrawal"):
                self.send_json({"success": False, "message": "Pending request already exists!"}); return
            if not user.get("wallet_address"):
                self.send_json({"success": False, "message": "No wallet! Use /wallet in bot."}); return
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
            except Exception as e:
                print(f"Admin notify error: {e}")
            self.send_json({"success": True, "amount": usd})
            return

        # ── POST /api/task/complete ────────────────────────
        if path == "/api/task/complete":
            task_id = body.get("task_id")
            if not uid or not task_id:
                self.send_json({"error": "Missing uid or task_id"}, 400); return
            user      = get_user(uid)
            completed = user.get("completed_tasks", [])
            tasks     = load_tasks()
            task      = next((t for t in tasks if t["id"] == task_id), None)
            if not task:
                self.send_json({"error": "Task not found"}, 404); return

            today = datetime.now().strftime("%Y-%m-%d")
            if task.get("type") == "daily":
                key = f"{task_id}_{today}"
            else:
                key = task_id

            if key in completed:
                self.send_json({"success": False, "message": "Already completed!"}); return

            completed.append(key)
            new_hpower = user["hpower"] + task["hpower"]
            update_user(uid, {"completed_tasks": completed, "hpower": new_hpower})
            self.send_json({"success": True, "hpower_gained": task["hpower"], "new_hpower": new_hpower})
            return

        self.send_json({"error": "Not found"}, 404)

def start_api_server():
    port   = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), WebAppAPIHandler)
    print(f"✅ API Server running on port {port}")
    server.serve_forever()

threading.Thread(target=start_api_server, daemon=True).start()

# ═══════════════════════════════════════════════════════
#              HELPER FUNCTIONS
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
        kb.add(InlineKeyboardButton(f"📢 Join {ch}", url=f"https://t.me/{ch.replace('@','')}"))
    kb.add(InlineKeyboardButton("✅ I Joined — Verify Now", callback_data="verify_force_join"))
    return kb

def get_mining_status(user):
    last      = datetime.fromisoformat(user.get("last_mining", datetime.now().isoformat()))
    diff      = (datetime.now() - last).total_seconds()
    next_mine = max(0, MINING_INTERVAL - diff)
    hours     = int(diff // MINING_INTERVAL)
    pending   = hours * user["hpower"] * COINS_PER_HPOWER
    return pending, f"{int(next_mine//60)}m {int(next_mine%60)}s", hours

def get_miner_rank(hpower):
    if hpower >= 5000: return "💎 Diamond"
    if hpower >= 2000: return "🥇 Gold"
    if hpower >= 500:  return "🥈 Silver"
    return "🥉 Bronze"

# ═══════════════════════════════════════════════════════
#              KEYBOARDS
# ═══════════════════════════════════════════════════════
def main_menu_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("⛏️ OPEN MINING APP", web_app=WebAppInfo(url=WEBAPP_URL)))
    kb.add(
        InlineKeyboardButton("💳 My Wallet",  callback_data="my_wallet"),
        InlineKeyboardButton("💎 Withdraw",   callback_data="withdraw"),
        InlineKeyboardButton("ℹ️ Help",        callback_data="help")
    )
    return kb

def admin_menu_kb():
    status = "🔴 Maintenance ON" if MAINTENANCE_MODE else "🟢 Maintenance OFF"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Add Channel",      callback_data="admin_add_ch"),
        InlineKeyboardButton("➖ Remove Channel",   callback_data="admin_rem_ch"),
        InlineKeyboardButton("📋 Channels List",    callback_data="admin_list_ch"),
        InlineKeyboardButton("👥 All Users",        callback_data="admin_users"),
        InlineKeyboardButton("⚡ Adjust H-Power",   callback_data="admin_hpower"),
        InlineKeyboardButton("💎 Withdrawals",      callback_data="admin_withdrawals"),
        InlineKeyboardButton("📢 Broadcast",        callback_data="admin_broadcast"),
        InlineKeyboardButton("📣 Post to Channels", callback_data="admin_post_channels"),
        InlineKeyboardButton("🚫 Ban User",         callback_data="admin_ban"),
        InlineKeyboardButton("✅ Unban User",        callback_data="admin_unban"),
        InlineKeyboardButton("📊 Analytics",        callback_data="admin_analytics"),
        InlineKeyboardButton(status,                callback_data="toggle_maintenance"),
    )
    return kb

# ═══════════════════════════════════════════════════════
#              /start
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=["start"])
def start(message):
    global MAINTENANCE_MODE
    user_id    = message.from_user.id
    username   = message.from_user.username or ""
    first_name = message.from_user.first_name or "Miner"

    if is_banned(user_id):
        bot.send_message(message.chat.id,
            f"🚫 *Account Suspended*\n\nContact support.\n\n— *{COMPANY}*",
            parse_mode="Markdown"); return

    if MAINTENANCE_MODE and user_id != ADMIN_ID:
        bot.send_message(message.chat.id,
            f"🔧 *{BOT_NAME} — Maintenance Mode*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"We are currently upgrading our systems to serve you better.\n\n"
            f"⏳ Please check back shortly.\n"
            f"🚀 Something bigger is coming!\n\n"
            f"— *{COMPANY}*",
            parse_mode="Markdown"); return

    args = message.text.split()
    user = get_user(user_id, username, first_name)

    if len(args) > 1:
        try:
            ref_id = int(args[1])
            if ref_id != user_id and not user.get("referred_by"):
                update_user(user_id, {"referred_by": ref_id})
                ref = get_user(ref_id)
                update_user(ref_id, {
                    "hpower":    ref["hpower"] + REFER_HPOWER_REWARD,
                    "referrals": ref["referrals"] + 1
                })
                try:
                    bot.send_message(ref_id,
                        f"🎉 *New Referral!*\n\n"
                        f"👤 *{first_name}* joined using your link!\n"
                        f"⚡ +{REFER_HPOWER_REWARD} H-Power added!\n\n— *{COMPANY}*",
                        parse_mode="Markdown")
                except: pass
        except: pass

    joined, not_joined = check_force_join(user_id)
    if not joined:
        bot.send_message(message.chat.id,
            f"⛔ *Join Required*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Please join our channel(s) to access *{BOT_NAME}*.\n\n"
            f"📋 Join {len(not_joined)} channel(s) below 👇",
            parse_mode="Markdown",
            reply_markup=force_join_keyboard(not_joined)); return

    rank = get_miner_rank(user["hpower"])
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
#              /maintenance
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=["maintenance"])
def toggle_maintenance_cmd(message):
    global MAINTENANCE_MODE
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Access Denied!"); return
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    status = "🔴 ENABLED" if MAINTENANCE_MODE else "🟢 DISABLED"
    bot.send_message(message.chat.id,
        f"🔧 *Maintenance Mode: {status}*\n\n"
        f"{'Notifying all users...' if MAINTENANCE_MODE else 'Bot is now live!'}",
        parse_mode="Markdown")
    all_users = load_all_users()
    for u in all_users:
        if u["id"] == ADMIN_ID: continue
        try:
            if MAINTENANCE_MODE:
                bot.send_message(u["id"],
                    f"🔧 *{BOT_NAME} — Scheduled Maintenance*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"Our systems are undergoing a scheduled upgrade.\n\n"
                    f"⏳ Expected downtime: *Limited*\n"
                    f"🚀 We'll be back better than ever!\n\n"
                    f"Thank you for your patience.\n\n— *{COMPANY}*",
                    parse_mode="Markdown")
            else:
                bot.send_message(u["id"],
                    f"✅ *{BOT_NAME} — Back Online!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"Upgrade complete! Mining has resumed! ⚡\n\n— *{COMPANY}*",
                    parse_mode="Markdown")
            time.sleep(0.05)
        except: pass

# ═══════════════════════════════════════════════════════
#              /admin
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        print(f"[SECURITY] Unauthorized /admin from {message.from_user.id}")
        bot.send_message(message.chat.id, "❌ Access Denied!"); return
    parts = message.text.strip().split()
    if len(parts) < 2 or parts[1] != ADMIN_SECRET:
        bot.send_message(message.chat.id,
            "🔐 Usage: `/admin <secret_key>`", parse_mode="Markdown"); return
    all_u = load_all_users()
    chs   = load_channels()
    total_coins  = sum(u.get("coins",0)  for u in all_u)
    total_hpower = sum(u.get("hpower",0) for u in all_u)
    m_status = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
    bot.send_message(message.chat.id,
        f"👑 *ADMIN DASHBOARD*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: *{len(all_u)}*\n"
        f"📺 Active Channels: *{len(chs)}*\n"
        f"🪙 Total Coins: *{total_coins:,}*\n"
        f"⚡ Total H-Power: *{total_hpower:,}*\n"
        f"🔧 Maintenance: *{m_status}*\n"
        f"🌐 WebApp: {WEBAPP_URL}\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown", reply_markup=admin_menu_kb())

# ═══════════════════════════════════════════════════════
#              ADMIN COMMANDS (Text)
# ═══════════════════════════════════════════════════════
@bot.message_handler(commands=["addchannel"])
def add_channel(message):
    if message.from_user.id != ADMIN_ID: return
    msg = bot.send_message(message.chat.id,
        "📺 Send channel username:\nExample: `@MyChannel`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_add_channel)

def process_add_channel(message):
    if message.from_user.id != ADMIN_ID: return
    username = message.text.strip()
    if not username.startswith("@"): username = "@" + username
    for ch in load_channels():
        if ch["username"] == username:
            bot.send_message(message.chat.id, f"⚠️ {username} already exists!"); return
    channels_col.insert_one({"username": username, "added": datetime.now().strftime("%Y-%m-%d")})
    bot.send_message(message.chat.id,
        f"✅ *Channel Added!*\n📺 {username}", parse_mode="Markdown")

@bot.message_handler(commands=["removechannel"])
def remove_channel(message):
    if message.from_user.id != ADMIN_ID: return
    channels = load_channels()
    if not channels:
        bot.send_message(message.chat.id, "⚠️ No channels!"); return
    text = "📋 *Send username to remove:*\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch['username']}\n"
    msg = bot.send_message(message.chat.id, text, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_remove_channel)

def process_remove_channel(message):
    if message.from_user.id != ADMIN_ID: return
    username = message.text.strip()
    if not username.startswith("@"): username = "@" + username
    result = channels_col.delete_one({"username": username})
    if result.deleted_count:
        bot.send_message(message.chat.id, f"✅ *{username} removed!*", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, f"❌ {username} not found!")

@bot.message_handler(commands=["addtask"])
def add_task_cmd(message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id,
        "📋 *Add Task*\n\nFormat: `NAME | LINK | HPOWER`\n\nExample:\n"
        "`Watch Video | https://youtube.com/xyz | 30`\n"
        "`Daily Login | daily | 10`",
        parse_mode="Markdown")
    bot.register_next_step_handler(message, process_add_task)

def process_add_task(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.strip().split("|")
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Format: NAME | LINK | HPOWER"); return
        name, link, hpower = [p.strip() for p in parts]
        hpower = int(hpower)
        task_id = f"task_{int(time.time())}"
        t_type  = "daily" if link == "daily" else "one_time"
        tasks_col.insert_one({"id": task_id, "name": name, "link": link, "hpower": hpower, "type": t_type})
        bot.send_message(message.chat.id,
            f"✅ *Task Added!*\n📋 {name}\n⚡ +{hpower} H-Power\n🔄 {t_type.title()}",
            parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(commands=["sethpower"])
def set_hpower(message):
    if message.from_user.id != ADMIN_ID: return
    msg = bot.send_message(message.chat.id,
        "⚡ Send: `USER_ID HPOWER`\nExample: `123456 500`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_set_hpower)

def process_set_hpower(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.strip().split()
        target_id, hpower = int(parts[0]), int(parts[1])
        update_user(target_id, {"hpower": hpower})
        bot.send_message(message.chat.id, f"✅ User {target_id} H-Power → {hpower}!")
        try:
            bot.send_message(target_id,
                f"⚡ *H-Power Updated!*\nNew H-Power: *{hpower} H/hr*\nMining speed boosted! 🚀",
                parse_mode="Markdown")
        except: pass
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(commands=["broadcast"])
def broadcast_cmd(message):
    if message.from_user.id != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "📢 Send broadcast message:")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    all_u = load_all_users()
    chs   = load_channels()
    text  = f"📢 *{BOT_NAME} Announcement:*\n\n{message.text}"
    ch_ok = ch_fail = ok = fail = 0
    for ch in chs:
        try:
            bot.send_message(ch["username"], text, parse_mode="Markdown")
            ch_ok += 1; time.sleep(0.3)
        except: ch_fail += 1
    for u in all_u:
        try:
            bot.send_message(u["id"], text, parse_mode="Markdown")
            ok += 1; time.sleep(0.05)
        except: fail += 1
    bot.send_message(message.chat.id,
        f"✅ *Broadcast Done!*\n\n"
        f"📺 Channels: ✅{ch_ok} ❌{ch_fail}\n"
        f"👥 Users: ✅{ok} ❌{fail}", parse_mode="Markdown")

@bot.message_handler(commands=["ban"])
def ban_cmd(message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.strip().split()
    if len(parts) < 2: bot.send_message(message.chat.id, "Usage: /ban USER_ID"); return
    try:
        target = int(parts[1]); ban_user(target)
        bot.send_message(message.chat.id, f"🚫 User {target} banned.")
        try: bot.send_message(target, f"🚫 *Account Suspended.*\n\n— *{COMPANY}*", parse_mode="Markdown")
        except: pass
    except Exception as e: bot.send_message(message.chat.id, f"❌ {e}")

@bot.message_handler(commands=["unban"])
def unban_cmd(message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.strip().split()
    if len(parts) < 2: bot.send_message(message.chat.id, "Usage: /unban USER_ID"); return
    try:
        target = int(parts[1]); unban_user(target)
        bot.send_message(message.chat.id, f"✅ User {target} unbanned.")
        try: bot.send_message(target, f"✅ *Account Reinstated!* Keep mining! ⚡\n\n— *{COMPANY}*", parse_mode="Markdown")
        except: pass
    except Exception as e: bot.send_message(message.chat.id, f"❌ {e}")

@bot.message_handler(commands=["wallet"])
def wallet_cmd(message):
    user = get_user(message.from_user.id)
    wallet = user.get("wallet_address")
    kb = InlineKeyboardMarkup()
    if wallet:
        kb.add(InlineKeyboardButton("🔄 Change Wallet", callback_data="change_wallet"))
        text = (f"💳 *MY WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ Wallet Bound!\n\n📍 Address:\n`{wallet}`\n\n🌐 Network: USDT/TRC20")
    else:
        kb.add(InlineKeyboardButton("💳 Bind Wallet", callback_data="bind_wallet"))
        text = (f"💳 *BIND WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"❌ No wallet bound yet!\n\nSend your *USDT TRC20* address to receive withdrawals.\n\n⚠️ TRC20 network only!")
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=kb)
    if not wallet:
        bot.register_next_step_handler(message, process_wallet_bind)

def process_wallet_bind(message):
    address = message.text.strip()
    if not address.startswith("T") or len(address) != 34:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔄 Try Again", callback_data="bind_wallet"))
        bot.send_message(message.chat.id,
            "❌ *Invalid TRC20 Address!*\n\nMust start with *T* and be *34 characters*.",
            parse_mode="Markdown", reply_markup=kb); return
    update_user(message.from_user.id, {"wallet_address": address})
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💎 Withdraw Now", callback_data="withdraw"))
    bot.send_message(message.chat.id,
        f"✅ *Wallet Bound!*\n\n💳 `{address}`\n🌐 USDT/TRC20",
        parse_mode="Markdown", reply_markup=kb)

# Approve / Reject
@bot.message_handler(func=lambda m: m.text and m.text.startswith("/approve_") and m.from_user.id == ADMIN_ID)
def approve_withdrawal(message):
    try:
        target_id = int(message.text.split("_")[1])
        user = get_user(target_id)
        usd  = user["coins"] // WITHDRAWAL_THRESHOLD
        remaining = user["coins"] % WITHDRAWAL_THRESHOLD
        update_user(target_id, {"coins": remaining, "pending_withdrawal": False, "total_withdrawn": user.get("total_withdrawn",0)+usd})
        bot.send_message(message.chat.id, f"✅ Approved ${usd} for user {target_id}")
        bot.send_message(target_id,
            f"✅ *Withdrawal Approved!*\n💵 *${usd} USD* sent!\n🪙 Remaining: *{remaining:,}*\n\n— *{COMPANY}*",
            parse_mode="Markdown")
    except Exception as e: bot.send_message(message.chat.id, f"❌ {e}")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("/reject_") and m.from_user.id == ADMIN_ID)
def reject_withdrawal(message):
    try:
        target_id = int(message.text.split("_")[1])
        update_user(target_id, {"pending_withdrawal": False})
        bot.send_message(message.chat.id, f"✅ Rejected for user {target_id}")
        bot.send_message(target_id,
            f"❌ *Withdrawal Rejected*\n\nPlease contact support.\n\n— *{COMPANY}*",
            parse_mode="Markdown")
    except Exception as e: bot.send_message(message.chat.id, f"❌ {e}")

# ═══════════════════════════════════════════════════════
#              CALLBACK HANDLER
# ═══════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global MAINTENANCE_MODE
    user_id = call.from_user.id

    if is_banned(user_id):
        bot.answer_callback_query(call.id, "🚫 Account suspended."); return

    user = get_user(user_id, call.from_user.username or "", call.from_user.first_name or "Miner")

    if MAINTENANCE_MODE and user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "🔧 Under maintenance!"); return

    d = call.data

    if d == "verify_force_join":
        joined, not_joined = check_force_join(user_id)
        if joined:
            bot.answer_callback_query(call.id, "✅ Verified!")
            rank = get_miner_rank(user["hpower"])
            bot.edit_message_text(
                f"⛏️ *{BOT_NAME}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ Access Granted! {rank}\n\n"
                f"⚡ H-Power: *{user['hpower']} H/hr*\n"
                f"🪙 Coins: *{user['coins']:,}*\n\n"
                f"👇 Open the app to mine!\n\n— *{COMPANY}*",
                call.message.chat.id, call.message.message_id,
                parse_mode="Markdown", reply_markup=main_menu_kb())
        else:
            bot.answer_callback_query(call.id, f"❌ Still need to join {len(not_joined)} channel(s)!")

    elif d == "my_wallet":
        wallet = user.get("wallet_address")
        if wallet:
            text = f"💳 *MY WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n✅ Wallet Bound!\n\n📍 `{wallet}`\n🌐 USDT/TRC20\n💵 Total Withdrawn: *${user.get('total_withdrawn',0)} USD*"
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔄 Change Wallet", callback_data="change_wallet"))
        else:
            text = f"💳 *MY WALLET*\n━━━━━━━━━━━━━━━━━━━━\n\n❌ No wallet bound yet!\n\nUse /wallet to bind USDT TRC20."
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💳 Bind Wallet", callback_data="bind_wallet"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=kb)

    elif d == "bind_wallet":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "💳 Send your USDT TRC20 wallet address:\n\n⚠️ TRC20 network only!")
        bot.register_next_step_handler(msg, process_wallet_bind)

    elif d == "change_wallet":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "💳 Send your new USDT TRC20 address:")
        bot.register_next_step_handler(msg, process_wallet_bind)

    elif d == "withdraw":
        coins  = user["coins"]
        usd    = coins // WITHDRAWAL_THRESHOLD
        needed = WITHDRAWAL_THRESHOLD - (coins % WITHDRAWAL_THRESHOLD)
        wallet = user.get("wallet_address")
        pct    = min(100, coins/WITHDRAWAL_THRESHOLD*100)
        if not wallet:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💳 Bind Wallet First", callback_data="bind_wallet"))
            bot.edit_message_text(
                f"💎 *WITHDRAWAL*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚠️ No wallet bound!\n🪙 Coins: *{coins:,}*\n\nBind your TRC20 wallet first.",
                call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        elif user.get("pending_withdrawal"):
            bot.answer_callback_query(call.id, "⏳ Withdrawal already pending!")
        elif coins < WITHDRAWAL_THRESHOLD:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📋 Tasks", callback_data="back_main"),
                   InlineKeyboardButton("🔙 Back", callback_data="back_main"))
            bot.edit_message_text(
                f"💎 *WITHDRAWAL*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"❌ Need *{needed:,}* more coins!\n"
                f"🪙 Your Coins: *{coins:,}*\n"
                f"📊 Progress: *{pct:.1f}%*",
                call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        else:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💰 Cash Out Now", callback_data="confirm_withdraw"))
            kb.add(InlineKeyboardButton("🔄 Change Wallet", callback_data="change_wallet"))
            bot.edit_message_text(
                f"💎 *WITHDRAWAL AVAILABLE!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🪙 Coins: *{coins:,}*\n"
                f"💵 Amount: *${usd} USD*\n"
                f"💳 Wallet: `{wallet[:10]}...{wallet[-6:]}`\n"
                f"🌐 Network: USDT/TRC20\n\n"
                f"Press *Cash Out Now* to submit!",
                call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)

    elif d == "confirm_withdraw":
        coins  = user["coins"]
        usd    = coins // WITHDRAWAL_THRESHOLD
        wallet = user.get("wallet_address","NOT SET")
        update_user(user_id, {"pending_withdrawal": True})
        try:
            bot.send_message(ADMIN_ID,
                f"💎 *WITHDRAWAL REQUEST*\n━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 {call.from_user.first_name} | `{user_id}`\n"
                f"🪙 Coins: *{coins:,}*\n💵 Amount: *${usd} USD*\n"
                f"💳 Wallet: `{wallet}`\n\n"
                f"✅ /approve_{user_id}\n❌ /reject_{user_id}",
                parse_mode="Markdown")
        except: pass
        bot.edit_message_text(
            f"✅ *Request Submitted!*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 Amount: *${usd} USD*\n⏳ Processing: 24 hours\n\n"
            f"You'll be notified once processed!\n\n— *{COMPANY}*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

    elif d == "help":
        bot.edit_message_text(
            f"ℹ️ *HOW IT WORKS*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ *H-Power* = Mining speed (H/hr)\n"
            f"🔋 *Auto Mining* runs 24/7\n"
            f"Formula: H-Power × Hours = Coins\n\n"
            f"🏅 *Ranks*\n"
            f"🥉 Bronze: 0–499 H/hr\n🥈 Silver: 500–1999 H/hr\n"
            f"🥇 Gold: 2000–4999 H/hr\n💎 Diamond: 5000+ H/hr\n\n"
            f"📋 *Earn H-Power*\n"
            f"• Tasks: +{TASK_HPOWER_REWARD} H/hr\n"
            f"• Referral: +{REFER_HPOWER_REWARD} H/hr\n"
            f"• Daily check-in: +{DAILY_CHECKIN_HPOWER} H/hr\n\n"
            f"💎 *Withdrawal*\n10,000 Coins = $1 USD (USDT TRC20)\n\n"
            f"📞 Support: @PakEarnPros\n\n— *{COMPANY}*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

    elif d == "toggle_maintenance":
        if user_id != ADMIN_ID: return
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        status = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
        bot.answer_callback_query(call.id, f"Maintenance: {status}")
        all_u = load_all_users()
        for u in all_u:
            if u["id"] == ADMIN_ID: continue
            try:
                msg_text = (
                    f"🔧 *{BOT_NAME} — Maintenance*\n\nUpgrade in progress. Back shortly!\n\n— *{COMPANY}*"
                    if MAINTENANCE_MODE else
                    f"✅ *{BOT_NAME} — Back Online!*\n\nMining resumed! ⚡\n\n— *{COMPANY}*"
                )
                bot.send_message(u["id"], msg_text, parse_mode="Markdown")
                time.sleep(0.05)
            except: pass

    elif d == "admin_analytics":
        if user_id != ADMIN_ID: return
        all_u = load_all_users()   # ✅ FIXED: was undefined 'users'
        total_coins    = sum(u.get("coins",0)  for u in all_u)
        total_hpower   = sum(u.get("hpower",0) for u in all_u)
        pending_w      = sum(1 for u in all_u if u.get("pending_withdrawal"))
        total_withdrawn= sum(u.get("total_withdrawn",0) for u in all_u)
        today          = datetime.now().strftime("%Y-%m-%d")
        new_today      = sum(1 for u in all_u if u.get("join_date") == today)
        bot.edit_message_text(
            f"📊 *ANALYTICS*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Total Users: *{len(all_u)}*\n"
            f"🆕 Joined Today: *{new_today}*\n"
            f"🪙 Total Coins: *{total_coins:,}*\n"
            f"⚡ Total H-Power: *{total_hpower:,}*\n"
            f"💎 Pending Withdrawals: *{pending_w}*\n"
            f"💵 Total Paid Out: *${total_withdrawn} USD*",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=admin_menu_kb())

    elif d == "admin_list_ch":
        if user_id != ADMIN_ID: return
        channels = load_channels()
        text = "📋 *Channels:*\n\n" + ("\n".join(f"{i}. {ch['username']}" for i,ch in enumerate(channels,1)) or "None added yet.")
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=admin_menu_kb())

    elif d == "admin_withdrawals":
        if user_id != ADMIN_ID: return
        pending = [u for u in load_all_users() if u.get("pending_withdrawal")]
        text = f"💎 *Pending: {len(pending)}*\n\n"
        for u in pending:
            usd = u["coins"] // WITHDRAWAL_THRESHOLD
            text += f"👤 {u['first_name']} | `{u['id']}` | ${usd}\n/approve_{u['id']}  /reject_{u['id']}\n\n"
        if not pending: text += "No pending withdrawals."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=admin_menu_kb())

    elif d == "admin_add_ch":
        if user_id != ADMIN_ID: return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "📺 Send channel username:\nExample: `@MyChannel`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_channel)

    elif d == "admin_rem_ch":
        if user_id != ADMIN_ID: return
        bot.answer_callback_query(call.id)
        channels = load_channels()
        text = "📋 *Send username to remove:*\n\n" + "\n".join(f"{i}. {ch['username']}" for i,ch in enumerate(channels,1))
        msg = bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_remove_channel)

    elif d == "admin_hpower":
        if user_id != ADMIN_ID: return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "⚡ Send: `USER_ID HPOWER`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_set_hpower)

    elif d == "admin_broadcast":
        if user_id != ADMIN_ID: return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "📢 Send broadcast message:")
        bot.register_next_step_handler(msg, process_broadcast)

    elif d == "admin_post_channels":
        if user_id != ADMIN_ID: return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id,
            "📣 Send message to post in ALL channels\n(Bot must be admin in channels):")
        bot.register_next_step_handler(msg, process_post_to_channels)

    elif d == "admin_ban":
        if user_id != ADMIN_ID: return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🚫 Send USER_ID to ban:")
        bot.register_next_step_handler(msg, lambda m: (ban_user(int(m.text.strip())),
            bot.send_message(m.chat.id, f"🚫 Banned {m.text.strip()}!")))

    elif d == "admin_unban":
        if user_id != ADMIN_ID: return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "✅ Send USER_ID to unban:")
        bot.register_next_step_handler(msg, lambda m: (unban_user(int(m.text.strip())),
            bot.send_message(m.chat.id, f"✅ Unbanned {m.text.strip()}!")))

    elif d == "admin_users":
        if user_id != ADMIN_ID: return
        total = users_col.count_documents({})
        bot.answer_callback_query(call.id, f"👥 Total Users: {total}")

    elif d == "back_main":
        rank = get_miner_rank(user["hpower"])
        _, next_mine, _ = get_mining_status(user)
        bot.edit_message_text(
            f"⛏️ *{BOT_NAME}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ H-Power: *{user['hpower']} H/hr* {rank}\n"
            f"🪙 Coins: *{user['coins']:,}*\n⏳ Next Mine: *{next_mine}*\n\n"
            f"Select an option below 👇",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown", reply_markup=main_menu_kb())

def process_post_to_channels(message):
    if message.from_user.id != ADMIN_ID: return
    channels = load_channels()
    ok = fail = 0
    for ch in channels:
        try:
            bot.send_message(ch["username"], message.text, parse_mode="Markdown")
            ok += 1; time.sleep(0.3)
        except: fail += 1
    bot.send_message(message.chat.id, f"📣 Posted!\n✅ {ok} | ❌ {fail}", parse_mode="Markdown")

# ═══════════════════════════════════════════════════════
#              START BOT (Auto-restart polling)
# ═══════════════════════════════════════════════════════
print(f"\n{'═'*50}")
print(f"  ⛏️  {BOT_NAME} — {COMPANY}")
print(f"  🌐  WebApp: {WEBAPP_URL}")
print(f"  🤖  Bot: @{BOT_USERNAME}")
print(f"{'═'*50}\n")

def start_polling():
    while True:
        try:
            print("🔄 Starting bot polling...")
            bot.delete_webhook(drop_pending_updates=True)
            bot.polling(none_stop=True, interval=0, timeout=30)
        except Exception as e:
            print(f"⚠️ Polling error: {e} — restarting in 5s...")
            time.sleep(5)

start_polling()
