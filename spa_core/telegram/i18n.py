#!/usr/bin/env python3
"""Bilingual (EN | RU) string tables for the interactive SPA Telegram bot.

Per ``docs/TELEGRAM_BOT_UX.md`` §6. Proper nouns (protocol names, ``Rates Desk``,
``FixedCarry``, ``aave_v3``, criteria keys, ``VOLATILE``) stay as-is in both
languages; only labels/structural copy localize.

Stdlib only. Deterministic. No LLM. ``t(key, lang)`` is a pure lookup that
falls back to EN, then to the key itself, and never raises.
"""
from __future__ import annotations

from typing import Dict

LANGS = ("en", "ru")
DEFAULT_LANG = "en"

# key -> {"en": ..., "ru": ...}
_STRINGS: Dict[str, Dict[str, str]] = {
    # ── Home buttons ───────────────────────────────────────────────────────
    "btn.portfolio": {"en": "📊 Portfolio", "ru": "📊 Портфель"},
    "btn.golive": {"en": "🎯 Go-Live", "ru": "🎯 Go-Live"},
    "btn.strategies": {"en": "🏦 Strategies", "ru": "🏦 Стратегии"},
    "btn.health": {"en": "🩺 Health", "ru": "🩺 Здоровье"},
    "btn.reports": {"en": "📅 Reports", "ru": "📅 Отчёты"},
    "btn.warnings": {"en": "⚠️ Warnings", "ru": "⚠️ Предупреждения"},
    "btn.settings": {"en": "⚙️ Settings", "ru": "⚙️ Настройки"},
    "btn.refresh": {"en": "🔄 Refresh", "ru": "🔄 Обновить"},
    "btn.back": {"en": "◀ Back", "ru": "◀ Назад"},
    "btn.home": {"en": "🏠 Home", "ru": "🏠 Домой"},
    # ── Portfolio sub-buttons ──────────────────────────────────────────────
    "btn.track": {"en": "📊 Track", "ru": "📊 Трек"},
    "btn.positions": {"en": "📦 Positions", "ru": "📦 Позиции"},
    "btn.equity_history": {"en": "📈 Equity history", "ru": "📈 История equity"},
    # ── Go-Live sub-buttons ────────────────────────────────────────────────
    "btn.passed": {"en": "✅ Passed", "ru": "✅ Пройдено"},
    "btn.open": {"en": "⏳ Open", "ru": "⏳ Открыто"},
    # ── Strategies sub-buttons ─────────────────────────────────────────────
    "btn.rates_desk": {"en": "🏦 Rates Desk", "ru": "🏦 Rates Desk"},
    "btn.rwa_board": {"en": "🛡️ RWA Board", "ru": "🛡️ RWA Board"},
    "btn.structural_desk": {"en": "🔬 Structural Desk", "ru": "🔬 Structural Desk"},
    "btn.refusal_log": {"en": "🛡️ Refusal Log", "ru": "🛡️ Журнал отказов"},
    # ── Health sub-buttons ─────────────────────────────────────────────────
    "btn.agents": {"en": "🤖 Agents", "ru": "🤖 Агенты"},
    "btn.system": {"en": "🩺 System", "ru": "🩺 Система"},
    "btn.last_cycle": {"en": "🔄 Last cycle", "ru": "🔄 Последний цикл"},
    "btn.only_failing": {"en": "⛔ Only failing", "ru": "⛔ Только сбои"},
    # ── Reports sub-buttons ────────────────────────────────────────────────
    "btn.today": {"en": "📅 Today", "ru": "📅 Сегодня"},
    "btn.weekly": {"en": "📆 Weekly", "ru": "📆 Неделя"},
    # ── Warnings sub-buttons ───────────────────────────────────────────────
    "btn.active": {"en": "⚠️ Active", "ru": "⚠️ Активные"},
    "btn.recent": {"en": "🗂️ Recent (7d)", "ru": "🗂️ Недавние (7д)"},
    # ── Settings sub-buttons ───────────────────────────────────────────────
    "btn.language": {"en": "🌐 Language", "ru": "🌐 Язык"},
    "btn.digests": {"en": "🔔 Digests", "ru": "🔔 Дайджесты"},
    "btn.daily": {"en": "🔔 Daily", "ru": "🔔 Дневной"},
    "btn.weekly_toggle": {"en": "🔔 Weekly", "ru": "🔔 Недельный"},
    "btn.warnings_pref": {"en": "🚨 Warnings", "ru": "🚨 Предупреждения"},
    "btn.mute": {"en": "💤 Mute", "ru": "💤 Без звука"},
    "btn.all": {"en": "All", "ru": "Все"},
    "btn.critical_only": {"en": "Critical only", "ru": "Только критич."},
    "btn.off": {"en": "Off", "ru": "Выкл"},
    "btn.on": {"en": "On", "ru": "Вкл"},
    "btn.until_unmute": {"en": "Until I unmute", "ru": "Пока не сниму"},
    # ── Breadcrumb segment labels ──────────────────────────────────────────
    "crumb.home": {"en": "Home", "ru": "Дом"},
    "crumb.portfolio": {"en": "Portfolio", "ru": "Портфель"},
    "crumb.track": {"en": "Track", "ru": "Трек"},
    "crumb.positions": {"en": "Positions", "ru": "Позиции"},
    "crumb.equity": {"en": "Equity history", "ru": "История equity"},
    "crumb.golive": {"en": "Go-Live", "ru": "Go-Live"},
    "crumb.passed": {"en": "Passed", "ru": "Пройдено"},
    "crumb.open": {"en": "Open", "ru": "Открыто"},
    "crumb.strategies": {"en": "Strategies", "ru": "Стратегии"},
    "crumb.rates": {"en": "Rates Desk", "ru": "Rates Desk"},
    "crumb.rwa": {"en": "RWA Board", "ru": "RWA Board"},
    "crumb.structural": {"en": "Structural Desk", "ru": "Structural Desk"},
    "crumb.refusal": {"en": "Refusal Log", "ru": "Журнал отказов"},
    "crumb.health": {"en": "Health", "ru": "Здоровье"},
    "crumb.agents": {"en": "Agents", "ru": "Агенты"},
    "crumb.system": {"en": "System", "ru": "Система"},
    "crumb.cycle": {"en": "Last cycle", "ru": "Последний цикл"},
    "crumb.reports": {"en": "Reports", "ru": "Отчёты"},
    "crumb.today": {"en": "Today", "ru": "Сегодня"},
    "crumb.weekly": {"en": "Weekly", "ru": "Неделя"},
    "crumb.warnings": {"en": "Warnings", "ru": "Предупреждения"},
    "crumb.recent": {"en": "Recent", "ru": "Недавние"},
    "crumb.settings": {"en": "Settings", "ru": "Настройки"},
    # ── Honest labels ──────────────────────────────────────────────────────
    "lbl.paper_readonly": {"en": "paper · read-only", "ru": "бумага · read-only"},
    "lbl.paper_sim": {"en": "paper · simulation", "ru": "бумага · симуляция"},
    "lbl.advisory_nocap": {"en": "advisory · no live capital",
                           "ru": "advisory · без живого капитала"},
    "lbl.advisory_paper": {"en": "advisory · paper", "ru": "advisory · бумага"},
    "lbl.not_ready": {"en": "NOT READY", "ru": "НЕ ГОТОВ"},
    "lbl.ready": {"en": "READY", "ru": "ГОТОВ"},
    "lbl.time_gated": {"en": "time-gated — nothing to fix",
                       "ru": "ждём по времени — чинить нечего"},
    "lbl.moves_no_capital": {"en": "moves NO live capital",
                             "ru": "живой капитал не двигает"},
    "lbl.monitoring_not_financial": {"en": "monitoring alert, not financial",
                                     "ru": "алерт мониторинга, не финансовый"},
    "lbl.unavailable": {"en": "⚠️ data unavailable", "ru": "⚠️ данные недоступны"},
    "lbl.updated": {"en": "updated", "ru": "обновлено"},
    "lbl.stale": {"en": "⚠️ stale", "ru": "⚠️ устарело"},
    # ── Common words ───────────────────────────────────────────────────────
    "w.equity": {"en": "Equity", "ru": "Капитал"},
    "w.track": {"en": "Track", "ru": "Трек"},
    "w.today": {"en": "Today", "ru": "Сегодня"},
    "w.health": {"en": "Health", "ru": "Здоровье"},
    "w.day": {"en": "Day", "ru": "День"},
    "w.real": {"en": "real", "ru": "реальный"},
    "w.regime": {"en": "regime", "ru": "режим"},
    "w.system_ok": {"en": "system OK", "ru": "система OK"},
    "w.agents": {"en": "agents", "ru": "агентов"},
    "w.total_return": {"en": "Total return", "ru": "Общая доходность"},
    "w.daily_yield": {"en": "Daily yield", "ru": "Дневной доход"},
    "w.daily_return": {"en": "Daily return", "ru": "Дневная доходность"},
    "w.drawdown": {"en": "Drawdown", "ru": "Просадка"},
    "w.since": {"en": "since", "ru": "с"},
    "w.anchor": {"en": "anchor", "ru": "якорь"},
    "w.days_running": {"en": "Days running", "ru": "Дней работает"},
    "w.kill_at": {"en": "kill at", "ru": "kill при"},
    "w.cash_buffer": {"en": "cash buffer", "ru": "кэш-буфер"},
    "w.deployed_across": {"en": "deployed across", "ru": "размещено в"},
    "w.model": {"en": "Model", "ru": "Модель"},
    "w.last_trade": {"en": "last trade", "ru": "последний трейд"},
    "w.eta": {"en": "ETA", "ru": "ETA"},
    "w.verdict": {"en": "verdict", "ru": "вердикт"},
    "w.tap_open": {"en": "tap to open", "ru": "нажмите чтобы открыть"},
    "w.overall": {"en": "overall", "ru": "итого"},
    "w.no_active": {"en": "No active warnings.", "ru": "Нет активных предупреждений."},
    "w.not_muted": {"en": "not muted", "ru": "без mute"},
    "w.active": {"en": "active", "ru": "активно"},
    "w.page": {"en": "page", "ru": "стр."},
    # ── Screen titles ──────────────────────────────────────────────────────
    "ttl.home": {"en": "SPA Monitor", "ru": "SPA Monitor"},
    "ttl.track": {"en": "TRACK STATUS", "ru": "СТАТУС ТРЕКА"},
    "ttl.positions": {"en": "ALLOCATION", "ru": "АЛЛОКАЦИЯ"},
    "ttl.golive": {"en": "GO-LIVE READINESS", "ru": "ГОТОВНОСТЬ К GO-LIVE"},
    "ttl.passed": {"en": "PASSED CRITERIA", "ru": "ПРОЙДЕННЫЕ КРИТЕРИИ"},
    "ttl.open": {"en": "OPEN CRITERIA", "ru": "ОТКРЫТЫЕ КРИТЕРИИ"},
    "ttl.strategies": {"en": "THE STRUCTURAL DESK", "ru": "СТРУКТУРНЫЙ ДЕСК"},
    "ttl.rates": {"en": "RATES DESK", "ru": "RATES DESK"},
    "ttl.rwa": {"en": "RWA SAFETY BOARD", "ru": "RWA SAFETY BOARD"},
    "ttl.refusal": {"en": "REFUSAL ENGINE", "ru": "ДВИЖОК ОТКАЗОВ"},
    "ttl.agents": {"en": "AGENTS", "ru": "АГЕНТЫ"},
    "ttl.system": {"en": "SYSTEM HEALTH", "ru": "ЗДОРОВЬЕ СИСТЕМЫ"},
    "ttl.cycle": {"en": "LAST CYCLE", "ru": "ПОСЛЕДНИЙ ЦИКЛ"},
    "ttl.daily": {"en": "DAILY DIGEST", "ru": "ДНЕВНОЙ ОТЧЁТ"},
    "ttl.weekly": {"en": "WEEKLY REPORT", "ru": "НЕДЕЛЬНЫЙ ОТЧЁТ"},
    "ttl.warnings": {"en": "ACTIVE WARNINGS", "ru": "АКТИВНЫЕ ПРЕДУПРЕЖДЕНИЯ"},
    "ttl.settings": {"en": "SETTINGS", "ru": "НАСТРОЙКИ"},
    # ── Strategies copy ────────────────────────────────────────────────────
    "s.three_theses": {"en": "Three theses, honest verdicts:",
                       "ru": "Три тезиса, честные вердикты:"},
    "s.all_advisory": {
        "en": "All sleeves are ADVISORY — simulate only, never\nallocate live, never touch the go-live track.",
        "ru": "Все слив-стратегии ADVISORY — только симуляция,\nне аллоцируют live, не трогают go-live трек."},
    "s.rwa_floor_bench": {"en": "RWA floor benchmark", "ru": "RWA floor бенчмарк"},
    "s.sleeves": {"en": "Sleeves", "ru": "Слив-стратегии"},
    "s.beats_floor_q": {"en": "beats floor?", "ru": "бьёт floor?"},
    "s.refusal_band": {"en": "all within safe band", "ru": "все в безопасной полосе"},
    "s.no_book_refused": {"en": "No book currently refused.",
                          "ru": "Ни одна книга сейчас не отклонена."},
    # ── Settings copy ──────────────────────────────────────────────────────
    "set.language": {"en": "Language", "ru": "Язык"},
    "set.daily": {"en": "Daily digest", "ru": "Дневной дайджест"},
    "set.weekly": {"en": "Weekly digest", "ru": "Недельный дайджест"},
    "set.warnings": {"en": "Warnings", "ru": "Предупреждения"},
    "set.mute": {"en": "Mute", "ru": "Без звука"},
    # ── Auth ───────────────────────────────────────────────────────────────
    "auth.denied": {"en": "⛔ Access denied. This bot serves the owner only.",
                    "ru": "⛔ Доступ запрещён. Бот обслуживает только владельца."},
}


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Translate ``key`` into ``lang``. Falls back EN → key. Never raises."""
    lang = lang if lang in LANGS else DEFAULT_LANG
    entry = _STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get(DEFAULT_LANG) or key


def normalize_lang(lang: str) -> str:
    """Coerce an arbitrary value to a supported language code."""
    return lang if lang in LANGS else DEFAULT_LANG
