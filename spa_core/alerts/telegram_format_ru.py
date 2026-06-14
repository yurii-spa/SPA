"""MP-136: Russian-language formatter for Telegram red-flag alerts.

Converts raw alert dicts (from ``data/red_flags.json``) into human-readable
Russian Telegram messages, including:

* Short alert block with WHY the event matters (``format_alert_ru``).
* Full detail message for the "📋 Подробнее" button (``format_alert_detail_ru``).
* Inline keyboard with "📋 Подробнее" buttons per CRITICAL/WARN alert
  (``build_detail_keyboard``).
* Combined message builder (``format_message_ru``).

Design constraints
------------------
* Pure formatting — no I/O, no network, no side effects.
* Stdlib only.
* Never raises — every public function is defensive.

Callback data format for "Подробнее" buttons
--------------------------------------------
``detail_{protocol}__{category}``
Examples::
    detail_aave-v3__governance_proposal
    detail_ethena-susde__token_unlock

Double-underscore separator (``__``) makes protocol + category unambiguous
because neither field ever contains ``__``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# ─── Lookup tables ────────────────────────────────────────────────────────────

PROTOCOL_NAMES: dict[str, str] = {
    "aave-v3":         "Aave V3",
    "compound-v3":     "Compound V3",
    "morpho":          "Morpho Blue",
    "morpho-blue":     "Morpho Blue",
    "yearn-v3":        "Yearn V3",
    "euler-v2":        "Euler V2",
    "maple":           "Maple Finance",
    "sky":             "Sky / sUSDS",
    "susds":           "Sky / sUSDS",
    "pendle-pt":       "Pendle PT",
    "curve-usdc-usdt": "Curve USDC/USDT",
    "ethena-susde":    "Ethena sUSDe",
}

SEVERITY_EMOJI: dict[str, str] = {
    "CRITICAL": "🔴",
    "WARN":     "🟡",
    "INFO":     "🔵",
    "OK":       "✅",
}

MONTH_NAMES_RU: dict[int, str] = {
    1:  "января",
    2:  "февраля",
    3:  "марта",
    4:  "апреля",
    5:  "мая",
    6:  "июня",
    7:  "июля",
    8:  "августа",
    9:  "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

# Short explanations shown in the main alert block (why the event matters).
_ALERT_EXPLANATIONS: dict[str, str] = {
    "token_unlock": (
        "Когда крупный процент токенов поступает на рынок одновременно, "
        "это часто создаёт давление на продажу и снижение цены."
    ),
    "governance_proposal": (
        "Предложение может изменить параметры протокола, условия вывода "
        "или уровень риска. Рекомендуется следить за голосованием."
    ),
    "tvl_drop": (
        "Резкое падение ликвидности может указывать на отток средств или "
        "потерю доверия к протоколу. APY может расти искусственно."
    ),
    "apy_spike": (
        "Аномально высокий APY часто сигнализирует о временном дисбалансе "
        "или субсидировании. Открытие новых позиций несёт повышенный риск."
    ),
}

# Source-link templates per category.
_SOURCE_URL_TEMPLATES: dict[str, str] = {
    "token_unlock":        "https://tokenunlocks.app/",
    "governance_proposal": "https://snapshot.org/#/",
    "tvl_drop":            "https://defillama.com/protocol/",
    "apy_spike":           "https://defillama.com/yields?project=",
}

# ─── Date helper ──────────────────────────────────────────────────────────────


def format_timestamp_ru(iso_str: str) -> str:
    """Convert an ISO-8601 timestamp string to a Russian date.

    Examples::

        format_timestamp_ru("2026-06-03T00:00:00Z")  →  "3 июня 2026 г."
        format_timestamp_ru("2026-01-15")             →  "15 января 2026 г."
        format_timestamp_ru("")                       →  ""
        format_timestamp_ru("bad")                    →  "bad"
    """
    if not iso_str:
        return iso_str
    try:
        clean = iso_str.replace("Z", "+00:00")
        if "T" not in clean and "+" not in clean and len(clean) == 10:
            dt = datetime.strptime(clean, "%Y-%m-%d")
        else:
            dt = datetime.fromisoformat(clean)
        month_ru = MONTH_NAMES_RU[dt.month]
        return f"{dt.day} {month_ru} {dt.year} г."
    except (ValueError, KeyError):
        return iso_str


# ─── Category-specific body formatters ───────────────────────────────────────


def _fmt_token_unlock(
    message: str, evidence: dict[str, Any]
) -> tuple[str, str]:
    """headline + description for a ``token_unlock`` red flag."""
    m = re.match(
        r"Token unlock\s+([\d.]+)%\s+of supply\s+\((\w+)\)\s+at\s+(\S+)",
        message,
        re.IGNORECASE,
    )
    if m:
        pct, symbol, ts = m.group(1), m.group(2), m.group(3)
        date_ru = format_timestamp_ru(ts)
        headline = f"Разблокировка токенов {symbol}"
        description = (
            f"{pct}% от общего предложения разблокируется {date_ru} — "
            f"возможно давление на цену."
        )
        return headline, description

    # Fallback: use evidence dict
    pct = evidence.get("pct_supply", "?")
    symbol = str(evidence.get("symbol", "TOKEN")).upper()
    unlock_at = str(evidence.get("unlock_at", ""))
    date_ru = format_timestamp_ru(unlock_at) if unlock_at else "?"
    headline = f"Разблокировка токенов {symbol}"
    description = f"{pct}% от общего предложения — {date_ru}."
    return headline, description


def _fmt_governance(
    message: str, evidence: dict[str, Any]
) -> tuple[str, str]:
    """headline + description for a ``governance_proposal`` red flag."""
    tag = str(evidence.get("tag", "")).lower()

    m = re.match(
        r"Risk-sensitive proposal\s*\[[\w-]+\]:\s*(.*)",
        message,
        re.IGNORECASE,
    )
    proposal_title = m.group(1).strip() if m else message

    if any(k in tag for k in ("emergency", "pause", "shutdown")):
        headline = "Экстренное голосование в DAO"
        rec = "Требует немедленного внимания."
    elif "upgrade" in tag:
        headline = "Предложение по обновлению протокола"
        rec = "Следить за результатами."
    elif any(k in tag for k in ("risk", "param")):
        headline = "Изменение риск-параметров DAO"
        rec = "Следить за результатами."
    elif "treasury" in tag:
        headline = "Предложение по казне DAO"
        rec = "Следить за результатами."
    else:
        headline = "Предложение в DAO"
        rec = "Следить за результатами."

    if proposal_title and proposal_title != message:
        description = f"{proposal_title}. {rec}"
    else:
        description = rec
    return headline, description


def _fmt_tvl_drop(
    message: str, evidence: dict[str, Any]
) -> tuple[str, str]:
    """headline + description for a ``tvl_drop`` red flag."""
    m = re.match(r"TVL dropped\s+([\d.]+)%\s+over\s+(\S+)", message, re.IGNORECASE)
    if m:
        pct, window = m.group(1), m.group(2)
        window_ru = {"24h": "24 ч", "7d": "7 дней"}.get(window, window)
        headline = "Падение ликвидности (TVL)"
        description = f"TVL упал на {pct}% за {window_ru}."
        return headline, description
    return "Падение ликвидности (TVL)", message


def _fmt_apy_spike(
    message: str, evidence: dict[str, Any]
) -> tuple[str, str]:
    """headline + description for an ``apy_spike`` red flag."""
    m = re.match(
        r"APY\s+([\d.]+)%\s+is\s+([\d.]+)x\s+baseline\s+([\d.]+)%",
        message,
        re.IGNORECASE,
    )
    if m:
        current, ratio, baseline = m.group(1), m.group(2), m.group(3)
        headline = "Аномальный рост APY"
        description = f"APY {current}% — в {ratio}x выше базового {baseline}%."
        return headline, description
    return "Аномальный рост APY", message


def _category_source_url(alert: dict[str, Any]) -> str:
    """Return a source URL for the event if one can be determined."""
    try:
        category = str(alert.get("category", ""))
        protocol = str(alert.get("protocol", ""))
        evidence: dict = alert.get("evidence") or {}

        if category == "governance_proposal":
            space = str(evidence.get("space", ""))
            if space:
                return f"https://snapshot.org/#/{space}"
            return "https://snapshot.org/"

        if category == "token_unlock":
            return "https://tokenunlocks.app/"

        if category == "tvl_drop":
            return f"https://defillama.com/protocol/{protocol}"

        if category == "apy_spike":
            return f"https://defillama.com/yields?project={protocol}"
    except Exception:
        pass
    return ""


# ─── Public formatters ────────────────────────────────────────────────────────


def format_alert_ru(alert: dict[str, Any]) -> str:
    """Format a single alert dict as a Russian 3-line Telegram block.

    Line 1: ``{emoji} {ProtocolName} — {headline}``
    Line 2: short description
    Line 3: why this matters (explanation)

    Never raises.
    """
    try:
        severity = str(alert.get("severity", "INFO")).upper()
        protocol_slug = str(alert.get("protocol", ""))
        category = str(alert.get("category", ""))
        message = str(alert.get("message", ""))
        evidence: dict[str, Any] = alert.get("evidence") or {}

        emoji = SEVERITY_EMOJI.get(severity, "⚪")
        proto_name = PROTOCOL_NAMES.get(protocol_slug, protocol_slug)

        if category == "token_unlock":
            headline, description = _fmt_token_unlock(message, evidence)
        elif category == "governance_proposal":
            headline, description = _fmt_governance(message, evidence)
        elif category == "tvl_drop":
            headline, description = _fmt_tvl_drop(message, evidence)
        elif category == "apy_spike":
            headline, description = _fmt_apy_spike(message, evidence)
        else:
            headline = message[:80] if message else "Событие"
            description = ""

        explanation = _ALERT_EXPLANATIONS.get(category, "")

        first_line = f"{emoji} {proto_name} — {headline}"
        parts = [first_line]
        if description:
            parts.append(description)
        if explanation:
            parts.append(f"_{explanation}_")   # Markdown italics
        return "\n".join(parts)

    except Exception:  # noqa: BLE001
        try:
            fallback = (
                f"⚪ {alert.get('protocol', '?')} — "
                f"{alert.get('message', '?')[:80]}"
            )
        except Exception:
            fallback = "⚪ — (ошибка форматирования)"
        return fallback


def format_alert_detail_ru(alert: dict[str, Any]) -> str:
    """Build a detailed 📋 "Подробнее" message for one alert.

    Sections:
    1. *Что произошло* — event specifics
    2. *Возможное влияние на портфель* — risk context
    3. *Рекомендованные действия* — what to watch
    4. *Источник* — URL if available

    Never raises.
    """
    try:
        severity = str(alert.get("severity", "INFO")).upper()
        protocol_slug = str(alert.get("protocol", ""))
        category = str(alert.get("category", ""))
        message = str(alert.get("message", ""))
        evidence: dict[str, Any] = alert.get("evidence") or {}

        emoji = SEVERITY_EMOJI.get(severity, "⚪")
        proto_name = PROTOCOL_NAMES.get(protocol_slug, protocol_slug)
        detected_at = str(alert.get("detected_at", ""))
        detected_str = format_timestamp_ru(detected_at) if detected_at else "?"

        # Section 1 — что произошло
        if category == "token_unlock":
            m = re.match(
                r"Token unlock\s+([\d.]+)%\s+of supply\s+\((\w+)\)\s+at\s+(\S+)",
                message, re.IGNORECASE,
            )
            if m:
                pct, symbol, ts = m.group(1), m.group(2), m.group(3)
                date_ru = format_timestamp_ru(ts)
                tokens = evidence.get("tokens", "?")
                what = (
                    f"Разблокировка *{pct}%* токенов *{symbol}* "
                    f"({tokens:,.0f} шт.) запланирована на *{date_ru}*."
                    if isinstance(tokens, (int, float)) else
                    f"Разблокировка *{pct}%* токенов *{symbol}* на *{date_ru}*."
                )
            else:
                what = message

            impact = (
                f"Крупный объём токенов {symbol if 'm' in dir() else 'протокола'} "
                "выходит на рынок. Вероятно кратковременное давление на цену. "
                "Если SPA держит позицию в этом протоколе — APY может кратко "
                "возрасти, а затем стабилизироваться."
            )
            actions = (
                "• Проверить наличие позиции в протоколе.\n"
                "• Следить за APY в течение 24–48 ч после разблокировки.\n"
                "• При значительном росте APY — рассмотреть увеличение позиции\n"
                "  (но только после подтверждения стабильности TVL)."
            )

        elif category == "governance_proposal":
            tag = str(evidence.get("tag", "")).lower()
            title = str(evidence.get("title", message))
            deadline = str(evidence.get("deadline", ""))
            deadline_str = format_timestamp_ru(deadline) if deadline else "?"
            what = (
                f"Активное предложение в DAO *{proto_name}*.\n"
                f"Тема: _{title}_\n"
                f"Дедлайн голосования: *{deadline_str}*"
            )
            if any(k in tag for k in ("emergency", "pause", "shutdown")):
                impact = (
                    "Экстренные предложения могут повлечь паузу контракта "
                    "или изменение ключевых параметров. Активы SPA могут "
                    "временно оказаться недоступны для вывода."
                )
                actions = (
                    "• НЕМЕДЛЕННО проверить proposal на форуме управления.\n"
                    "• При угрозе заморозки — рассмотреть закрытие позиции.\n"
                    "• Следить за on-chain транзакциями Timelock контракта."
                )
            else:
                impact = (
                    "Принятие предложения может изменить параметры доходности, "
                    "лимиты или структуру риска протокола."
                )
                actions = (
                    "• Отследить итог голосования.\n"
                    "• При принятии — пересмотреть риск-параметры позиции.\n"
                    "• Проверить изменения в docs/protocol changelog после принятия."
                )

        elif category == "tvl_drop":
            tvl_now = evidence.get("tvl_now", 0)
            delta_7d = evidence.get("delta_7d", 0)
            tvl_str = f"${tvl_now/1e9:.2f}B" if tvl_now >= 1e9 else f"${tvl_now/1e6:.0f}M"
            what = (
                f"TVL *{proto_name}* упал на *{abs(delta_7d):.1f}%* за 7 дней. "
                f"Текущий TVL: *{tvl_str}*."
            )
            impact = (
                "Уменьшение TVL сигнализирует об оттоке средств. Возможно: "
                "конкурент предлагает лучшие условия, появились опасения по "
                "безопасности, или крупный игрок вывел средства. APY может "
                "кратко вырасти из-за уменьшения конкуренции (ложный сигнал)."
            )
            actions = (
                "• Проверить Discord/Twitter протокола на наличие объявлений.\n"
                "• Оценить, не является ли это системным оттоком (>7 дней подряд).\n"
                "• При продолжении падения TVL ниже $5M — позиция нарушает "
                "RiskPolicy TVL floor и будет закрыта автоматически."
            )

        elif category == "apy_spike":
            current = evidence.get("current_apy", 0)
            baseline = evidence.get("baseline_apy", 0)
            ratio = evidence.get("ratio", 0)
            what = (
                f"APY *{proto_name}* вырос до *{current:.2f}%* "
                f"(в *{ratio:.2f}x* выше недельного базового уровня {baseline:.2f}%)."
            )
            impact = (
                "Аномальный рост APY обычно временный. Причины: субсидирование, "
                "технический сбой в расчётах, или резкое снижение предложения "
                "ликвидности. Погоня за высоким APY без проверки причины — риск."
            )
            actions = (
                "• НЕ открывать новые позиции автоматически.\n"
                "• Выяснить причину роста через DeFiLlama / docs протокола.\n"
                "• Если APY держится >48ч и TVL стабилен — событие может быть "
                "  легитимным (новая программа стимулирования)."
            )

        else:
            what = message
            impact = "Требует дополнительного анализа."
            actions = "• Проверить состояние протокола на DeFiLlama."

        source_url = _category_source_url(alert)
        source_line = f"\n🔗 [Источник]({source_url})" if source_url else ""

        text = (
            f"{emoji} *{proto_name}* — детали события\n"
            f"_(обнаружено {detected_str})_\n"
            f"\n"
            f"*Что произошло:*\n{what}\n"
            f"\n"
            f"*Влияние на портфель:*\n{impact}\n"
            f"\n"
            f"*Рекомендованные действия:*\n{actions}"
            f"{source_line}"
        )
        return text

    except Exception:  # noqa: BLE001
        try:
            fallback = (
                f"⚪ *{alert.get('protocol', '?')}* "
                f"— детали события недоступны.\n"
                f"Оригинальное сообщение: {alert.get('message', '?')[:200]}"
            )
        except Exception:
            fallback = "⚪ — (ошибка форматирования деталей)"
        return fallback


def build_detail_keyboard(alerts: list[dict[str, Any]]) -> dict | None:
    """Build an inline keyboard with "📋 Подробнее" buttons per CRITICAL/WARN alert.

    Callback data format: ``detail_{protocol}__{category}``

    Returns ``None`` when no actionable alerts are present (empty result).
    """
    try:
        rows = []
        seen: set[tuple[str, str]] = set()
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            severity = str(alert.get("severity", "")).upper()
            if severity not in ("CRITICAL", "WARN"):
                continue
            protocol = str(alert.get("protocol", ""))
            category = str(alert.get("category", ""))
            if not protocol or not category:
                continue
            key = (protocol, category)
            if key in seen:
                continue
            seen.add(key)
            proto_name = PROTOCOL_NAMES.get(protocol, protocol)
            callback_data = f"detail_{protocol}__{category}"
            # Telegram callback_data limit: 64 bytes
            if len(callback_data.encode("utf-8")) > 64:
                callback_data = callback_data[:64]
            rows.append(
                [{"text": f"📋 Подробнее: {proto_name}", "callback_data": callback_data}]
            )
        if not rows:
            return None
        return {"inline_keyboard": rows}
    except Exception:  # noqa: BLE001
        return None


def parse_detail_callback(callback_data: str) -> tuple[str, str] | None:
    """Parse a ``detail_{protocol}__{category}`` callback data string.

    Returns ``(protocol, category)`` or ``None`` if the format is unrecognised.

    Examples::

        parse_detail_callback("detail_aave-v3__governance_proposal")
        →  ("aave-v3", "governance_proposal")

        parse_detail_callback("cmd_now")
        →  None
    """
    if not callback_data.startswith("detail_"):
        return None
    payload = callback_data[len("detail_"):]
    protocol, sep, category = payload.partition("__")
    if not sep or not protocol or not category:
        return None
    return protocol, category


def format_message_ru(alerts: list[dict[str, Any]]) -> str:
    """Build a complete Russian-language Telegram message for a list of alerts.

    Produces a Markdown-compatible string (``*bold*``, ``_italic_``) suitable
    for ``telegram_client.send_message`` with ``parse_mode=Markdown``.

    Empty list → single "no events" message.
    Never raises.
    """
    try:
        if not alerts:
            return "✅ *SPA — Важные события*\n\nНовых событий нет."

        lines: list[str] = ["🚨 *SPA — Важные события*", ""]
        for alert in alerts:
            if isinstance(alert, dict):
                block = format_alert_ru(alert)
            else:
                block = f"• {alert}"
            lines.append(block)
            lines.append("")

        while lines and lines[-1] == "":
            lines.pop()

        return "\n".join(lines)

    except Exception:  # noqa: BLE001
        return "🚨 *SPA — Важные события*\n\n(ошибка форматирования)"
