#!/usr/bin/env python3
"""
SPA 7-Day Checkpoint — MP-434
Автоматическая валидация после 7 дней paper trading (2026-06-19).

Checks:
  1. Gap check       — нет пропусков в ежедневных записях за последние 7 дней
  2. Sharpe check    — S7 >= 0.8, S5/S6 >= 0.9, promote >= 1.0
  3. Equity floor    — текущий equity >= $95,000, APY (7d) >= 5%
  4. Files existence — критические файлы data/*.json
  5. Summary output  — форматированный вывод в консоль
  6. Telegram alert  — при FAIL (или PASS) через Keychain-токен

Exit code — КОД ВОЗВРАТА ОТВЕЧАЕТ ЗА РАБОТОСПОСОБНОСТЬ, НЕ ЗА ВЕРДИКТ:
  0 — отчёт ПОСТРОЕН (красные проверки живут в теле отчёта и в алерте);
  1 — только по явной просьбе (`--verdict-exit-code`): в отчёте есть красное;
  2 — отчёт построить НЕ УДАЛОСЬ (настоящий сбой: нечего читать, нечем считать).
Почему так — см. docstring `run_checkpoint`.

Stdlib only: json, subprocess, urllib.request, os, datetime, pathlib, sys
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ─── Constants ────────────────────────────────────────────────────────────────

BASE = Path.home() / "Documents" / "SPA_Claude"
DATA = BASE / "data"

PAPER_START_DATE = date(2026, 6, 12)
CHECKPOINT_DAY   = 7
CHECKPOINT_DATE  = PAPER_START_DATE + timedelta(days=CHECKPOINT_DAY)  # 2026-06-19

EQUITY_FLOOR_USD  = 95_000.0
BASE_CAPITAL      = 100_000.0
APY_MIN_PCT       = 5.0

# ─── Коды возврата (конвенция флота) ─────────────────────────────────────────
# `last_exit` у launchd-агента читают сторожа флота (`agent_health`) как ответ на
# вопрос «агент РАБОТАЕТ?». Агент-репортёр, выходящий 1 при красной проверке,
# отвечает этим же кодом на ДРУГОЙ вопрос — «в отчёте есть красное?» — и потому
# числится вечно сломанным: гейт деплоя его не пропускает, а пропущенный писал бы
# WARN каждую неделю до конца времён (карточка `agent-checkpoint-7day-gate-conflict`).
EXIT_OK           = 0   # отчёт построен (вердикт — в отчёте и в алерте)
EXIT_VERDICT_FAIL = 1   # ТОЛЬКО по явному `--verdict-exit-code`
EXIT_BROKEN       = 2   # отчёт построить не удалось — настоящий сбой

# Sharpe thresholds
SHARPE_S7_WARN    = 0.8   # S7 < this → warning
SHARPE_T2_MIN     = 0.9   # S5 / S6 should reach this
SHARPE_PROMOTE    = 1.0   # любая стратегия >= this → PROMOTE candidate

# Telegram Keychain keys
TELEGRAM_KEY      = "TELEGRAM_BOT_TOKEN_SPA"
TELEGRAM_CHAT_KEY = "TELEGRAM_CHAT_ID_SPA"

# Critical data files that must exist
CRITICAL_FILES = [
    DATA / "golive_status.json",
    DATA / "paper_evidence.json",
    DATA / "tournament_ranking.json",
    DATA / "adapter_status.json",
]

# ─── Keychain ────────────────────────────────────────────────────────────────

def get_keychain(service: str) -> str | None:
    """Читает секрет из macOS Keychain. Возвращает None при ошибке."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


# ─── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Отправляет сообщение в Telegram через canonical rate-limited client.

    FLOOD-GUARD: routed through spa_core.alerts.telegram_client so the shared
    cross-process rate limit applies. Transport only — same HTML message. The
    token/chat_id args are kept for signature compatibility; the canonical
    client re-resolves them from the Keychain (TELEGRAM_*_SPA).
    """
    try:
        if str(BASE) not in sys.path:
            sys.path.insert(0, str(BASE))
        from spa_core.alerts.telegram_client import send_message
        return send_message(text, parse_mode="HTML")
    except Exception:
        return False


def get_telegram_chat_id(token: str) -> str | None:
    """Получает chat_id из первого входящего обновления."""
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates?limit=1"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        updates = data.get("result", [])
        if updates:
            msg = updates[-1]
            if "message" in msg:
                return str(msg["message"]["chat"]["id"])
            elif "channel_post" in msg:
                return str(msg["channel_post"]["chat"]["id"])
    except Exception:
        pass
    return None


def notify_telegram(msg: str) -> bool:
    """Отправляет уведомление через Telegram, креды из Keychain.

    chat_id берётся напрямую из Keychain (TELEGRAM_CHAT_ID_SPA). Раньше он
    выводился из getUpdates, но постоянный long-poll бот (com.spa.bot_commands)
    выгребает апдейты first → getUpdates почти всегда пуст → chat_id=None →
    «token/chat_id unavailable» и отчёт не уходил. getUpdates оставлен лишь как
    best-effort fallback, если ключа в Keychain нет.
    """
    token = get_keychain(TELEGRAM_KEY)
    if not token:
        return False
    chat_id = get_keychain(TELEGRAM_CHAT_KEY) or get_telegram_chat_id(token)
    if not chat_id:
        return False
    return send_telegram(token, chat_id, msg)


# ─── Data loaders ────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict | list | None:
    """Безопасно читает JSON-файл. None если файл отсутствует или повреждён."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ─── Доказанный трек: якорь и окно (решение владельца 09.08) ─────────────────
