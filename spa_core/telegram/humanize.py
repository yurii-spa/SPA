#!/usr/bin/env python3
"""spa_core/telegram/humanize.py — «простым языком» для Tier-1 алертов владельцу.

Owner-задание (inbox 2026-07-20 «перевести формат алертов на человеческий русский»
+ inbox 2026-07-27 «алерты в телеграм присылать простым языком»). Мониторы пишут
операторские строки (``com.spa.daily_cycle — last_exit=1``, ``autopush lag 239.4h
(>2h)``), которые владельцу ничего не говорят. Этот модуль — ЧИСТЫЙ текстовый
слой поверх них: он подключён в единственный чокпоинт Tier-1 пушей
(``push_policy._format_message``), поэтому один перевод покрывает все мониторы.

Контракт (нарушать нельзя — на нём держится доверие к алерту):

* **Никакой потери информации.** Нераспознанная строка проходит ВЕРБАТИМ.
  Лучше техническая строка, чем молча съеденная проблема.
* **Никакой выдумки.** Числа/имена/пороги переносятся из исходной строки как есть
  (единственное производное число — точный перевод базисных пунктов в проценты,
  ``bps/100``, потому что владелец мыслит процентами).
* **Детерминированно, stdlib, без LLM, без I/O.** Это alerts-путь: LLM здесь
  запрещён (CLAUDE.md, инвариант #3). Чистая функция от строки.
* **Никогда не рейзит.** Любой сбой → исходный текст (fail-safe: алерт должен
  дойти даже сломанным, но дойти).
* **Логику гейта не трогает.** Whitelist / edge-trigger / ceiling / held-scoping
  ``push_policy`` живут отдельно — здесь только рендеринг.

Публичный API::

    humanize_title(title) -> str
    humanize_body(body, *, title=None) -> str
    humanize(title, body) -> tuple[str, str]
"""
from __future__ import annotations

import re
from typing import Callable, Optional, Pattern

__all__ = ["humanize_title", "humanize_body", "humanize", "SEVERITY_RU"]


# ── Заголовки Tier-1 событий (реальные title= из call-site'ов push_critical) ──
# Точное совпадение (после снятия иконок/тегов). Неизвестный заголовок → как есть.
_TITLES: dict[str, str] = {
    "SPA Agent Health — CRITICAL": "Агенты: критическая проблема",
    "SPA Agent Health — recovered": "Агенты: всё восстановилось",
    "SPA Agent Health Alert": "Проверка агентов",
    "SPA System Health — CRITICAL": "Здоровье системы: критическая проблема",
    "SPA — Cycle Gap Detected": "Пропущен ежедневный цикл",
    # Отдельный заголовок для случая «возраст последнего цикла НЕ измерен»
    # (cycle_gap_monitor, 2026-07-30): раньше такой случай уезжал под
    # «Пропущен ежедневный цикл» — утверждение, которого никто не проверял.
    "SPA — Cycle Age NOT MEASURED": "Не удалось проверить, был ли сегодня цикл",
    "SPA FAIL-SAFE: safety check error": "Аварийный отказ: сбой проверки безопасности",
    "SPA Rules Watchdog — CRITICAL breach": "Нарушены правила портфеля (критично)",
    "SPA Threat Reactor — Kill Switch": "Сработал аварийный стоп (kill-switch)",
    "SPA Watchdog": "Сторож агентов",
    "SPA Self-Heal": "Самовосстановление агентов",
    "DataTrust Alarm": "Тревога: данным нельзя доверять",
    "SPA Competitive Watch — BREACH": "Конкурентный монитор: превышен порог",
}

# Заголовки с «хвостом» (имя агента и т.п.): префикс → шаблон.
_TITLE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("SPA Core Agent DOWN:", "Ключевой агент не работает:"),
)

SEVERITY_RU: dict[str, str] = {
    "CRITICAL": "критично",
    "FAIL": "проблема",
    "WARNING": "предупреждение",
    "WARN": "предупреждение",
    "INFO": "к сведению",
    "OK": "норма",
}

