#!/usr/bin/env python3
"""Warnings views: Active (open warnings, urgent first) + Recent (UX §4.14).

Derives warnings READ-ONLY from monitor state files (agent_health critical,
kill-switch, cycle status, refusal). Honest financial-vs-monitoring framing.

**Второй вход к вариантам ответа (вторая половина задания владельца 2026-08-07).**
Задание звучало «либо кнопки под алертом, либо то же самое в меню». Кнопки под
алертом доставлены циклом #148 (ADR-069). Здесь — тот же выбор из меню: экран
«Проблемы» перечисляет журнал `data/telegram_alert_actions.json`, нажатие на
проблему открывает её лист-вид с ТЕМИ ЖЕ кнопками. Ценность: сообщение уезжает
в ленте чата вверх за сутки, а проблема остаётся — закрыть её можно позже.

Два правила этого входа, оба ради того, чтобы входы не разъехались:

* **Реестр вариантов не дублируется.** Клавиатура берётся у
  ``alert_actions.build_keyboard`` целиком; здесь к ней лишь дописывается ряд
  навигации. Свой список вариантов рядом с существующим — это два реестра,
  которые расходятся молча.
* **Маячка обработчика тут НЕ спрашиваем — и это не послабление.** Интерлок
  ADR-069 защищает от того, что кнопки уедут РАНЬШЕ обработчика: отправитель
  алерта (короткоживущий монитор) уже с новым кодом, а долгоживущий бот — ещё
  со старым. Здесь отправитель и обработчик — ОДИН процесс: экран рисует тот же
  бот, чей роутер обработает нажатие, и обе половины приезжают одним деревом.
  Бот, не умеющий обработать нажатие, не умеет и нарисовать этот экран.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.telegram import alert_actions, menus
from spa_core.telegram.i18n import t
from spa_core.telegram.views import _base as B

# Сколько проблем показывать в списке. Журнал хранит 200; экран Telegram — не
# архив, а способ дотянуться до недавней проблемы, которую унесло из ленты.
PROBLEMS_SHOWN = 10


def _active_warnings() -> List[Dict]:
    out: List[Dict] = []
    # Canonical fail-CLOSED reader: a stale agent_health snapshot is itself a
    # warning (the fleet's real state is UNKNOWN) — an 8h-old "healthy 69/69"
    # must never read as calm (2026-08-05 incident). Fallback to raw read only
    # if the monitor module is unavailable.
    try:
        from spa_core.monitoring.agent_health_monitor import load_report
        ah = load_report(B.DATA_DIR)
    except Exception:
        ah = B.read_json("agent_health.json", {})
    if isinstance(ah, dict) and ah.get("snapshot_stale"):
        age = ah.get("snapshot_age_min")
        age_txt = ("{:.1f}h old".format(age / 60.0)
                   if isinstance(age, (int, float)) else "age unknown")
        out.append({
            "sev": "WARNING", "key": "agent_health_stale",
            "title": "agent_health snapshot STALE",
            "detail": "snapshot {} · fleet state UNKNOWN (monitor not running?)".format(age_txt),
            "since": B.short_ts(ah.get("timestamp")),
            "financial": False,
        })
    if isinstance(ah, dict) and ah.get("overall_status") == "CRITICAL":
        n = ah.get("critical_count", 0)
        out.append({
            "sev": "CRITICAL", "key": "agent_health",
            "title": "agent_health",
            "detail": "{} agents down · overall CRITICAL".format(n),
            "since": B.short_ts(ah.get("timestamp")),
            "financial": False,
        })
    ks = B.read_json("kill_switch_active.json", {})
    if isinstance(ks, dict) and ks.get("active"):
        out.append({
            "sev": "CRITICAL", "key": "kill_switch", "title": "kill-switch",
            "detail": "all positions flat (paper) · {}".format(ks.get("reason", "")),
            "since": B.short_ts(ks.get("set_at")), "financial": True,
        })
    st = B.read_json("paper_trading_status.json", {})
    if isinstance(st, dict) and st.get("last_cycle_status") not in ("ok", None, ""):
        out.append({
            "sev": "CRITICAL", "key": "cycle", "title": "cycle failure",
            "detail": "last cycle status={}".format(st.get("last_cycle_status")),
            "since": B.short_ts(st.get("last_cycle_ts")), "financial": False,
        })
    ref = B.read_json("refusal_status.json", {})
    if isinstance(ref, dict):
        refused = [u for u in ref.get("underlyings", [])
                   if u.get("verdict") not in ("SAFE", None)]
        if refused:
            out.append({
                "sev": "WARNING", "key": "refusal", "title": "refusal fired",
                "detail": "{} book(s) refused".format(len(refused)),
                "since": B.short_ts(ref.get("generated_at")), "financial": False,
            })
    # urgent first
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    out.sort(key=lambda w: order.get(w["sev"], 9))
    return out


def render_active(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    warns = _active_warnings()
    body = ["⚠️  {}".format(t("ttl.warnings", lang)), ""]
    if not warns:
        body.append(t("w.no_active", lang))
    for w in warns:
        emoji = "⛔" if w["sev"] == "CRITICAL" else "⚠️"
        frame = (t("lbl.monitoring_not_financial", lang)
                 if not w["financial"] else "financial")
        body.append(" {} {}  {}".format(emoji, w["sev"], w["title"]))
        body.append("    {}".format(w["detail"]))
        body.append("    since {} · {}".format(w["since"], frame))
        body.append("")
    ah = B.read_json("agent_health.json", {})
    footer = B.freshness(ah.get("timestamp"), lang,
                         "{} {}".format(len(warns), t("w.active", lang)))
    text = B.screen("warnings", "{} {}".format(len(warns), t("w.active", lang)),
                    body, footer, lang)
    return text, menus.standard_keyboard("warnings", lang)


# ── второй вход: список проблем из журнала + лист-вид проблемы ───────────────


def _first_line(text: str, limit: int = 46) -> str:
    """Первая строка алерта — ровно то, что владелец видел темой сообщения."""
    stripped = (text or "").strip()
    if not stripped:
        return "—"
    line = stripped.splitlines()[0].strip()
    return (line[: limit - 1] + "…") if len(line) > limit else line


def _carded(entry: Dict) -> Optional[str]:
    """Идентификатор уже заведённой по проблеме карточки, либо ``None``.

    Показывать это обязательно: иначе владелец жмёт вариант повторно, гадая,
    сработало ли в прошлый раз. (Само нажатие идемпотентно, но молчание экрана
    об этом не говорит.)
    """
    choices = entry.get("choices")
    if not isinstance(choices, dict):
        return None
    for rec in choices.values():
        if isinstance(rec, dict) and rec.get("card"):
            return Path(str(rec["card"])).stem
    return None


def render_problems(arg: str = "", lang: str = "en", page: int = 0,
                    prefs: Dict = None) -> Tuple[str, Dict]:
    """Список проблем, приходивших с вариантами: каждая строка — кнопка."""
    ru = str(lang).lower().startswith("ru")
    rows = alert_actions.recent_alerts(limit=PROBLEMS_SHOWN)
    body = ["🧾  {}".format(t("ttl.problems", lang)), ""]
    buttons: List[List[Dict]] = []
    if not rows:
        body.append(t("w.no_problems", lang))
    for entry in rows:
        alert_id = str(entry.get("id") or "")
        if not alert_id:
            continue
        kind = str(entry.get("kind") or "problem")
        kind_ru = alert_actions.KIND_TITLE_RU.get(kind, kind)
        card_id = _carded(entry)
        mark = "✅" if card_id else "•"
        body.append(" {} {}  {}".format(mark, B.short_ts(entry.get("ts")),
                                        _first_line(entry.get("text", ""))))
        tail = "    {}".format(kind_ru if ru else kind)
        if card_id:
            tail += " · {} `{}`".format(t("w.card_done", lang), card_id)
        body.append(tail)
        buttons.append([{
            "text": "{} {}".format(mark, _first_line(entry.get("text", ""), 34)),
            "callback_data": "nav:warnings.problems.item|{}".format(alert_id),
        }])
    footer = B.freshness(rows[0].get("ts") if rows else None, lang,
                         "{} {}".format(len(rows), t("w.problems_shown", lang)))
    text = B.screen("warnings.problems",
                    "{} {}".format(len(rows), t("w.problems_shown", lang)),
                    body, footer, lang)
    return text, menus.standard_keyboard("warnings.problems", lang,
                                         extra_rows=buttons)


def render_item(arg: str = "", lang: str = "en", page: int = 0,
                prefs: Dict = None) -> Tuple[str, Dict]:
    """Лист-вид одной проблемы: её текст дословно + ТЕ ЖЕ варианты ответа.

    ``arg`` — идентификатор алерта из ``nav:warnings.problems.item|<id>``.
    Алерта нет (кольцевой журнал вытеснил его, а панель в чате осталась) →
    честно говорим об этом и кнопок вариантов НЕ показываем: нажатие всё равно
    получило бы отказ «цитировать нечего», и лучше сказать это до нажатия.
    """
    alert_id = str(arg or "").strip()
    entry = alert_actions.get_alert(alert_id) if alert_id else None
    if entry is None:
        body = ["🧾  {}".format(t("ttl.problems", lang)), "",
                t("w.problem_gone", lang)]
        text = B.screen("warnings.problems.item", alert_id or "—", body,
                        B.freshness(None, lang), lang)
        return text, menus.standard_keyboard("warnings.problems.item", lang)

    ru = str(lang).lower().startswith("ru")
    kind = str(entry.get("kind") or "problem")
    kind_ru = alert_actions.KIND_TITLE_RU.get(kind, kind)
    body = ["🧾  {}".format(kind_ru if ru else kind), ""]
    body.extend((entry.get("text") or "").strip().splitlines() or ["—"])
    body.append("")
    card_id = _carded(entry)
    if card_id:
        body.append("{} `{}`".format(t("w.card_done", lang), card_id))
    body.append(t("w.pick_option", lang))
    footer = B.freshness(entry.get("ts"), lang, alert_id)
    text = B.screen("warnings.problems.item", B.short_ts(entry.get("ts")),
                    body, footer, lang)

    # Клавиатура вариантов — ЦЕЛИКОМ из реестра алерта; здесь только навигация.
    kb = alert_actions.build_keyboard(alert_id, kind, lang)
    rows = list(kb.get("inline_keyboard", []))
    rows.append(menus.nav_row("warnings.problems.item", lang))
    return text, {"inline_keyboard": rows}


def render_recent(arg: str = "", lang: str = "en", page: int = 0,
                  prefs: Dict = None) -> Tuple[str, Dict]:
    hist = B.read_json("alert_history.json", [])
    rows = hist if isinstance(hist, list) else hist.get("alerts", []) if isinstance(hist, dict) else []
    body = ["🗂️  {}".format(t("crumb.recent", lang)), ""]
    if not rows:
        body.append(B.unavailable(lang, "alert_history.json"))
    for r in (rows[-10:] if isinstance(rows, list) else []):
        if not isinstance(r, dict):
            continue
        preview = str(r.get("preview", r.get("text", "")))[:50]
        ts = B.short_ts(r.get("ts") or r.get("timestamp"))
        body.append(" • {}  {}".format(ts, preview))
    text = B.screen("warnings.recent", "last 7d", body, B.freshness(None, lang), lang)
    return text, menus.standard_keyboard("warnings.recent", lang)
