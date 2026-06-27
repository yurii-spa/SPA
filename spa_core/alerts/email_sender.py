"""
SPA Email Alerts — sends via Gmail SMTP using GitHub Actions secrets.
Secrets expected: SPA_ALERT_EMAIL (sender), SPA_ALERT_PASSWORD (app password),
                  SPA_NOTIFY_EMAIL (recipient, defaults to sender if not set)
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from spa_core.utils import clock

log = logging.getLogger("spa.alerts.email")


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------

def send_alert(subject: str, body_html: str, body_text: str) -> bool:
    """
    Send an email alert via Gmail SMTP.

    Reads credentials from environment variables:
        SPA_ALERT_EMAIL    — Gmail sender address
        SPA_ALERT_PASSWORD — Gmail App Password (16 chars, no spaces)
        SPA_NOTIFY_EMAIL   — Recipient address (defaults to SPA_ALERT_EMAIL)

    Returns True on success, False on any failure. Never raises.
    """
    sender = os.getenv("SPA_ALERT_EMAIL", "").strip()
    password = os.getenv("SPA_ALERT_PASSWORD", "").strip()
    recipient = os.getenv("SPA_NOTIFY_EMAIL", sender).strip()

    if not sender or not password:
        log.warning("Email not configured — SPA_ALERT_EMAIL / SPA_ALERT_PASSWORD not set, skipping.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"SPA Bot 🤖 <{sender}>"
        msg["To"] = recipient

        # Attach plain-text first, HTML second (preferred by email clients)
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        log.info(f"Email sent → {recipient}: {subject}")
        return True

    except smtplib.SMTPAuthenticationError as exc:
        log.error(f"Email auth failed (check App Password): {exc}")
        return False
    except smtplib.SMTPException as exc:
        log.error(f"SMTP error sending email: {exc}")
        return False
    except Exception as exc:
        log.error(f"Unexpected error sending email: {exc}")
        return False


# ---------------------------------------------------------------------------
# Email builders
# ---------------------------------------------------------------------------

def build_risk_alert_email(
    alerts: list[dict],
    portfolio: dict,
) -> tuple[str, str, str]:
    """
    Build a risk-alert email.

    Returns (subject, html_body, text_body).
    """
    now_str = clock.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    count = len(alerts)
    subject = f"🚨 SPA Risk Alert: {count} alert(s) — {now_str}"

    # ---- HTML ---------------------------------------------------------------
    severity_badge = {
        "critical": '<span style="background:#dc2626;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;">CRITICAL</span>',
        "warning":  '<span style="background:#f59e0b;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700;">WARNING</span>',
    }

    alert_rows = ""
    for a in alerts:
        badge = severity_badge.get(a.get("severity", "warning").lower(), severity_badge["warning"])
        protocol = a.get("protocol", a.get("protocol_key", "—"))
        message  = a.get("message", "")
        alert_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{badge}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;">{protocol}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{message}</td>
        </tr>"""

    total_val   = portfolio.get("total_capital_usd", 0)
    cash_usd    = portfolio.get("cash_usd", 0)
    invested    = portfolio.get("invested_usd", 0)
    total_pnl   = portfolio.get("total_pnl_usd", 0)
    total_pnl_p = portfolio.get("total_pnl_pct", 0)
    pnl_color   = "#16a34a" if total_pnl >= 0 else "#dc2626"
    pnl_sign    = "+" if total_pnl >= 0 else ""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif;">
  <div style="max-width:600px;margin:32px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">

    <!-- Header -->
    <div style="background:#dc2626;padding:24px 32px;">
      <h1 style="margin:0;color:#fff;font-size:22px;">🚨 SPA Risk Alert</h1>
      <p style="margin:6px 0 0;color:#fecaca;font-size:14px;">{now_str} &nbsp;|&nbsp; {count} active alert(s)</p>
    </div>

    <!-- Alerts table -->
    <div style="padding:24px 32px;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#111827;">Active Alerts</h2>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Severity</th>
            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Protocol</th>
            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Message</th>
          </tr>
        </thead>
        <tbody>{alert_rows}
        </tbody>
      </table>
    </div>

    <!-- Portfolio snapshot -->
    <div style="padding:0 32px 24px;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#111827;">Portfolio Snapshot</h2>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;background:#f9fafb;border-radius:6px;overflow:hidden;">
        <tr>
          <td style="padding:10px 16px;color:#6b7280;">Total Value</td>
          <td style="padding:10px 16px;text-align:right;font-weight:700;">${total_val:,.2f}</td>
        </tr>
        <tr style="background:#fff;">
          <td style="padding:10px 16px;color:#6b7280;">Cash</td>
          <td style="padding:10px 16px;text-align:right;">${cash_usd:,.2f}</td>
        </tr>
        <tr>
          <td style="padding:10px 16px;color:#6b7280;">Invested</td>
          <td style="padding:10px 16px;text-align:right;">${invested:,.2f}</td>
        </tr>
        <tr style="background:#fff;">
          <td style="padding:10px 16px;color:#6b7280;">Total PnL</td>
          <td style="padding:10px 16px;text-align:right;font-weight:700;color:{pnl_color};">{pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pnl_p:.2f}%)</td>
        </tr>
      </table>
    </div>

    <!-- Footer -->
    <div style="background:#f9fafb;padding:16px 32px;text-align:center;border-top:1px solid #e5e7eb;">
      <a href="https://yuriiykulieshov.github.io/SPA_Claude/" style="color:#6366f1;font-size:13px;text-decoration:none;">Open SPA Dashboard →</a>
      <p style="margin:8px 0 0;color:#9ca3af;font-size:12px;">Smart Passive Aggregator · Paper Trading Bot</p>
    </div>
  </div>