# Коды Site Custodian (`scripts/site_freshness_monitor.py`) — что это значит
# человеку. Технический detail-хвост в алерте СОХРАНЯЕТСЯ как есть.
SITE_CUSTODIAN_CODES: dict[str, str] = {
    "MISSING_ASOF": "нет даты актуальности данных",
    "STALE_SNAPSHOT": "снимок данных для сайта устарел",
    "STALE_API": "данные API устарели",
    "SITE_BEHIND_SNAPSHOT": "на сайте старые числа — свежий снимок ещё не доехал",
    "SNAPSHOT_BEHIND_API": "снимок отстал от API — его не перегенерировали после цикла",
    "OVERSTATED_METRIC": "сайт показывает доходность ВЫШЕ реальной",
    "UNAVAILABLE": "страница недоступна",
    "VERIFIER_PIN_MISMATCH": "верификатор на сайте не совпадает с зафиксированной версией",
}

_AGENT_RU: dict[str, str] = {
    "com.spa.daily_cycle": "ежедневный цикл",
    "com.spa.autopush": "автопуш в GitHub",
    "com.spa.apiserver": "API-сервер",
    "com.spa.orchestrator": "оркестратор",
    "com.spa.self_heal": "самовосстановление",
    "com.spa.agent_health": "проверка агентов",
    "com.spa.system_briefing": "сводка состояния",
}


# ── Утилиты ──────────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_LEAD_ICON_RE = re.compile(r"^(\s*(?:[🚨⚠️❌✅🔴🟡🔵ℹ️🛡️⛔•\-–—]+\s*)+)")
_AGE_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(min|h|d)\b")


def _strip_markup(text: str) -> str:
    """Снять HTML-теги и ведущие иконки — для сравнения/поиска, не для вывода."""
    return _TAG_RE.sub("", _LEAD_ICON_RE.sub("", text or "")).strip()


def _age(text: str) -> str:
    """`26.7h` → `26.7 ч`, `25min` → `25 мин`, `1.2d` → `1.2 дн`. Число не трогаем."""
    units = {"min": "мин", "h": "ч", "d": "дн"}
    return _AGE_RE.sub(lambda m: f"{m.group(1)} {units[m.group(2)]}", text or "")


def _agent_ru(name: str) -> str:
    """`com.spa.daily_cycle` → `ежедневный цикл (com.spa.daily_cycle)`.

    Техническое имя ОСТАЁТСЯ в скобках — владелец должен уметь назвать агента
    в ответном сообщении, а мы не должны прятать идентификатор.
    """
    friendly = _AGENT_RU.get(name)
    return f"{friendly} ({name})" if friendly else name


def _bps_ru(bps: str) -> str:
    """`127` → `~127 б.п. в год (≈1.27% годовых)` — точный перевод, не оценка."""
    try:
        pct = float(bps) / 100.0
    except (TypeError, ValueError):
        return f"~{bps} б.п. в год"
    return f"~{bps} б.п. в год (≈{pct:g}% годовых)"


# ── Правила по строкам тела алерта ───────────────────────────────────────────
# (regex, builder). ПЕРВОЕ совпадение выигрывает; совпадений нет → строка
# проходит вербатим. Все числа/имена берутся из match-групп — ничего не выдумываем.
_Rule = tuple[Pattern[str], Callable[[re.Match], str]]

