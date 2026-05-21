# Setting Up Telegram Alerts for SPA

Telegram alerts are simpler and faster than email — no SMTP, no app passwords, instant delivery.
The bot sends three types of messages:

- **Risk alerts** — immediate, whenever concentration or drawdown limits are breached
- **4h cycle summary** — compact snapshot after every data export
- **Weekly go-live update** — Monday morning readiness check

---

## Step 1 — Create a bot via @BotFather

1. Open Telegram and search for **@BotFather** (the official Telegram bot creation service).
2. Send `/newbot` and follow the prompts:
   - **Name**: `SPA Alerts` (this is the display name)
   - **Username**: something like `spa_yurii_alerts_bot` (must end in `bot`)
3. BotFather replies with your **token** — a string that looks like:
   ```
   123456789:ABC-DEFghijKLMNopqrSTUVwxyz
   ```
   Save this — it's `SPA_TELEGRAM_TOKEN`.

---

## Step 2 — Get your chat_id

1. Open a chat with your new bot and send it **any message** (e.g., "hello").
   This is required — Telegram won't deliver messages to chats the bot hasn't been introduced to.

2. Visit this URL in your browser (replace `{TOKEN}` with your actual token):
   ```
   https://api.telegram.org/bot{TOKEN}/getUpdates
   ```

3. In the JSON response, find:
   ```json
   "chat": {
     "id": 123456789,
     ...
   }
   ```
   That number is `SPA_TELEGRAM_CHAT_ID`.

> **Tip:** If the JSON is empty (`{"ok":true,"result":[]}`), send another message to your bot and reload the URL.

---

## Step 3 — Add secrets to GitHub

1. Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** and add:

   | Secret name           | Value                        |
   |-----------------------|------------------------------|
   | `SPA_TELEGRAM_TOKEN`  | `123456789:ABC-DEF...`        |
   | `SPA_TELEGRAM_CHAT_ID`| `123456789`                  |

---

## Step 4 — Test it

1. Go to **Actions** tab in your GitHub repository.
2. Select the **SPA — Run & Export** workflow.
3. Click **Run workflow** → **Run workflow** (manual trigger).
4. Watch the logs — you should see lines like:
   ```
   Telegram cycle summary: sent
   ```
5. Check Telegram — you should receive a `📊 SPA 4h Report` message within seconds.

> If you see `Telegram not configured` in the logs, double-check the secret names — they must match exactly (`SPA_TELEGRAM_TOKEN`, `SPA_TELEGRAM_CHAT_ID`).

---

## What the bot sends

### Risk alert (immediate, if thresholds are breached)
```
🚨 SPA Risk Alert

⚠️ 2 alert(s) detected

• CRITICAL: Maple concentration 48% > 45% limit
• WARNING: Portfolio drawdown -2.1% approaching 5% kill switch

💰 Portfolio: $100,138 | PnL: +$138 (+0.14%)
📊 View Dashboard
```

### 4h cycle summary (every run)
```
📊 SPA 4h Report · 16:00

💰 $100,138 | +0.14%
📈 APY: 4.35% weighted avg

Positions:
• Aave V3: $40K @4.23%
• Compound: $35K @4.02%
• Maple: $20K @4.80%

🟢 No alerts | Cash: 5%
```

### Weekly go-live update (Monday, 00:00–04:00 UTC)
```
🎯 SPA Go-Live Update

Verdict: 🔴 NOT READY (5/8 criteria)
Days remaining: 54

❌ Paper Duration: 1/50 days
✅ PnL: +$138
✅ No Critical Alerts
...

Next milestone: 2026-07-09
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No message received | Bot hasn't been messaged first | Send any message to the bot in Telegram |
| `HTTP error 401` in logs | Wrong token | Re-copy the token from BotFather |
| `HTTP error 400 Bad Request` | Wrong chat_id | Re-fetch from `/getUpdates` |
| Logs show "not configured" | Secrets missing or misnamed | Check GitHub Secrets spelling |
| Bot works locally but not in CI | Secrets not added to repo | Add both secrets in Settings → Secrets |

---

## Local testing

Set environment variables and run export manually:

```bash
export SPA_TELEGRAM_TOKEN="123456789:ABC-DEF..."
export SPA_TELEGRAM_CHAT_ID="123456789"
cd spa_core
python -c "
from alerts.telegram_sender import TelegramSender
tg = TelegramSender()
print('available:', tg.available)
ok = tg.send('✅ SPA Telegram test — it works!')
print('sent:', ok)
"
```

You should see `sent: True` and a message appear in Telegram immediately.