</body>
</html>"""

    # ---- Plain text ---------------------------------------------------------
    lines = [
        f"SPA RISK ALERT — {now_str}",
        f"{count} active alert(s)",
        "",
        "ALERTS",
        "------",
    ]
    for a in alerts:
        sev      = a.get("severity", "warning").upper()
        protocol = a.get("protocol", a.get("protocol_key", "—"))
        message  = a.get("message", "")
        lines.append(f"[{sev}] {protocol}: {message}")

    lines += [
        "",
        "PORTFOLIO SNAPSHOT",
        "------------------",
        f"Total Value : ${total_val:,.2f}",
        f"Cash        : ${cash_usd:,.2f}",
        f"Invested    : ${invested:,.2f}",
        f"Total PnL   : {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pnl_p:.2f}%)",
        "",
        "Dashboard: https://yuriiykulieshov.github.io/SPA_Claude/",
    ]
    text = "\n".join(lines)

    return subject, html, text


def build_cycle_summary_email(
    portfolio: dict,
    positions: list[dict],
    new_trades: list[dict],
) -> tuple[str, str, str]:
    """
    Build a 4-hour cycle summary email.

    Returns (subject, html_body, text_body).
    """
    now_str    = clock.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    date_str   = clock.utcnow().strftime("%Y-%m-%d")
    total_val  = portfolio.get("total_capital_usd", 0)
    cash_usd   = portfolio.get("cash_usd", 0)
    invested   = portfolio.get("invested_usd", 0)
    total_pnl  = portfolio.get("total_pnl_usd", 0)
    total_pnl_p = portfolio.get("total_pnl_pct", 0)
    pnl_sign   = "+" if total_pnl >= 0 else ""
    pnl_color  = "#16a34a" if total_pnl >= 0 else "#dc2626"

    subject = f"📊 SPA 4h Report — {date_str} | PnL: {pnl_sign}{total_pnl_p:.2f}%"

    # Best APY across open positions
    apys = [p.get("current_apy", 0) or 0 for p in positions if p.get("status") == "open"]
    best_apy = max(apys) if apys else 0.0

    # ---- Positions table rows -----------------------------------------------
    pos_rows = ""
    open_positions = [p for p in positions if p.get("status") == "open"]
    if open_positions:
        for p in open_positions:
            protocol  = p.get("protocol_key", "—")
            value     = p.get("current_value_usd", p.get("entry_value_usd", 0)) or 0
            apy       = p.get("current_apy", 0) or 0
            pos_pnl   = p.get("unrealized_pnl_usd", 0) or 0
            pos_pnl_p = p.get("unrealized_pnl_pct", 0) or 0
            pos_sign  = "+" if pos_pnl >= 0 else ""
            pos_color = "#16a34a" if pos_pnl >= 0 else "#dc2626"
            pos_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;">{protocol}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">${value:,.2f}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{apy:.1f}%</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;color:{pos_color};">{pos_sign}${pos_pnl:,.2f} ({pos_sign}{pos_pnl_p:.2f}%)</td>
        </tr>"""
    else:
        pos_rows = '<tr><td colspan="4" style="padding:16px;text-align:center;color:#9ca3af;">No open positions</td></tr>'

    # ---- New trades rows ----------------------------------------------------
    trade_rows = ""
    if new_trades:
        for t in new_trades:
            protocol   = t.get("protocol_key", "—")
            action     = t.get("action", "—").upper()
            amount     = t.get("amount_usd", 0) or 0
            ts         = t.get("timestamp", "—")
            action_color = "#16a34a" if action == "BUY" else "#dc2626"
            trade_rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{ts[:16] if len(str(ts)) > 16 else ts}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;">{protocol}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:{action_color};font-weight:700;">{action}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">${amount:,.2f}</td>
        </tr>"""
    else:
        trade_rows = '<tr><td colspan="4" style="padding:16px;text-align:center;color:#9ca3af;">No new trades this cycle</td></tr>'

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif;">
  <div style="max-width:620px;margin:32px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">

    <!-- Header -->
    <div style="background:#4f46e5;padding:24px 32px;">
      <h1 style="margin:0;color:#fff;font-size:22px;">📊 SPA 4h Cycle Report</h1>
      <p style="margin:6px 0 0;color:#c7d2fe;font-size:14px;">{now_str}</p>
    </div>

    <!-- KPI strip -->
    <div style="display:flex;padding:20px 32px;gap:16px;background:#fafafa;border-bottom:1px solid #e5e7eb;">
      <div style="flex:1;text-align:center;">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;">Portfolio Value</div>
        <div style="font-size:20px;font-weight:700;color:#111827;margin-top:4px;">${total_val:,.0f}</div>
      </div>
      <div style="flex:1;text-align:center;">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;">Total PnL</div>
        <div style="font-size:20px;font-weight:700;color:{pnl_color};margin-top:4px;">{pnl_sign}{total_pnl_p:.2f}%</div>
      </div>
      <div style="flex:1;text-align:center;">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;">Best APY</div>
        <div style="font-size:20px;font-weight:700;color:#059669;margin-top:4px;">{best_apy:.1f}%</div>
      </div>
      <div style="flex:1;text-align:center;">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;">Cash</div>
        <div style="font-size:20px;font-weight:700;color:#111827;margin-top:4px;">${cash_usd:,.0f}</div>
      </div>
    </div>

    <!-- Open positions -->
    <div style="padding:24px 32px 0;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#111827;">Open Positions ({len(open_positions)})</h2>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Protocol</th>
            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Value</th>
            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">APY</th>
            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Unrealized PnL</th>
          </tr>
        </thead>
        <tbody>{pos_rows}
        </tbody>
      </table>
    </div>

    <!-- Recent trades -->
    <div style="padding:24px 32px;">
      <h2 style="margin:0 0 16px;font-size:16px;color:#111827;">Recent Trades (last 5)</h2>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Time</th>
            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Protocol</th>
            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Action</th>
            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:12px;text-transform:uppercase;">Amount</th>
          </tr>
        </thead>
        <tbody>{trade_rows}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="background:#f9fafb;padding:16px 32px;text-align:center;border-top:1px solid #e5e7eb;">
      <a href="https://yuriiykulieshov.github.io/SPA_Claude/" style="color:#6366f1;font-size:13px;text-decoration:none;">Open SPA Dashboard →</a>
      <p style="margin:8px 0 0;color:#9ca3af;font-size:12px;">Smart Passive Aggregator · Paper Trading Bot · {now_str}</p>
    </div>
  </div>
</body>
</html>"""

    # ---- Plain text ---------------------------------------------------------
    lines = [
        f"SPA 4h CYCLE REPORT — {now_str}",
        "=" * 40,
        f"Portfolio Value : ${total_val:,.2f}",
        f"Total PnL       : {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pnl_p:.2f}%)",
        f"Best APY        : {best_apy:.1f}%",
        f"Cash            : ${cash_usd:,.2f}",
        f"Invested        : ${invested:,.2f}",
        "",
        "OPEN POSITIONS",
        "-" * 40,
    ]
    for p in open_positions:
        protocol  = p.get("protocol_key", "—")
        value     = p.get("current_value_usd", p.get("entry_value_usd", 0)) or 0
        apy       = p.get("current_apy", 0) or 0
        pos_pnl   = p.get("unrealized_pnl_usd", 0) or 0
        pos_pnl_p = p.get("unrealized_pnl_pct", 0) or 0
        pos_sign  = "+" if pos_pnl >= 0 else ""
        lines.append(f"  {protocol:<30} ${value:>10,.2f}  APY:{apy:>5.1f}%  PnL:{pos_sign}${pos_pnl:,.2f} ({pos_sign}{pos_pnl_p:.2f}%)")

    if not open_positions:
        lines.append("  (no open positions)")

    lines += ["", "RECENT TRADES (last 5)", "-" * 40]
    for t in new_trades:
        protocol = t.get("protocol_key", "—")
        action   = t.get("action", "—").upper()
        amount   = t.get("amount_usd", 0) or 0
        ts       = str(t.get("timestamp", "—"))[:16]
        lines.append(f"  {ts}  {action:<4} {protocol:<30} ${amount:,.2f}")

    if not new_trades:
        lines.append("  (no new trades this cycle)")

    lines += [
        "",
        "Dashboard: https://yuriiykulieshov.github.io/SPA_Claude/",
    ]
    text = "\n".join(lines)

    return subject, html, text
