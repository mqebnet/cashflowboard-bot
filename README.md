# ⛏️ CashFlowBoard — Telegram Mining Bot + WebApp

**Phantom MD Technology**

A professional Telegram H-Power Mining bot with a full WebApp dashboard.

---

## 🚀 Features

- ⚡ Auto H-Power Mining (24/7)
- 🎮 Telegram WebApp Dashboard
- 📋 Task System (admin-managed)
- 👥 Referral Program (+100 H-Power per referral)
- 🎁 Daily Check-in Rewards
- 💎 USDT TRC20 Withdrawal System
- 🏆 Real-time Leaderboard
- 🔒 Force Join Channels
- 👑 Full Admin Panel
- 📢 Broadcast to users & channels

---

## 📁 File Structure

```
cashflowboard-bot/
├── bot.py           ← Telegram Bot + API Server
├── requirements.txt ← Python dependencies
├── index.html       ← WebApp (GitHub Pages)
├── README.md
└── data/            ← Auto-created by bot
    ├── users.json
    ├── channels.json
    ├── tasks.json
    └── banned.json
```

---

## ⚙️ Setup Guide

### 1. Bot Token
Get your bot token from [@BotFather](https://t.me/BotFather)

### 2. Environment Variables
Set these before running:
```
BOT_TOKEN=your_bot_token_here
ADMIN_ID=your_telegram_id
ADMIN_SECRET=your_secret_key
WEBAPP_URL=https://abrarali97987.github.io/cashflowboard-bot
```

### 3. Deploy Bot (Railway)
1. Go to [railway.app](https://railway.app)
2. New Project → Deploy from GitHub
3. Select this repo
4. Add environment variables
5. Bot starts automatically!

### 4. WebApp (GitHub Pages)
1. Go to repo Settings → Pages
2. Source: `main` branch, `/ (root)`
3. Your WebApp URL: `https://abrarali97987.github.io/cashflowboard-bot`

### 5. Update index.html
In `index.html`, update:
```javascript
const API_BASE = 'https://YOUR-RAILWAY-URL.railway.app';
```

---

## 💰 Mining System

| Rank | H-Power | 
|------|---------|
| 🥉 Bronze | 0–499 H/hr |
| 🥈 Silver | 500–1999 H/hr |
| 🥇 Gold | 2000–4999 H/hr |
| 💎 Diamond | 5000+ H/hr |

**10,000 Coins = $1 USD (USDT TRC20)**

---

## 🤖 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/wallet` | Bind USDT TRC20 wallet |
| `/admin <secret>` | Admin panel |
| `/addchannel` | Add force-join channel |
| `/removechannel` | Remove channel |
| `/addtask` | Add task |
| `/removetask` | Remove task |
| `/sethpower` | Set user H-Power |
| `/broadcast` | Broadcast message |
| `/ban USER_ID` | Ban user |
| `/unban USER_ID` | Unban user |

---

*© Phantom MD Technology — CashFlowBoard*
