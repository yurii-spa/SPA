"""Owner view — the deterministic presentation layer over Company Truth (ADR-762, RFC-690).

The Director OS page used to compose its sentences in the browser straight from ``mission.json →
truth``. DIRECTOR-OS-UX-02 needs one fact to read the same everywhere, in plain Russian, and
«не измерено» never to become a zero or «всё в порядке». This module is that one place.

Contract (ADR-762 §1–3):
  * PURE: ``build(model, now)`` reads only the already-built mission model (``truth``, ``overview``,
    ``capital.real_capital``, ``release_feed``) and the injected clock. No I/O, no second memory,
    no cache, no registry of its own. Same input ⇒ same output (pinned by a test).
  * Every metric carries ``source`` (the canon), ``measured_at``, ``updated_at`` (the snapshot it
    was read from), ``unit`` and ``confidence`` ∈ CONFIDENCE. Absence/error ⇒ NOT_MEASURED with a
    reason; an unrecognised status ⇒ INTERPRETATION_PROBLEM («проблема отображения»), never success.
  * Real money comes ONLY from ``capital.real_capital`` (``usd``/``state``/``basis``/``observed_at``);
    there is no money literal in this module.
  * Main texts are free of machine codes; the raw value travels in ``technical`` with an explanation.

LLM_FORBIDDEN: deterministic string assembly only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from spa_core.studio_os.owner_dictionary import UNKNOWN_STAGE, note_says_done, stage_title
from spa_core.utils.presentation import fmt_owner_time

SCHEMA = "owner-view/1"

MEASURED = "MEASURED"
STALE = "STALE"
NOT_MEASURED = "NOT_MEASURED"
PARTIAL = "PARTIAL"
INTERPRETATION_PROBLEM = "INTERPRETATION_PROBLEM"
CONFIDENCE = (MEASURED, STALE, NOT_MEASURED, PARTIAL, INTERPRETATION_PROBLEM)

CONFIDENCE_RU = {
    MEASURED: "Измерено",
    STALE: "Нет свежих данных",
    NOT_MEASURED: "Не измерено",
    PARTIAL: "Проверено частично",
    INTERPRETATION_PROBLEM: "Проблема отображения",
}

# Company Truth cell states (company_truth.STATES) → confidence. Anything else is NOT guessed.
_CELL_STATE = {
    "MEASURED": MEASURED, "MEASURED_ZERO": MEASURED, "DEFINITIONAL": MEASURED,
    "STALE": STALE, "NOT_MEASURED": NOT_MEASURED, "NOT_ENOUGH_HISTORY": NOT_MEASURED,
    "CORRUPT": NOT_MEASURED,
}
_CELL_STATE_REASON = {
    "NOT_ENOUGH_HISTORY": "мало истории",
    "CORRUPT": "данные повреждены",
}

# ADR-285 subject order for the owner's own queue (money first).
# Keys as company_truth emits them (owner_queue.subject; None = not declared).
SUBJECT_ORDER = ("MONEY", "PUBLIC_NUMBERS_NAMING_LEGAL", "IRREVERSIBLE", "PHYSICAL_ACTION")
SUBJECT_RU = {
    "MONEY": "Реальные деньги",
    "PUBLIC_NUMBERS_NAMING_LEGAL": "Публичные числа, названия, юридика",
    "IRREVERSIBLE": "Необратимое или внешнее действие",
    "PHYSICAL_ACTION": "Нужно ваше действие руками",
}

ROADMAP_STATE_RU = {"DONE": "Сделано", "IN_PROGRESS": "Идёт", "QUEUED": "В очереди", "BLOCKED": "Остановлено"}

# Upper bound of the release feed (mission_control._git_feed(limit=…)): a count equal to it is
# «не меньше N», never «ровно N» (AUDIT §3.6).
RELEASE_FEED_LIMIT = 25

# ── dictionary (RFC-690 §4): one human name per concept; the original stays in technical details ──
DICTIONARY = [
    {"term": "NAV", "owner": "Стоимость портфеля", "explain": "позиции + кэш + начисленный доход − издержки"},
    {"term": "APY", "owner": "Годовая ставка (расчётная)", "explain": "годовой пересчёт доходности; метод и окно указаны рядом"},
    {"term": "ADR-NNN", "owner": "Решение № NNN", "explain": "запись архитектурного решения в docs/decisions"},
    {"term": "NOT_MEASURED", "owner": "Не измерено", "explain": "значения нет; причина указана рядом"},
    {"term": "STALE", "owner": "Нет свежих данных", "explain": "последнее значение старше допустимого; дата рядом"},
    {"term": "DEGRADED", "owner": "Работает с ограничениями", "explain": "часть проверок с предупреждениями"},
    {"term": "com.spa.*", "owner": "Фоновая задача", "explain": "метка процесса launchd на Mac"},
    {"term": "exit_nonzero", "owner": "Задача завершилась с ошибкой", "explain": "ненулевой код выхода"},
    {"term": "LIVE_NOT_APPROVED", "owner": "Реальные деньги не разрешены", "explain": "режим исполнения бумажный; решение владельца не принято"},
    {"term": "PAPER / REALIZED_PAPER", "owner": "Расчётный (бумажный) портфель", "explain": "виртуальный капитал, реальные деньги не двигаются"},
    {"term": "BACKTEST", "owner": "Бэктест (модель на истории)", "explain": "расчёт на прошлых данных, не деньги и не трек"},
]

# Tokens that must never reach a main text (RFC-690 §4, owner list). Used by the sanitizer here and
# by the jargon scan test, so the two cannot drift.
JARGON_PATTERNS = (
    r"\bNAV\b", r"\bAPY\b", r"\bADR-\d+", r"\bP1\b", r"\bCI\b", r"\bE2E\b", r"\bREADY\b",
    r"\bBLOCKED\b", r"launchctl", r"com\.spa\.", r"exit_nonzero", r"intent=", r"\b[A-Z]{2,}_[A-Z_]{2,}\b",
    r"\b[\w\-/]+\.(?:py|jsonl|plist)\b", r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b",
)
_JARGON_RX = [re.compile(p) for p in JARGON_PATTERNS]


def jargon_hits(text: str) -> list:
    """Every forbidden token in ``text`` (empty list = clean)."""
    if not isinstance(text, str):
        return []
    return [m.group(0) for rx in _JARGON_RX for m in rx.finditer(text)]


_CODE_PREFIX = re.compile(r"^\s*[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\s*[·:—-]\s*")
_ADR = re.compile(r"\bADR-0*(\d+)")
_COMSPA = re.compile(r"com\.spa\.([a-z0-9_\-]+)")
_MACHINE = re.compile(r"\b[A-Z]{2,}_[A-Z_]{2,}\b")
_PATH = re.compile(r"(?<![\w/])[\w.\-]*(?:/[\w.\-]+)+\.(?:py|json|jsonl|md|js|sh|ya?ml|plist|css|html)\b|"
                   r"\b[\w\-]+\.(?:py|jsonl|plist)\b")
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def plain(s: Any) -> Optional[str]:
    """Human text from canon free text: markdown stripped, codes translated or removed.

    Deterministic and conservative: a token it cannot translate is replaced by a neutral word
    (the original is always available in ``technical``), never silently kept on the main screen.
    """
    if not isinstance(s, str):
        return None
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"^\s*>\s?", "", s, flags=re.M)
    s = _ADR.sub(lambda m: "решение № " + m.group(1), s)
    s = _CODE_PREFIX.sub("", s)
    s = _COMSPA.sub(lambda m: "фоновая задача «" + m.group(1).replace("_", " ") + "»", s)
    s = re.sub(r"\bexit_nonzero[:_]?\d*", "ошибка завершения", s)
    s = re.sub(r"\bintent=\w+", "", s)
    s = re.sub(r"\bNAV\b", "стоимость портфеля", s)
    s = re.sub(r"\bAPY\b", "годовая ставка", s)
    s = re.sub(r"\blaunchctl\b", "служебная команда", s)
    s = _MACHINE.sub("(служебный код)", s)
    s = _PATH.sub("(файл — в подробностях)", s)
    s = _SNAKE.sub("(служебное имя)", s)
    for tok in ("P1", "CI", "E2E", "READY", "BLOCKED"):
        s = re.sub(r"\b" + tok + r"\b", {"P1": "срочное", "CI": "автотесты", "E2E": "сквозная проверка",
                                       "READY": "готово", "BLOCKED": "остановлено"}[tok], s)
    # a code that already stood in brackets must not get a second pair: «((служебное имя))» → «(служебное имя)»
    s = re.sub(r"\(\((служебн[^()]*|файл — в подробностях)\)\)", r"(\1)", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _get(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _madrid(ts: Any) -> Optional[str]:
    return fmt_owner_time(ts, "ru") if ts else None


def _cell_confidence(cell: Any) -> tuple:
    """(confidence, reason) of a Company Truth cell; unknown shape/state is never success."""
    if not isinstance(cell, dict):
        return NOT_MEASURED, "раздел не передан в пульт"
    st = cell.get("state")
    if st not in _CELL_STATE:
        return INTERPRETATION_PROBLEM, f"не удалось понять статус «{st}» — это проблема отображения"
    conf = _CELL_STATE[st]
    fr = cell.get("freshness") if isinstance(cell.get("freshness"), dict) else {}
    age, lim = fr.get("age_min"), fr.get("stale_after_min")
    if conf == MEASURED and isinstance(age, (int, float)) and isinstance(lim, (int, float)) and age > lim:
        conf = STALE
    reason = None
    if conf == NOT_MEASURED:
        reason = plain(cell.get("unknown_ru")) or _CELL_STATE_REASON.get(st) or "причина не названа"
    return conf, reason


_NEG_HYPHEN = re.compile(r"(?<![\w\-−])-(?=\d)")


def metric(label: str, text: Optional[str], *, confidence: str, source: Optional[str],
           measured_at: Optional[str], updated_at: Optional[str], unit: Optional[str] = None,
           reason: Optional[str] = None, technical: Optional[dict] = None, tone: Optional[str] = None) -> dict:
    """One owner-facing metric. ``text`` is what the owner reads; for anything not MEASURED the text
    names the confidence in WORDS (so colour is never the only signal)."""
    if confidence not in CONFIDENCE:
        confidence, reason = INTERPRETATION_PROBLEM, f"не удалось понять оценку «{confidence}»"
    if confidence == NOT_MEASURED:
        text = "Не измерено" + (f" — {reason}" if reason else "")
    elif confidence == INTERPRETATION_PROBLEM:
        text = "Проблема отображения" + (f" — {reason}" if reason else "")
    elif confidence == STALE:
        last = _madrid(measured_at)
        text = (text or "") + (f" · Нет свежих данных (последнее значение: {last})" if last
                                else " · Нет свежих данных")
    elif confidence == PARTIAL:
        text = (text or "") + " · Проверено частично"
    if isinstance(text, str):
        # typographic minus for a negative number shown to the owner («−0,04 %», not «-0,04 %»);
        # a hyphen inside a date or a word («2026-10-08», «T-1») is not touched (look-behind: non-word)
        text = _NEG_HYPHEN.sub("\u2212", text)
    return {"label": label, "text": text, "confidence": confidence, "confidence_ru": CONFIDENCE_RU[confidence],
            "source": source, "measured_at": measured_at, "measured_at_ru": _madrid(measured_at),
            "updated_at": updated_at, "unit": unit, "tone": tone or _tone(confidence),
            "technical": technical or {}}


def _tone(conf: str) -> str:
    return {MEASURED: "ok", STALE: "warn", PARTIAL: "warn", NOT_MEASURED: "unknown",
            INTERPRETATION_PROBLEM: "problem"}.get(conf, "problem")


def _usd(v: float) -> str:
    whole = int(round(abs(v)))
    s = f"{whole:,}".replace(",", " ")
    return ("−$" if v < 0 else "$") + s


# ── blocks ──────────────────────────────────────────────────────────────────────────────────────
def real_money(model: dict, updated: Optional[str]) -> dict:
    """Real money — ONLY from capital.real_capital (ADR-762 §3). No literal, no fallback."""
    rc = _get(model, "capital.real_capital") or _get(model, "overview.capital.real_capital")
    src = "capital.real_capital ← paper_trading_status.execution_mode + живой капитал движков"
    if not isinstance(rc, dict):
        return metric("Настоящие деньги", None, confidence=NOT_MEASURED, source=src, measured_at=None,
                      updated_at=updated, unit="USD", reason="состояние реального капитала не передано")
    state, usd, basis, obs = rc.get("state"), rc.get("usd"), rc.get("basis"), rc.get("observed_at")
    tech = {"state": state, "basis": basis, "explain": "state — политика допуска реальных денег; usd — сумма, "
                                                       "которую сообщают движки исполнения"}
    known = {"LIVE_NOT_APPROVED", "LIVE_APPROVED", "UNKNOWN"}
    if state not in known:
        return metric("Настоящие деньги", None, confidence=INTERPRETATION_PROBLEM, source=src, measured_at=obs,
                      updated_at=updated, unit="USD", technical=tech,
                      reason=f"не удалось понять состояние «{state}»")
    if state == "UNKNOWN" or not isinstance(usd, (int, float)) or isinstance(usd, bool):
        return metric("Настоящие деньги", None, confidence=NOT_MEASURED, source=src, measured_at=obs,
                      updated_at=updated, unit="USD", technical=tech, reason="сумма не измерена")
    why = ("реальный капитал не разрешён: исполнение только бумажное"
           if state == "LIVE_NOT_APPROVED" else "реальный капитал разрешён решением владельца")
    if isinstance(basis, str) and "read_only_simulation" in basis:
        why += " (режим: бумажная симуляция)"
    return metric("Настоящие деньги", f"{_usd(usd)} — {why}", confidence=MEASURED, source=src, measured_at=obs,
                  updated_at=updated, unit="USD", technical=tech, tone="neutral")


def _book_metric(key: str, book: Any, updated: Optional[str]) -> dict:
    names = {"conservative": "Консервативный", "balanced": "Сбалансированный", "aggressive": "Агрессивный"}
    label = names.get(key, key)
    conf, reason = _cell_confidence(book)
    if not isinstance(book, dict):
        return metric(label, None, confidence=NOT_MEASURED, source=None, measured_at=None,
                      updated_at=updated, reason=reason)
    src = book.get("canon")
    acc = book.get("accumulating_days")
    if book.get("state") == "NOT_ENOUGH_HISTORY" and isinstance(acc, int):
        return metric(label, None, confidence=NOT_MEASURED, source=src, measured_at=book.get("as_of"),
                      updated_at=updated, unit="%", reason=f"копится история: {acc} из 30 дней",
                      technical={"state": book.get("state")})
    if conf != MEASURED and conf != STALE:
        return metric(label, None, confidence=conf, source=src, measured_at=book.get("as_of"),
                      updated_at=updated, unit="%", reason=reason, technical={"state": book.get("state")})
    rate, dd, days = book.get("rate_ru"), book.get("dd_ru"), book.get("evidenced_days")
    if not rate:
        return metric(label, None, confidence=NOT_MEASURED, source=src, measured_at=book.get("as_of"),
                      updated_at=updated, unit="%", reason="ставка не передана")
    v = book.get("value") if isinstance(book.get("value"), dict) else {}
    pr = book.get("period_return_ru")
    if pr:
        # Wave 2 method (read-only from Company Truth's ONE yield cell): the period return is the
        # primary figure; the annualised number is only an ESTIMATED equivalent, said so in words.
        start, end = _ddmmyyyy(book.get("period_start")), _ddmmyyyy(book.get("period_end"))
        period = f"за {start}–{end}" if start and end else "за период (даты не переданы)"
        text = f"{pr} {period} (модель, бумага) · худшая просадка {dd or 'не измерена'}"
        tech = {"metric_type": book.get("metric_type"),
                "method": "доходность за период: NAV конца / NAV начала − 1 (отношение NAV, внешних потоков нет)",
                "equivalent": f"оценочный годовой эквивалент: {book.get('apy_convention') or 'ACT/365 Fixed'}",
                "mechanism": v.get("mechanism_ru"), "position": v.get("position_ru"),
                "live": v.get("live_reason_ru"), "version": v.get("version")}
        m = metric(label, text, confidence=conf, source=src, measured_at=book.get("as_of"), updated_at=updated,
                   unit="%", technical=tech)
        if rate:
            m["secondary_short"] = f"Оценочный годовой эквивалент: {rate}"
            m["secondary"] = (f"Оценочный годовой эквивалент {rate}: пересчёт этой доходности на год по датам "
                              "оценки (ACT/365 Fixed); время начальной оценки не записано; это не прогноз. "
                              "Показывать ли его на сайте — ваше решение.")
        m["data_date_ru"] = f"Данные на {end}" if end else "Дата данных не передана"
        return m
    text = f"годовая ставка {rate} (метод — в подробностях) · худшая просадка {dd or 'не измерена'}"
    tech = {"metric_type": book.get("metric_type"), "method": "годовая ставка рукава (sleeve_track)",
            "mechanism": v.get("mechanism_ru"), "position": v.get("position_ru"),
            "live": v.get("live_reason_ru"), "version": v.get("version")}
    return metric(label, text, confidence=conf, source=src, measured_at=book.get("as_of"), updated_at=updated,
                  unit="%", technical=tech)


def _ddmmyyyy(d: Any) -> Optional[str]:
    if not isinstance(d, str) or len(d) < 10 or d[4] != "-" or d[7] != "-":
        return None
    return f"{d[8:10]}.{d[5:7]}.{d[0:4]}"


def paper_portfolio(truth: dict, updated: Optional[str]) -> dict:
    books = _get(truth, "capital.defi.books")
    out = []
    for key in ("conservative", "balanced", "aggressive"):
        out.append(_book_metric(key, (books or {}).get(key) if isinstance(books, dict) else None, updated))
    return {"title": "Доходность по пакетам: период и метод", "note": "Модель на виртуальном капитале — реальные "
            "деньги здесь не двигаются.", "items": out,
            "limitations": ["Расходы на сделки показаны итогом с начала пакета; разбивка по сделкам — в журнале.",
                            "Время начальной оценки периода не записано — записана только дата."]}


# ── KPI tiles of the directions (DIRECTOR-OS-UX-03, owner 13.10) ───────────────────────────────────
# «показать все три пакета, сколько виртуальных денег выделено на каждый, текущую доходность каждого и
# общий результат; трейдинг: сколько стратегий, на какой стадии, сколько данных накоплено». Every number
# is read from the snapshot (capital.package_values, truth.capital.defi.books, truth.capital.trading_lab);
# a progress bar is drawn ONLY with a measurable denominator (days of the 30-day maturity rule).
PACKAGE_RU = {"conservative": "Консервативный", "balanced": "Сбалансированный", "aggressive": "Агрессивный"}
try:   # the ONE reportability threshold of a paper track (ADR-580 C2) — read, never retyped
    from spa_core.defi_engine.package_status import REPORTABLE_AFTER as MATURITY_DAYS
except Exception:  # noqa: BLE001
    MATURITY_DAYS = None


def _pct_signed(v: Optional[float]) -> Optional[str]:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    from spa_core.utils.presentation import fmt_pct
    return fmt_pct(v, "ru", signed=True)


def kpi(label: str, big: Optional[str], caption: Optional[str], *, confidence: str, source: Optional[str],
        measured_at: Optional[str], updated_at: Optional[str], state: Optional[tuple] = None,
        bar: Optional[dict] = None, reason: Optional[str] = None, technical: Optional[dict] = None,
        link_area: Optional[str] = None, unit: Optional[str] = None) -> dict:
    """A compact tile: a big number, one caption, an optional status pill (words + tone) and an
    optional bar ``{"value", "max", "text"}`` — only when both value and max are measured."""
    m = metric(label, caption if confidence in (MEASURED, STALE, PARTIAL) else None, confidence=confidence,
               source=source, measured_at=measured_at, updated_at=updated_at, reason=reason, technical=technical,
               unit=unit)
    m["big"] = big if confidence in (MEASURED, STALE, PARTIAL) else "—"
    if state:
        m["state_pill"] = {"text": state[0], "tone": state[1]}
    if bar and isinstance(bar.get("value"), (int, float)) and isinstance(bar.get("max"), (int, float)) and bar["max"] > 0:
        m["bar"] = {"value": bar["value"], "max": bar["max"], "text": bar.get("text"),
                    "ratio": max(0.0, min(1.0, float(bar["value"]) / float(bar["max"])))}
    m["link_area"] = link_area
    return m


def package_tiles(model: dict, updated: Optional[str], with_costs: bool = False) -> list:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    pv = _get(model, "capital.package_values") or {}
    items = pv.get("items") if isinstance(pv.get("items"), dict) else {}
    pv_meta = pv.get("_meta") if isinstance(pv.get("_meta"), dict) else {}
    books = _get(truth, "capital.defi.books") or {}
    pk = _get(model, "capital.packages.items") or {}
    out = []
    for key in ("conservative", "balanced", "aggressive"):
        name = PACKAGE_RU[key]
        it = items.get(key) if isinstance(items.get(key), dict) else {}
        nav, seed = it.get("nav_usd"), it.get("seed_usd")
        book = books.get(key) if isinstance(books, dict) and isinstance(books.get(key), dict) else {}
        health = (pk.get(key) or {}).get("state") if isinstance(pk, dict) else None
        acc = book.get("accumulating_days")
        tech = {"источник стоимости": "data/defi_engine/status.json books.%s.nav_usd" % key,
                "стартовый капитал": f"{_usd(seed)} с {_ddmmyyyy(it.get('seed_date')) or 'дата не записана'}"
                if isinstance(seed, (int, float)) else "не записан",
                "состояние пакета (движок)": health}
        if nav is None:
            out.append(kpi(name, None, None, confidence=NOT_MEASURED, source="capital.package_values",
                           measured_at=pv_meta.get("observed_at"), updated_at=updated,
                           reason="стоимость пакета не передана", technical=tech, link_area="money"))
            continue
        bar = None
        if book.get("period_return_ru"):
            start, end = _ddmmyyyy(book.get("period_start")), _ddmmyyyy(book.get("period_end"))
            cap = f"{book['period_return_ru']} за {start}–{end}" if start and end else book["period_return_ru"]
            state = ("работает", "ok")
        elif isinstance(acc, int):
            need = f" из {MATURITY_DAYS}" if MATURITY_DAYS else ""
            cap = f"результат: рано — собрано {acc}{need} дней"
            state = ("собирает данные", "info")
            bar = {"value": acc, "max": MATURITY_DAYS, "text": f"{acc}{need} дней"} if MATURITY_DAYS else None
        elif book.get("rate_ru"):
            # snapshot built by code without the period method — the book's own annual rate, method named
            cap = f"годовая ставка {book['rate_ru']} (метод — в «Деньгах»)"
            state = ("работает", "ok")
        else:
            cap = "результат: не измерен"
            state = ("не измерено", "unknown")
        if health in ("DEGRADED", "CRITICAL", "STALE"):
            state = ("требует внимания", "warn" if health != "CRITICAL" else "problem")
        cost = it.get("costs_paid_usd")
        tech["расходы на сделки с начала"] = _usd(cost) if isinstance(cost, (int, float)) else "не переданы"
        if with_costs:
            cap += f" · расходы {_usd(cost)}" if isinstance(cost, (int, float)) else " · расходы: не переданы"
        out.append(kpi(name, _usd(nav), cap, confidence=MEASURED, source="capital.package_values",
                       measured_at=pv_meta.get("observed_at"), updated_at=updated, state=state, bar=bar,
                       technical=tech, link_area="money", unit="USD (виртуальные)"))
    return out


def totals_tile(model: dict, updated: Optional[str]) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    pv = _get(model, "capital.package_values") or {}
    items = pv.get("items") if isinstance(pv.get("items"), dict) else {}
    meta = pv.get("_meta") if isinstance(pv.get("_meta"), dict) else {}
    navs = [items.get(k, {}).get("nav_usd") for k in ("conservative", "balanced", "aggressive")]
    seeds = [items.get(k, {}).get("seed_usd") for k in ("conservative", "balanced", "aggressive")]
    if not all(isinstance(x, (int, float)) for x in navs + seeds):
        return kpi("Всего на модели", None, None, confidence=NOT_MEASURED, source="capital.package_values",
                   measured_at=meta.get("observed_at"), updated_at=updated,
                   reason="стоимость или стартовый капитал хотя бы одного пакета не передан", link_area="money")
    total, start = sum(navs), sum(seeds)
    change = total - start
    books = _get(truth, "capital.defi.books") or {}
    young = [(PACKAGE_RU[k], (books.get(k) or {}).get("accumulating_days")) for k in ("balanced", "aggressive")
             if isinstance(books, dict) and isinstance((books.get(k) or {}).get("accumulating_days"), int)]
    annual = ("общий годовой показатель: рано — " + ", ".join(f"{n} {d}" + (f" из {MATURITY_DAYS}" if MATURITY_DAYS else "") + " дней" for n, d in young)
              if young else "общий годовой показатель: не считается — методика объединения не утверждена")
    sign = "+" if change >= 0 else "−"
    cap = (f"изменение стоимости: {sign}{_usd(abs(change))} ({_pct_signed(change / start * 100)}) от стартовых "
           f"{_usd(start)}")
    tech = {"как посчитано": "сумма текущей стоимости трёх пакетов минус сумма их стартового капитала",
            "почему это не доходность": "у пакетов разные даты старта; у Сбалансированного и Агрессивного история "
                                        "до 02.10.2026 считалась по прежней (ошибочной) экономике, ADR-531",
            "годовой": annual}
    m = kpi("Всего на модели", _usd(total), cap, confidence=MEASURED, source="capital.package_values",
            measured_at=meta.get("observed_at"), updated_at=updated, state=("модель, не деньги", "info"),
            technical=tech, link_area="money", unit="USD (виртуальные)")
    m["secondary_short"] = annual[0].upper() + annual[1:]
    m["secondary"] = ("Это изменение стоимости, а не доходность: пакеты стартовали в разные даты, и часть истории "
                      "двух пакетов считалась по прежней модели. Общий годовой показатель появится, когда все "
                      "пакеты наберут по 30 дней данных.")
    return m


def trading_tile(model: dict, updated: Optional[str]) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    cell = _get(truth, "capital.trading_lab")
    conf, reason = _cell_confidence(cell)
    v = cell.get("value") if isinstance(cell, dict) and isinstance(cell.get("value"), dict) else {}

    def val(k):
        x = v.get(k)
        return x.get("value") if isinstance(x, dict) else None
    n = val("strategies_researched")
    if conf != MEASURED or not isinstance(n, int):
        return kpi("Трейдинг (исследование)", None, None, confidence=conf if conf != MEASURED else NOT_MEASURED,
                   source=_get(cell, "canon"), measured_at=_get(cell, "as_of"), updated_at=updated,
                   reason=reason or "число стратегий не передано", link_area="money")
    rob = val("robustness_pass") or {}
    fwd, champ = val("forward_paper_active"), val("champions")
    perf = val("performance_since_forward_start") or {}
    days = [x.get("days_elapsed") for x in perf.values() if isinstance(x, dict)
            and isinstance(x.get("days_elapsed"), (int, float))]
    try:
        from spa_core.trading_research.lifecycle import ROBUST_RULES
        need = ROBUST_RULES.get("min_days")
    except Exception:  # noqa: BLE001 — the rule unreadable ⇒ the bar is not drawn, never guessed
        need = None
    stages = []
    if isinstance(rob, dict) and isinstance(rob.get("backtest_qualified"), int):
        stages.append(f"{rob['backtest_qualified']} прошли бэктест")
    if isinstance(fwd, int):
        stages.append(f"{fwd} на бумажной проверке")
    if isinstance(champ, int):
        stages.append(f"{champ} готовых")
    bar = None
    if days and isinstance(need, int):
        d = int(max(days))
        bar = {"value": d, "max": need, "text": f"{d} из {need} дней статистики (лучшая)"}
    state = ("собирает данные", "info") if isinstance(champ, int) and champ == 0 else ("работает", "ok")
    return kpi("Трейдинг (исследование)", f"{n}", "исследовано · " + " · ".join(stages),
               confidence=MEASURED, source=cell.get("canon"), measured_at=cell.get("as_of"), updated_at=updated,
               state=state, bar=bar, link_area="money", unit="стратегий",
               technical={"правило зрелости": f"надёжность после {need} дней бумажной проверки" if need else "не прочитано",
                          "дни по стратегиям": {k: (x or {}).get("days_elapsed") for k, x in list(perf.items())[:8]}})


def owner_questions(truth: dict, updated: Optional[str]) -> dict:
    dec = _get(truth, "decisions") or {}
    groups = dec.get("groups") if isinstance(dec, dict) else None
    src = "nimbalyst-local/tracker (очередь владельца, origin)"
    if not isinstance(groups, dict):
        return {"title": "Нужно ваше решение", "count": None,
                "summary": metric("Вопросы владельцу", None, confidence=NOT_MEASURED, source=src, measured_at=None,
                                  updated_at=updated, reason=plain(dec.get("unknown_ru")) or "очередь не прочитана"),
                "items": []}
    items = [d for d in (groups.get("owner") or []) if isinstance(d, dict)]

    def order(d):
        sk = d.get("subject_key")
        rank = SUBJECT_ORDER.index(sk) if sk in SUBJECT_ORDER else len(SUBJECT_ORDER)
        age = d.get("age_days") if isinstance(d.get("age_days"), (int, float)) else -1
        return (rank, -age, str(d.get("id")))

    rows = []
    for d in sorted(items, key=order):
        sk = d.get("subject_key")
        rows.append({"id": d.get("id"), "title": plain(d.get("title_ru")) or "Без названия",
                     "subject": SUBJECT_RU.get(sk, "Тема не объявлена" if sk is None
                                               else "Тема не распознана — проблема отображения"),
                     "subject_known": sk in SUBJECT_RU, "age_days": d.get("age_days"),
                     "why": plain(d.get("reason_ru")), "link_area": "decisions"})
    n = len(rows)
    text = ("Вопросов к вам нет" if n == 0 else f"Ждут вашего ответа: {n}")
    return {"title": "Нужно ваше решение", "count": n,
            "summary": metric("Вопросы владельцу", text, confidence=MEASURED, source=src, measured_at=None,
                              updated_at=updated, unit="шт."),
            "items": rows,
            "note": "Открытие карточки — не одобрение. Ответ даётся только кнопкой в Телеграме."}


def _system_problems(model: dict, truth: dict, updated: Optional[str]) -> list:
    out = []
    sysv = _get(model, "overview.system") or {}
    st = sysv.get("state")
    reasons = {"resources": "мало ресурсов на Mac (диск, память)", "agents": "часть фоновых задач с предупреждениями",
               "guard": "сторож данных устарел", "packages": "сбой бумажного портфеля"}
    if st in ("DEGRADED", "CRITICAL"):
        parts = [reasons[k] for k in reasons if isinstance(sysv.get("reason"), str) and k in sysv["reason"]]
        txt = ("Система работает с ограничениями" if st == "DEGRADED" else "Авария системы") + \
              (": " + ", ".join(parts) if parts else "")
        out.append(metric("Состояние системы", txt, confidence=MEASURED, source="overview.system",
                          measured_at=None, updated_at=updated, tone="warn" if st == "DEGRADED" else "problem",
                          technical={"state": st, "reason": sysv.get("reason")}))
    elif st not in ("HEALTHY", None):
        out.append(metric("Состояние системы", None, confidence=INTERPRETATION_PROBLEM, source="overview.system",
                          measured_at=None, updated_at=updated, reason=f"не удалось понять статус «{st}»"))
    if sysv.get("kill_switch"):
        out.insert(0, metric("Стоп-кран", "Стоп-кран взведён: исполнение остановлено", confidence=MEASURED,
                             source="overview.system", measured_at=None, updated_at=updated, tone="problem"))
    pr = _get(truth, "studio.problems")
    conf, reason = _cell_confidence(pr)
    if conf == MEASURED and isinstance(pr, dict):
        items = [i for i in (pr.get("items") or []) if isinstance(i, dict)]
        n = pr.get("open") if isinstance(pr.get("open"), int) else len(items)
        if n:
            out.append(metric("Открытые проблемы", f"Открыто проблем: {n} — подробности в разделе «Защита»",
                              confidence=MEASURED, source=pr.get("canon"), measured_at=pr.get("as_of"),
                              updated_at=updated, tone="warn", unit="шт.",
                              technical={"items": [plain(i.get("plain_ru")) for i in items]}))
    elif conf != MEASURED:
        out.append(metric("Открытые проблемы", None, confidence=conf, source=_get(pr, "canon"),
                          measured_at=_get(pr, "as_of"), updated_at=updated, reason=reason))
    inc = _get(truth, "studio.incidents")
    if isinstance(inc, dict) and isinstance(inc.get("open"), int) and inc["open"] > 0:
        out.append(metric("Тревоги", f"Открытых тревог: {inc['open']}", confidence=MEASURED,
                          source=inc.get("canon"), measured_at=inc.get("as_of"), updated_at=updated, tone="problem"))
    return out


def _current_epic(model: dict, truth: dict) -> Optional[dict]:
    ce = _get(model, "overview.now.current_epic")
    if isinstance(ce, dict) and ce.get("epic"):
        return ce
    items = _get(truth, "studio.roadmap.value.items") or []
    for it in items:
        if isinstance(it, dict) and it.get("state") == "IN_PROGRESS":
            return it
    return None


def headline(model: dict, truth: dict, questions: dict, problems: list, updated: Optional[str]) -> dict:
    """«Главное сейчас» + следующий шаг — deterministic priority, every branch named."""
    sysv = _get(model, "overview.system") or {}
    if sysv.get("kill_switch"):
        main, nxt = "Стоп-кран взведён — исполнение остановлено", "Разобрать причину в разделе «Защита»"
    elif questions.get("count"):
        first = questions["items"][0]
        main = f"Ждут вашего решения: {questions['count']}"
        nxt = f"Ответить на вопрос «{first['title']}» ({first['subject'].lower()}, {first['age_days']} дн.)"
    else:
        ep = _current_epic(model, truth)
        main = ("Идёт работа: " + (stage_title(ep.get("epic")).get("text") or "без названия")) if ep \
            else "Активной работы не видно"
        cw = _get(truth, "studio.claude_work") or {}
        nxt = plain(cw.get("next_step_ru")) or "Ваших действий не требуется"
    if problems and not questions.get("count") and not sysv.get("kill_switch"):
        nxt = nxt + " · есть проблемы — см. ниже"
    return {"title": "Главное сейчас", "main": main, "next": nxt, "updated_at": updated,
            "updated_at_ru": _madrid(updated), **_money_mode(model)}


def _money_mode(model: dict) -> dict:
    """The two lines the first screen and «Деньги» open with (ARB 09.10, round 5): real money and the
    operating mode — both from ``capital.real_capital`` only; anything unknown is said, never $0.
    ``mode_detail`` carries the mode's explanation ONCE (shown behind a tap on «Деньги»)."""
    rc = _get(model, "capital.real_capital") or _get(model, "overview.capital.real_capital")
    if not isinstance(rc, dict):
        return {"real_line": "Настоящие деньги: не измерено", "mode_line": "Режим работы: не измерен",
                "mode_detail": "Состояние настоящих денег в пульт не передано."}
    usd, st, basis = rc.get("usd"), rc.get("state"), rc.get("basis")
    real = (f"Настоящие деньги: {_usd(usd)}" if isinstance(usd, (int, float)) and not isinstance(usd, bool)
            and st in ("LIVE_NOT_APPROVED", "LIVE_APPROVED") else "Настоящие деньги: не измерено")
    if st == "LIVE_NOT_APPROVED" and isinstance(basis, str) and "read_only_simulation" in basis:
        mode = "Сейчас система работает на виртуальном капитале"
        detail = ("Настоящие деньги не разрешены: исполнение только бумажное (бумажная симуляция). "
                  "Все суммы и доходности ниже — модель на виртуальном капитале.")
    elif st == "LIVE_NOT_APPROVED":
        mode = "Настоящие деньги не разрешены; режим исполнения не назван"
        detail = "Режим исполнения в пульт не передан."
    elif st == "LIVE_APPROVED":
        mode = "Настоящие деньги разрешены решением владельца"
        detail = "Исполнение с настоящими деньгами разрешено решением владельца."
    else:
        mode = "Режим работы: не измерен"
        detail = "Состояние настоящих денег не измерено."
    return {"real_line": real, "mode_line": mode, "mode_detail": detail}