#
# ПОЧЕМУ ОКНО СЧИТАЕТСЯ ДОКАЗАННЫМИ ДНЯМИ, А НЕ КАЛЕНДАРНЫМИ.
# Первая правка этой проверки завела окно «последние 7 дней» от `date.today()`.
# Она сняла вечный отказ, но принесла свой дефект — fail-OPEN ПО ЧАСАМ: дыра
# перестаёт блокировать просто оттого, что сдвинулся календарь, даже если после неё
# трек не набрал НИ ОДНОГО доказанного дня. Замер на этом дереве (17.08): дыры
# 2026-07-18 → 2026-07-20 и 2026-07-26 → 2026-07-28 — настоящие, после якоря — уже
# числились «историческими», потому что край окна уехал на 2026-08-10. Ждать
# достаточно долго стало способом закрыть проверку.
#
# Трек считается ДОКАЗАННЫМИ БАРАМИ (`spa_core.paper_trading.track_evidence` —
# единственный источник правды: он же решает, что бар с пустой книгой доказанным
# не считается). Поэтому дыра уходит из окна только тогда, когда после неё
# накопилось `window_days` НОВЫХ доказанных дней, — то есть трек доказал, что
# восстановился. Календарь на это больше не влияет.
#
# Якорь трека (`evidenced_anchor`, 2026-06-22) отрезает предысторию: дыра, начавшаяся
# ДО якоря (2026-06-21 → 2026-06-30 — цикл в те дни умер, дорисовывать запрещено),
# видна в отчёте, но не блокирует — то самое решение владельца, что и ADR-087 для
# гейта go-live.


def _track_evidence_module():
    """Канонический модуль доказанности трека. Бросает, если его нет (fail-CLOSED).

    Собственного определения «доказанного дня» здесь НЕТ и быть не должно: правило
    живёт в одном месте (`track_evidence`), и когда владелец закроет карточку про
    день с пустой книгой, эта проверка получит новое правило без единой правки.
    Дубликат правила означал бы, что чекпойнт и go-live-гейт считают разный трек.
    """
    try:
        from spa_core.paper_trading import track_evidence  # noqa: PLC0415
        return track_evidence
    except Exception:
        pass
    # Скрипт запускают и из своего дерева, и обёрткой агента из прода — путь к
    # пакету добываем от СЕБЯ, а не от константы.
    for root in (Path(__file__).resolve().parents[1], BASE):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
    from spa_core.paper_trading import track_evidence  # noqa: PLC0415
    return track_evidence


def _iso_dates(raw: Any) -> list[date]:
    """Отсортированные уникальные даты из списка ISO-строк. Мусор молча отбрасываем."""
    out: set[date] = set()
    for item in raw or []:
        if not isinstance(item, str):
            continue
        try:
            out.add(date.fromisoformat(item[:10]))
        except ValueError:
            continue
    return sorted(out)


def evidenced_series(data_dir: Path, *, today: date | None = None) -> list[date] | None:
    """Доказанные дни трека, возрастающе. `None` ⇒ судить не по чему (fail-CLOSED).

    Читается `equity_curve_daily.json` — файл, в котором бары НЕСУТ честные метки
    (`evidenced` / `source`), и прогоняется через канонический предикат. Отсутствие
    файла возвращает `None`, а не пустой список: «доказанных дней ноль» и «мы не
    смогли посмотреть» — разные ответы, и второй не имеет права ничего погасить.
    """
    ec = load_json(data_dir / "equity_curve_daily.json")
    if not isinstance(ec, dict) or not isinstance(ec.get("daily"), list):
        return None
    te = _track_evidence_module()
    return _iso_dates(te.evidenced_dates(ec["daily"], today=today))


