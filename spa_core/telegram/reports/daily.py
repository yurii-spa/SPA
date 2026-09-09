#!/usr/bin/env python3
"""spa_core/telegram/reports/daily.py — THE one daily digest (Tier 2).

Single canonical daily Telegram message (~08:10 UTC, after the 08:00 cycle).
Collapses the former four+ duplicate daily-report senders into one:

  * builds the rich day summary by PROMOTING the clean read-only builder
    ``spa_core.reporting.daily_telegram_report`` (track day, equity, P&L, APY,
    positions, go-live, cycle health, Base chain);
  * folds in any events ``push_policy`` demoted to the digest queue
    (``data/telegram/digest_queue.json``) as a «События за сутки» section —
    a count + the few most important bodies in words instead of N pushes;
  * sends the morning as TWO messages via ``telegram_client`` (the only
    transport): first a ≤900-char Russian HEADLINE (:func:`build_headline_message`
    — is the system healthy, what changed, what waits for the owner, the paper
    track), then the full report as «Подробности» (аудит 08.09: 56 lines of
    mixed-language text with the day's only real alert on line 51 were unreadable);
  * is idempotent — a date-stamp guard (``data/.last_daily_digest``) refuses to
    send twice for the same UTC date even if the launchd agent double-fires.

Allowlisted Telegram sender (see test_telegram_single_authority): it is one of
the digest builders permitted to call the transport directly.

stdlib only · deterministic · fail-safe (never raises) · atomic guard write.

CLI::

    python3 -m spa_core.telegram.reports.daily --check   # print, no send
    python3 -m spa_core.telegram.reports.daily --run     # send (idempotent/day)
    python3 -m spa_core.telegram.reports.daily --run --force   # ignore date guard
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.reporting.daily_telegram_report import (
    _fmt_money,
    _fmt_pct,
    build_report_data,
    format_daily_message,
)
from spa_core.telegram import push_policy
from spa_core.utils.atomic import atomic_load, atomic_save

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода. Источники: запись, видимая в этом модуле,
#: и авторская карта AGENT_OUTPUT_FILES в spa_core/monitoring/uptime_monitor.py.
#: Сверка — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/telegram_alert_state.json",
)

log = logging.getLogger("spa.telegram.reports.daily")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
GUARD_FILENAME = ".last_daily_digest"
ALERT_STATE_FILENAME = "telegram_alert_state.json"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


# ── digest-queue → section ───────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
# Строки тела, которые не несут смысла события (подвал дашборд-алерта, рамки).
_EVENT_NOISE_PREFIXES = ("📊 Portfolio", "🤖 Agents", "━", "─")
_EVENT_SIGNAL_MARKS = ("🔴", "🟠", "🟡", "⚠️", "❌", "🛑", "⛔")
_EVENT_SIGNAL_WORDS = ("CRITICAL", "WARNING", "DOWN", "FAIL", "ERROR")
_EVENT_GISTS_SHOWN = 3


def _event_gist(item: dict) -> str:
    """Одна строка события СЛОВАМИ (не event_key): что случилось.

    Тело — чужой HTML в несколько строк; берём строку с сигналом (эмодзи
    статуса / CRITICAL / DOWN …), иначе первую содержательную. Пустое тело →
    заголовок события. Never raises on a malformed item.
    """
    body = _TAG_RE.sub("", str(item.get("body") or ""))
    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines
             if ln and not ln.startswith(_EVENT_NOISE_PREFIXES)
             and any(ch.isalnum() for ch in ln)]
    if not lines:
        return _TAG_RE.sub("", str(item.get("title") or item.get("event_key") or "?")).strip()
    for ln in lines:
        if ln.startswith(_EVENT_SIGNAL_MARKS) or any(w in ln.upper() for w in _EVENT_SIGNAL_WORDS):
            return ln
    return lines[0]


def _format_digest_section(items: list[dict]) -> str:
    """Render the queued (demoted) events as a compact summary section.

    Аудит 08.09: секция перечисляла внутренние ключи (dashboard_watch ×34…),
    а 15 из 62 тел несли CRITICAL — и этого владелец не видел. Теперь: одна
    строка счёта «N событий, из них M с CRITICAL» + до трёх самых важных тел
    словами (CRITICAL первыми, одинаковые схлопнуты с ×N). Гистограмма по
    event_key остаётся только когда тел меньше трёх — тогда она и есть всё,
    что известно. Never lists each event individually — a flapping detector
    would otherwise re-create the flood inside the digest.
    """
    if not items:
        return ""
    n_crit = sum(1 for i in items if "CRITICAL" in str(i.get("body") or "").upper())
    lines = ["", "🗂️ <b>События за сутки</b>"]
    lines.append(f"  событий с прошлого отчёта: {len(items)}, из них с CRITICAL: {n_crit}")
    with_body = [i for i in items if str(i.get("body") or "").strip()]
    if len(with_body) < _EVENT_GISTS_SHOWN:
        by_key: Counter[str] = Counter(str(i.get("event_key", "?")) for i in items)
        for key, n in sorted(by_key.items(), key=lambda kv: (-kv[1], kv[0])):
            suffix = f" ×{n}" if n > 1 else ""
            lines.append(f"  • {_esc(key)}{suffix}")
        return "\n".join(lines)
    gists: Counter[str] = Counter(_event_gist(i)[:120] for i in with_body)
    ranked = sorted(gists.items(),
                    key=lambda kv: ("CRITICAL" not in kv[0].upper(), -kv[1], kv[0]))
    for gist, n in ranked[:_EVENT_GISTS_SHOWN]:
        suffix = f" ×{n}" if n > 1 else ""
        lines.append(f"  • {_esc(gist)}{suffix}")
    rest = len(ranked) - _EVENT_GISTS_SHOWN
    if rest > 0:
        lines.append(f"  • …и ещё разных событий: {rest}")
    return "\n".join(lines)


def build_digest_message(
    date_str: Optional[str] = None,
    *,
    data_dir: Optional[str | Path] = None,
    now: Optional[datetime] = None,
    drain: bool = True,
) -> tuple[str, dict]:
    """Build the DETAILS message («Подробности») + structured data. Never raises.

    ``drain`` clears the digest queue once consumed (set False for --check).
    Returns ``(html_message, data)``. The headline that precedes it is built
    by :func:`build_headline_message` (see :func:`build_digest_messages`).
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    try:
        data = build_report_data(date_str, data_dir=str(ddir), now=now)
        base_msg = format_daily_message(data)
    except Exception as exc:  # noqa: BLE001 — degrade, never raise
        log.warning("daily digest: base report build failed: %s", exc)
        data = {}
        base_msg = "📊 <b>SPA — отчёт за день</b>\n⚠️ сводка недоступна"

    try:
        queued = push_policy.drain_digest_queue(data_dir=str(ddir), clear=drain)
    except Exception:  # noqa: BLE001
        queued = []
    data["digest_queue_count"] = len(queued)

    section = _format_digest_section(queued)
    message = base_msg + ("\n" + section if section else "")

    office, consumed = _build_office_section(ddir)
    if office:
        message += "\n\n" + office  # пустая строка отделяет блок надзора от событий
    data["office_consumed"] = consumed

    factory = _build_factory_section(ddir)
    if factory:
        message += "\n" + factory

    oversight = _build_oversight_section(ddir)
    if oversight:
        message += "\n" + oversight

    # Самопроверка стандарта живёт в data (её читают тесты и сторожа), а в ТЕКСТ
    # больше не идёт: строка «📋 Стандарт отчёта: не хватает — 3 трека» была
    # вечной ложной тревогой (аудит 08.09) — маркер «3 трека» не производил
    # никто, блок рендерился как «Пакеты (3 независимые книги)». Маркер починен
    # ниже; если дыра появится по-настоящему, её назовёт data, а не владелец.
    data["report_standard_gaps"] = _standard_gaps(message)
    return message, data