_RULES: tuple[_Rule, ...] = (
    # --- статус-строка шапки agent_health ---
    (re.compile(r"^Status:\s*(\w+)\s*\|\s*(\d+)\s*issue\(s\) found$", re.I),
     lambda m: f"Статус: {SEVERITY_RU.get(m.group(1).upper(), m.group(1))} · "
               f"нашли проблем: {m.group(2)}"),

    # --- жизнь агента ---
    (re.compile(r"^last_exit=(-?\d+)$"),
     lambda m: f"последний запуск завершился с ошибкой (код выхода {m.group(1)})"),
    (re.compile(r"^malformed plist$"),
     lambda m: "сломан файл настроек агента (plist) — он не запустится"),
    (re.compile(r"^PID=0 \(server down\)$"),
     lambda m: "процесс не запущен — сервис лежит"),
    (re.compile(r"^log missing \(never ran\?\)$"),
     lambda m: "нет лога — похоже, ни разу не запускался"),
    (re.compile(r"^log stale ([\d.]+\s*(?:min|h|d)) \(>([\d.]+\s*(?:min|h|d))\)$"),
     lambda m: f"лог не обновлялся {_age(m.group(1))} — норма не реже "
               f"{_age(m.group(2))}"),
    (re.compile(r"^Missing \(not loaded\)$", re.I),
     lambda m: "агент не загружен в launchd"),

    # --- цикл и трек (деньги и go-live) ---
    (re.compile(r"^daily cycle stale ([\d.]+)h \(>([\d.]+)h\)$"),
     lambda m: f"ежедневный цикл не отрабатывал {m.group(1)} ч — норма раз в "
               f"{m.group(2)} ч"),
    (re.compile(r"^equity_curve stale ([\d.]+)h \(>([\d.]+)h\)$"),
     lambda m: f"кривая капитала не обновлялась {m.group(1)} ч — норма раз в "
               f"{m.group(2)} ч"),
    (re.compile(r"^track accrual STALE: newest evidenced bar ([\d.]+)h old "
                r"\(>([\d.]+)h SLA\)$"),
     lambda m: f"трек go-live не растёт: последняя подтверждённая запись "
               f"{m.group(1)} ч назад — норма {m.group(2)} ч"),
    (re.compile(r"^track accrual STALE: freshness check error \(fail-closed\)$"),
     lambda m: "трек go-live: проверка свежести упала — считаем по худшему "
               "(fail-closed)"),
    (re.compile(r"^track accrual STALE: (.+?) \(>([\d.]+)h SLA\)$"),
     lambda m: f"трек go-live не растёт: {m.group(1)} — норма {m.group(2)} ч"),
    (re.compile(r"^portfolio_health ([\d.]+)/100 \(<([\d.]+)\)$"),
     lambda m: f"здоровье портфеля {m.group(1)} из 100 — норма не ниже "
               f"{m.group(2)}"),

    # --- рынок / протоколы ---
    (re.compile(r"^(\d+) CRITICAL red flag\(s\) on HELD protocols$"),
     lambda m: f"критических «красных флагов» по протоколам, где лежат наши "
               f"деньги: {m.group(1)}"),

    # --- инфраструктура доставки кода ---
    (re.compile(r"^autopush lag ([\d.]+)h \(>([\d.]+)h\)$"),
     lambda m: f"изменения не уезжают в GitHub {m.group(1)} ч — норма каждые "
               f"{m.group(2)} ч"),

    # --- аварийное восстановление / флот ---
    (re.compile(r"^resilience posture stale ([\d.]+)h \(>([\d.]+)h\) — "
                r"DR proof-chain not fresh$"),
     lambda m: f"проверка аварийного восстановления не запускалась {m.group(1)} ч "
               f"— норма {m.group(2)} ч (доказательство бэкапа несвежее)"),
    (re.compile(r"^resilience posture (\w+) \(DR drill/offsite not passing\)$"),
     lambda m: f"аварийное восстановление в статусе {m.group(1)}: учения или "
               f"резервная копия не проходят"),
    (re.compile(r"^fleet parity stale ([\d.]+)h \(>([\d.]+)h\) — "
                r"drift guard not re-run$"),
     lambda m: f"сверка списка агентов не запускалась {m.group(1)} ч — норма "
               f"{m.group(2)} ч, расхождения сейчас не отслеживаются"),
    (re.compile(r"^fleet parity DRIFT \((.+)\)$"),
     lambda m: f"список агентов разошёлся с фактическим: {m.group(1)}"),

    # --- данные / турнир ---
    (re.compile(r"^tournament data-trust ALERT — (.+) \(human review\)$"),
     lambda m: f"турнирным данным нельзя доверять: {m.group(1)} — нужен человек"),

    # --- Site Custodian (ADR-YL-011) ---
    (re.compile(r"^SITE CUSTODIAN — (\d+) FAIL\(s\) @ (.+)$"),
     lambda m: f"Сайт-сторож: нашёл проблем — {m.group(1)} ({m.group(2)})"),
    (re.compile(r"^\[(\w+)\]\s+([A-Z_]+):\s*(.+)$"),
     lambda m: f"[{SEVERITY_RU.get(m.group(1).upper(), m.group(1))}] "
               f"{SITE_CUSTODIAN_CODES.get(m.group(2), m.group(2))} — {m.group(3)}"),
    (re.compile(r"^KILL-RULE: site set to DEGRADED \((.+)\)$"),
     lambda m: f"сработало правило защиты: сайт переведён в режим «данные "
               f"устарели» (причина: {m.group(1)})"),

    # --- эффективность капитала ---
    (re.compile(r"^capital-efficiency LAZY: ([\d.]+)% deployable capital idle at 0%"
                r"(?: — ~(\d+(?:\.\d+)?)bps/yr forgone)? "
                r"\(allocator left safe headroom unused\)$"),
     lambda m: f"{m.group(1)}% свободного капитала простаивает под 0%"
               + (f" — теряем {_bps_ru(m.group(2))}" if m.group(2) else "")
               + " (аллокатор не занял безопасный запас)"),
    (re.compile(r"^capital-efficiency UNKNOWN \(idle book, feed unreadable — "
                r"fail-closed\)$"),
     lambda m: "эффективность капитала неизвестна: фид не читается, считаем по "
               "худшему (fail-closed)"),
)