def active_work(model: dict, truth: dict, updated: Optional[str]) -> dict:
    tasks = _get(truth, "studio.tasks")
    conf, reason = _cell_confidence(tasks)
    if conf == MEASURED and isinstance(tasks, dict):
        ip, st, bl = tasks.get("in_progress"), tasks.get("in_progress_stale"), tasks.get("blocked")
        txt = f"В работе задач: {ip}" + (f" (давно без движения: {st})" if st else "") + \
              (f" · остановлено: {bl}" if bl else "")
        t = metric("Задачи", txt, confidence=MEASURED, source=tasks.get("canon"), measured_at=tasks.get("as_of"),
                   updated_at=updated, unit="шт.")
    else:
        t = metric("Задачи", None, confidence=conf, source=_get(tasks, "canon"), measured_at=_get(tasks, "as_of"),
                   updated_at=updated, reason=reason)
    cw = _get(truth, "studio.claude_work")
    cconf, creason = _cell_confidence(cw)
    if cconf == MEASURED and isinstance(cw, dict):
        active = [a for a in (cw.get("active") or []) if isinstance(a, dict)]
        if active:
            txt = "Сейчас работает: " + "; ".join(plain(a.get("card_title_ru") or a.get("epic") or a.get("card"))
                                                  or "задача без названия" for a in active)
        else:
            txt = "Сейчас никто не работает"
        c = metric("Работа ассистента", txt, confidence=MEASURED, source=cw.get("canon"),
                   measured_at=cw.get("as_of"), updated_at=updated)
    else:
        c = metric("Работа ассистента", None, confidence=cconf, source=_get(cw, "canon"),
                   measured_at=_get(cw, "as_of"), updated_at=updated, reason=creason)
    ep = _current_epic(model, truth)
    st_t = stage_title(ep.get("epic")) if ep else {"text": None, "known": False, "original": None}
    e = metric("Текущий этап плана", st_t["text"] if ep else None,
               confidence=MEASURED if ep else NOT_MEASURED, source="docs/ROADMAP.md (через studio.roadmap)",
               measured_at=None, updated_at=updated, reason=None if ep else "текущий этап не найден в плане",
               technical={"исходное название этапа (в плане — по-английски)": st_t.get("original")} if ep else None)
    return {"title": "Идёт работа", "items": [e, c, t]}