def build_digest_messages(
    date_str: Optional[str] = None,
    *,
    data_dir: Optional[str | Path] = None,
    now: Optional[datetime] = None,
    drain: bool = True,
) -> tuple[str, str, dict]:
    """Both morning messages: ``(headline, details, data)``. Never raises."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    details, data = build_digest_message(date_str, data_dir=ddir, now=now, drain=drain)
    headline = build_headline_message(data, ddir)
    return headline, details, data


def _build_factory_section(ddir: Path, repo_root: "Path | None" = None) -> str:
    """AI1 гл.19/гл.3 (мандат владельца 20.08): экономика цеха + паспорта агентов.

    Обе строки — из детерминированных модулей мониторинга; артефакт свежее —
    берём его, иначе считаем на месте (git/manifest локальны и дёшевы).
    Never raises; недоступность источника — честная строка, не молчание.
    """
    lines: list[str] = []
    try:
        try:
            from spa_core.monitoring import fleet_economics as fe

            art = ddir / fe.ARTIFACT_REL
            eco = (json.loads(art.read_text(encoding="utf-8")) if art.is_file()
                   else fe.summary(repo_root))
            if eco.get("commits") is None:
                lines.append("⚙️ Цех: экономика не измерена (git недоступен — это сигнал)")
            else:
                cost = eco.get("cost_estimate_usd")
                tail = (f" · ~${cost}" if cost is not None
                        else " · стоимость не оценена (SPA_COST_PER_CYCLE_USD)")
                lines.append(
                    f"⚙️ Цех за 24ч: циклов <b>{_esc(eco.get('cycles'))}</b> · "
                    f"коммитов {_esc(eco.get('commits'))}{tail}")
        except Exception:  # noqa: BLE001
            lines.append("⚙️ Цех: экономика недоступна (нет данных — это сигнал)")
        try:
            from spa_core.monitoring import agent_passports as ap

            mp = (Path(repo_root) / ap.MANIFEST_REL) if repo_root else None
            pa = ap.audit(mp)
            if pa.get("total") is None:
                lines.append("🪪 Паспорта агентов: не измерено (манифест не прочитан)")
            else:
                missing = pa.get("missing") or []
                tail = ""
                if missing:
                    shown = ", ".join(m.replace("com.spa.", "") for m in missing[:3])
                    more = f" +{len(missing) - 3}" if len(missing) > 3 else ""
                    tail = f" · без паспорта: {_esc(shown)}{_esc(more)}"
                lines.append(
                    f"🪪 Паспорта агентов: <b>{_esc(pa.get('with_passport'))}/"
                    f"{_esc(pa.get('total'))}</b>{tail}")
        except Exception:  # noqa: BLE001
            lines.append("🪪 Паспорта агентов: недоступно (нет данных — это сигнал)")
    except Exception:  # noqa: BLE001
        return ""
    return "\n".join(lines)


# Обязательные блоки дневного отчёта (AI1 гл.10, мандат владельца 20.08):
# «хороший результат позволяет начать работу без уточняющих вопросов».
# Маркер отсутствует ⇒ отчёт НАЗЫВАЕТ дыру сам — владелец не должен спрашивать
# «а где три пакета?» (его живой вопрос 19.08, с него стандарт и начался).
#
# Маркер обязан быть подстрокой того, что РЕНДЕРИТСЯ. Аудит 08.09: маркер
# «3 трека» не производил никто (блок называется «Пакеты (3 независимые книги)»,
# daily_telegram_report._books_lines), и отчёт год называл дыру, которой не было.
_REQUIRED_BLOCKS: "list[tuple[str, str]]" = [
    ("отчёт за день", "сводка портфеля"),
    ("Офис", "постура офиса"),
    ("Архитектура", "сторож архитектуры"),
    ("Цех", "экономика цеха"),
    ("Паспорта агентов", "паспорта агентов"),
    ("Пакеты (3 независимые книги)", "3 трека (Cons/Bal/Agg)"),
    # Мандат владельца 29.08: надзор должен быть ВИДЕН каждый день, а не
    # лежать в data/, куда не смотрит ни один читатель.
    ("Надзор аллокации", "надзор аллокации"),
    ("Доказанность APY", "доказанность APY"),
    ("Гейт доказательств", "гейт доказательств (ADR-169)"),
    ("Скачки APY", "сторож скачков APY"),
    # ADR-183: цена газа должна быть видна владельцу каждый день.
    ("Цена газа", "цена газа (ADR-183)"),
]


def _build_oversight_section(ddir: Path) -> str:
    """Три строки надзора в отчёт владельцу (AI1, мандат владельца 29.08).

    Сторож, который говорит только в файл, — это файл. Аудитор аллокации и
    доказанность APY писали свои вердикты в `data/`, где их не читал НИКТО:
    на весь отчётный слой было ноль упоминаний обоих. Сторож скачков APY имел
    верный порог (8 % для compound_v3, и он сработал бы на 9.2007 %), но его
    не звал вообще никто.

    Владелец выбрал: не новый канал в Telegram, а три строки в том отчёте,
    который он и так читает каждый день.

    Скачки считаются ВЫЗОВОМ `check_spikes()` — она читает `adapter_status` и
    ничего не пишет (ни телеграма, ни диска), поэтому отчёту можно её звать.
    Never raises; недоступность источника — честная строка, не молчание.
    """
    lines: list[str] = []

    # 1. Аудитор аллокации (ADR-055 / allocation_auditor)
    try:
        raw = json.loads((ddir / "allocation_audit_daily.json").read_text(encoding="utf-8"))
        counts = raw.get("counts") or {}
        verdict = str(raw.get("verdict") or "?")
        # Ключи именно такие: `rule_id`/`verdict` (см. allocation_auditor).
        # Первая редакция читала `rule`/`status` и молча давала пустой хвост —
        # строка выглядела рабочей, а самого нарушения не называла.
        bad = [f"{f.get('rule_id')} ({f.get('subject')})"
               for f in (raw.get("findings") or [])
               if isinstance(f, dict) and f.get("verdict") == "VIOLATION"]
        mark = {"OK": "✅", "VIOLATION": "❌", "UNCHECKED": "❓"}.get(verdict, "❓")
        tail = f" · нарушено: {_esc(', '.join(str(b) for b in bad[:3]))}" if bad else ""
        lines.append(
            f"🔎 Надзор аллокации: {mark} <b>{_esc(verdict)}</b> — "
            f"норм {_esc(counts.get('OK', 0))} · нарушений {_esc(counts.get('VIOLATION', 0))} · "
            f"не измерено {_esc(counts.get('UNCHECKED', 0))}{tail}")
    except Exception:  # noqa: BLE001
        lines.append("🔎 Надзор аллокации: нет данных — это сигнал "
                     "(allocation_auditor не отработал)")

    # 2. Доказанность APY (ADR-061 / apy_evidencer)
    try:
        raw = json.loads((ddir / "apy_evidence.json").read_text(encoding="utf-8"))
        counts = raw.get("counts") or {}
        pct = raw.get("quotable_pct")
        pct_s = f"{float(pct):.0f}%" if isinstance(pct, (int, float)) else "не измерено"
        lines.append(
            f"📐 Доказанность APY: цитировать можно <b>{_esc(pct_s)}</b> чисел "
            f"(наблюдено {_esc(counts.get('L2', 0))} · косвенно {_esc(counts.get('L1', 0))} · "
            f"литерал {_esc(counts.get('L0', 0))} · не измерено {_esc(counts.get('UNCHECKED', 0))})")
    except Exception:  # noqa: BLE001
        lines.append("📐 Доказанность APY: нет данных — это сигнал "
                     "(apy_evidencer не отработал)")

    # 2б. ADR-169: САМОЕ опасное состояние — гейт доказательств выключен.
    # Уровни выше говорят «насколько доказаны числа»; здесь другой вопрос —
    # «работал ли вообще отбор по доказанности». Выключенный гейт значит, что
    # покрытие обвалилось и мы подозреваем СВОЮ поломку: капитал в этот цикл
    # раскладывался по устаревшей вселенной. Молчать об этом нельзя.
    try:
        # Файл ЗАМЕРЕН, а не угадан: `_build_feed_coverage()` уезжает в
        # `current_positions.json` под ключом `feed_coverage`. Первая редакция
        # читала `target_allocation.json` — такого файла в проде нет вовсе, и
        # строка была бы вечно «не измерен», выглядя при этом рабочей.
        raw = json.loads((ddir / "current_positions.json").read_text(encoding="utf-8"))
        cov = (raw.get("feed_coverage") or {}).get("evidence_coverage") or {}
        if not cov:
            lines.append("🚦 Гейт доказательств: не измерен — это сигнал")
        elif cov.get("gate_applied"):
            lines.append(
                f"🚦 Гейт доказательств: ✅ применён "
                f"({_esc(cov.get('evidenced'))} из {_esc(cov.get('attempted'))} "
                f"наблюдений, нужно {_esc(cov.get('required'))})")
        else:
            lines.append(
                f"🚦 Гейт доказательств: ⚠️ <b>НЕ применён</b> — покрытие "
                f"{_esc(cov.get('evidenced'))} из {_esc(cov.get('attempted'))} "
                f"при нужных {_esc(cov.get('required'))}: подозрение на поломку "
                f"НАШЕГО производителя, раскладка шла по устаревшей вселенной")
    except Exception:  # noqa: BLE001
        lines.append("🚦 Гейт доказательств: не измерен — это сигнал")

    # 3. Скачки APY (сторож был написан и не позван ни разу)
    try:
        from spa_core.alerts.apy_spike_monitor import APYSpikeMonitor

        spikes = APYSpikeMonitor(base_dir=str(ddir.parent)).check_spikes()
        if not spikes:
            lines.append("⚡ Скачки APY: порогов никто не превысил")
        else:
            named = ", ".join(
                f"{s.protocol} {s.current_apy:.2f}% > {s.threshold:.2f}%"
                for s in spikes[:3])
            more = f" +{len(spikes) - 3}" if len(spikes) > 3 else ""
            lines.append(f"⚡ Скачки APY: <b>{len(spikes)}</b> — {_esc(named)}{_esc(more)}")
    except Exception:  # noqa: BLE001
        lines.append("⚡ Скачки APY: не измерено — это сигнал (сторож не отработал)")

    # 4. Цена газа (ADR-183): агент меряет каждые 30 мин — отчёт показывает.
    # Затяжное «не измерено» обязано быть видно владельцу, а не только файлу:
    # отказ источников агент честно пишет как unchecked, и эта строка — его
    # единственный человеческий читатель до подключения алертов.
    try:
        raw = json.loads((ddir / "gas_price_history.json").read_text(encoding="utf-8"))
        chains = raw.get("chains") or {}
        if not chains:
            lines.append("⛽ Цена газа: нет данных — это сигнал "
                         "(gas_price_agent не отработал)")
        else:
            _REGIME_RU = {"cheap": "дёшево", "normal": "обычно",
                          "expensive": "ДОРОГО", "insufficient_history": "мало истории",
                          "unmeasured": "не измерено"}
            parts: list[str] = []
            dark: list[str] = []
            for c in ("ethereum", "base", "arbitrum", "optimism"):
                e = chains.get(c) or {}
                if e.get("source") == "live":
                    leg = e.get("usd_per_leg")
                    leg_s = (f" ${float(leg):.2f}/ногу"
                             if isinstance(leg, (int, float)) else "")
                    parts.append(f"{c[:3]} {_REGIME_RU.get(str(e.get('regime') or ''), '?')}{leg_s}")
                else:
                    dark.append(c)
            body = " · ".join(parts) if parts else "все сети не измерены — это сигнал"
            tail = f" · не измерено: {', '.join(dark)}" if dark else ""
            lines.append(f"⛽ Цена газа: {_esc(body + tail)}")
    except Exception:  # noqa: BLE001
        lines.append("⛽ Цена газа: нет данных — это сигнал "
                     "(gas_price_agent не отработал)")

    return "\n".join(lines)


def _standard_gaps(message: str) -> "list[str]":
    """Каких обязательных блоков в собранном отчёте нет. Never raises."""
    try:
        return [human for marker, human in _REQUIRED_BLOCKS if marker not in message]
    except Exception:  # noqa: BLE001
        return []


def _build_office_section(ddir: Path) -> tuple[str, list[str]]:
    """ADR-066 Фаза 2: строка house_view + строка conformance в дайджест владельца.

    Возвращает (html-секция, [repo-relative пути УСПЕШНО прочитанных файлов]) —
    квитанции по ним пишет run_daily_digest ПОСЛЕ фактической отправки.
    Файл не прочитан ⇒ честная строка «нет данных», в consumed не попадает.
    Never raises.
    """
    lines: list[str] = []
    consumed: list[str] = []
    try:
        hv_rel = "data/investment_os/chief_investment.json"
        try:
            hv = json.loads((ddir / "investment_os" / "chief_investment.json").read_text())
            view = hv.get("house_view") or {}
            conflicts = view.get("conflicts") or []
            tail = f" · конфликт: {_esc(str(conflicts[0])[:80])}" if conflicts else ""
            lines.append(f"🏛 Офис: постура <b>{_esc(view.get('overall_posture'))}</b>{tail}")
            consumed.append(hv_rel)
        except Exception:  # noqa: BLE001
            lines.append("🏛 Офис: house_view недоступен (нет данных — это сигнал)")
        conf_rel = "data/architecture_conformance.json"
        try:
            conf = json.loads((ddir / "architecture_conformance.json").read_text())
            c = conf.get("counts") or {}
            lines.append(
                f"🏗 Архитектура: <b>{_esc(conf.get('overall'))}</b> — "
                f"critical {c.get('critical', '?')} · warn {c.get('warn', '?')} · "
                f"unchecked {c.get('unchecked', '?')}")
            consumed.append(conf_rel)
        except Exception:  # noqa: BLE001
            lines.append("🏗 Архитектура: отчёт сторожа недоступен (нет данных — это сигнал)")
        health_rel = "data/investment_os/_health.json"
        try:
            json.loads((ddir / "investment_os" / "_health.json").read_text())
            consumed.append(health_rel)  # читается ради квитанции офис-здоровья
        except Exception:  # noqa: BLE001
            pass
        loop_rel = "data/loop_health.json"
        try:
            lh = json.loads((ddir / "loop_health.json").read_text())
            fate = lh.get("cards_fate") or {}
            lines.append(
                f"🔁 Петля: открыто {lh.get('open_cards', '?')} · "
                f"взято в работу {fate.get('in_progress', 0) + fate.get('done_by_human', 0)} · "
                f"рецидивов {lh.get('recurrences_total', '?')}")
            consumed.append(loop_rel)
        except Exception:  # noqa: BLE001
            pass  # петля моложе дайджеста — до первого прогона строки честно нет
    except Exception:  # noqa: BLE001
        return "", []
    return "\n".join(lines), consumed


# ── headline: первое утреннее сообщение ──────────────────────────────────────
#
# Аудит 08.09: владелец получал 56 строк, где английские шапки мешались с
# русским хвостом, единственная настоящая тревога дня стояла 51-й строкой
# кодом правила, а «жива ли система» не отвечал никто (system_health.json
# CRITICAL и 74/77 агентов не читались вовсе). Заголовок — ≤900 знаков,
# по-русски, самое важное первым. Каждый источник, которого нет, — «не
# измерено» (третий исход), никогда догадка.
HEADLINE_MAX_CHARS = 900
HEADLINE_FOOTER = "📄 Подробности — следующим сообщением."
_UNMEASURED = "не измерено"

_DOMAIN_RU = {
    "d1_data_pipeline": "данные",
    "d2_connectivity": "связь",
    "d3_strategy_quality": "качество стратегий",
    "d4_external": "внешние сервисы",
    "d5_code_integrity": "целостность кода",
    "d6_risk_gates": "риск-гейты",
    "d7_hygiene": "гигиена",
    "d_dfb_defi_board": "доска DeFi",
    "d_riskwire": "лента рисков (RiskWire)",
}
_STATUS_MARK = {"OK": "🟢", "INFO": "🟢", "WARNING": "🟠", "CRITICAL": "🔴"}
_STATUS_WORD = {"OK": "в порядке", "INFO": "в порядке",
                "WARNING": "есть предупреждения", "CRITICAL": "КРИТИЧНО"}
# Советующие пакеты — paper, капитал не двигают (инвариант #9).
_ADVISORY_BOOKS = ("balanced", "aggressive")


def _load_json(ddir: Path, name: str) -> Any:
    """Документ из ``ddir/name`` или ``None`` — третий исход, не догадка."""
    try:
        return json.loads((ddir / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt ⇒ «не измерено»
        return None


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _fmt_ts(iso: Any) -> str:
    """'2026-09-08T17:27:38+00:00' → '08.09 17:27 UTC'; непарсибельное — как есть."""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%d.%m %H:%M UTC")
    except (TypeError, ValueError):
        return _clip(str(iso), 25)


def _system_line(ddir: Path, compact: bool = False) -> str:
    """«🟢/🟠/🔴 Система: …» из system_health.json — статус + домены словами."""
    sh = _load_json(ddir, "system_health.json")
    sh = sh if isinstance(sh, dict) else {}
    status = str(sh.get("overall_status") or "").upper()
    if not status:
        return f"⚪ Система: {_UNMEASURED} (system_health.json не прочитан)"
    domains: dict = sh.get("domains") if isinstance(sh.get("domains"), dict) else {}
    by_status: dict[str, list[str]] = {"CRITICAL": [], "WARNING": []}
    for key, doc in domains.items():
        st = str(doc.get("status") or "").upper() if isinstance(doc, dict) else ""
        if st in by_status:
            by_status[st].append(_DOMAIN_RU.get(str(key), str(key)))
    crit_checks = [str(c.get("id")) for c in (sh.get("checks") or [])
                   if isinstance(c, dict) and str(c.get("status") or "").upper() == "CRITICAL"
                   and c.get("id")]
    parts: list[str] = []
    if by_status["CRITICAL"]:
        ids = f" ({', '.join(crit_checks[:2])})" if (crit_checks and not compact) else ""
        parts.append("сбой: " + ", ".join(by_status["CRITICAL"]) + ids)
    if by_status["WARNING"] and not compact:
        parts.append("предупреждения: " + ", ".join(by_status["WARNING"]))
    elif by_status["WARNING"]:
        parts.append(f"предупреждений: {len(by_status['WARNING'])}")
    head = f"{_STATUS_MARK.get(status, '⚪')} Система: {_STATUS_WORD.get(status, status)}"
    return _esc(head + (" — " + " · ".join(parts) if parts else ""))


def _fleet_line(ddir: Path, data: dict) -> str:
    """Агенты · последний цикл · стоп-кран · аварийный статус — одной строкой."""
    parts: list[str] = []
    ah = _load_json(ddir, "agent_health.json")
    if (isinstance(ah, dict) and isinstance(ah.get("healthy_count"), int)
            and isinstance(ah.get("total_agents"), int)):
        parts.append(f"агенты {ah['healthy_count']} из {ah['total_agents']} в порядке")
    else:
        parts.append(f"агенты: {_UNMEASURED}")
    st = _load_json(ddir, "paper_trading_status.json")
    ts = st.get("last_cycle_ts") if isinstance(st, dict) else None
    parts.append(f"цикл {_fmt_ts(ts)}" if ts else f"цикл: {_UNMEASURED}")
    # Контракт governance/kill_switch.check_manual_trigger: файл есть и в нём
    # не сказано active:false ⇒ стоп-кран включён.
    ks_path = ddir / "kill_switch_active.json"
    if ks_path.exists():
        ks = _load_json(ddir, "kill_switch_active.json")
        off = isinstance(ks, dict) and ks.get("active") is False
        parts.append("стоп-кран не включён" if off else "🛑 СТОП-КРАН ВКЛЮЧЁН")
    else:
        parts.append("стоп-кран не включён")
    em = _load_json(ddir, "emergency_status.json")
    em_status = str(em.get("status") or "").upper() if isinstance(em, dict) else ""
    if not em_status:
        parts.append(f"аварийный статус: {_UNMEASURED}")
    elif em_status == "CLEAR":
        parts.append("аварий нет")
    else:
        parts.append(f"аварийный статус {em_status}")
    return "🤖 " + _esc(" · ".join(parts))


def _display_names(ddir: Path) -> dict[str, str]:
    doc = _load_json(ddir, "adapter_status.json")
    adapters = doc.get("adapters") if isinstance(doc, dict) else None
    if not isinstance(adapters, dict):
        return {}
    return {str(k): str(v.get("display_name") or k)
            for k, v in adapters.items() if isinstance(v, dict)}


def _positions_diff(ddir: Path) -> "tuple[str, list[str]] | None":
    """(«07.09 → 08.09», строки «• имя: $a → $b») по двум последним барам; None — не измерено."""
    eq = _load_json(ddir, "equity_curve_daily.json")
    daily = eq.get("daily") if isinstance(eq, dict) else None
    if not isinstance(daily, list) or len(daily) < 2:
        return None
    prev, last = daily[-2], daily[-1]
    if not (isinstance(prev, dict) and isinstance(last, dict)):
        return None
    p0, p1 = prev.get("positions"), last.get("positions")
    if not (isinstance(p0, dict) and isinstance(p1, dict)):
        return None
    names = _display_names(ddir)
    changes: list[tuple[float, str, float, float]] = []
    for key in set(p0) | set(p1):
        a, b = p0.get(key, 0.0), p1.get(key, 0.0)
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
            continue
        if abs(float(b) - float(a)) >= 1.0:
            changes.append((abs(float(b) - float(a)), names.get(str(key), str(key)), float(a), float(b)))
    changes.sort(key=lambda c: (-c[0], c[1]))
    span = f"{_short_date(prev.get('date'))} → {_short_date(last.get('date'))}"
    return span, [f"• {_esc(name)}: {_fmt_money(a)} → {_fmt_money(b)}" for _, name, a, b in changes]


def _short_date(value: Any) -> str:
    s = str(value or "")
    return f"{s[8:10]}.{s[5:7]}" if len(s) >= 10 else (s or "?")


def _oversight_lines(ddir: Path, compact: bool = False) -> list[str]:
    """Только НЕ-OK находки надзора аллокации, словами из ``detail`` (код правила в скобках)."""
    raw = _load_json(ddir, "allocation_audit_daily.json")
    if not isinstance(raw, dict):
        return [f"❓ Надзор аллокации: {_UNMEASURED} (allocation_auditor не отработал)"]
    findings = [f for f in (raw.get("findings") or [])
                if isinstance(f, dict) and f.get("verdict") != "OK"]
    if not findings:
        return ["✅ Надзор аллокации: нарушений нет"]
    viol = [f for f in findings if f.get("verdict") == "VIOLATION"]
    other = [f for f in findings if f.get("verdict") != "VIOLATION"]
    limit = 90 if compact else 160
    out: list[str] = []
    for f in viol[:2]:
        detail = str(f.get("detail") or "").strip() or f"нарушение у {f.get('subject')}"
        out.append(f"⚠️ Нарушение: {_esc(_clip(detail, limit))} "
                   f"({_esc(f.get('rule_id'))}, {_esc(f.get('subject'))})")
    if len(viol) > 2:
        out.append(f"⚠️ …и ещё нарушений: {len(viol) - 2}")
    if other:
        # UNCHECKED — третий исход: правило не посчитано, а не «всё хорошо».
        subjects = ", ".join(str(f.get("subject")) for f in other[:3])
        out.append(f"❓ Не измерено правил надзора: {len(other)} ({_esc(subjects)})")
    return out


def _frontmatter(path: Path) -> dict[str, str]:
    """Плоские ключи YAML-шапки карточки (status/title/created); без YAML-парсера."""
    out: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline().strip()
            if first != "---":
                return out
            for _ in range(60):
                line = fh.readline()
                if not line or line.strip() == "---":
                    break
                m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
                if m:
                    out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        return {}
    return out


def _owner_queue(ddir: Path, tracker_dir: "Path | None" = None) -> "tuple[int, str] | None":
    """(сколько карточек ждёт владельца, заголовок самой новой) или None — не измерено.

    Источник — карточки ``nimbalyst-local/tracker/*.md`` со ``status: needs-owner``
    в ДЕРЕВЕ этого кода; запасной — ``data/owner_queue*.json``, если такой артефакт
    вообще есть (на 08.09 его нет).
    """
    tdir = tracker_dir if tracker_dir is not None else _REPO_ROOT / "nimbalyst-local" / "tracker"
    if not tdir.is_dir():
        return _owner_queue_fallback(ddir)
    cards: list[tuple[str, float, str]] = []
    try:
        for p in tdir.glob("*.md"):
            fm = _frontmatter(p)
            if fm.get("status") != "needs-owner":
                continue
            cards.append((fm.get("created", ""), p.stat().st_mtime, fm.get("title") or p.stem))
    except OSError:
        return _owner_queue_fallback(ddir)
    cards.sort(reverse=True)
    return len(cards), (cards[0][2] if cards else "")


def _owner_queue_fallback(ddir: Path) -> "tuple[int, str] | None":
    for p in sorted(ddir.glob("owner_queue*.json")):
        doc = _load_json(ddir, p.name)
        items = doc.get("items") if isinstance(doc, dict) else doc
        if isinstance(items, list):
            open_ = [i for i in items if isinstance(i, dict)
                     and i.get("status", "needs-owner") == "needs-owner"]
            title = str(open_[0].get("title") or "") if open_ else ""
            return len(open_), title
    return None


def _owner_line(ddir: Path, compact: bool = False) -> str:
    q = _owner_queue(ddir)
    if q is None:
        return f"🧑‍⚖️ Ждут тебя: {_UNMEASURED} (очередь карточек не прочитана)"
    n, newest = q
    if n == 0:
        return "🧑‍⚖️ Ждут тебя: карточек нет"
    tail = f" · новая: «{_esc(_clip(newest, 40 if compact else 80))}»" if newest else ""
    return f"🧑‍⚖️ Ждут тебя: карточек {n}{tail}"


def _evidenced_return(ddir: Path) -> "tuple[float, int, str] | None":
    """(накопленный %, подтверждённых дней, якорь) по golive_status + equity_curve; None — не измерено."""
    gl = _load_json(ddir, "golive_status.json")
    if not isinstance(gl, dict):
        return None
    days, anchor = gl.get("real_track_days"), gl.get("evidenced_anchor")
    if not (isinstance(days, int) and isinstance(anchor, str)):
        return None
    eq = _load_json(ddir, "equity_curve_daily.json")
    daily = eq.get("daily") if isinstance(eq, dict) else None
    if not isinstance(daily, list) or not daily:
        return None
    first = next((b for b in daily if isinstance(b, dict) and str(b.get("date", "")) >= anchor), None)
    last = daily[-1] if isinstance(daily[-1], dict) else None
    if first is None or last is None:
        return None
    base = first.get("open_equity", first.get("close_equity"))
    close = last.get("close_equity", last.get("equity"))
    if not (isinstance(base, (int, float)) and isinstance(close, (int, float)) and base > 0):
        return None
    return (float(close) / float(base) - 1.0) * 100.0, days, anchor


def _track_lines(data: dict, ddir: Path) -> list[str]:
    """«💰 Бумажный трек» — те же числа, что в подробностях, только короче."""
    lines = ["💰 <b>Бумажный трек</b> (paper, капитал виртуальный)"]
    ev = _evidenced_return(ddir)
    cum = (f"{ev[0]:+.2f}% за {ev[1]} подтверждённых дн. (с {_esc(ev[2])})" if ev
           else f"накопленный % за подтверждённые дни: {_UNMEASURED}")
    lines.append(f"{_fmt_money(data.get('equity_usd'))} · "
                 f"{_fmt_money(data.get('daily_pnl_usd'), signed=True)} за день · {cum}")
    lines.append(f"APY сегодня {_fmt_pct(data.get('apy_today_pct'))} · "
                 f"среднее за 7 дн. {_fmt_pct(data.get('apy_7day_avg_pct'))}")
    books = (data.get("books_summary") or {}).get("books") if isinstance(data.get("books_summary"), dict) else None
    if isinstance(books, dict):
        adv = [books[k] for k in _ADVISORY_BOOKS
               if isinstance(books.get(k), dict) and books[k].get("available")
               and isinstance(books[k].get("equity"), (int, float))]
        total = sum(float(b["equity"]) for b in adv)
        lines.append("Советующие пакеты (paper, капитал не двигают): "
                     f"Σ {_fmt_money(total) if adv else _UNMEASURED}")
    else:
        lines.append(f"Советующие пакеты (paper): {_UNMEASURED}")
    return lines


def _changed_lines(ddir: Path, compact: bool = False) -> list[str]:
    diff = _positions_diff(ddir)
    if diff is None:
        head = [f"📌 <b>Что изменилось</b>: позиции — {_UNMEASURED} (нужны два бара equity_curve)"]
    else:
        span, rows = diff
        head = [f"📌 <b>Что изменилось</b> (позиции {span})"]
        if not rows:
            head.append("• позиции без изменений")
        elif compact and len(rows) > 4:
            # Схлопывать есть смысл, только если хвост длиннее одной строки.
            head.extend(rows[:3])
            head.append(f"• …и ещё изменений: {len(rows) - 3}")
        else:
            head.extend(rows)
    return head + _oversight_lines(ddir, compact=compact)


def _compose_headline(data: dict, ddir: Path, compact: bool) -> str:
    blocks = [
        [_system_line(ddir, compact=compact), _fleet_line(ddir, data)],
        _changed_lines(ddir, compact=compact),
        [_owner_line(ddir, compact=compact)],
        _track_lines(data, ddir),
        [HEADLINE_FOOTER],
    ]
    return "\n\n".join("\n".join(b) for b in blocks)


def _drop_trailing_lines(msg: str) -> str:
    """Последний рубеж бюджета: снимать ЦЕЛЫЕ строки с конца тела (подвал остаётся).

    Строки в заголовке идут по убыванию важности, поэтому теряется хвост трека,
    а не «жива ли система». Резать строку посередине — нечитаемо.
    """
    body = msg[: msg.rfind("\n\n" + HEADLINE_FOOTER)]
    lines = body.split("\n")
    while lines and len("\n".join(lines)) + len(HEADLINE_FOOTER) + 3 > HEADLINE_MAX_CHARS:
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines) + "\n…\n\n" + HEADLINE_FOOTER


def build_headline_message(data: dict, ddir: "str | Path") -> str:
    """Первое утреннее сообщение: ≤``HEADLINE_MAX_CHARS`` знаков, по-русски.

    ``data`` — результат ``build_report_data`` (может быть ``{}``: тогда числа
    трека честно «—»/«не измерено»); ``ddir`` — каталог ``data/``. Порядок:
    жива ли система → что изменилось (позиции + не-OK надзор словами) → что
    ждёт владельца → бумажный трек → «Подробности — следующим сообщением».
    Длина — жёсткий контракт: сначала компактный вариант, затем усечение тела
    с сохранением подвала. Never raises.
    """
    ddir = Path(ddir)
    try:
        msg = _compose_headline(data or {}, ddir, compact=False)
        if len(msg) > HEADLINE_MAX_CHARS:
            msg = _compose_headline(data or {}, ddir, compact=True)
        if len(msg) > HEADLINE_MAX_CHARS:
            msg = _drop_trailing_lines(msg)
        return msg
    except Exception as exc:  # noqa: BLE001 — never raise, never guess
        log.warning("daily digest: headline build failed: %s", exc)
        return (f"⚪ Система: {_UNMEASURED} (заголовок не собрался: {_esc(_clip(str(exc), 80))})"
                f"\n\n{HEADLINE_FOOTER}")


# ── idempotency guard ────────────────────────────────────────────────────────
def _guard_path(ddir: Path) -> Path:
    return ddir / GUARD_FILENAME


def _already_sent_today(ddir: Path, today: str) -> bool:
    try:
        doc = atomic_load(str(_guard_path(ddir)), default={})
        if isinstance(doc, dict):
            return doc.get("date") == today
    except Exception:  # noqa: BLE001
        pass
    return False


def _mark_sent_today(ddir: Path, today: str, now_iso: str) -> None:
    try:
        atomic_save({"date": today, "sent_at": now_iso}, str(_guard_path(ddir)))
    except Exception:  # noqa: BLE001
        log.warning("daily digest: guard write failed", exc_info=True)


def _days_between(prev_iso: str, today_iso: str) -> int | None:
    """Whole UTC days from ``prev_iso`` (YYYY-MM-DD) to ``today_iso``, or None."""
    try:
        d0 = datetime.strptime(prev_iso[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(today_iso[:10], "%Y-%m-%d").date()
        return (d1 - d0).days
    except (ValueError, TypeError):
        return None


def _detect_and_record_miss(ddir: Path, today: str, now_iso: str) -> dict:
    """Make a SILENTLY missed digest day VISIBLE (logged + flagged in state).

    WS-2.4 digest-miss guard: on each run we compare the last successfully-sent
    ``daily_summary`` date against today. If more than one calendar day elapsed
    (e.g. state jumped 06-26 → 06-28, so 06-27 was never sent), at least one day
    was silently missed. We DO NOT fabricate a sent-state for the missed day
    (honesty); instead we record the gap under ``daily_summary_misses`` (an
    append-only, capped list of {detected_at, last_sent, today, days_missed})
    and emit a WARNING so the miss is observable, never silent.

    Returns a dict ``{"days_missed": int, "last_sent": str|None}`` describing the
    detected gap (``days_missed == 0`` when there is no miss). Fail-safe.
    """
    info: dict[str, object] = {"days_missed": 0, "last_sent": None}
    try:
        path = ddir / ALERT_STATE_FILENAME
        doc = atomic_load(str(path), default={})
        if not isinstance(doc, dict):
            doc = {}
        last_sent = str(doc.get("daily_summary", "") or "")[:10]
        info["last_sent"] = last_sent or None
        if not last_sent:
            return info  # never sent → no "miss" to record (first-run, not a gap)
        gap = _days_between(last_sent, today)
        if gap is None or gap <= 1:
            return info  # 0 = already today, 1 = consecutive day — no miss
        days_missed = gap - 1
        info["days_missed"] = days_missed
        log.warning(
            "daily digest: %d day(s) silently MISSED — last successful daily "
            "summary %s, today %s (no send recorded for the gap)",
            days_missed, last_sent, today,
        )
        misses = doc.get("daily_summary_misses")
        if not isinstance(misses, list):
            misses = []
        misses.append({
            "detected_at": now_iso,
            "last_sent": last_sent,
            "today": today,
            "days_missed": days_missed,
        })
        doc["daily_summary_misses"] = misses[-50:]  # cap the audit list
        atomic_save(doc, str(path))
    except Exception:  # noqa: BLE001
        log.warning("daily digest: miss-guard write failed", exc_info=True)
    return info


def _mark_daily_summary_sent(ddir: Path, today: str) -> None:
    """Record that today's daily Telegram summary went out.

    Updates ``data/telegram_alert_state.json`` setting ``daily_summary`` to the
    UTC date, atomically, PRESERVING the other state keys (red_flag, gap_alert,
    weekly_report, daily_summary_misses). This is the state the go-live gate
    (``GoLiveChecker._check_telegram_alert_today``) reads — the RETIRED legacy
    daily-report agents used to write it, so the new digest must take that over
    or ``telegram_alert_today`` could never pass again. Honest: only called on a
    SUCCESSFUL send, so the criterion reflects "the summary actually went out
    today", never force-passed. Fail-safe (never raises).
    """
    try:
        path = ddir / ALERT_STATE_FILENAME
        doc = atomic_load(str(path), default={})
        if not isinstance(doc, dict):
            doc = {}
        doc["daily_summary"] = today
        doc["daily_summary_sent_at"] = datetime.now(timezone.utc).isoformat()
        atomic_save(doc, str(path))
    except Exception:  # noqa: BLE001
        log.warning("daily digest: alert-state write failed", exc_info=True)


# ── transport (allowlisted) ──────────────────────────────────────────────────
def _send_html(message: str) -> bool:
    try:
        from spa_core.alerts.telegram_client import _post_message
        return bool(_post_message({"text": message, "parse_mode": "HTML"}))
    except Exception as exc:  # noqa: BLE001
        log.warning("daily digest: send failed: %s", exc)
        return False


def run_daily_digest(
    date_str: Optional[str] = None,
    *,
    data_dir: Optional[str | Path] = None,
    send: bool = True,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Build + (optionally) send the morning pair (headline, then details).
    Idempotent per UTC date.

    Returns ``{"sent", "skipped", "headline", "message", "data", "error"}``
    (``message`` is the details text, as before). Never raises.
    """
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    now_dt = now or datetime.now(timezone.utc)
    today = now_dt.date().isoformat()
    result: dict[str, Any] = {
        "sent": False, "skipped": False, "headline": "", "message": "", "data": {},
        "error": None,
    }
    try:
        if send and not force and _already_sent_today(ddir, today):
            result["skipped"] = True
            log.info("daily digest: already sent for %s — skipping", today)
            # Still build the messages (for observability) but do not drain/send.
            head, msg, data = build_digest_messages(date_str, data_dir=ddir, now=now_dt, drain=False)
            result["headline"], result["message"], result["data"] = head, msg, data
            return result

        # Drain only when we will actually send (so --check doesn't lose the queue).
        head, msg, data = build_digest_messages(date_str, data_dir=ddir, now=now_dt, drain=bool(send))
        result["headline"], result["message"], result["data"] = head, msg, data
        if send:
            # WS-2.4 miss-guard: BEFORE today's send overwrites the state, detect
            # whether the previous successful day was >1 day ago (a silently
            # missed digest day) and make it visible (log + flagged state). We do
            # NOT fabricate a sent-state for the missed day.
            miss = _detect_and_record_miss(ddir, today, now_dt.isoformat())
            result["days_missed"] = miss["days_missed"]
            # Заголовок ПЕРВЫМ, подробности ВТОРЫМ. Дневной страж ставится, как
            # только заголовок ушёл: повторный запуск не должен прислать его
            # владельцу второй раз, даже если подробности не дошли — об этом
            # честно скажет error, а не дубль в чате.
            head_ok = _send_html(head)
            if head_ok:
                _mark_sent_today(ddir, today, now_dt.isoformat())
            ok = head_ok and _send_html(msg)
            result["sent"] = ok
            if ok:
                # ADR-066 Фаза 2: квитанции потребления — ТОЛЬКО после реальной
                # отправки (превью/--check не потребление) и только за то, что
                # реально прочитано в сообщение.
                try:
                    from spa_core.monitoring.consumption_receipts import write_receipt
                    for rel in data.get("office_consumed", []):
                        write_receipt(rel, "digest_daily", root=str(ddir.parent))
                except Exception:  # noqa: BLE001
                    pass
                # The go-live gate's telegram_alert_today criterion reads
                # data/telegram_alert_state.json:daily_summary — record that the
                # daily summary went out today so it can pass (the retired legacy
                # daily-report agents used to own this write).
                _mark_daily_summary_sent(ddir, today)
            else:
                result["error"] = ("Telegram send returned False (headline)" if not head_ok
                                   else "Telegram send returned False (details)")
    except Exception as exc:  # noqa: BLE001 — never raises
        log.warning("daily digest: unexpected error: %s", exc)
        result["error"] = str(exc)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telegram.reports.daily", description="SPA single daily digest."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="print preview, no send")
    group.add_argument("--run", action="store_true", help="send (idempotent per day)")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--force", action="store_true", help="ignore date-stamp guard")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.check:
        head, msg, _ = build_digest_messages(args.date, data_dir=args.data_dir, drain=False)
        print(_TAG_RE.sub("", head))
        print(f"\n──── сообщение 2/2 ({len(head)} знаков в заголовке) ────\n")
        print(_TAG_RE.sub("", msg))
        return 0

    res = run_daily_digest(args.date, data_dir=args.data_dir, send=True, force=args.force)
    if res["skipped"]:
        print("↺ Daily digest already sent today — skipped")
    elif res["sent"]:
        print("✅ Daily digest sent")
    else:
        print(f"⚠️  Not sent: {res['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