# Строка вида `<label> — <issue>`: переводим только issue, метку сохраняем.
_LABELLED_RE = re.compile(r"^(?P<label>com\.spa\.[\w.\-]+)\s+—\s+(?P<issue>.+)$")


def _humanize_issue(issue: str) -> Optional[str]:
    """Перевести одну техническую формулировку. ``None`` = правила нет."""
    for pattern, build in _RULES:
        m = pattern.match(issue)
        if m:
            return build(m)
    return None


def _is_known_title(core: str) -> bool:
    """Строка — это шапка события (мониторы дублируют её внутри тела)?"""
    return core in _TITLES or any(core.startswith(p) for p, _ in _TITLE_PREFIXES)


def _humanize_line(line: str) -> str:
    """Одна строка тела: иконка сохраняется, распознанное переводится,
    нераспознанное проходит вербатим."""
    if not line.strip():
        return line
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]  # отступ — часть структуры, храним
    icon_m = _LEAD_ICON_RE.match(stripped)
    icon = icon_m.group(1) if icon_m else ""
    rest = stripped[len(icon):]
    core = _TAG_RE.sub("", rest).strip()

    if _is_known_title(core):
        return f"{indent}{icon}{humanize_title(core)}"

    labelled = _LABELLED_RE.match(core)
    if labelled:
        issue_ru = _humanize_issue(labelled.group("issue").strip())
        if issue_ru is None:
            return line
        return f"{indent}{icon}{_agent_ru(labelled.group('label'))} — {issue_ru}"

    ru = _humanize_issue(core)
    if ru is None:
        return line
    return f"{indent}{icon}{ru}"


# ── Публичный API ────────────────────────────────────────────────────────────
def humanize_title(title: str) -> str:
    """Заголовок Tier-1 события простым языком. Неизвестный — как есть."""
    try:
        raw = _strip_markup(title)
        if not raw:
            return title
        exact = _TITLES.get(raw)
        if exact:
            return exact
        for prefix, ru_prefix in _TITLE_PREFIXES:
            if raw.startswith(prefix):
                return f"{ru_prefix}{raw[len(prefix):]}"
        return title
    except Exception:  # noqa: BLE001 — алерт обязан дойти
        return title


def humanize_body(body: str, *, title: Optional[str] = None) -> str:
    """Тело алерта построчно. Строка-дубль заголовка снимается (мониторы часто
    повторяют шапку внутри тела); всё нераспознанное — вербатим."""
    try:
        if not body:
            return body
        title_key = _strip_markup(title) if title else ""
        out: list[str] = []
        for line in body.split("\n"):
            core = _strip_markup(line)
            # Шапку снимаем ТОЛЬКО в начале тела и только когда заголовок уже
            # есть в самом сообщении — иначе это содержание, а не дубль.
            is_dup_head = bool(core) and not out and bool(title_key) and (
                core == title_key or _is_known_title(core)
            )
            if is_dup_head:
                continue
            out.append(_humanize_line(line))
        while out and not out[0].strip():
            out.pop(0)
        return "\n".join(out)
    except Exception:  # noqa: BLE001 — алерт обязан дойти
        return body


def humanize(title: str, body: str) -> tuple[str, str]:
    """`(title, body)` простым языком — то, что зовёт ``push_policy``."""
    return humanize_title(title), humanize_body(body, title=title)