def _decisions_tile(q: dict, updated: Optional[str]) -> dict:
    s = q.get("summary") or {}
    if q.get("count") is None:
        return kpi("Ждут вашего решения", None, None, confidence=s.get("confidence", NOT_MEASURED),
                   source=s.get("source"), measured_at=None, updated_at=updated,
                   reason="очередь решений не прочитана", link_area="decisions")
    n = q["count"]
    first = q["items"][0] if q.get("items") else None
    cap = (f"первое: {first['title']}" if first else "вопросов к вам нет")
    return kpi("Ждут вашего решения", str(n), cap, confidence=MEASURED, source=s.get("source"), measured_at=None,
               updated_at=updated, state=(("нужен ответ", "warn") if n else ("всё отвечено", "ok")),
               link_area="decisions", unit="шт.")


def _work_tile(truth: dict, updated: Optional[str]) -> dict:
    tasks = _get(truth, "studio.tasks")
    conf, reason = _cell_confidence(tasks)
    ip = tasks.get("in_progress") if isinstance(tasks, dict) else None
    if conf != MEASURED or not isinstance(ip, int):
        return kpi("Работа", None, None, confidence=conf if conf != MEASURED else NOT_MEASURED,
                   source=_get(tasks, "canon"), measured_at=_get(tasks, "as_of"), updated_at=updated,
                   reason=reason or "счётчики задач не переданы", link_area="work")
    bl, stale = tasks.get("blocked"), tasks.get("in_progress_stale")
    parts = []
    if isinstance(bl, int):
        parts.append(f"остановлено: {bl}")
    if isinstance(stale, int):
        parts.append(f"давно без движения: {stale}")
    cw = _get(truth, "studio.claude_work") or {}
    active = [a for a in (cw.get("active") or []) if isinstance(a, dict)] if isinstance(cw, dict) else []
    parts.append("ассистент сейчас работает" if active else "ассистент сейчас не работает")
    state = ("есть остановленные", "warn") if isinstance(bl, int) and bl else ("идёт", "ok")
    return kpi("Задачи в работе", str(ip), " · ".join(parts), confidence=MEASURED, source=tasks.get("canon"),
               measured_at=tasks.get("as_of"), updated_at=updated, state=state, link_area="work", unit="шт.")


def _problems_tile(truth: dict, updated: Optional[str]) -> dict:
    pr = _get(truth, "studio.problems")
    conf, reason = _cell_confidence(pr)
    if conf != MEASURED or not isinstance(pr, dict):
        return kpi("Проблемы", None, None, confidence=conf if conf != MEASURED else NOT_MEASURED,
                   source=_get(pr, "canon"), measured_at=_get(pr, "as_of"), updated_at=updated,
                   reason=reason or "реестр проблем не прочитан", link_area="protection")
    rows = [_problem_row(i) for i in (pr.get("items") or []) if isinstance(i, dict)]
    counts = {k: sum(1 for r in rows if r["severity"] == k) for k in SEVERITY_ORDER}
    cap = " · ".join(f"{SEVERITY_RU[k].lower()}: {counts[k]}" for k in SEVERITY_ORDER if counts[k]) or "открытых нет"
    state = (("есть критичные", "problem") if counts["critical"] else
             ("есть важные", "warn") if counts["important"] else
             ("к сведению", "info") if rows else ("всё спокойно", "ok"))
    return kpi("Проблемы", str(len(rows)), cap, confidence=MEASURED, source=pr.get("canon"),
               measured_at=pr.get("as_of"), updated_at=updated, state=state, link_area="protection", unit="шт.")


def overview(model: dict, updated: Optional[str]) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    q = owner_questions(truth, updated)
    probs = _system_problems(model, truth, updated)
    return {
        "title": "Обзор",
        "kpis": {"title": "Направления", "packages": package_tiles(model, updated),
                 "total": totals_tile(model, updated), "trading": trading_tile(model, updated),
                 "decisions": _decisions_tile(q, updated), "problems": _problems_tile(truth, updated),
                 "work": _work_tile(truth, updated),
                 "note": "Все суммы — виртуальный капитал модели, не настоящие деньги."},
        "headline": headline(model, truth, q, probs, updated),
        "questions": q,
        "money": {"title": "Модельный портфель", "real": real_money(model, updated),
                  "paper": paper_portfolio(truth, updated)["items"][0],
                  "note": "Подробнее — в разделе «Деньги»."},
        "work": active_work(model, truth, updated),
        "problems": {"title": "Существенные проблемы", "items": probs,
                     "empty": "Существенных проблем не видно" if not probs else None},
    }


# Plan rows fall into four owner groups; a «queued» row whose own note says it is done is a
# CONTRADICTION in the plan (shown as such), never silently resolved either way (ARB 09.10).
PLAN_GROUPS = (("done", "Сделано"), ("active", "Идёт"), ("queued", "В очереди"),
               ("conflict", "Противоречие в плане"), ("unknown", "Состояние не распознано"))


