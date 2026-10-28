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

__all__ = ["humanize_title", "humanize_body", "humanize", "SEVERITY_RU",
           "describe_queued_event", "EVENT_KEY_RU"]


# ── Заголовки Tier-1 событий (реальные title= из call-site'ов push_critical) ──
# Точное совпадение (после снятия иконок/тегов). Неизвестный заголовок → как есть.
_TITLES: dict[str, str] = {
    "SPA Agent Health — CRITICAL": "Агенты: критическая проблема",
    "SPA Agent Health — recovered": "Агенты: всё восстановилось",
    # 16.10 (ARB): «всё восстановилось» говорилось и при оставшихся предупреждениях — снятие тревоги
    # называет ровно то, что снято: критичных сбоев больше нет.
    "SPA Agent Health — no critical issues": "Агенты: критичных сбоев больше нет",
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
    # uptime_monitor (не-ключевой агент, понижен в сводку): процесс действительно остановлен.
    ("SPA Agent DOWN:", "Агент не работает:"),
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
# человеку. Detail-хвост переводится отдельно (`_DETAIL_RULES`); формат, для
# которого правила нет, проходит ВЕРБАТИМ.
SITE_CUSTODIAN_CODES: dict[str, str] = {
    "MISSING_ASOF": "нет даты актуальности данных",
    "STALE_SNAPSHOT": "снимок данных для сайта устарел",
    "STALE_API": "данные API устарели",
    # Пояснение — в скобках, а не через тире: detail-хвост теперь тоже переводится
    # и присоединяется через « — », два тире в строке читаются плохо.
    "SITE_BEHIND_SNAPSHOT": "на сайте старые числа (свежий снимок ещё не доехал)",
    # ADR-478: страница печатает ВИТРИНУ недельного такта, а не дневной снимок. Две
    # беды разведены по дверям: витрину чинит наш же генератор, публикацию — Cloudflare.
    "SHELF_UNREADABLE": "не прочитана витрина чисел сайта — отставание сайта НЕ ИЗМЕРЕНО",
    "SHELF_OVERDUE": "витрина чисел сайта просрочила свой недельный такт (чинится у нас, не в Cloudflare)",
    "PUBLISHER_STUCK": "сборка сайта встала — посетитель не видит опубликованных чисел",
    "SNAPSHOT_BEHIND_API": "снимок отстал от API (не перегенерировали после цикла)",
    "OVERSTATED_METRIC": "сайт показывает доходность ВЫШЕ реальной",
    # ADR-523 (заказ G86 п. 1): у сверки ТРИ исхода. «Не измерено» доходит до владельца
    # своими словами, иначе оно снова читается как «всё сошлось».
    "COMPARISON_NOT_MEASURED": "сверку числа сделать НЕ УДАЛОСЬ — операнда нет (это не «сошлось»)",
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
_LEAD_ICON_RE = re.compile(r"^(\s*(?:[🚨⚠️❌✅🔴🟡🔵ℹ️🛡️⛔🏆•\-–—]+\s*)+)")
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


# ── detail-хвост строки `[SEV] CODE: detail` ─────────────────────────────────
# Owner-задание 2026-08-04 («писать мне в чат простым языком, а не вот это вот»):
# раньше код переводился, а хвост оставался операторским —
# `снимок данных для сайта устарел — snapshot as_of 2026-08-03 is 32.9h old (> 30h)`.
# Владелец видел ровно ту английскую строку, на которую жаловался. Теперь хвост
# тоже переводится; контракт модуля не меняется:
#   * все числа/даты/URL/пороги переносятся из match-групп — ничего не выдумываем
#     и ничего не теряем (регресс-тест сверяет КАЖДОЕ число исходной строки);
#   * формата нет в таблице → хвост проходит ВЕРБАТИМ (лучше по-английски, чем никак).
_DETAIL_RULES: tuple[_Rule, ...] = (
    # MISSING_ASOF
    (re.compile(r"^snapshot has no parseable as_of$"),
     lambda m: "у самого снимка данных дата не читается"),
    (re.compile(r"^(\w+) page has no as-of label$"),
     lambda m: f"на странице «{m.group(1)}» нет отметки «данные на …»"),
    # STALE_SNAPSHOT / STALE_API
    (re.compile(r"^snapshot as_of (\S+) is ([\d.]+)h old \(> ?([\d.]+)h\)$"),
     lambda m: f"снимок сделан {m.group(1)}, ему уже {m.group(2)} ч — "
               f"норма не старше {m.group(3)} ч"),
    (re.compile(r"^API last bar (\S+) is ([\d.]+)h old \(> ?([\d.]+)h\)$"),
     lambda m: f"последняя запись API — {m.group(1)}, ей уже {m.group(2)} ч — "
               f"норма не старше {m.group(3)} ч"),
    # SITE_BEHIND_SNAPSHOT
    (re.compile(r"^(\w+) as-of (\S+) != snapshot as_of (\S+)$"),
     lambda m: f"на странице «{m.group(1)}» дата {m.group(2)}, "
               f"а в свежем снимке {m.group(3)}"),
    (re.compile(r"^site (\S+)=(\S+) != snapshot \1=(\S+)$"),
     lambda m: f"на сайте {m.group(1)} = {m.group(2)}, а в снимке {m.group(3)}"),
    # SNAPSHOT_BEHIND_API
    (re.compile(r"^snapshot days=(\S+) != API days=(\S+)$"),
     lambda m: f"в снимке дней трека {m.group(1)}, а по API {m.group(2)}"),
    # OVERSTATED_METRIC
    (re.compile(r"^(\w+) shows APY ([\d.]+)% > live API ([\d.]+)% "
                r"\(\+([\d.]+)pp tol\)$"),
     lambda m: f"страница «{m.group(1)}» показывает {m.group(2)}% годовых, "
               f"а живой API — {m.group(3)}% (допуск {m.group(4)} п.п.)"),
    # UNAVAILABLE
    (re.compile(r"^(\S+) -> HTTP (\d+)$"),
     lambda m: f"{m.group(1)} отвечает кодом HTTP {m.group(2)}"),
    # VERIFIER_PIN_MISMATCH
    (re.compile(r"^live verify_spa\.py (\S+) != pin (\S+)$"),
     lambda m: f"на сайте лежит версия {m.group(1)}, "
               f"а закреплена {m.group(2)}"),
)


def _humanize_detail(detail: str) -> str:
    """Хвост `[SEV] CODE: <detail>` простым языком. Нет правила → как есть."""
    for pattern, build in _DETAIL_RULES:
        m = pattern.match(detail)
        if m:
            return build(m)
    return detail


_DRIFT_CLASS_RU = {
    "retired-still-installed": "списаны, но ещё установлены",
    "orphan-plist": "установлены, но не объявлены в списке",
    "declared-no-plist": "объявлены, но не установлены",
    "declared-not-running": "объявлены, но не работают",
}


def _drift_classes_ru(text: str) -> str:
    """`5 retired-still-installed, 8 orphan-plist` → словами; неизвестный класс — как есть."""
    out = []
    for part in (x.strip() for x in text.split(",")):
        m = re.fullmatch(r"(\d+) ([\w-]+)", part)
        out.append(f"{_DRIFT_CLASS_RU[m.group(2)]} — {m.group(1)}"
                   if m and m.group(2) in _DRIFT_CLASS_RU else part)
    return ", ".join(out)


def _compact_ts_ru(ts: str) -> str:
    """`20261028T1900` → `28.10 19:00 UTC` (точная перестановка, без пересчёта)."""
    return f"{ts[6:8]}.{ts[4:6]} {ts[9:11]}:{ts[11:13]} UTC"


_RULES: tuple[_Rule, ...] = (
    # --- пульс проверки панели (dashboard_watcher) — не тревога, а отметка «проверено» ---
    (re.compile(r"^Dashboard check OK(?: — (?:(\d+)/(\d+) agents)?(?:, )?(?:equity (\$[\d,]+))?"
                r"(?:, )?(?:APY (-?[\d.]+)%)?)?$"),
     lambda m: "проверка панели: находок нет"
               + (f" — агентов в порядке {m.group(1)} из {m.group(2)}" if m.group(1) else "")
               + (f", капитал {m.group(3)}" if m.group(3) else "")
               + (f", APY за день {m.group(4)}%" if m.group(4) else "")),
    (re.compile(r"^Dashboard check INCOMPLETE — not measured:$"),
     lambda m: "проверка панели НЕПОЛНАЯ — часть проверок не измерена (это не «всё в порядке»)"),
    # --- договор кодов выхода resource_guard (agent_health, ARB 27.10 / UX-01) ---
    (re.compile(r"^ресурсы Мака: измерено WARN(?: \((.+?)\))? — код 1 по договору resource_guard, "
                r"не сбой агента$"),
     lambda m: "контроль ресурсов Mac сообщает о нехватке ресурсов"
               + (f" ({m.group(1)})" if m.group(1) else "")
               + " — это предупреждение замера, агент отработал штатно"),
    (re.compile(r"^ресурсы Мака: измерено CRITICAL или замер не удался — код 2 по договору "
                r"resource_guard, не сбой агента$"),
     lambda m: "контроль ресурсов Mac сообщает о критической нехватке ресурсов или не смог "
               "их измерить — агент отработал штатно, подробности в его отчёте"),
    # --- запись проверки панели до 28.10: любое «не OK» называлось «Agent DOWN» ---
    (re.compile(r"^Agent DOWN: (com\.spa\.[\w.\-]+)( \(CRITICAL agent\))?$"),
     lambda m: f"проверка панели отметила {'ключевого ' if m.group(2) else ''}агента "
               f"{m.group(1)} как неисправного (вид неисправности в записи не указан — "
               f"это не обязательно остановка)"),
    # --- сторож сторожей (watchdog) ---
    (re.compile(r"^SPA Watchdog \(guardian-of-guardians\)$"),
     lambda m: "Сторож агентов (следит за самовосстановлением и реакцией на угрозы)"),
    (re.compile(r"^guardian (com\.spa\.[\w.\-]+) heartbeat stale \(([\d.]+)min old\)$"),
     lambda m: f"{_agent_ru(m.group(1))} не подаёт признаков жизни {m.group(2)} мин"),
    (re.compile(r"^guardian (com\.spa\.[\w.\-]+) heartbeat stale \(no status ts\)$"),
     lambda m: f"{_agent_ru(m.group(1))}: признак жизни не читается — состояние НЕ ИЗМЕРЕНО"),
    (re.compile(r"^guardian (com\.spa\.[\w.\-]+) was NOT loaded$"),
     lambda m: f"{_agent_ru(m.group(1))} не был загружен"),
    (re.compile(r"^kickstarted (com\.spa\.[\w.\-]+) \(stale: (.+)\)$"),
     lambda m: f"команда перезапуска выполнена: {_agent_ru(m.group(1))} — что агент ожил, это сообщение не подтверждает"),
    (re.compile(r"^kickstart failed (com\.spa\.[\w.\-]+) \(stale: (.+)\)$"),
     lambda m: f"перезапуск НЕ УДАЛСЯ: {_agent_ru(m.group(1))}"),
    (re.compile(r"^revived \(bootstrap\) (com\.spa\.[\w.\-]+) \(was not loaded\)$"),
     lambda m: f"команда загрузки выполнена: {_agent_ru(m.group(1))} — что агент ожил, это сообщение не подтверждает"),
    (re.compile(r"^bootstrap failed (com\.spa\.[\w.\-]+) \(not loaded\)$"),
     lambda m: f"загрузить НЕ УДАЛОСЬ: {_agent_ru(m.group(1))}"),
    # --- commit-reveal книги SPA (audit/book_commitments): хеш — в подробностях, не в строке ---
    (re.compile(r"^SPA COMMIT книги (\d{4}-\d{2}-\d{2})$"),
     lambda m: f"раскладка книги SPA за {m.group(1)} зафиксирована хешем — раскрытие позже, "
               f"делать ничего не нужно"),
    (re.compile(r"^SPA REVEAL книги (\d{4}-\d{2}-\d{2})$"),
     lambda m: f"раскрыта зафиксированная раскладка книги SPA за {m.group(1)} — её можно сверить с хешем"),
    # --- свежесть артефактов и турнир (понижены в сводку) ---
    (re.compile(r"^Artifact freshness: (\d+) stale$"),
     lambda m: f"устарели файлы данных: {m.group(1)}"),
    (re.compile(r"^SPA Tournament — (\d{4}-\d{2}-\d{2})$"),
     lambda m: f"итоги теневого турнира стратегий за {m.group(1)} (бумажный, капитал не двигает)"),
    # --- сводка system_health_monitor ---
    (re.compile(r"^SPA System Health — (\w+) \((\d{8}T\d{4})\)$"),
     lambda m: f"проверка здоровья системы: {SEVERITY_RU.get(m.group(1).upper(), m.group(1))} "
               f"(замер {_compact_ts_ru(m.group(2))})"),
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
    # --- доказательство работы (ARB 15.10: квитанция и окно после загрузки) ---
    (re.compile(r"^no successful result for ([\d.]+\s*(?:min|h|d)) "
                r"\(>([\d.]+\s*(?:min|h|d)); receipt (\S+)\)$"),
     lambda m: f"нет успешного результата {_age(m.group(1))} — норма не реже "
               f"{_age(m.group(2))} (квитанция {m.group(3)})"),
    (re.compile(r"^running \(pid (\d+)\) but no successful result for "
                r"([\d.]+\s*(?:min|h|d)) \(>([\d.]+\s*(?:min|h|d))\)$"),
     lambda m: f"процесс работает (pid {m.group(1)}), но успешного результата нет "
               f"{_age(m.group(2))} — норма не реже {_age(m.group(3))}"),
    (re.compile(r"^no run since reboot ([\d.]+\s*(?:min|h|d)) "
                r"\(>([\d.]+\s*(?:min|h|d))\) — missed first scheduled run due by (\S+)$"),
     lambda m: f"после перезагрузки ни одного запуска за {_age(m.group(1))} — первый был "
               f"положен в пределах {_age(m.group(2))} (срок {m.group(3)}), плановый запуск пропущен"),
    (re.compile(r"^no run since reboot ([\d.]+\s*(?:min|h|d)) "
                r"\(>([\d.]+\s*(?:min|h|d))\)$"),
     lambda m: f"после перезагрузки ни одного запуска за {_age(m.group(1))} — "
               f"первый был положен в пределах {_age(m.group(2))}"),
    (re.compile(r"^success receipt unreadable \((.+)\) — NOT VERIFIED$"),
     lambda m: f"не проверено: квитанция успешного выполнения не читается "
               f"({m.group(1)})"),
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
     lambda m: f"список агентов разошёлся с фактическим: {_drift_classes_ru(m.group(1))}"),
    # --- вопросы владельцу (owner_decision_pending), строка может прийти усечённой ---
    (re.compile(r"^owner_decision_pending: (.+)$", re.S),
     lambda m: f"вопросы владельцу: {m.group(1)}"),

    # --- данные / турнир ---
    (re.compile(r"^tournament data-trust ALERT — (.+) \(human review\)$"),
     lambda m: f"турнирным данным нельзя доверять: {m.group(1)} — нужен человек"),

    # --- Site Custodian (ADR-YL-011) ---
    (re.compile(r"^SITE CUSTODIAN — (\d+) FAIL\(s\) @ (.+)$"),
     lambda m: f"Сайт-сторож: нашёл проблем — {m.group(1)} ({m.group(2)})"),
    (re.compile(r"^\[(\w+)\]\s+([A-Z_]+):\s*(.+)$"),
     lambda m: f"[{SEVERITY_RU.get(m.group(1).upper(), m.group(1))}] "
               f"{SITE_CUSTODIAN_CODES.get(m.group(2), m.group(2))} — "
               f"{_humanize_detail(m.group(3).strip())}"),
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
_PROBLEM_REF_RE = re.compile(r"\s*\[Problem [^\]]+\]$")
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
    # Ссылка на запись реестра проблем — для исполнителя; переводу не мешает и не теряется.
    ref_m = _PROBLEM_REF_RE.search(core)
    ref = ""
    if ref_m:
        ref, core = ref_m.group(0), core[:ref_m.start()].rstrip()

    if _is_known_title(core):
        return f"{indent}{icon}{humanize_title(core)}"

    labelled = _LABELLED_RE.match(core)
    if labelled:
        issue_ru = _humanize_issue(labelled.group("issue").strip())
        if issue_ru is None:
            return line
        return f"{indent}{icon}{_agent_ru(labelled.group('label'))} — {issue_ru}{ref}"

    ru = _humanize_issue(core)
    if ru is None:
        return line
    return f"{indent}{icon}{ru}{ref}"


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


# ── Событие из очереди дневной сводки (TELEGRAM-OWNER-UX-01, п. 2–3) ─────────
# Один смысл для дневной сводки и для отдельной тревоги: строка события строится тем же
# переводчиком, что и Tier-1 пуш. Контракт модуля сохраняется: ничего не выдумываем,
# нераспознанное идёт дословно, неизвестный код получает честное ОБЩЕЕ пояснение, а сам
# код остаётся в строке — исходная диагностика не теряется.

#: Ключи событий, которые встречаются в очереди сводки без внятного тела. Только то,
#: что ключ действительно означает; неизвестный ключ сюда не дописывается «на глаз».
EVENT_KEY_RU: dict[str, str] = {
    "dashboard_watch": "находка проверки панели (агенты, портфель, API)",
    "agent_down": "агент не работает",
    "system_health_summary": "сводка проверки здоровья системы",
    "artifact_freshness": "часть файлов данных устарела",
    "tournament": "итоги теневого турнира стратегий (бумажный, капитал не двигает)",
    "apy_spike": "резкий скачок доходности протокола",
    "pilot_request": "заявка на пилот",
}

_HASH_LINE_RE = re.compile(r"^(?:sha256\b|[0-9a-f]{32,}\b)", re.I)
_JSON_LINE_RE = re.compile(r"^[\[{]")
_EVENT_NOISE_PREFIXES = ("📊 Portfolio", "🤖 Agents", "━", "─", "🖥️ Dashboard Alert",
                         "Dashboard Alert", "⚠️ Not measured")
#: Заголовки, которые ничего не говорят о событии (общая шапка источника).
_GENERIC_TITLES = frozenset({"Dashboard watcher finding", "Tournament update", "System health summary"})
_SIGNAL_MARKS = ("🔴", "🟠", "🟡", "⚠️", "❌", "🛑", "⛔", "🚨")
_SIGNAL_WORDS = ("CRITICAL", "WARNING", "DOWN", "FAIL", "ERROR", "КРИТИЧ", "ПРЕДУПРЕЖД",
                 "НЕ РАБОТАЕТ", "ПРОБЛЕМ")
# Изменчивые части строки, которые НЕ меняют инцидент: возраст, время, отметки.
_VOLATILE_RES: tuple[Pattern[str], ...] = (
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\b\d{8}T\d{4,6}Z?\b"),
    re.compile(r"\b\d{1,2}:\d{2}(?:\s*UTC)?\b"),
    re.compile(r"\d+(?:[.,]\d+)?\s*(?:мин|min|ч|h|д|дн|d|сут(?:ок|ки)?|с|s)\b"
               r"(?:\s*назад|\s*ago|\s*old)?"),
)


def _event_lines(item: dict) -> list[str]:
    body = _TAG_RE.sub("", str(item.get("body") or ""))
    out: list[str] = []
    for ln in body.splitlines():
        ln = ln.strip()
        if (not ln or ln.startswith(_EVENT_NOISE_PREFIXES)
                or not any(ch.isalnum() for ch in ln)
                or _HASH_LINE_RE.match(ln) or _JSON_LINE_RE.match(ln)):
            continue
        out.append(ln)
    return out


def _incident_signature(text: str) -> str:
    sig = text
    for rx in _VOLATILE_RES:
        sig = rx.sub("·", sig)
    return re.sub(r"\s+", " ", sig).strip()


def describe_queued_event(item: dict) -> dict:
    """Событие очереди сводки → ``{"text", "incident", "critical", "known"}``.

    * ``text`` — одна строка по-русски: готовая ``summary`` источника, иначе сигнальная
      строка тела через общий переводчик, иначе заголовок, иначе пояснение ключа.
      Хеши, JSON и подвалы в основную строку не попадают.
    * ``incident`` — идентичность: объявленная источником (``incident``), иначе
      ключ + ПОЛНАЯ строка без изменчивых частей (возраст/время). Не первые 120
      символов: разные проблемы с одинаковым началом не сливаются, а смена
      одного возраста не рождает новый инцидент. Иконка/степень входят в
      идентичность — ухудшение отличимо.
    * ``critical`` — CRITICAL по степени события или по самому тексту.
    * ``known`` — False, когда пришлось ограничиться общим пояснением по коду.

    Чистая функция, без I/O, без LLM, никогда не рейзит.
    """
    try:
        key = str(item.get("event_key") or "?")
        sev = str(item.get("severity") or "").upper()
        body_upper = str(item.get("body") or "").upper()
        critical = sev == "CRITICAL" or "CRITICAL" in body_upper
        known = True
        text = str(item.get("summary") or "").strip()
        if not text:
            lines = _event_lines(item)
            # Источник сам сказал, что это НЕ сбой агента (договор кодов выхода, ARB 27.10):
            # эта строка точнее заголовка «Agent DOWN», под которым её ставили до 28.10.
            contract = next((ln for ln in lines if "не сбой агента" in ln), None)
            if contract is not None:
                lines = [re.sub(r"^(?:Issues|Причина):\s*", "", contract)]
            pick = next((ln for ln in lines if ln.startswith(_SIGNAL_MARKS)
                         or any(w in ln.upper() for w in _SIGNAL_WORDS)), None)
            title = _strip_markup(str(item.get("title") or ""))
            meaningful_title = bool(title) and title != key and title not in _GENERIC_TITLES
            if pick is None and lines and not meaningful_title:
                pick = lines[0]
            if pick is not None:
                text = _humanize_line(pick)
            else:
                if meaningful_title:
                    text = _humanize_line(title)
                elif key in EVENT_KEY_RU:
                    text = EVENT_KEY_RU[key]
                else:
                    known = False
                    text = f"событие без описания — источник прислал только код «{key}»"
        incident = str(item.get("incident") or "").strip()
        if not incident:
            incident = f"{key}|{_incident_signature(text)}"
        return {"text": text, "incident": incident, "critical": critical, "known": known}
    except Exception:  # noqa: BLE001 — событие обязано дойти хотя бы кодом
        key = str(item.get("event_key", "?")) if isinstance(item, dict) else "?"
        return {"text": f"событие без описания — код «{key}»", "incident": key,
                "critical": False, "known": False}