def track_anchor(data_dir: Path, *, today: date | None = None) -> date | None:
    """Якорь честного трека — первый доказанный день. `None` ⇒ неизвестен.

    Порядок: пересчёт по барам (канонический) → записанный `evidenced_anchor`
    (`equity_curve_daily.summary`, затем `golive_status.json`). Литерального
    2026-06-22 здесь нет намеренно: якорь двигается вместе с треком, и вбитая дата
    рано или поздно начала бы врать.
    """
    series = None
    try:
        series = evidenced_series(data_dir, today=today)
    except Exception:
        series = None
    if series:
        return series[0]

    ec = load_json(data_dir / "equity_curve_daily.json")
    if isinstance(ec, dict) and isinstance(ec.get("summary"), dict):
        for key in ("evidenced_anchor", "first_real_date"):
            got = _iso_dates([ec["summary"].get(key)])
            if got:
                return got[0]
    gl = load_json(data_dir / "golive_status.json")
    if isinstance(gl, dict):
        got = _iso_dates([gl.get("evidenced_anchor")])
        if got:
            return got[0]
    return None


def evidenced_window_edge(series: list[date] | None, *, window_days: int,
                          anchor: date | None) -> date | None:
    """Левый край окна = `window_days`-й доказанный день с конца. `None` ⇒ неизвестен.

    Доказанных дней меньше, чем длина окна ⇒ край = якорь: молодому треку нечего
    выводить из окна, и «ещё не набрали» не должно читаться как «уже прощено».
    """
    if not series:
        return anchor
    edge = series[-window_days:][0] if window_days > 0 else series[0]
    if anchor is not None and edge < anchor:
        edge = anchor
    return edge


def classify_gaps(dates: list[date], *, anchor: date | None,
                  window_edge: date | None) -> tuple[list[str], list[str]]:
    """Разбор дыр в ряду дат на (блокирующие, исторические-но-видимые).

    Дыра БЛОКИРУЕТ, когда выполнено И то, И другое:
      * началась ПОСЛЕ якоря трека (иначе это предыстория — восстановить нечем);
      * дотягивается до окна последних доказанных дней (иначе трек уже доказал,
        что восстановился, `window_days` барами после неё).
    Неизвестный якорь или неизвестный край окна ⇒ дыра блокирует (fail-CLOSED):
    «мы не смогли посмотреть» не является прощением.
    """
    blocking: list[str] = []
    historic: list[str] = []
    for prev, cur in zip(dates, dates[1:]):
        delta = (cur - prev).days
        if delta <= 1:
            continue
        span = f"{prev} → {cur} ({delta} days)"
        pre_anchor = anchor is not None and prev < anchor
        aged_out = window_edge is not None and cur < window_edge
        if pre_anchor:
            historic.append(f"{span} — до якоря трека {anchor}")
        elif aged_out:
            historic.append(f"{span} — вне окна доказанных дней (край {window_edge})")
        else:
            blocking.append(span)
    return blocking, historic


# ─── Check 1: Gap check ──────────────────────────────────────────────────────