def _roadmap_rows(truth: dict) -> list:
    rows = []
    for it in _get(truth, "studio.roadmap.value.items") or []:
        if not isinstance(it, dict):
            continue
        st = it.get("state")
        name = stage_title(it.get("epic"))
        if st == "QUEUED" and note_says_done(it.get("note")):
            group, state = "conflict", "Противоречие: в плане «в очереди», а в заметке — «сделано»"
        elif st in ROADMAP_STATE_RU:
            group = {"DONE": "done", "IN_PROGRESS": "active", "QUEUED": "queued", "BLOCKED": "active"}[st]
            state = ROADMAP_STATE_RU[st]
        else:
            group, state = "unknown", "Состояние не распознано — проблема отображения"
        rows.append({"n": it.get("n"), "title": name["text"] or "Без названия", "title_known": name["known"],
                     "state": state, "state_known": group not in ("conflict", "unknown"), "group": group,
                     "technical": {"state": st, "исходное название": it.get("epic"), "заметка": plain(it.get("note"))}})
    return rows


_LAT = re.compile(r"[A-Za-z]")
_CYR = re.compile(r"[А-Яа-яЁё]")


def _release_title(summary: Any) -> str:
    """A change description in Russian, or a neutral Russian line when the commit was written in
    English (ARB 09.10: no English on main screens; the original stays in technical details)."""
    t = plain(summary)
    if not t:
        return "Без описания"
    if len(_LAT.findall(t)) > 2 * len(_CYR.findall(t)):
        return "Служебное изменение (описание только на английском — см. подробности)"
    return t


def recent_releases(model: dict, updated: Optional[str]) -> dict:
    feed = model.get("release_feed") if isinstance(model.get("release_feed"), dict) else {}
    items = [i for i in (feed.get("items") or []) if isinstance(i, dict)]
    n = len(items)
    count = (f"не меньше {RELEASE_FEED_LIMIT} (лента показывает только последние {RELEASE_FEED_LIMIT})"
             if n >= RELEASE_FEED_LIMIT else str(n))
    meta = feed.get("_meta") if isinstance(feed.get("_meta"), dict) else {}
    rows = [{"title": _release_title(i.get("summary")), "at_ru": _madrid(i.get("at")),
             "technical": {"commit": i.get("commit"), "kind": i.get("kind"),
                           "исходное описание": i.get("summary")}} for i in items[:8]]
    conf = MEASURED if meta.get("state") in ("HEALTHY", None) and items else (NOT_MEASURED if not items else MEASURED)
    return {"title": "Сделано недавно",
            "summary": metric("Изменений в ленте", count if items else None, confidence=conf,
                              source=", ".join(meta.get("sources") or []) or "git origin/main",
                              measured_at=meta.get("observed_at"), updated_at=updated,
                              reason=None if items else "лента изменений пуста или не прочитана"),
            "items": rows}


# ── ADR-760 «Мои записи»: что стало с записями владельца из пульта ───────────────────────────────
RECORD_STATUS_RU = {
    "new": "записано, ещё не разобрано",
    "in-progress": "в работе",
    "blocked": "остановлено",
    "done": "сделано",
}
RECORD_KIND_RU = {"idea": "идея", "task": "задача", "note": "замечание"}

#: Сквозной путь пульта (ADR-763): исход проверки → (причина, следующий шаг), когда в карточке их нет.
#: Копия слов исполнителя (``owner_queue.cockpit_loop.REASON_RU``) намеренно НЕ ввозится: пульт читает
#: снимок модели, а не код исполнителя; расхождение слов безопасно, расхождение смысла держит тест.
_NOT_ACCEPTED_DEFAULT = {
    "no_probe": ("проверка результата не объявлена, поэтому «сделано» поставить нельзя",
                 "исполнитель объявляет проверку и только потом продолжает"),
    "not_satisfied": ("проверка показала, что результат ещё не достигнут",
                      "исполнитель доделывает работу и запускает проверку снова"),
    "unmeasured": ("проверку не удалось провести — результат нечем измерить",
                   "исполнитель чинит саму проверку и перемеряет"),
    "executor_failed": ("исполнитель не смог выполнить работу",
                        "следующий цикл разберёт причину и возьмёт карточку снова"),
}


def _record_outcome(r: dict) -> dict:
    """Что стало с записью — простыми словами и со структурой, которую проверяет проба.

    ``kind``: carried · done_verified · done_unverified · not_accepted · in_work · accepted · new ·
    unknown. «Сделано и проверено» — ТОЛЬКО ``done`` с ``verified_by_probe``; закрытая без пробы
    карточка так не читается никогда (приём и закрытие ≠ проверенный результат)."""
    def out(kind, text, known=True, verified=False, reason=None, next_step=None):
        return {"kind": kind, "text": text, "known": known, "verified": verified,
                "reason": reason, "next_step": next_step}

    carried = r.get("carried_to")
    if carried:
        return out("carried", "перенесено: " + (plain(str(carried)) or "куда — в подробностях"))
    st = r.get("status")
    verdict = r.get("acceptance_verdict")
    if st == "done":
        if r.get("verified_by_probe") and verdict in (None, "satisfied"):
            when = _madrid(r.get("verified_at"))
            return out("done_verified", "сделано и проверено автоматической проверкой"
                       + (f" ({when})" if when else ""), verified=True)
        return out("done_unverified", "закрыто без проверки результата — не считается проверенным")
    if st in ("in-progress", "blocked"):
        head = "в работе" if st == "in-progress" else "остановлено"
        if not r.get("acceptance_probe"):
            verdict = "no_probe"
        if verdict in _NOT_ACCEPTED_DEFAULT:
            d_reason, d_next = _NOT_ACCEPTED_DEFAULT[verdict]
            reason = plain(r.get("acceptance_reason")) or d_reason
            nxt = plain(r.get("acceptance_next")) or d_next
            return out("not_accepted", f"{head} — не принято: {reason}; следующий шаг: {nxt}",
                       reason=reason, next_step=nxt)
        if verdict == "satisfied":
            return out("in_work", f"{head} — проверка пройдена, закрытие ещё не завершено")
        return out("in_work", f"{head} — результат ещё не проверялся")
    if st == "new" and r.get("intake_seen"):
        if verdict == "no_probe":
            # ARB 26.10 U1: простыми словами; служебный текст диспетчера — в технических подробностях
            return out("not_accepted", "не взято в работу: проверка результата ещё не назначена; работа не начата",
                       reason="проверка результата ещё не назначена; работа не начата",
                       next_step="назначить проверку результата до начала работы — автоматически это пока не делается")
        if verdict in _NOT_ACCEPTED_DEFAULT:
            # исполнитель не взял: у записи нет машинной проверки результата (cockpit_dispatch, ARB 16.10)
            d_reason, d_next = _NOT_ACCEPTED_DEFAULT[verdict]
            reason = plain(r.get("acceptance_reason")) or d_reason
            nxt = plain(r.get("acceptance_next")) or d_next
            return out("not_accepted", f"не взято в работу: {reason}; следующий шаг: {nxt}",
                       reason=reason, next_step=nxt)
        return out("accepted", "принято, ждёт исполнителя")
    if st in RECORD_STATUS_RU:
        return out(st, RECORD_STATUS_RU[st])
    return out("unknown", f"состояние не распознано («{plain(str(st)) or 'пусто'}») — это проблема отображения",
               known=False)


#: ARB 16.10 — три разных вопроса о записи пульта, и ни один не отвечает за другой.
RECORD_CHANNEL_RU = {
    "cockpit-public": "через публичный пульт (Cloudflare Access)",
    "cockpit-local": "через локальный пульт на Mac",
    "agent-local": "агент / автоматизация через локальный пульт на Mac",
    "unknown": "канал не назван",
}
#: Полномочия — одна строка, не зависящая от автора и не называющая его.
RECORD_AUTHORITY_RU = ("Полномочий не даёт: ни на деньги, ни на публичные числа, ни на необратимые действия "
                       "(ADR-285) — кто бы ни написал запись")


def _record_author_ru(r: dict) -> str:
    """Автор — только установленный сервером. Владелец называется ТОЛЬКО при ``author == owner``."""
    a = r.get("author")
    if a == "owner":
        return "автор: владелец (подтверждено подписью Cloudflare Access)"
    if a == "agent":
        who = plain(str(r.get("author_identity") or "")) or "без имени"
        return f"автор: агент «{who}», не владелец"
    if a == "not-established":
        return {"access-unverified": "автор не установлен (канал защищён Access, личность не проверена подписью)",
                "loopback": "автор не установлен (локальный доступ к Mac)"}.get(
                    r.get("author_basis"), "автор не установлен")
    if r.get("provenance_legacy"):
        return "автор не записан (запись сделана до разделения канала и автора, 16.10)"
    return "автор не распознан — это проблема отображения"


def _record_provenance(r: dict) -> dict:
    channel = r.get("channel")
    ch = RECORD_CHANNEL_RU.get(channel) or ("канал не записан" if channel is None else "канал не распознан")
    author = _record_author_ru(r)
    note = None
    if r.get("legacy_owner_claim") and r.get("author") != "owner":
        note = "строка «заметка владельца» в самой карточке не подтверждена — автор не установлен как владелец"
    return {"channel_ru": ch, "author_ru": author, "authority_ru": RECORD_AUTHORITY_RU,
            "author_established": r.get("author") in ("owner", "agent"),
            "by_owner": r.get("author") == "owner",
            "provenance": f"Пришло {ch}; {author}." + (" Уточнено дописанной строкой." if r.get("provenance_corrected")
                                                       else ""),
            "provenance_note": note}


def _record_status(r: dict) -> tuple:
    """(text, known) — a status the dictionary does not know is named, never shown as success."""
    o = _record_outcome(r)
    return o["text"], o["known"]


#: ARB 26.10 — the preparation of a record, in the owner's words. A preparation permits nothing.
PREP_TEXT_LIMIT = 1500
#: The owner-facing heading of each preparation state (U1: a question is a question, never «план подготовлен»).
PREP_HEAD_RU = {
    "none": "Плана пока нет — подготовку для этой записи не запускали",
    "plan": "План подготовлен — это предложение для разбора, работа не начата",
    "clarification": "Нужно уточнение",
    "stale": "План устарел — его нужно подготовить заново",
    "incomplete": "Подготовка не удалась — плана нет",
    "unreadable": "Подготовку не удалось прочитать — это проблема отображения",
    "busy": "Подготовка идёт",
}
#: Model-declared subject (ADR-285 vocabulary) in plain words; always marked as the MODEL's estimate.
_SUBJECT_RU = {"NONE": "особых полномочий не требуется", "MONEY": "касается денег — решает только владелец",
               "PUBLIC_NUMBERS_NAMING_LEGAL": "касается публичных чисел, названий или юридических формулировок — "
                                              "решает только владелец",
               "IRREVERSIBLE": "необратимое действие — решает только владелец",
               "PHYSICAL_ACTION": "нужно действие, которое может сделать только владелец",
               "UNKNOWN": "не определено"}
_MARKERS = ((re.compile(r"(?mi)^\s*UNKNOWN\s*:\s*"), "Неизвестно: "),
            (re.compile(r"(?i)NEW CHECK NEEDED\s*:\s*"), ""),
            (re.compile(r"(?mi)^\s*subject\s*:.*$\n?"), ""),
            (re.compile(r"`([^`]*)`"), r"«\1»"),
            (re.compile(r"(?mi)^\s*(Вопрос|Question)\s*:\s*"), ""))


def _prep_text(v: Any) -> Optional[str]:
    """Model text shown AS TEXT (the UI uses text nodes), bounded; raw model markers become plain words."""
    if not isinstance(v, str) or not v.strip():
        return None
    for rx, rep in _MARKERS:
        v = rx.sub(rep, v)
    v = v.strip()
    if not v:
        return None
    return v if len(v) <= PREP_TEXT_LIMIT else v[:PREP_TEXT_LIMIT] + " …(сокращено)"


def _prep_reason_ru(r: str) -> str:
    """Diagnostic reason (English, for the technical details) → one plain Russian phrase."""
    r = str(r)
    if r == "the request text changed":
        return "текст записи изменился после подготовки"
    if r.startswith("source changed or missing"):
        return "изменились документы, на которых построен план"
    if r.startswith("the card's request is not readable"):
        return "текст записи сейчас не читается"
    if r.startswith("no source fingerprints"):
        return "актуальность плана проверить нельзя"
    if r == "the code version changed":
        return "изменилась версия кода"
    if r.startswith("no code fingerprint"):
        return "у плана нет отпечатка версии кода — подготовить заново"
    if r.startswith("the code version is not measurable"):
        return "версию кода сейчас установить нельзя"
    if r == "provider status quota":
        return "у модели закончился лимит"
    if r == "provider status refused":
        return "подготовка не запускалась: модель не назначена"
    if r.startswith("provider status"):
        return "модель не дала ответа"
    if r.startswith("preparation"):
        return "ответ модели неполный"
    if r.startswith("another preparation"):
        return "подготовка этой записи уже идёт"
    return "причина записана в технических подробностях"


