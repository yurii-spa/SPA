# Decision: Email Alerts Removed (2026-06-21)

**Status:** REJECTED — Telegram replaces this entirely

Code exists in `spa_core/alerts/email_sender.py` but was never deployed (no credentials).
All notifications go via Telegram: daily@08:00, weekly@Sunday, spikes, governance, T2 alerts.

**If email needed in future:** Configure `GMAIL_APP_PASSWORD` or `SENDGRID_API_KEY` in Keychain
as appropriate, then update `spa_core/alerts/email_sender.py` credential lookup.