def check_gaps(data_dir: Path = DATA, *, window_days: int = 7,
               today: date | None = None) -> dict[str, Any]:
    """
    Читает gap_monitor.json и paper_evidence.json.
    Проверяет: нет пробелов за последние `window_days` дней.

    Окно — часть контракта, а не украшение. Раньше описание обещало «за последние
    7 дней», а код проверял ВСЮ историю и падал на первой найденной дыре. Дыры
    2026-06-21 → 2026-06-30 восстановить нечем (цикл умер, дорисовывать запрещено),
    поэтому проверка не могла быть закрыта НИКАКИМ действием: вечный замок, который
    каждую неделю рождал владельцу карточку.

    Тот же класс, что решён владельцем в ADR-087 (выписан как ADR-067) для гейта go-live: блокируют
    АКТИВНЫЕ дыры, историческая остаётся видимой в отчёте. Здесь решение применено
    ко второму потребителю — недельной проверке.

    `today` инъектируется: иначе тест про окно начнёт падать просто оттого, что
    сдвинулся календарь (`.claude/rules/deployment.md`).
    """
    result = {
        "name": "gap_check",
        "status": "pass",
        "days_tracked": 0,        # ДОКАЗАННЫХ дней (не календарных, не «записанных»)
        "days_recorded": 0,       # сколько дней записал регистратор — для сверки
        "gap_detected": False,
        "detail": "",
        "historic_gaps": [],
        "blocking_gaps": [],
        "window_days": window_days,
        "anchor": None,
        "window_edge": None,
        "evidence_source": "unavailable",
    }

    # Читаем gap_monitor.json
    gm = load_json(data_dir / "gap_monitor.json")
    if gm is not None:
        # ADR-087 (выписан как ADR-067): блокируют АКТИВНЫЕ дыры. `gap_detected` истинно и для
        # исторических, восстановить которые нечем, — на нём проверка вставала
        # намертво. Отсутствие поля `active_gaps` ⇒ старый производитель ⇒
        # прежнее поведение (fail-CLOSED): неизвестное не считается чистым.
        _active = gm.get("active_gaps")
        _stale_producer = "active_gaps" not in gm
        if _stale_producer and gm.get("gap_detected", False):
            result["status"] = "fail"
            result["gap_detected"] = True
            result["detail"] = (
                f"Gap detected (fail-CLOSED: производитель не пишет active_gaps): "
                f"{gm.get('message', 'unknown')}")
        elif _active:
            result["status"] = "fail"
            result["gap_detected"] = True
            result["detail"] = f"Активная дыра в треке: {_active}"
        elif not isinstance(_active, list) and not _stale_producer:
            # Мусор в поле не должен читаться как «активных нет».
            result["status"] = "fail"
            result["gap_detected"] = True
            result["detail"] = f"active_gaps испорчено ({_active!r}) — fail-CLOSED"
        else:
            hours = gm.get("hours_since_last_entry", 999)
            if hours > 26:  # допуск 26 часов (дневной цикл + буфер)
                result["status"] = "fail"
                result["gap_detected"] = True
                result["detail"] = f"Last entry {hours:.1f}h ago (>26h threshold)"
            else:
                result["detail"] = f"OK — last entry {hours:.1f}h ago"
    else:
        result["detail"] = "gap_monitor.json not found — relying on paper_evidence"

    # ── Доказанный трек: якорь + окно доказанными днями (не календарными) ────
    series: list[date] | None = None
    anchor: date | None = None
    try:
        series = evidenced_series(data_dir, today=today)
        anchor = track_anchor(data_dir, today=today)
    except Exception as exc:  # noqa: BLE001 — судить нечем ⇒ ничего не прощаем
        result["status"] = "fail"
        result["gap_detected"] = True
        result["detail"] = (
            (result["detail"] + " · " if result["detail"] else "")
            + f"канонический счёт доказанных дней недоступен ({exc!r}) — fail-CLOSED: "
              "без него ни одна дыра не выводится из окна"
        )

    edge = evidenced_window_edge(series, window_days=window_days, anchor=anchor)
    result["anchor"] = anchor.isoformat() if anchor is not None else None
    result["window_edge"] = edge.isoformat() if edge is not None else None
    if series is not None:
        result["days_tracked"] = len(series)
        result["evidence_source"] = "equity_curve_daily (доказанные бары)"

    # Регистратор трека: его дни — то, что ЗАПИСАНО, а доказано ли — решает
    # `track_evidence`. Раньше здесь стоял `days_tracked = len(days)`, и отчёт
    # объявлял «44/30» при 13 доказанных днях: 30-дневная норма выглядела взятой
    # с запасом там, где трек не добрал и половины (инвариант #8).
    pe = load_json(data_dir / "paper_evidence.json")
    recorded: list[date] = []
    if isinstance(pe, dict):
        recorded = _iso_dates(
            [d.get("date") for d in pe.get("days", []) if isinstance(d, dict)]
        )
        result["days_recorded"] = len(recorded)

    # Что сканируем на дыры: доказанный ряд, если он есть. Дни регистратора без
    # честных меток — только запасной вариант, и он объявляется вслух.
    if series is not None:
        scan, scanned_label = series, "доказанном треке"
    else:
        scan, scanned_label = recorded, "paper_evidence (без честных меток)"
        if recorded:
            result["evidence_source"] = "paper_evidence (метки доказанности отсутствуют)"

    blocking, historic = classify_gaps(scan, anchor=anchor, window_edge=edge)

    # Дыры по РЕГИСТРАТОРУ — только видимость, никогда блокировка. Доказанный ряд
    # начинается с якоря и про предысторию не знает вовсе, поэтому дыра
    # 2026-06-21 → 2026-06-30 исчезла бы из отчёта совсем — а решение владельца
    # требует ровно обратного: «остаётся ВИДИМОЙ, но не роняет чекпойнт вечно».
    # Блокировать по дням без честных меток нельзя: авторитет — доказанный ряд.
    if series is not None and recorded:
        rec_block, rec_hist = classify_gaps(recorded, anchor=anchor, window_edge=edge)
        for span in rec_block + rec_hist:
            marked = f"{span} [по регистратору]"
            if span not in blocking and marked not in historic:
                historic.append(marked)

    result["blocking_gaps"] = blocking
    result["historic_gaps"] = historic

    if blocking:
        result["status"] = "fail"
        result["gap_detected"] = True
        result["detail"] = f"Gap in {scanned_label}: {blocking[0]}"
    # Видимая история печатается ВСЕГДА, а не только когда всё остальное чисто:
    # «не блокирует» не имеет права превращаться в «не существует».
    if historic:
        hist = "; ".join(historic)
        result["detail"] = (
            (result["detail"] + " · " if result["detail"] else "")
            + f"историческая дыра вне окна {window_days} доказанных дней "
              f"(не блокирует): {hist}"
        )

    if series is not None and result["days_recorded"] > result["days_tracked"]:
        # Разбавление видно, а не спрятано: записанных дней больше, чем доказанных.
        result["detail"] += (
            f" · записано дней {result['days_recorded']}, доказано "
            f"{result['days_tracked']}"
        )

    return result