def _record_preparation_ru(p: Any) -> Optional[dict]:
    if p is None:
        return None                                   # feature not attached (production) — no block at all
    if not isinstance(p, dict) or p.get("state") not in ("none", "current", "stale", "incomplete", "unreadable"):
        return {"state": "unreadable", "head": PREP_HEAD_RU["unreadable"], "known": False, "technical": {}}
    st = p["state"]
    shown = st
    if st == "current":
        shown = "clarification" if p.get("form") == "clarification" else "plan"
    out: dict = {"state": shown, "head": PREP_HEAD_RU[shown], "known": st != "unreadable",
                           "alert": shown in ("stale", "incomplete", "unreadable", "clarification")}
    raw = p.get("reasons")
    reasons = [str(r) for r in raw] if isinstance(raw, list) else []
    plain_reasons = list(dict.fromkeys(_prep_reason_ru(r) for r in reasons))
    if plain_reasons:
        out["why"] = "; ".join(plain_reasons)
    if shown == "plan":
        out["outcome"] = _prep_text(p.get("outcome"))
        out["plan"] = _prep_text(p.get("plan"))
        out["check"] = (("Нужна новая проверка результата (её ещё нет): " + (_prep_text(p.get("acceptance_text")) or ""))
                        if p.get("acceptance") == "new_check_proposed" else
                        "Названа существующая проверка — относится ли она к поручению, не установлено")
        out["question"] = _prep_text(p.get("question"))
    elif shown == "clarification":
        out["question"] = _prep_text(p.get("question"))
    ap = p.get("approval") if isinstance(p.get("approval"), dict) else None
    oc = p.get("execution") if isinstance(p.get("execution"), dict) else None
    if ap is not None:
        when = _madrid(ap.get("at")) or "время не записано"
        how = ("перенесено агентом из сессии — импорт оператора, не подтверждённый канал"
               if ap.get("source") == "operator-import" else
               "запись до привязки задачи, предмета и проверки — ручной сценарий")
        if ap.get("valid"):
            out["approval"] = (f"Одобрено: {ap.get('approver') or '?'} ({when}), версия плана "
                               f"{str(ap.get('version'))[:12]}; {how}")
            out["head"] = ("План одобрен — исполнение допускается только с объявленной проверкой"
                           if ap.get("bound") else
                           "План одобрен до привязки проверки — к исполнению по этой записи не допускается")
        else:
            out["approval"] = (f"Одобрение {when} относится к ПРЕЖНЕЙ версии плана — "
                               "для текущего плана оно не действует, нужно одобрить заново")
            out["alert"] = True
    if oc is not None:
        # «Проверено» — только по записи ФАКТИЧЕСКОГО запуска одобренной пробы (ADR-839,
        # work_packet.decisions_for); файл итога со словом satisfied этого не доказывает.
        verdict = str(oc.get("verdict"))
        if oc.get("verified"):
            out["head"] = "Выполнено и проверено: проверка запущена и результат подтвердила"
        else:
            out["head"] = ("Итог записан, но проверкой НЕ подтверждён: "
                           + str(oc.get("not_verified_because") or "причина не названа"))
            out["alert"] = True
        out["result"] = f"Проверка «{oc.get('probe')}» ({verdict}): {_prep_text(oc.get('detail')) or verdict}"
    if shown in ("plan", "clarification"):
        out["authority"] = ("по оценке модели — " + _SUBJECT_RU.get(str(p.get("subject")), "не определено")
                            + ". Это не проверка прав и не разрешение начинать работу.")
        out["by"] = "тестовый адаптер (не модель)" if p.get("real_provider") is False else "модель"
        out["prepared_at"] = _madrid(p.get("prepared_at")) or "время не записано"
    out["technical"] = {"подготовка: код состояния": st, "подготовка: форма": p.get("form"),
                        "подготовка: предмет (код)": p.get("subject"),
                        "подготовка: диагностика": "; ".join(reasons) or None,
                        "подготовка: каталог": p.get("run"),
                        "подготовка: исходный текст плана" if shown == "stale" else "подготовка: исходный текст приёмки":
                            (p.get("plan") if shown == "stale" else p.get("acceptance_text"))}
    return out


def my_records(model: dict, updated: Optional[str]) -> Optional[dict]:
    """«Мои записи» — the latest cockpit records from the production tracker, read-only."""
    mr = _get(model, "intake.my_records")
    title = "Мои записи"
    # ARB 16.10: не «ваши» — автор каждой записи назван в её строке, и владельцем он назван только
    # по проверенной подписи.
    sub = "что стало с записями из пульта; у каждой — канал, установленный автор и граница полномочий"
    if mr is None:
        # снимок старше этого блока (до ADR-760 «Мои записи») — блока нет, а не «записей нет»
        return None
    if not isinstance(mr, dict) or mr.get("state") not in (MEASURED, NOT_MEASURED):
        m = metric(title, None, confidence=INTERPRETATION_PROBLEM, source=None, measured_at=None,
                   updated_at=updated, reason="не удалось понять раздел «Мои записи»")
        return {"title": title, "sub": sub, "summary": m, "rows": [], "empty": None}
    if mr["state"] == NOT_MEASURED or not isinstance(mr.get("items"), list):
        m = metric(title, None, confidence=NOT_MEASURED, source=mr.get("source"), measured_at=mr.get("measured_at"),
                   updated_at=updated, reason=plain(mr.get("reason")) or "причина не названа")
        return {"title": title, "sub": sub, "summary": m, "rows": [], "empty": None}
    rows = []
    for r in mr["items"]:
        if not isinstance(r, dict):
            continue
        o = _record_outcome(r)
        pv = _record_provenance(r)
        prep = _record_preparation_ru(r.get("preparation")) if "preparation" in r else None
        rows.append({**pv, "title": plain(r.get("title")) or "запись без названия",
                     "at_ru": _madrid(r.get("created_at")) or "время не записано",
                     "kind": RECORD_KIND_RU.get(r.get("kind"), "без пометки"),
                     "state": o["text"], "state_known": o["known"],
                     "state_kind": o["kind"], "verified": o["verified"],
                     "reason": o["reason"], "next_step": o["next_step"],
                     "voice": bool(r.get("voice")),
                     **({"preparation": prep} if prep is not None else {}),
                     "technical": {**(prep["technical"] if prep is not None else {}),
                                   "карточка": r.get("card"), "статус в трекере": r.get("status"),
                                   "перенесено в": r.get("carried_to"),
                                   "исполнитель": r.get("claimed_by"),
                                   "проба приёмки": r.get("acceptance_probe"),
                                   "проверено пробой": r.get("verified_by_probe"),
                                   "исход проверки": r.get("acceptance_verdict"),
                                   "причина (служебная)": r.get("acceptance_reason"),
                                   "следующий шаг (служебный)": r.get("acceptance_next"),
                                   "канал": r.get("channel"), "автор": r.get("author"),
                                   "основание авторства": r.get("author_basis")}})
    total = mr.get("total")
    text = (f"Записей из пульта: {total}; ниже последние {len(rows)}" if rows and isinstance(total, int)
            and total > len(rows) else (f"Записей из пульта: {len(rows)}" if rows else "Записей из пульта пока нет"))
    m = metric(title, text, confidence=MEASURED, source=mr.get("source"), measured_at=mr.get("measured_at"),
               updated_at=updated, unit="записей")
    return {"title": title, "sub": sub, "summary": m, "rows": rows,
            "empty": None if rows else "Записей из пульта пока нет"}


def work(model: dict, updated: Optional[str]) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    aw = active_work(model, truth, updated)
    cw = _get(truth, "studio.claude_work") or {}
    blocking = plain(cw.get("blocker_ru"))
    nxt = plain(cw.get("next_step_ru"))
    tasks = _get(truth, "studio.tasks") or {}
    blocked_n = tasks.get("blocked") if isinstance(tasks, dict) else None
    items = tasks.get("blocked_items") if isinstance(tasks, dict) else None
    stopped = _stopped_tasks(items) if isinstance(items, list) else None
    cmd = "python3 scripts/orchestrator_queue.py list --status blocked"
    if not blocked_n:
        blocked_txt, reason_state, blocked_tech = "Остановленных задач нет", "none_stopped", {}
    elif stopped is None:
        # older model: the board passed only the number
        blocked_txt = (f"Остановлено задач: {blocked_n}. Какая задача и почему — не измерено: эта версия данных "
                       "передаёт пульту только число остановленных. Узнать можно в трекере задач (способ — в подробностях).")
        reason_state = "not_in_model"
        blocked_tech = {"чего нет в модели пульта": "studio.tasks.blocked_items отсутствует — только число",
                        "как узнать на Mac": cmd}
    else:
        known = [x for x in stopped if x["reason"]]
        blocked_txt = (f"Остановлено задач: {blocked_n}. " +
                       ("Причина указана в карточке." if len(known) == len(stopped) and stopped else
                        "В трекере нет отдельного поля для причины остановки — ниже то, что указано в самой "
                        "карточке."))
        reason_state = "known" if stopped and len(known) == len(stopped) else "not_in_card"
        blocked_tech = {"откуда": "studio.tasks.blocked_items ← build_loop.board (поле карточки blocked_by и раздел "
                                  "«Следующий шаг»)",
                        "как посмотреть все остановленные на Mac": cmd}
    return {
        "title": "Работа",
        "now": aw,
        "blocking": {"title": "Что мешает", "text": blocking or blocked_txt,
                     "known_reason": bool(blocking) or reason_state == "known",
                     "reason_state": "known" if blocking else reason_state,
                     "stopped": stopped or [],
                     "technical": {} if blocking else blocked_tech},
        "next": {"title": "Что дальше", "text": nxt or "Следующий шаг в журнале работы не записан"},
        "plan": _plan(truth),
        "done": recent_releases(model, updated),
        "my_records": my_records(model, updated),
    }



def _stopped_tasks(items: list) -> list:
    """Stopped tasks in plain words, read-only from the card (ARB 09.10). Absent ⇒ said so."""
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        reason, nxt = plain(it.get("reason")), plain(it.get("next_step"))
        upd = it.get("last_transition") or it.get("created")
        out.append({"title": plain(it.get("title")) or "Задача без названия",
                    "reason": reason,
                    "reason_text": f"Причина: {reason}" if reason else "Причина не указана в карточке",
                    "next_text": f"Следующий шаг: {nxt}" if nxt else "Следующий шаг не указан в карточке",
                    "updated_ru": (f"обновлено {_madrid(upd)}" if upd and "T" in str(upd) else
                                   (f"заведена {upd}" if upd else "время обновления не записано")),
                    "technical": {"карточка": it.get("card"), "blocked_by": it.get("reason"),
                                  "последний переход статуса": it.get("last_transition")}})
    return out

def _plan(truth: dict) -> dict:
    rows = _roadmap_rows(truth)
    groups = [{"key": k, "title": t, "count": sum(1 for r in rows if r["group"] == k)} for k, t in PLAN_GROUPS]
    return {"title": "План работ", "rows": rows,
            "groups": [g for g in groups if g["count"] or g["key"] in ("done", "active", "queued")],
            "note": "Процент выполнения не показывается: у плана нет измеримого знаменателя. Названия этапов "
                    "переведены по словарю; исходные — в подробностях."}


def money(model: dict, updated: Optional[str]) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    rd = _get(truth, "capital.readiness")
    rconf, rreason = _cell_confidence(rd)
    if rconf == MEASURED and isinstance(rd, dict):
        v = rd.get("value") if isinstance(rd.get("value"), dict) else {}
        st, n = v.get("status"), v.get("go_live_conditions_open")
        if st == "NOT_READY":
            txt = "Настоящие деньги не разрешены" + (f": открыто условий — {n}" if isinstance(n, int) else "")
            ready = metric("До настоящих денег", txt, confidence=MEASURED, source=rd.get("canon"),
                           measured_at=rd.get("as_of"), updated_at=updated, tone="neutral", technical={"status": st})
        elif st == "READY":
            ready = metric("До настоящих денег", "Все условия выполнены; нужно решение владельца",
                           confidence=MEASURED, source=rd.get("canon"), measured_at=rd.get("as_of"),
                           updated_at=updated, technical={"status": st})
        else:
            ready = metric("До настоящих денег", None, confidence=INTERPRETATION_PROBLEM, source=rd.get("canon"),
                           measured_at=rd.get("as_of"), updated_at=updated, reason=f"не удалось понять статус «{st}»")
    else:
        ready = metric("До настоящих денег", None, confidence=rconf, source=_get(rd, "canon"),
                       measured_at=_get(rd, "as_of"), updated_at=updated, reason=rreason)
    research = []
    for key, label in (("trading_lab", "Лаборатория торговых стратегий"), ("oracle", "Советник по инвестициям")):
        cell = _get(truth, f"capital.{key}")
        conf, reason = _cell_confidence(cell)
        txt = None
        if key == "oracle" and conf == MEASURED:
            stance = _get(cell, "value.stance")
            txt = {"INSUFFICIENT_EVIDENCE": "доказательств недостаточно — рекомендации нет",
                   "RECOMMEND": "есть рекомендация (бумага)"}.get(stance)
            if txt is None:
                conf, reason = INTERPRETATION_PROBLEM, f"не удалось понять позицию «{stance}»"
        if key == "trading_lab" and conf == MEASURED:
            n = _get(cell, "value.strategies_researched.value")
            txt = f"исследовано стратегий: {n} — это модели, не деньги" if isinstance(n, int) else None
            if txt is None:
                conf, reason = NOT_MEASURED, "число стратегий не передано"
        research.append(metric(label, txt, confidence=conf, source=_get(cell, "canon"),
                               measured_at=_get(cell, "as_of"), updated_at=updated, reason=reason))
    head = _money_mode(model)
    if isinstance(ready.get("text"), str):
        # the readiness count belongs to the same explanation — said once, inside the mode details
        head["mode_detail"] = head["mode_detail"] + " До настоящих денег: " + ready["text"].split(": ", 1)[-1] + "."
    return {
        "title": "Деньги",
        "head": head,
        "summary": {"title": "Сводка по пакетам (модель)", "packages": package_tiles(model, updated, with_costs=True),
                    "total": totals_tile(model, updated), "trading": trading_tile(model, updated)},
        "real": real_money(model, updated),
        "paper": paper_portfolio(truth, updated),
        "research": {"title": "Исследования и бэктест", "note": "Модели и расчёты на истории — не деньги и не трек.",
                     "items": research},
        "readiness": ready,
    }


# ── Решения (задача D, ADR-762 §4) ─────────────────────────────────────────────────────────────
# The version of a card is a fingerprint of EXACTLY the fields the canon hands to the Director OS.
# The canon shortens long texts («…»), so an edit in the invisible tail does not move the
# fingerprint — that limit is named on every card (``version.partial``), never hidden.
VERSION_FIELDS = ("id", "title_ru", "reason_ru", "action_ru", "done_when_ru", "subject_key", "status")
# ARB 09.10: the cockpit does NOT bind an answer to a version. The same sentence stands next to EVERY
# way to answer the cockpit offers (the new card and the previous view), so no path promises more.
HONEST_ANSWER_NOTE = ("Ответ даётся в Телеграме. Пульт не проверяет ответ в Телеграме; защищённого "
                      "подтверждения точной версии сейчас нет. Открытие карточки — не одобрение.")
_REQUIRED = (("title_ru", "название"), ("reason_ru", "зачем это нужно"), ("action_ru", "что предлагается"),
             ("done_when_ru", "как понять, что готово"))
