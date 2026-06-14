# SPA Email Alerts — Setup Guide

SPA sends two types of automated emails via GitHub Actions:

- **Risk alerts** — triggered immediately when `RiskAgent` detects concentration, drawdown, or cash-floor violations
- **4h cycle summary** — sent on every scheduled run with portfolio value, open positions, PnL, and recent trades

Both emails are sent through your Gmail account using an App Password (no OAuth needed).

---

## Step 1 — Enable Gmail 2-Factor Authentication

If you haven't already:

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Under **"How you sign in to Google"**, click **2-Step Verification**
3. Follow the prompts to enable it

2FA is required before Gmail will let you generate App Passwords.

---

## Step 2 — Generate a Gmail App Password

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   (or: Google Account → Security → App Passwords)
2. In the **"App name"** field, type `SPA Alerts`
3. Click **Create**
4. Google shows a **16-character password** — copy it now (it's only shown once)

> The App Password looks like: `abcd efgh ijkl mnop`
> Remove the spaces before pasting into GitHub: `abcdefghijklmnop`

---

## Step 3 — Add GitHub Secrets

1. Open your repo on GitHub: `github.com/YourUsername/SPA_Claude`
2. Go to **Settings → Secrets and variables → Actions**
3. Click **New repository secret** for each of the following:

| Secret name | Value |
|---|---|
| `SPA_ALERT_EMAIL` | `yuriycooleshov@gmail.com` |
| `SPA_ALERT_PASSWORD` | The 16-char App Password (no spaces) |
| `SPA_NOTIFY_EMAIL` | `yuriycooleshov@gmail.com` (or a different recipient) |

> `SPA_NOTIFY_EMAIL` is optional — if omitted, alerts go to `SPA_ALERT_EMAIL`.

---

## Step 4 — Test It

Trigger the workflow manually to verify everything works:

1. Go to your repo → **Actions** tab
2. Select **SPA — Run & Export**
3. Click **Run workflow** → **Run workflow**
4. Watch the **"Initialize DB & fetch DeFiLlama data"** step logs
5. You should see lines like:
   ```
   Cycle summary email: sent
   ```
   or, if there are active risk alerts:
   ```
   Risk alert email: sent
   ```

If you see `failed (no credentials?)`, double-check that the three secrets are set correctly.

---

## Troubleshooting

**`SMTPAuthenticationError`** — The App Password is wrong or has spaces. Re-generate one and paste without spaces.

**`failed (no credentials?)`** in logs** — `SPA_ALERT_EMAIL` secret is missing or empty. Check Settings → Secrets.

**No email received** — Check your spam folder. Gmail may flag automated sends the first time. Mark as "Not spam" to train it.

**`SPA_NOTIFY_EMAIL` not set** — That's fine; the email goes to the sender address (`SPA_ALERT_EMAIL`) by default.

---

## How It Works Internally

The email logic lives in `spa_core/alerts/email_sender.py`. It is called at the end of `export_data.py` (section 10) after all JSON exports are written. If the `SPA_ALERT_EMAIL` environment variable is not set, the entire block is skipped silently — so the bot works fine without email configured.

Gmail SMTP settings used: `smtp.gmail.com:465` (SSL).