# ─── Check 2: Sharpe check ───────────────────────────────────────────────────

def check_sharpe(data_dir: Path = DATA) -> dict[str, Any]:
    """
    Читает tournament_ranking.json.
    Проверяет Sharpe-пороги для S5/S6/S7 и PROMOTE кандидатов.
    """
    result = {
        "name": "sharpe_check",
        "status": "pass",
        "best_sharpe_id": None,
        "best_sharpe_val": None,
        "promote_candidates": [],
        "warnings": [],
        "detail": "",
    }

    tr = load_json(data_dir / "tournament_ranking.json")
    if tr is None:
        result["status"] = "warn"
        result["detail"] = "tournament_ranking.json not found"
        return result

    strategies = tr.get("strategies", [])
    if not strategies:
        result["status"] = "warn"
        result["detail"] = "No strategies in tournament_ranking.json"
        return result

    # Индексируем по ID
    by_id: dict[str, dict] = {s["id"]: s for s in strategies if "id" in s}

    best_sharpe = 0.0
    best_id = None

    for s in strategies:
        sid = s.get("id", "?")
        sharpe = s.get("sharpe", 0.0) or 0.0
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_id = sid
        if sharpe >= SHARPE_PROMOTE:
            result["promote_candidates"].append({"id": sid, "sharpe": sharpe})

    result["best_sharpe_id"] = best_id
    result["best_sharpe_val"] = best_sharpe

    # S7 check
    s7 = by_id.get("S7", {})
    s7_sharpe = s7.get("sharpe", 0.0) or 0.0
    if s7_sharpe < SHARPE_S7_WARN:
        result["warnings"].append(f"S7 Sharpe={s7_sharpe:.2f} < {SHARPE_S7_WARN} (warning)")

    # S5 / S6 check
    for sid in ("S5", "S6"):
        sx = by_id.get(sid, {})
        sx_sharpe = sx.get("sharpe", 0.0) or 0.0
        if sx_sharpe > 0 and sx_sharpe < SHARPE_T2_MIN:
            result["warnings"].append(
                f"{sid} Sharpe={sx_sharpe:.2f} < {SHARPE_T2_MIN} threshold"
            )

    # Форматируем detail
    promo_str = (
        ", ".join(f"{p['id']} (Sharpe {p['sharpe']:.2f})" for p in result["promote_candidates"])
        or "none"
    )
    warn_str = "; ".join(result["warnings"]) or "none"
    result["detail"] = (
        f"Best Sharpe: {best_id}={best_sharpe:.2f}; "
        f"PROMOTE candidates: {promo_str}; "
        f"Warnings: {warn_str}"
    )

    return result


# ─── Check 3: Equity floor ───────────────────────────────────────────────────

def check_equity(data_dir: Path = DATA) -> dict[str, Any]:
    """
    Читает paper_trading_status.json или equity_curve_daily.json.
    Проверяет equity floor и 7d rolling APY.
    """
    result = {
        "name": "equity_floor",
        "status": "pass",
        "current_equity": None,
        "return_pct": None,
        "apy_7d_pct": None,
        "kill_switch_active": False,
        "detail": "",
    }

    # Приоритет: paper_trading_status.json
    pts = load_json(data_dir / "paper_trading_status.json")
    if pts is not None:
        equity = pts.get("current_equity") or pts.get("equity")
        result["current_equity"] = equity
        result["kill_switch_active"] = pts.get("kill_switch_active", False)
        apy_today = pts.get("apy_today_pct") or pts.get("apy_today")
        result["apy_7d_pct"] = apy_today  # Используем текущий APY как приближение
    else:
        # Fallback: equity_curve_daily.json
        ec = load_json(data_dir / "equity_curve_daily.json")
        if ec is not None:
            summary = ec.get("summary", {})
            equity = summary.get("end_equity")
            result["current_equity"] = equity
            result["apy_7d_pct"] = None  # нет в этом файле напрямую

    if result["current_equity"] is None:
        result["status"] = "fail"
        result["detail"] = "Cannot determine current equity (files missing)"
        return result

    equity = result["current_equity"]

    # Расчёт return %
    if equity and BASE_CAPITAL > 0:
        result["return_pct"] = (equity - BASE_CAPITAL) / BASE_CAPITAL * 100

    # Расчёт 7d rolling APY из equity_curve_daily.json
    ec = load_json(data_dir / "equity_curve_daily.json")
    if ec is not None:
        daily = ec.get("daily", [])
        if len(daily) >= 2:
            # Берём последние 7 (или сколько есть) записей
            window = daily[-7:] if len(daily) >= 7 else daily
            start_eq = window[0].get("open_equity") or window[0].get("equity") or BASE_CAPITAL
            end_eq   = window[-1].get("equity") or window[-1].get("close_equity") or equity
            n_days   = len(window)
            if start_eq > 0 and n_days > 0:
                period_return = (end_eq - start_eq) / start_eq
                apy = period_return / n_days * 365 * 100
                result["apy_7d_pct"] = round(apy, 2)

    # Equity floor check
    if equity < EQUITY_FLOOR_USD:
        result["status"] = "fail"
        result["detail"] = (
            f"Equity ${equity:,.0f} < floor ${EQUITY_FLOOR_USD:,.0f} — ALERT"
        )
    else:
        result["detail"] = f"Equity ${equity:,.2f} OK"

    # APY check
    apy = result["apy_7d_pct"]
    if apy is not None and apy < APY_MIN_PCT:
        if result["status"] == "pass":
            result["status"] = "warn"
        result["detail"] += f"; APY {apy:.1f}% < {APY_MIN_PCT}% threshold (warn)"
    elif apy is not None:
        result["detail"] += f"; APY {apy:.1f}%"

    # Kill switch
    if result["kill_switch_active"]:
        result["status"] = "fail"
        result["detail"] += " — KILL SWITCH ACTIVE"

    return result