_OPTION = re.compile(r"(?:^|\s)(\d)\.\s+(.+?)(?=\s\d\.\s|$)", re.S)
_OPTION_LETTER = re.compile(r"Вариант ([A-ZА-Я])\b[^.:]*?[.:]?\s+(.+?)(?=\s-?\s*Вариант [A-ZА-Я]\b|$)", re.S)
_ANSWER_WORD = {"ack": "да", "nack": "нет"}
GROUP_EXPLAIN = {
    # ARB 27.10: «тема не объявлена» — это НЕИЗВЕСТНО, а не «темы владельца нет». Среди таких карточек бывают
    # риск, публикация и лицензия; обещать, что ответ не нужен, нельзя (UNKNOWN ≠ NONE).
    "undeclared": ("Тема не определена — на разборе", "У этих вопросов не объявлена тема: неизвестно, касаются ли они "
                   "денег, публичных чисел или необратимых действий. Это не значит, что ваш ответ не нужен. Система "
                   "обязана разобрать каждый: закрыть сам с объяснением или поднять к вам с объявленной темой."),
    "accepted": ("Приняты вами, выполняются", "Вы уже приняли решение; агент выполняет. Отвечать не нужно."),
    "prod_only": ("Только на рабочем Mac", "Карточки есть на Mac, но ещё не доставлены в общий журнал. "
                  "Это технический хвост доставки, не вопрос к вам."),
}


def _full_sections(card: dict) -> list:
    fs = card.get("full_sections_ru")
    if not isinstance(fs, list):
        return []
    return [{"heading": str(x.get("heading") or ""), "text": str(x.get("text") or "")}
            for x in fs if isinstance(x, dict)]


def _section_text(full: list, prefix: str) -> Optional[str]:
    for x in full:
        if x["heading"].startswith(prefix):
            return x["text"]
    return None


_SENTENCE_END = re.compile(r"(?<=[^\d][.!?…])\s+(?=[«\"A-ZА-ЯЁ0-9])")


def first_sentence(text: Optional[str]) -> Optional[str]:
    """The first WHOLE sentence (or first line) of a canonical text — never cut mid-sentence."""
    if not isinstance(text, str) or not text.strip():
        return None
    # the canonical cards are hard-wrapped: the first PARAGRAPH (lines joined) is the unit, then its
    # first sentence; markdown emphasis/code markers are presentation, not content — dropped here only
    para = re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]
    lines = [ln.strip() for ln in para.split("\n")]
    if lines and re.match(r"^(\d+\.|[-*•])\s", lines[0]):
        lines = lines[:1]                       # a list starts the section: its first item is the unit
    line = re.sub(r"\*\*|`", "", " ".join(x for x in lines if x))
    parts = _SENTENCE_END.split(line, maxsplit=1)
    out = plain(parts[0].strip()) if parts else plain(line)
    # a path already inside parentheses becomes «((файл …))» after plain(); one pair is enough
    return re.sub(r"\(\(([^()]*)\)\)", r"(\1)", out) if isinstance(out, str) else out


def card_version(card: dict) -> dict:
    """Deterministic content fingerprint of a decision card. With the full canonical text available
    (``full_sections_ru``) the fingerprint covers the WHOLE text the cockpit shows; still not a
    decision version — the answer in Telegram is not bound to it (ADR-762 boundary)."""
    full = _full_sections(card)
    if full:
        payload = {"id": card.get("id"), "title_ru": card.get("title_ru"), "subject_key": card.get("subject_key"),
                   "sections": full}
        fp = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return {"measured": True, "fingerprint": fp, "short": fp[:8], "partial": False,
                "text": (f"Отпечаток полного текста карточки в пульте: {fp[:8]}. Ответ в Телеграме к этому "
                         "отпечатку не привязан: версий решений механизм ответа сейчас не ведёт."),
                "fields": ["id", "title_ru", "subject_key", "full_sections_ru"], "is_decision_version": False}
    fields = {k: card.get(k) for k in VERSION_FIELDS}
    if not any(fields.get(k) for k in ("title_ru", "reason_ru", "action_ru")):
        return {"measured": False, "fingerprint": None, "short": None, "is_decision_version": False,
                "text": "Отпечаток не посчитан — в карточке нет текста, по которому его посчитать"}
    fp = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    partial = any(isinstance(v, str) and v.rstrip().endswith("…") for v in fields.values())
    txt = (f"Отпечаток видимого в пульте текста: {fp[:8]}. Это не версия полного решения"
           + (" — пульт видит сокращённый текст, полный — в Телеграме." if partial else
              " — считается только по полям, которые передаются пульту."))
    return {"measured": True, "fingerprint": fp, "short": fp[:8], "partial": partial, "text": txt,
            "fields": list(VERSION_FIELDS), "is_decision_version": False}


def _options(action: Optional[str]) -> list:
    if not isinstance(action, str):
        return []
    found = [{"n": n, "text": plain(t.strip())} for n, t in _OPTION.findall(action)]
    if len(found) < 2:
        found = [{"n": n, "text": plain(t.strip(" -"))} for n, t in _OPTION_LETTER.findall(action)]
    return found if len(found) >= 2 else []


def _decision_card(d: dict, answered: dict, updated: Optional[str]) -> dict:
    sk = d.get("subject_key")
    missing = [name for key, name in _REQUIRED if not (isinstance(d.get(key), str) and d.get(key).strip())]
    if sk not in SUBJECT_RU:
        missing.append("тема владельца")
    link = d.get("telegram_link") if isinstance(d.get("telegram_link"), str) and \
        d.get("telegram_link").startswith("https://t.me/") else None
    ver = card_version(d)
    full = _full_sections(d)
    opts = _options(_section_text(full, "Что от тебя нужно") or d.get("action_ru"))
    done = answered.get(d.get("id"))
    if done:
        answer = {"kind": "ANSWERED", "link": None,
                  "text": "Ответ уже записан" + (f" {_madrid(done.get('answered_at'))}" if done.get("answered_at") else ""),
                  "reason": "Повторно отвечать не нужно. На какой текст карточки дан ответ, механизм ответа "
                            "не записывает — сверить это пульт не может."}
    elif missing or not link:
        why = []
        if missing:
            why.append("в карточке не хватает: " + ", ".join(missing))
        if not link:
            why.append("нет ссылки на действующий механизм ответа (Телеграм)")
        answer = {"kind": "BLOCKED_UNPREPARED", "link": None, "text": "Не готово к ответу",
                  "reason": "; ".join(why) + ". Агент обязан дополнить карточку."}
    else:
        answer = {"kind": "READY", "link": link, "text": "Ответить в Телеграме",
                  "reason": HONEST_ANSWER_NOTE}
    nm = "не указано в карточке"
    cut = "в сокращённом тексте пульта не видно — полный текст в Телеграме"
    if not opts and ver.get("partial"):
        alt, cons = cut, cut
    else:
        alt, cons = (None, "описаны в вариантах ответа") if opts else (nm, nm)
    why_full = _section_text(full, "Что случилось")
    need_full = _section_text(full, "Что от тебя нужно")
    return {
        "id": d.get("id"), "title": plain(d.get("title_ru")) or "Без названия",
        # short list text: whole first sentences, never a mid-sentence cut (ARB 09.10)
        "short_why": first_sentence(why_full) or first_sentence(d.get("reason_ru")) or nm,
        "short_next": first_sentence(need_full) or first_sentence(d.get("action_ru")) or nm,
        # the WHOLE canonical card, section by section, read-only (shown on expansion)
        "full": full,
        # owner 13.10: the WHOLE text in plain words first (codes, files, document numbers translated or
        # moved — ``plain()``); the verbatim ``full`` stays one tap away, unchanged (ARB 09.10)
        "full_plain": [{"heading": plain(x["heading"]) or "", "text": plain(x["text"]) or ""} for x in full],
        "full_available": bool(full),
        "subject": SUBJECT_RU.get(sk, "Тема не объявлена" if sk is None else "Тема не распознана — проблема отображения"),
        "subject_known": sk in SUBJECT_RU, "age_days": d.get("age_days"),
        "proposal": plain(d.get("action_ru")) or nm,
        "why": plain(d.get("reason_ru")) or nm,
        "options": opts,
        "alternatives": alt,
        "consequences": cons,
        "checked": plain(d.get("done_when_ru")) or nm,
        "blocking": answer["reason"] if answer["kind"] == "BLOCKED_UNPREPARED" else "ничего не мешает ответу",
        "scope": plain(d.get("action_ru")) or nm,
        "limitations": ("Текст карточки в пульте сокращён — полный текст в Телеграме" if ver.get("partial")
                        else ("полный текст карточки — ниже, по нажатию" if full else nm)),
        "rollback": nm,
        "version": ver, "answer": answer,
        "summary": metric("Вопрос владельцу", plain(d.get("title_ru")) or "Без названия", confidence=MEASURED,
                          source="nimbalyst-local/tracker (очередь владельца)", measured_at=None, updated_at=updated,
                          unit=None, technical={"id": d.get("id"), "status": d.get("status"), "subject": sk,
                                                "version_fields": list(VERSION_FIELDS),
                                                "fingerprint": ver.get("fingerprint")}),
    }


def decisions(model: dict, updated: Optional[str]) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    dec = _get(truth, "decisions") or {}
    groups = dec.get("groups") if isinstance(dec, dict) else None
    src = "nimbalyst-local/tracker (очередь владельца, origin)"
    # once per screen (ARB 09.10); the same honest sentence stands again only next to the answer button
    note = ("Открытие карточки — не одобрение. Ответ даётся только в Телеграме. Пульт не проверяет ответ в "
            "Телеграме; защищённого подтверждения точной версии сейчас нет.")
    if not isinstance(groups, dict):
        return {"title": "Решения", "note": note, "owner": [], "groups": [], "history": [],
                "summary": metric("Вопросы владельцу", None, confidence=NOT_MEASURED, source=src, measured_at=None,
                                  updated_at=updated, reason=plain(dec.get("unknown_ru")) or "очередь не прочитана")}
    answered_rows = [a for a in (groups.get("answered") or []) if isinstance(a, dict)]
    answered = {a.get("id"): a for a in answered_rows}
    items = [d for d in (groups.get("owner") or []) if isinstance(d, dict)]

    def order(d):
        sk = d.get("subject_key")
        rank = SUBJECT_ORDER.index(sk) if sk in SUBJECT_ORDER else len(SUBJECT_ORDER)
        age = d.get("age_days") if isinstance(d.get("age_days"), (int, float)) else -1
        return (rank, -age, str(d.get("id")))

    owner = [_decision_card(d, answered, updated) for d in sorted(items, key=order)]
    other = []
    for key, (title, explain) in GROUP_EXPLAIN.items():
        rows = [g for g in (groups.get(key) or []) if isinstance(g, dict)]
        other.append({"key": key, "title": title, "explain": explain, "count": len(rows),
                      "items": [{"title": plain(r.get("title_ru")) or "Без названия",
                                 "technical": {"id": r.get("id")}} for r in rows]})
    history = [{"title": plain(a.get("title_ru")) or "Без названия",
                "answer": ("Ответ: вариант " + a["owner_answer_ru"]) if str(a.get("owner_answer_ru") or "").isdigit()
                else ("Ответ: " + (_ANSWER_WORD.get(str(a.get("owner_answer_ru")).strip().lower())
                                   or plain(a.get("owner_answer_ru")) or "не записан")),
                "at_ru": _madrid(a.get("answered_at")) or "время не записано",
                "version": "на какой текст дан ответ — не записано",
                "technical": {"id": a.get("id")}} for a in sorted(answered_rows, key=lambda a: str(a.get("answered_at") or ""),
                                                                    reverse=True)]
    n = len(owner)
    u = len([g for g in (groups.get("undeclared") or []) if isinstance(g, dict)])
    head = "Вопросов к вам нет" if n == 0 else f"Ждут вашего ответа: {n}"
    if u:
        head += f"; ещё {u} без объявленной темы — на разборе, не закрыты"
    return {"title": "Решения", "note": note, "owner": owner, "groups": other, "history": history,
            "summary": metric("Вопросы владельцу", head,
                              confidence=MEASURED, source=src, measured_at=None, updated_at=updated, unit="шт.")}


# ── Защита (задача D) ──────────────────────────────────────────────────────────────────────────
# Known background jobs in owner words; an unknown name is NOT guessed (it stays in technical details).
JOB_RU = {
    "resource_guard": "сторож ресурсов Mac", "site_freshness": "проверка свежести сайта",
    "swarm_health": "проверка исследовательского роя", "monthly_statement": "ежемесячный отчёт",
    "weekly_backup": "недельная резервная копия", "digest_weekly": "недельная сводка",
    "tier1_digest": "сводка по портфелю", "daily_backup": "ежедневная резервная копия",
}
PROBLEM_RU = {
    "retired_but_loaded": ("Отключённые фоновые задачи всё ещё запущены",
                           "Остановить их на Mac — это действие владельца; команда в подробностях"),
    "domains_degraded": ("Проверка здоровья предупреждает в нескольких областях",
                         "Ничего нажимать не нужно: ассистент разбирает предупреждения в работе"),
    "MISSING_ASOF": ("У числа на сайте нет даты замера", "Исправление сайта идёт отдельной задачей"),
    "COMPARISON_NOT_MEASURED": ("Сайт не удалось сверить с живыми данными",
                                "Не измерено — не значит «расходится»; сверка будет повторена"),
}
_SNAPSHOT_STALE_MIN = 30

# Severity is a deterministic reading of WHAT broke, not of how loud it is (owner 13.10: «насколько они
# критичны, чем грозят»). critical — protection of data/track is at stake; important — a working part keeps
# failing; info — housekeeping. Unknown codes are «important» (fail-closed: never downplayed).
SEVERITY_RU = {"critical": "Критично", "important": "Важно", "info": "К сведению"}
SEVERITY_ORDER = ("critical", "important", "info")
_BACKUP_JOBS = ("daily_backup",)


def _severity(code: str, agent: Any, occ: Any) -> tuple:
    short = str(agent or "").split("com.spa.")[-1]
    if short in _BACKUP_JOBS and (code.startswith("exit_nonzero") or code.startswith("log_missing")):
        return "critical", "Может не быть свежей резервной копии — при сбое Mac можно потерять последние данные"
    if code == "retired_but_loaded":
        return "info", "Лишние фоновые задачи тратят ресурсы и шумят в проверках; данным не грозит"
    if code in ("MISSING_ASOF", "COMPARISON_NOT_MEASURED"):
        return "important", "Посетитель сайта может видеть число без даты или не сверенное с живыми данными"
    if code == "domains_degraded":
        return "important", "Часть проверок работает с ограничениями — проблема может быть замечена позже"
    if code.startswith("log_missing"):
        return "info", "Задача ещё ни разу не выполнялась — её результата пока нет"
    if code.startswith("exit_nonzero"):
        return "important", ("Задача регулярно не выполняет свою работу — то, что она проверяет или "
                             "готовит, может устаревать")
    return "important", "Не распознано — последствия неизвестны; лучше спросить ассистента"


def _job_name(agent: Any) -> Optional[str]:
    if not isinstance(agent, str):
        return None
    short = agent.split("com.spa.")[-1]
    return JOB_RU.get(short)


def _problem_row(it: dict) -> dict:
    code = str(it.get("cause_code") or "")
    occ = it.get("occurrences")
    if code in PROBLEM_RU:
        what, action = PROBLEM_RU[code]
    elif code.startswith("exit_nonzero"):
        job = _job_name(it.get("agent_ru"))
        what = (f"Задача «{job}» регулярно завершается с ошибкой" if job
                else "Фоновая задача регулярно завершается с ошибкой (какая — в подробностях)")
        action = "Ваших действий не требуется; если держится больше суток — спросите ассистента"
    elif code.startswith("log_missing"):
        job = _job_name(it.get("agent_ru"))
        what = (f"Задача «{job}» ни разу не запускалась" if job
                else "Фоновая задача ни разу не запускалась (какая — в подробностях)")
        action = "Ваших действий не требуется; задача заведена ассистенту"
    else:
        what = "Проблема не распознана — проблема отображения (код в подробностях)"
        action = "Спросите ассистента, что это значит"
    sev, threat = _severity(code, it.get("agent_ru"), occ)
    return {"what": what, "action": action, "repeats": occ if isinstance(occ, int) else None,
            "severity": sev, "severity_ru": SEVERITY_RU[sev], "threat": threat,
            "status_ru": "открыта" + (f" · повторялась {occ} раз" if isinstance(occ, int) and occ > 1 else ""),
            "technical": {"agent": it.get("agent_ru"), "cause": it.get("cause_ru"), "code": code,
                          "commands": ("launchctl bootout gui/$(id -u)/<метка> — выгрузить задачу"
                                       if code == "retired_but_loaded" else None)}}


def _age_minutes(ts: Any, now: datetime) -> Optional[float]:
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 60.0


def protection(model: dict, updated: Optional[str], now: datetime) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    checks = []
    # 1 — the snapshot itself: is what the owner reads fresh?
    age = _age_minutes(updated, now)
    if age is None:
        checks.append(metric("Свежесть данных пульта", None, confidence=NOT_MEASURED, source="mission.json generated_at",
                             measured_at=None, updated_at=updated, unit="мин", reason="время сборки снимка не записано"))
    elif age > _SNAPSHOT_STALE_MIN:
        checks.append(metric("Свежесть данных пульта", "Данные собраны давно", confidence=STALE,
                             source="mission.json generated_at", measured_at=updated, updated_at=updated, unit="мин",
                             technical={"age_min": round(age, 1), "stale_after_min": _SNAPSHOT_STALE_MIN}))
    else:
        checks.append(metric("Свежесть данных пульта", f"Данные свежие: собраны {_madrid(updated)}",
                             confidence=MEASURED, source="mission.json generated_at", measured_at=updated,
                             updated_at=updated, unit="мин", technical={"age_min": round(age, 1)}))
    # 2 — the system as a whole
    sysv = _get(model, "overview.system") or {}
    st = sysv.get("state")
    if st == "HEALTHY":
        checks.append(metric("Система в целом", "Работает", confidence=MEASURED, source="overview.system",
                             measured_at=None, updated_at=updated, technical={"state": st}))
    elif st in ("DEGRADED", "CRITICAL"):
        reasons = {"resources": "мало ресурсов на Mac", "agents": "часть фоновых задач с предупреждениями",
                   "guard": "сторож данных устарел", "packages": "сбой бумажного портфеля"}
        parts = [v for k, v in reasons.items() if isinstance(sysv.get("reason"), str) and k in sysv["reason"]]
        txt = ("Работает с ограничениями" if st == "DEGRADED" else "Авария") + (": " + ", ".join(parts) if parts else "")
        checks.append(metric("Система в целом", txt, confidence=MEASURED, source="overview.system", measured_at=None,
                             updated_at=updated, tone="warn" if st == "DEGRADED" else "problem",
                             technical={"state": st, "reason": sysv.get("reason"), "alerts": sysv.get("alerts")}))
    else:
        checks.append(metric("Система в целом", None, confidence=INTERPRETATION_PROBLEM if st else NOT_MEASURED,
                             source="overview.system", measured_at=None, updated_at=updated,
                             reason=f"не удалось понять статус «{st}»" if st else "состояние системы не передано"))
    # 3 — background jobs
    fl = _get(truth, "studio.fleet")
    conf, reason = _cell_confidence(fl)
    if conf == MEASURED and isinstance(fl, dict):
        v = fl.get("value") if isinstance(fl.get("value"), dict) else {}
        ok, dec_n, crit, warn = v.get("ok"), v.get("declared"), v.get("critical"), v.get("warning")
        if all(isinstance(x, int) for x in (ok, dec_n)):
            full = ok == dec_n and not crit
            txt = f"В норме {ok} из {dec_n}" + (f"; с предупреждением: {warn}" if warn else "") + \
                  (f"; авария: {crit}" if crit else "")
            checks.append(metric("Фоновые задачи", txt, confidence=MEASURED if full else PARTIAL,
                                 source=fl.get("canon"), measured_at=fl.get("as_of"), updated_at=updated, unit="шт.",
                                 tone="ok" if full else ("problem" if crit else "warn"),
                                 technical={"failing": fl.get("failing"), "display": fl.get("display_ru")}))
        else:
            checks.append(metric("Фоновые задачи", None, confidence=NOT_MEASURED, source=fl.get("canon"),
                                 measured_at=fl.get("as_of"), updated_at=updated, reason="счётчики не переданы"))
    else:
        checks.append(metric("Фоновые задачи", None, confidence=conf, source=_get(fl, "canon"),
                             measured_at=_get(fl, "as_of"), updated_at=updated, reason=reason))
    # 4 — the Mac
    mc = _get(truth, "studio.machine")
    conf, reason = _cell_confidence(mc)
    disk = _get(mc, "value.disk_free_gb")
    if conf in (MEASURED, STALE) and isinstance(disk, (int, float)):
        checks.append(metric("Место на диске Mac", f"Свободно {int(disk)} ГБ", confidence=conf, source=_get(mc, "canon"),
                             measured_at=_get(mc, "as_of"), updated_at=updated, unit="ГБ"))
    else:
        checks.append(metric("Место на диске Mac", None, confidence=conf if conf != MEASURED else NOT_MEASURED,
                             source=_get(mc, "canon"), measured_at=_get(mc, "as_of"), updated_at=updated, unit="ГБ",
                             reason=reason or "место на диске не передано"))
    # 5 — the public site check
    wh = _get(truth, "product.website_health")
    conf, reason = _cell_confidence(wh)
    status = _get(wh, "value.status")
    if conf == MEASURED and status == "OK":
        checks.append(metric("Проверка сайта", "Прошла", confidence=MEASURED, source=_get(wh, "canon"),
                             measured_at=_get(wh, "as_of"), updated_at=updated))
    elif conf == MEASURED and status in ("WARN", "FAIL"):
        codes = [c for c in PROBLEM_RU if c.isupper() and c in str(_get(wh, "display_ru") or "")]
        txt = "Проверка не прошла" + (": " + "; ".join(PROBLEM_RU[c][0].lower() for c in codes) if codes else "")
        checks.append(metric("Проверка сайта", txt, confidence=MEASURED, source=_get(wh, "canon"),
                             measured_at=_get(wh, "as_of"), updated_at=updated,
                             tone="warn" if status == "WARN" else "problem",
                             technical={"status": status, "display": _get(wh, "display_ru")}))
    else:
        checks.append(metric("Проверка сайта", None,
                             confidence=INTERPRETATION_PROBLEM if conf == MEASURED else conf,
                             source=_get(wh, "canon"), measured_at=_get(wh, "as_of"), updated_at=updated,
                             reason=(f"не удалось понять статус «{status}»" if conf == MEASURED else reason)))
    # verdict — partial is NEVER «в порядке»
    good = [c for c in checks if c["confidence"] == MEASURED and c["tone"] in ("ok", "neutral")]
    if len(good) == len(checks):
        verdict = metric("Итог", f"Всё в порядке: проверено {len(checks)} из {len(checks)}", confidence=MEASURED,
                         source="раздел «Защита»", measured_at=None, updated_at=updated, tone="ok")
    else:
        verdict = metric("Итог", None, confidence=PARTIAL, source="раздел «Защита»", measured_at=None,
                         updated_at=updated)
        # the badge already says «Проверено частично»; the text names the count instead of repeating it
        verdict["text"] = f"Есть замечания: без замечаний {len(good)} из {len(checks)} проверок"
    # open problems + what to do
    pr = _get(truth, "studio.problems")
    pconf, preason = _cell_confidence(pr)
    if pconf == MEASURED and isinstance(pr, dict):
        rows = [_problem_row(i) for i in (pr.get("items") or []) if isinstance(i, dict)]
        rows.sort(key=lambda r: (SEVERITY_ORDER.index(r["severity"]), -(r["repeats"] or 0)))
        counts = {k: sum(1 for r in rows if r["severity"] == k) for k in SEVERITY_ORDER}
        problems = {"title": "Открытые проблемы", "rows": rows, "counts": counts,
                    "counts_ru": " · ".join(f"{SEVERITY_RU[k].lower()}: {counts[k]}" for k in SEVERITY_ORDER if counts[k]),
                    "actions_note": "Сейчас доступно только «Посмотреть детали». Кнопки «Проверить» и «Исправить» "
                                    "появятся после вашего решения: пульт пока ничего не меняет в системе.",
                    "summary": metric("Открытые проблемы", f"Открыто: {len(rows)}" if rows else "Открытых проблем нет",
                                      confidence=MEASURED, source=pr.get("canon"), measured_at=pr.get("as_of"),
                                      updated_at=updated, unit="шт.", tone="warn" if rows else "ok")}
    else:
        problems = {"title": "Открытые проблемы", "rows": [],
                    "summary": metric("Открытые проблемы", None, confidence=pconf, source=_get(pr, "canon"),
                                      measured_at=_get(pr, "as_of"), updated_at=updated, reason=preason)}
    cnt = problems.get("counts") or {}
    level = ("Уровень защиты: под угрозой — есть критичные проблемы" if cnt.get("critical") else
             "Уровень защиты: есть замечания" if (cnt.get("important") or verdict["confidence"] != MEASURED) else
             "Уровень защиты: в порядке")
    return {"title": "Защита", "level": level, "verdict": verdict, "checks": checks, "check_groups": check_groups(checks),
            "problems": problems, "backups": backups(truth, updated)}


# Three owner groups (ARB 09.10): «проверено» only for a measured check with nothing to fix; any
# warning/problem — «проблема»; everything else (not measured, stale, partial without a problem
# tone, unreadable) — «не проверено». No check is left out and none is counted twice.
def check_groups(checks: list) -> list:
    def grp(c):
        if c["tone"] in ("warn", "problem"):
            return "problem"
        if c["confidence"] == MEASURED and c["tone"] in ("ok", "neutral"):
            return "verified"
        return "unverified"
    out = []
    for key, title in (("verified", "Проверено, замечаний нет"), ("unverified", "Не проверено"),
                       ("problem", "Есть проблема")):
        items = [c["label"] for c in checks if grp(c) == key]
        out.append({"key": key, "title": title, "count": len(items), "items": items})
    return out


def backups(truth: dict, updated: Optional[str]) -> dict:
    b = _get(truth, "studio.backups") or {}
    out = {}
    loc = b.get("local") if isinstance(b, dict) else None
    conf, reason = _cell_confidence(loc)
    if conf in (MEASURED, STALE) and isinstance(loc, dict):
        out["local"] = metric("Резервная копия на Mac", f"Последняя копия: {_madrid(loc.get('as_of')) or 'время не записано'}",
                              confidence=conf, source=loc.get("canon"), measured_at=loc.get("as_of"), updated_at=updated)
    else:
        out["local"] = metric("Резервная копия на Mac", None, confidence=conf, source=_get(loc, "canon"),
                              measured_at=_get(loc, "as_of"), updated_at=updated, reason=reason)
    off = b.get("off_host") if isinstance(b, dict) else None
    conf, reason = _cell_confidence(off)
    if conf in (MEASURED, STALE) and isinstance(off, dict) and off.get("value") is True:
        remote = off.get("remote_upload")
        if remote == "NOT_MEASURED" or remote is None:
            out["off_host"] = metric("Копия вне Mac", "Копия лежит в папке iCloud и сверена; дошла ли она до серверов "
                                     "iCloud — не измерено", confidence=PARTIAL, source=off.get("canon"),
                                     measured_at=off.get("as_of"), updated_at=updated,
                                     technical={"remote_upload": remote})
        else:
            out["off_host"] = metric("Копия вне Mac", "Копия в iCloud сверена", confidence=conf, source=off.get("canon"),
                                     measured_at=off.get("as_of"), updated_at=updated, technical={"remote_upload": remote})
    elif conf == MEASURED and isinstance(off, dict):
        out["off_host"] = metric("Копия вне Mac", "Копии вне Mac нет", confidence=MEASURED, source=off.get("canon"),
                                 measured_at=off.get("as_of"), updated_at=updated, tone="problem")
    else:
        out["off_host"] = metric("Копия вне Mac", None, confidence=conf, source=_get(off, "canon"),
                                 measured_at=_get(off, "as_of"), updated_at=updated, reason=reason)
    rec = b.get("recovery") if isinstance(b, dict) else None
    conf, reason = _cell_confidence(rec)
    res = _get(rec, "drill_result")
    when = _get(rec, "date") or _get(rec, "as_of")
    words = {"OK": "прошло", "FAILED": "не прошло", "STALE": "давно не проводилось", "NEVER_RUN": "ни разу не проводилось"}
    if conf in (MEASURED, STALE) and res in words:
        out["recovery"] = metric("Проверка восстановления", f"Учебное восстановление {words[res]}"
                                 + (f": {_madrid(when)}" if when and res != "NEVER_RUN" else ""),
                                 confidence=conf, source=_get(rec, "canon"), measured_at=when, updated_at=updated,
                                 tone="ok" if res == "OK" else "problem", technical={"drill_result": res})
    elif conf in (MEASURED, STALE):
        out["recovery"] = metric("Проверка восстановления", None, confidence=INTERPRETATION_PROBLEM,
                                 source=_get(rec, "canon"), measured_at=when, updated_at=updated,
                                 reason=f"не удалось понять результат «{res}»")
    else:
        out["recovery"] = metric("Проверка восстановления", None, confidence=conf, source=_get(rec, "canon"),
                                 measured_at=when, updated_at=updated, reason=reason)
    return out