# ─── Check 4: Files existence ────────────────────────────────────────────────

def check_files(data_dir: Path = DATA) -> dict[str, Any]:
    """
    Проверяет существование критических data-файлов.
    """
    result = {
        "name": "files_existence",
        "status": "pass",
        "found": [],
        "missing": [],
        "detail": "",
    }
    expected = [
        data_dir / "golive_status.json",
        data_dir / "paper_evidence.json",
        data_dir / "tournament_ranking.json",
        data_dir / "adapter_status.json",
    ]
    for f in expected:
        if f.exists():
            result["found"].append(f.name)
        else:
            result["missing"].append(f.name)
            result["status"] = "fail"

    if result["missing"]:
        result["detail"] = f"Missing: {', '.join(result['missing'])}"
    else:
        result["detail"] = f"All {len(result['found'])} critical files present"

    return result


# ─── Summary formatter ───────────────────────────────────────────────────────

def format_summary(
    gaps: dict,
    sharpe: dict,
    equity: dict,
    files: dict,
    today: date | None = None,
    data_dir: Path = DATA,
) -> str:
    """Форматирует итоговый вывод в консоль.

    `data_dir` — вход, а не константа: до 2026-08-17 добор счёта дней читал
    модульный `DATA` (канонический трек) даже когда весь прогон шёл против
    песочницы, и отчёт по песочнице подмешивал живые числа.
    """
    if today is None:
        today = date.today()

    # Доказанных дней. Дополнять их «сколько всего баров в файле» ЗАПРЕЩЕНО —
    # именно так в отчёт попадало 44/30 при 13 доказанных днях.
    days_tracked = gaps.get("days_tracked") or 0
    days_recorded = gaps.get("days_recorded") or 0

    gap_ok     = gaps["status"] == "pass"
    eq_val     = equity.get("current_equity") or 0
    apy_val    = equity.get("apy_7d_pct")
    ret_pct    = equity.get("return_pct") or 0
    kill_sw    = equity.get("kill_switch_active", False)

    best_id    = sharpe.get("best_sharpe_id", "?")
    best_sh    = sharpe.get("best_sharpe_val")
    promote    = sharpe.get("promote_candidates", [])

    golive_ok  = files["status"] == "pass"

    days_line = f"Days tracked:   {days_tracked}/30 evidenced"
    if days_recorded and days_recorded != days_tracked:
        days_line += f" (записано {days_recorded})"
    if gaps.get("anchor"):
        days_line += f" · якорь {gaps['anchor']}"

    lines = [
        f"=== SPA 7-Day Checkpoint ({CHECKPOINT_DATE.isoformat()}) ===",
        days_line,
        f"Gap-free:       {'✅ YES' if gap_ok else '❌ NO — ' + gaps.get('detail', '')}",
        f"Equity:         ${eq_val:,.2f} ({ret_pct:+.3f}%)",
        f"APY (7d):       {f'{apy_val:.1f}%' if apy_val is not None else 'N/A'}",
    ]

    if best_id and best_sh is not None:
        promo_label = " [PROMOTE candidate]" if best_sh >= SHARPE_PROMOTE else ""
        lines.append(f"Best Sharpe:    {best_id} = {best_sh:.2f}{promo_label}")

    if promote:
        cands = ", ".join(f"{p['id']} (Sharpe {p['sharpe']:.2f})" for p in promote)
        lines.append(f"PROMOTE ready:  {cands} ← auto-promote candidate")
    else:
        lines.append("PROMOTE ready:  — (no strategy >= 1.0 yet)")

    lines.append(f"Kill-switch:    {'❌ ACTIVE' if kill_sw else '✅ NOT triggered'}")
    lines.append(f"GoLive status:  {'✅ PASS' if golive_ok else '❌ FAIL — missing files'}")

    # Предупреждения Sharpe
    for w in sharpe.get("warnings", []):
        lines.append(f"⚠️  {w}")

    return "\n".join(lines)


# ─── Overall status ──────────────────────────────────────────────────────────

def overall_pass(checks: list[dict]) -> tuple[bool, list[str]]:
    """Возвращает (all_pass, [список failов])."""
    failures = []
    for c in checks:
        if c["status"] == "fail":
            failures.append(f"{c['name']}: {c.get('detail', 'failed')}")
    return len(failures) == 0, failures


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_checkpoint(data_dir: Path = DATA, *, notify: bool = True,
                   verdict_exit_code: bool = False,
                   today: date | None = None) -> int:
    """
    Запускает все проверки, выводит summary, шлёт Telegram. Возвращает код возврата.

    КОД ВОЗВРАТА ОТВЕЧАЕТ НА ВОПРОС «АГЕНТ РАБОТАЕТ?», А НЕ «ВСЁ ЛИ ЗЕЛЕНО?»
    ------------------------------------------------------------------------
    * `EXIT_OK` (0) — отчёт ПОСТРОЕН. Красные проверки при этом никуда не деваются:
      они печатаются в блоке FAILURES и уходят владельцу алертом через push_policy.
    * `EXIT_BROKEN` (2) — отчёт построить НЕ УДАЛОСЬ (нечего читать, упало посреди
      счёта). Это и есть «агент сломан».
    * `EXIT_VERDICT_FAIL` (1) — только когда позвали с `verdict_exit_code=True`
      (флаг `--verdict-exit-code`): человеку у терминала и внешнему CI код вердикта
      по-прежнему доступен, но не по умолчанию.

    ПОЧЕМУ. До 2026-08-17 функция возвращала 1 на любую красную проверку, и это
    ломало ДВЕ вещи сразу (карточка `agent-checkpoint-7day-gate-conflict`):
    гейт деплоя `check_agent_before_deploy.sh` читает код пробного прогона как
    ответ на «агент работоспособен?» и отказывался ставить агента вовсе; а если бы
    поставили — `agent_health` писал бы WARN вечно, потому что `last_exit=1` у
    launchd означает «сломан», и настоящая поломка утонула бы в этом шуме.
    Ни одна проверка при этом НЕ ослаблена: вердикт полностью сохранён в отчёте и
    в алерте, изменился только смысл кода возврата — он приведён к конвенции флота.

    `notify=False` — единственный поддерживаемый способ НЕ трогать канал (флаг
    `--no-telegram`). До 2026-08-10 флаг был пустышкой: он переопределял
    `notify_telegram`, которую `run_checkpoint` не вызывает с тех пор, как отправка
    уехала в `_notify_via_push_policy` — то есть «выключенное» уведомление уходило
    владельцу как ни в чём не бывало. Подавление ВСЕГДА объявляется вслух: молчание
    канала не имеет права выглядеть как «сообщать было нечего».

    `today` — вход, а не окружение (`.claude/rules/deployment.md`, лекарство №1):
    окно доказанных дней и якорь трека судят о свежести, и тест, завязанный на
    настоящие часы, начал бы падать просто оттого, что сдвинулся календарь.
    """
    today = today or date.today()
    data_dir = Path(data_dir)

    # Нечего читать — отчёта не будет. Это НАСТОЯЩИЙ сбой, и он обязан звучать
    # иначе, чем красная проверка: иначе «агент сломан» и «трек в дыре» слились бы
    # в один код возврата, как это и было до сих пор.
    if not data_dir.is_dir():
        print(f"❌ BROKEN: каталог данных не читается: {data_dir} — "
              f"отчёт построить нечем (код {EXIT_BROKEN}).")
        return EXIT_BROKEN

    # Выполняем все 4 проверки
    try:
        gaps   = check_gaps(data_dir, today=today)
        sharpe = check_sharpe(data_dir)
        equity = check_equity(data_dir)
        files  = check_files(data_dir)
    except Exception as exc:  # noqa: BLE001 — сбой счёта ≠ вердикт «в треке дыра»
        print(f"❌ BROKEN: проверки упали, отчёт не построен: {exc!r} "
              f"(код {EXIT_BROKEN}).")
        return EXIT_BROKEN

    checks = [gaps, sharpe, equity, files]
    passed, failures = overall_pass(checks)

    # Summary в консоль
    summary = format_summary(gaps, sharpe, equity, files, today, data_dir=data_dir)
    print(summary)

    if not passed:
        print("\n--- FAILURES ---")
        for f in failures:
            print(f"  ❌ {f}")

    # Telegram
    if passed:
        tg_msg = (
            f"✅ SPA 7-Day Checkpoint PASSED — Day {CHECKPOINT_DAY}/30\n"
            f"{summary}"
        )
    else:
        fail_str = "\n".join(f"  • {f}" for f in failures)
        tg_msg = (
            f"⚠️ SPA 7-Day Checkpoint FAILED: {len(failures)} check(s)\n"
            f"{fail_str}\n\n{summary}"
        )

    # ОТПРАВКА — через push_policy, а не напрямую в транспорт.
    #
    # Замер 08.08: три ОДИНАКОВЫХ сообщения владельцу за шесть минут (13:06, 13:08, 13:12),
    # каждое — про одну и ту же дыру в треке 2026-06-21 → 2026-06-30, известную с июня.
    # Прямая отправка не помнит, что уже говорила, поэтому повторяет при каждом запуске:
    # владелец получает шум, а на шум перестают смотреть — и следующая НАСТОЯЩАЯ поломка
    # проедет незамеченной.
    #
    # `dedup_key` — отпечаток КОНКРЕТНОГО набора провалов. Тот же набор молчит; ДРУГОЙ
    # набор (появилась новая дыра, отвалилась ещё проверка) — звучит. Это дедуп, а не
    # подавление: ни одна проверка не ослаблена, изменился только повтор одного и того же.
    if not notify:
        print("\n[Telegram] Уведомление ПОДАВЛЕНО флагом --no-telegram "
              "(канал не тронут; результат проверок от этого не изменился).")
        return _exit_code(passed, verdict_exit_code=verdict_exit_code)

    ok = _notify_via_push_policy(passed, failures, tg_msg)
    if not ok and not passed:
        print("\n[Telegram] Уведомление не ушло (либо дедуп: тот же набор провалов уже сообщён).")

    return _exit_code(passed, verdict_exit_code=verdict_exit_code)