# ── DIRECTOR-OS-UX-04: the owner's mockup («SPA Director OS», ChatGPT, 30.08) as the spec ──────────────
# Every block of the mockup is either filled from the canon OR shown honestly as «в разработке» with
# the reason — never hidden and never a demo number (owner 15.10: «что ещё не готово или нет данных —
# пометить как в разработке»). This registry is the ONE list the UI renders and the roadmap list is
# generated from; adding a block to the screen without a row here is caught by a test.
REASON_NO_DATA = "нет данных"
REASON_NOT_DECIDED = "не решено"
REASON_NOT_BUILT = "не сделано"

IN_DEVELOPMENT = [
    {"key": "week_balance", "title": "Баланс недели (продукт / надёжность / исследования)", "where": "Обзор",
     "reason_kind": REASON_NO_DATA,
     "reason": "задачи не размечены по направлениям, поэтому доли недели посчитать не из чего",
     "needs": "разметка каждой задачи направлением (продукт / надёжность / исследования) и правило подсчёта",
     "priority": "средний", "nav": False},
    {"key": "claude_load", "title": "Полезная загрузка Claude", "where": "Обзор, Мощность",
     "reason_kind": REASON_NO_DATA,
     "reason": "загрузка подписки Claude и сессий нигде не измеряется",
     "needs": "источник данных об использовании (лимиты, сессии) и определение «полезной» загрузки",
     "priority": "низкий", "nav": False},
    {"key": "capacity", "title": "Мощность и загрузка (вычислительные узлы, слоты)", "where": "раздел «Мощность»",
     "reason_kind": REASON_NOT_BUILT,
     "reason": "раздела нет: загрузка Mac и слоты агентов в модель пульта не передаются",
     "needs": "сборщик загрузки Mac (процессор, память, очередь) и список занятых слотов", "priority": "низкий",
     "nav": True, "nav_title": "Мощность", "nav_group": "Исполнение"},
    {"key": "agents", "title": "Агенты: кто сейчас работает и над чем", "where": "раздел «Агенты»",
     "reason_kind": REASON_NOT_BUILT,
     "reason": "в пульт передаются только счётчики фоновых задач, а не живые слоты агентов",
     "needs": "живой список агентов с текущей задачей и временем работы", "priority": "средний",
     "nav": True, "nav_title": "Агенты", "nav_group": "Исполнение"},
    {"key": "memory", "title": "Память: поиск по решениям и документам", "where": "раздел «Память»",
     "reason_kind": REASON_NOT_BUILT,
     "reason": "поиск по памяти компании есть только в командной строке, в пульт не выведен",
     "needs": "поиск по памяти (только чтение) в пульте", "priority": "средний",
     "nav": True, "nav_title": "Память", "nav_group": "Знания и система"},
    {"key": "policies", "title": "Политики и правила (переключатели)", "where": "раздел «Политики»",
     "reason_kind": REASON_NOT_DECIDED,
     "reason": "переключатели меняли бы систему, а пульт пока ничего не меняет — нужно решение владельца",
     "needs": "решение владельца, какие правила можно менять из пульта, и ADR", "priority": "низкий",
     "nav": True, "nav_title": "Политики", "nav_group": "Знания и система"},
    {"key": "repos", "title": "Репозитории и каталог компонентов", "where": "разделы «Репозитории», «Каталог»",
     "reason_kind": REASON_NOT_BUILT,
     "reason": "состояние репозиториев и каталог модулей в модель пульта не передаются",
     "needs": "сборщик состояния репозиториев (ветки, что не доставлено) и каталог модулей", "priority": "низкий",
     "nav": True, "nav_title": "Репозитории", "nav_group": "Знания и система"},
    {"key": "fix_actions", "title": "Кнопки «Проверить» и «Исправить» в «Защите»", "where": "Защита",
     "reason_kind": REASON_NOT_DECIDED,
     "reason": "пульт пока ничего не меняет в системе; голосовой ввод — первое и единственное действие",
     "needs": "решение владельца, какие безопасные действия разрешены, ADR и подтверждение каждого",
     "priority": "высокий", "nav": False},
    {"key": "aggregate_annual", "title": "Общий годовой показатель по пакетам", "where": "Обзор, Деньги",
     "reason_kind": REASON_NO_DATA,
     "reason": "Сбалансированный и Агрессивный ещё не набрали 30 дней данных",
     "needs": "30 дней данных по всем пакетам и утверждённая методика объединения", "priority": "средний",
     "nav": False},
    {"key": "infra_plan", "title": "Инфраструктура через 2 шага (второй Mac)", "where": "Обзор",
     "reason_kind": REASON_NOT_DECIDED,
     "reason": "решение о втором Mac не принято, данных о нём нет",
     "needs": "решение владельца о покупке и замеры нагрузки текущего Mac", "priority": "низкий", "nav": False},
]


def in_development(keys: Optional[list] = None) -> list:
    rows = [dict(r) for r in IN_DEVELOPMENT if keys is None or r["key"] in keys]
    for r in rows:
        r["badge"] = "в разработке"
        r["line"] = f"{r['reason_kind'][0].upper()}{r['reason_kind'][1:]}: {r['reason']}"
    return rows


def health_tile(prot: dict, updated: Optional[str]) -> dict:
    """«Здоровье системы» — the mockup tile, from the SAME checks «Защита» shows (no second rule)."""
    checks = prot.get("checks") or []
    if not checks:
        return kpi("Здоровье системы", None, None, confidence=NOT_MEASURED, source="раздел «Защита»",
                   measured_at=None, updated_at=updated, reason="проверки не построены", link_area="protection")
    groups = {g["key"]: g["count"] for g in prot.get("check_groups") or []}
    good, total = groups.get("verified", 0), len(checks)
    cnt = (prot.get("problems") or {}).get("counts") or {}
    parts = ["проверок без замечаний"]
    if cnt:
        parts.append(" · ".join(f"{SEVERITY_RU[k].lower()}: {cnt[k]}" for k in SEVERITY_ORDER if cnt.get(k)))
    state = (("под угрозой", "problem") if cnt.get("critical") else
             ("есть замечания", "warn") if (cnt.get("important") or good < total) else ("в порядке", "ok"))
    return kpi("Здоровье системы", f"{good}/{total}", " · ".join(p for p in parts if p), confidence=MEASURED,
               source="раздел «Защита» (те же проверки)", measured_at=None, updated_at=updated, state=state,
               bar={"value": good, "max": total, "text": f"{good} из {total} проверок без замечаний"},
               link_area="protection", unit="проверок")


def _abbr(text: str) -> str:
    words = [w for w in str(text or "").replace("«", "").replace("»", "").split() if w[:1].isalpha()]
    if not words:
        return "•"
    return (words[0][0] + (words[1][0] if len(words) > 1 else "")).upper()


def happening(model: dict, prot: dict, updated: Optional[str]) -> dict:
    """«Что сейчас происходит» — rows of the mockup, each from the canon; nothing invented."""
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    rows = []
    ep = _current_epic(model, truth)
    if ep:
        st = stage_title(ep.get("epic"))
        rows.append({"abbr": "ЭТ", "tone": "violet", "title": st.get("text") or "Текущий этап плана",
                     "sub": "текущий этап плана", "pill": {"text": "идёт", "tone": "ok"}, "meta": None,
                     "link_area": "work"})
    cw = _get(truth, "studio.claude_work")
    cconf, _r = _cell_confidence(cw)
    if cconf == MEASURED and isinstance(cw, dict):
        active = [a for a in (cw.get("active") or []) if isinstance(a, dict)]
        for a in active[:3]:
            title = plain(a.get("card_title_ru") or a.get("epic") or a.get("card")) or "задача без названия"
            rows.append({"abbr": "АС", "tone": "violet", "title": title, "sub": "работает ассистент",
                         "pill": {"text": "в работе", "tone": "ok"}, "meta": None, "link_area": "work"})
        if not active:
            rows.append({"abbr": "АС", "tone": "muted", "title": "Ассистент сейчас не работает",
                         "sub": plain(cw.get("next_step_ru")) or "следующий шаг в журнале не записан",
                         "pill": {"text": "свободен", "tone": "info"}, "meta": None, "link_area": "work"})
    for m in package_tiles(model, updated):
        pill = m.get("state_pill") or {"text": m.get("confidence_ru") or "не измерено", "tone": "unknown"}
        rows.append({"abbr": {"Консервативный": "КС", "Сбалансированный": "СБ", "Агрессивный": "АГ"}.get(m["label"], _abbr(m["label"])), "tone": "green" if pill.get("tone") == "ok" else "teal",
                     "title": f"Пакет «{m['label']}»", "sub": m.get("text") or "не измерено",
                     "pill": pill, "meta": m.get("big") if m.get("big") not in (None, "—") else None,
                     "link_area": "money"})
    tr = trading_tile(model, updated)
    rows.append({"abbr": "ТР", "tone": "teal", "title": "Трейдинг: исследование стратегий",
                 "sub": tr.get("text") or "не измерено",
                 "pill": tr.get("state_pill") or {"text": "не измерено", "tone": "unknown"},
                 "meta": (tr.get("bar") or {}).get("text"), "link_area": "money"})
    tasks = _get(truth, "studio.tasks") or {}
    for it in _stopped_tasks((tasks.get("blocked_items") or []) if isinstance(tasks, dict) else [])[:3]:
        rows.append({"abbr": "СТ", "tone": "amber", "title": it["title"], "sub": it["reason_text"],
                     "pill": {"text": "остановлена", "tone": "warn"}, "meta": it["updated_ru"], "link_area": "work"})
    return {"title": "Что сейчас происходит", "sub": "работа, пакеты и исследования — по живым данным",
            "rows": rows}


def _short(text: Optional[str], limit: int = 140) -> Optional[str]:
    if not text:
        return None
    t = " ".join(str(text).split())
    return t if len(t) <= limit else t[:limit - 1].rsplit(" ", 1)[0] + "…"


def attention(questions: dict, prot: dict) -> dict:
    """«Требует твоего внимания» — owner questions first (number badge = days waiting), then the
    critical/important problems of «Защита»; both read from the same rows those sections show."""
    rows = []
    for q in questions.get("items") or []:
        rows.append({"badge": str(q["age_days"]) if isinstance(q.get("age_days"), (int, float)) else "?",
                     "badge_hint": "дней ждёт", "tone": "amber", "title": q["title"],
                     "sub": _short(first_sentence(q.get("why"))) or q["subject"],
                     "pill": {"text": q["subject"].lower(), "tone": "warn"},
                     "link_area": "decisions"})
    for r in ((prot.get("problems") or {}).get("rows") or []):
        if r["severity"] in ("critical", "important"):
            rows.append({"badge": "!", "badge_hint": r["severity_ru"], "tone": "coral" if r["severity"] == "critical"
                         else "amber", "title": r["what"], "sub": r["threat"],
                         "pill": {"text": r["severity_ru"].lower(), "tone": "problem" if r["severity"] == "critical"
                                  else "warn"}, "link_area": "protection"})
    count = questions.get("count")
    return {"title": "Требует твоего внимания",
            "sub": ("вопросы владельцу и важные проблемы" if rows else "сейчас ничего не требует вашего внимания"),
            "rows": rows[:6], "more": max(0, len(rows) - 6), "questions_count": count}


def nav_counts(questions: dict, prot: dict, model: dict) -> dict:
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    cnt = (prot.get("problems") or {}).get("counts") or {}
    tasks = _get(truth, "studio.tasks") or {}
    bl = tasks.get("blocked") if isinstance(tasks, dict) else None
    return {"decisions": questions.get("count"),
            "protection": (cnt.get("critical", 0) + cnt.get("important", 0)) if cnt else None,
            "work": bl if isinstance(bl, int) else None}


def build(model: dict, now: Optional[datetime] = None) -> dict:
    """The owner view of one mission snapshot. Pure: ``model`` + ``now`` → dict."""
    now = now or datetime.now(timezone.utc)
    model = model if isinstance(model, dict) else {}
    updated = model.get("generated_at")
    prot = protection(model, updated, now)
    ovw = overview(model, updated)
    truth = model.get("truth") if isinstance(model.get("truth"), dict) else {}
    q = ovw.get("questions") or owner_questions(truth, updated)
    ovw["kpis"]["health"] = health_tile(prot, updated)
    ovw["happening"] = happening(model, prot, updated)
    ovw["attention"] = attention(q, prot)
    ovw["in_development"] = in_development(["week_balance", "claude_load", "infra_plan", "aggregate_annual"])
    prot["in_development"] = in_development(["fix_actions"])
    return {
        "schema": SCHEMA,
        "computed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_generated_at": updated,
        "snapshot_generated_at_ru": _madrid(updated),
        "sections": {
            "overview": ovw,
            "work": work(model, updated),
            "money": money(model, updated),
            "decisions": decisions(model, updated),
            "protection": prot,
        },
        "nav_counts": nav_counts(q, prot, model),
        "in_development": in_development(),
        "dictionary": DICTIONARY,
    }


# ── helpers for tests / the acceptance probe ─────────────────────────────────────────────────────
_MAIN_TEXT_KEYS = ("secondary", "secondary_short", "data_date_ru", "short_why", "short_next", "real_line", "mode_line",
                   "text", "label", "title", "main", "next", "note", "summary_text", "subject", "state", "why", "empty",
                   "proposal", "alternatives", "consequences", "checked", "blocking", "scope", "limitations",
                   "rollback", "reason", "explain", "what", "action", "answer", "version")


def main_texts(node: Any, path: str = "") -> list:
    """(path, text) of every owner-facing string, skipping technical subtrees and metadata."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            # "full" = the canonical card text shown verbatim on expansion — never rewritten, so not
            # held to the jargon dictionary (ARB 09.10: «не переписывай каноническое содержание»)
            if k in ("full", "technical", "dictionary", "source", "measured_at", "updated_at", "unit", "confidence",
                     "tone", "id", "link_area", "computed_at", "snapshot_generated_at", "schema"):
                continue
            p = f"{path}.{k}" if path else k
            if isinstance(v, str) and k in _MAIN_TEXT_KEYS + ("confidence_ru", "measured_at_ru", "at_ru",
                                                                "updated_at_ru", "snapshot_generated_at_ru"):
                out.append((p, v))
            elif isinstance(v, list) and k in ("limitations",):
                out.extend((f"{p}[{i}]", s) for i, s in enumerate(v) if isinstance(s, str))
            else:
                out.extend(main_texts(v, p))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(main_texts(v, f"{path}[{i}]"))
    return out


def metrics(node: Any) -> list:
    """Every metric dict in the view (has label + confidence)."""
    out = []
    if isinstance(node, dict):
        if "confidence" in node and "label" in node:
            out.append(node)
        for k, v in node.items():
            if k != "technical":
                out.extend(metrics(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(metrics(v))
    return out