def _exit_code(passed: bool, *, verdict_exit_code: bool) -> int:
    """Код возврата отчётного агента. Отчёт построен ⇒ агент работоспособен.

    Красный вердикт при коде 0 ОБЪЯВЛЯЕТСЯ вслух: иначе ноль читался бы как «всё
    зелено» — ровно та подмена смысла, из-за которой этот код и переделали.
    """
    if passed:
        return EXIT_OK
    if verdict_exit_code:
        print(f"\n[exit] В отчёте есть красное; по просьбе --verdict-exit-code "
              f"выхожу кодом {EXIT_VERDICT_FAIL} (вердикт, НЕ поломка агента).")
        return EXIT_VERDICT_FAIL
    print(f"\n[exit] В отчёте ЕСТЬ КРАСНОЕ (см. FAILURES выше и алерт владельцу). "
          f"Код возврата {EXIT_OK} означает «отчёт построен, агент работоспособен», "
          f"а НЕ «всё зелено»: код {EXIT_VERDICT_FAIL} по флагу --verdict-exit-code, "
          f"код {EXIT_BROKEN} — настоящий сбой.")
    return EXIT_OK


def _notify_via_push_policy(passed: bool, failures: list, tg_msg: str) -> bool:
    """Отправить через единственный авторитет с дедупом. Никогда не бросает.

    Провал не проходит ⇒ печатаем в консоль и возвращаем False: молчание канала не имеет
    права выглядеть как «проверка прошла».
    """
    try:
        if str(BASE) not in sys.path:
            sys.path.insert(0, str(BASE))
        from spa_core.telegram import push_policy

        if passed:
            # Выход из тревоги обязателен: без него следующий провал был бы беззвучным
            # («всё ещё плохо») — ровно дефект ADR-070 п.4.
            return bool(push_policy.resolve(
                "checkpoint_failed",
                "7-дневный чекпойнт снова проходит",
                tg_msg,
            ))
        return bool(push_policy.push_critical(
            "checkpoint_failed",
            "WARNING",
            f"7-дневный чекпойнт: провалов {len(failures)}",
            tg_msg,
            dedup_key=",".join(sorted(str(f) for f in failures)),
        ))
    except Exception:  # noqa: BLE001 — уведомление не имеет права уронить сам чекпойнт
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SPA 7-Day Checkpoint MP-434")
    parser.add_argument(
        "--data-dir", type=Path, default=DATA,
        help=f"Path to data directory (default: {DATA})"
    )
    parser.add_argument(
        "--no-telegram", action="store_true",
        help="Skip Telegram notification"
    )
    parser.add_argument(
        "--verdict-exit-code", action="store_true",
        help=(f"Выходить кодом {EXIT_VERDICT_FAIL}, когда в отчёте есть красное. "
              f"По умолчанию код возврата отвечает за работоспособность агента "
              f"({EXIT_OK} — отчёт построен, {EXIT_BROKEN} — построить не удалось): "
              f"launchd и гейт деплоя читают его именно так.")
    )
    args = parser.parse_args()

    # Флаг передаётся В функцию, а не «переопределяет» имя, которого она не зовёт:
    # прежняя форма (подмена notify_telegram) не подавляла ничего — см. docstring
    # run_checkpoint.
    sys.exit(run_checkpoint(
        data_dir=args.data_dir,
        notify=not args.no_telegram,
        verdict_exit_code=args.verdict_exit_code,
    ))
