#!/usr/bin/env python3
"""Заполнить паспорта агентов в `architecture/manifest.json` — ИЗ ИСТОЧНИКОВ.

Паспорт (AI1 гл. 3/24) = деловая цель · метрика качества · эскалация.
Замер 2026-08-20: агентов 89, паспортов 0. Инструмент, который меряет полноту
(`spa_core/monitoring/agent_passports.py`), построен днём раньше — заполнять
было нечем и некому.

ГЛАВНОЕ ПРАВИЛО ЭТОГО ФАЙЛА: **ничего не выдумывать.** Паспорт на 89 агентов,
написанный от руки, — это 267 правдоподобных предложений, из которых проверить
нельзя ни одного; такой паспорт хуже пустого, потому что выглядит как знание.
Поэтому каждое поле выводится из того, что уже есть в репозитории, и если
источника нет — поле остаётся ПУСТЫМ, а агент попадает в список «нужен
владелец/автор» (fail-CLOSED, инвариант #2).

Откуда берётся каждое поле:

* **goal** — первая фраза docstring'а python-модуля, который запускает обёртка
  `scripts/agent_*.sh`. Docstring писал автор агента; это его формулировка, а
  не наша.
* **quality_metric** — из блока `produces` самого манифеста: артефакт и его
  `slo_hours`. Это ИЗМЕРИМАЯ метрика («артефакт свежее N часов»), уже
  используемая сторожами свежести, а не пожелание вроде «работает хорошо».
* **escalation** — из кода: модуль, вызывающий `push_critical`, эскалирует
  владельцу в Телеграм через `push_policy`; агент без такого вызова, но с
  артефактом под SLO, эскалирует молчанием — его ловит сторож свежести.
  Ни того, ни другого нет ⇒ поле пустое, эскалация НЕ ПРИДУМЫВАЕТСЯ.

Только stdlib. Пишет атомарно. `--check` ничего не пишет.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "architecture" / "manifest.json"
# Паспорт (AI1 гл. 3/24). Мандат владельца 2026-08-21 расширил его тремя полями
# книги на два самых важных для риск-модели SPA: rights (что агенту МОЖНО —
# какие артефакты он пишет, куда эскалирует) и limits (чего НЕЛЬЗЯ — advisory-режим,
# запрет LLM, запрет импорта execution). До этого «чего агенту нельзя» жило только
# прозой в CLAUDE.md и промптах — машина не могла проверить незаписанное.
FIELDS = ("goal", "quality_metric", "escalation", "rights", "limits")

# Три способа, которыми обёртки называют свой python-модуль. Порядок важен:
# `export MODULE=` встречается в обёртках нового образца, позиционный
# аргумент `agent_template.sh <имя> <модуль>` — в старых.
_MODULE_PATTERNS = (
    re.compile(r'export\s+MODULE\s*=\s*"([\w][\w.]*\.[\w]+)"'),
    re.compile(r"agent_template\.sh\s+\S+\s+([\w][\w.]*\.[\w]+)"),
    re.compile(r"-m\s+([\w][\w.]*\.[\w]+)"),
)

# ─── точка входа, названная ПУТЁМ К ФАЙЛУ ─────────────────────────────────────
# Замер 2026-08-28: из 26 агентов без деловой цели у 19 докстринг автора ЛЕЖАЛ НА
# МЕСТЕ — его не читали, потому что все три образца выше требуют записи
# `пакет.модуль`, а обёртки называют точку входа файлом:
# `agent_template.sh golive_freshness /Users/…/scripts/golive_freshness_cycle.py`.
# Ловушка «я не нашёл» ⇒ «этого нет»: список звался «нужен автор», хотя автор всё написал.
#
# ОДНАКО путь к .py в обёртке — ещё не точка входа. Первый (наивный) вариант этой
# правки читал ЛЮБОЕ упоминание .py и выдал двум агентам (`inbox_watch`,
# `novel_edge_rnd`) цель «записать изменение сессии» — докстринг служебного
# `log_session_change.py`, который они дёргают для бухгалтерии. Ровно та беда, от
# которой защищает правило «больше одной точки входа ⇒ None»: чужая цель выглядит
# как знание и потому хуже пустой. Поэтому засчитываются только ОБЪЯВЛЕННЫЕ позиции:
#   * `export RUN_SCRIPT=…` / `export MODULE=…` — объявление;
#   * второй позиционный у `agent_template.sh <имя> <точка входа>` — объявление;
#   * строка с `exec` — процесс, которым агент СТАНОВИТСЯ;
#   * `-m пакет.модуль` — объявление модуля.
# Рядовой `"$PY" scripts/foo.py` в середине обёртки — ШАГ, а не цель агента.
# Хвост берётся и от АБСОЛЮТНОГО пути: обёртки пишут точку входа полным путём
# (`/Users/…/SPA_Claude/scripts/x.py`), поэтому запрет на `/` слева отрезал бы
# ровно основной случай — шесть агентов молча остались бы «без автора».
_EXPORT_MODULE_RX = _MODULE_PATTERNS[0]
_SCRIPT_PATH_RX = re.compile(r"(?<![\w])((?:scripts|spa_core|tests)/[\w/]+)\.py\b")
_UVICORN_RX = re.compile(r"uvicorn\s+([\w][\w.]*):\w+")
_RUN_SCRIPT_RX = re.compile(r'export\s+RUN_SCRIPT\s*=')
#: Строки, в которых путь к .py засчитывается как ОБЪЯВЛЕННАЯ точка входа.
# ОБЪЯВЛЕНИЕ обёртки о своей точке входа. Читается ПЕРВЫМ и бьёт любой вывод.
# Это не «комментарий как свидетельство» (тот запрет остаётся: «Generated from
# agent_template.sh» есть почти везде и выдавал модуль «(canonical bash» сорока
# агентам сразу) — это ЗАРЕЗЕРВИРОВАННЫЙ ключ, которым автор говорит прямо.
# Понадобился 29.08: `run_daily_paper_cycle.sh` получил третий и четвёртый шаги
# (allocation_auditor, apy_evidencer), целей стало четыре, вывод честно отказал —
# и САМЫЙ ВАЖНЫЙ агент системы молча выпал из переписи контрактов вместе со своим
# противоречием. Отказ был верным; неверно было то, что сказать правду оказалось нечем.
_AGENT_MODULE_RX = re.compile(r"#\s*AGENT_MODULE:\s*([\w][\w.]*)")

_DECLARING_RX = re.compile(r"(?:^|\s)exec\s|agent_template\.sh|export\s+RUN_SCRIPT\s*=")


def _logical_lines(text: str) -> list[str]:
    """Строки обёртки со склеенными переносами `\\` и без комментариев.

    Без склейки `exec` и его аргумент оказываются в разных строках, и позиция
    «объявление» теряется: так записан `agent_site_freshness.sh` — `exec …
    agent_template.sh \\` на одной строке, путь к монитору на следующей.
    """
    out: list[str] = []
    buf = ""
    for raw in text.splitlines():
        t = raw.strip()
        if buf:
            buf = buf[:-1].rstrip() + " " + t
        elif not t or t.startswith("#"):
            continue
        else:
            buf = t
        if buf.endswith("\\"):
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf.rstrip("\\").strip())
    return out


def module_of(program: str | None) -> str | None:
    """Python-модуль агента по его launchd-обёртке. Комментарии игнорируются.

    Комментарий — не свидетельство: строка «Generated from agent_template.sh»
    есть почти в каждой обёртке и при наивном поиске выдавала модуль
    «(canonical bash» для сорока агентов сразу.

    Точка входа записана в обёртках тремя способами, и читаются все три: модуль
    (`-m` / `export MODULE=`), путь к файлу и `uvicorn пакет.модуль:app`. Но
    веса у них РАЗНЫЕ, и порядок здесь — не стиль, а защита от регрессии:
    путь к файлу спрашивается ТОЛЬКО тогда, когда модуля не нашлось вовсе.
    Поэтому ни один агент, у которого цель выводилась раньше, не может её
    потерять из-за нового источника (проверено сравнением по всем 95: 0 потерь).
    """
    if not program:
        return None
    wrapper = REPO / "scripts" / program
    if not wrapper.is_file():
        return None
    try:
        raw = wrapper.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # Объявление старше любого вывода — но проверяется на существование: опечатка
    # в объявлении обязана дать ОТКАЗ, а не тихо приписать агенту чужой модуль.
    decl = _AGENT_MODULE_RX.search(raw)
    if decl and _module_file(decl.group(1)) is not None:
        return decl.group(1)
    lines = _logical_lines(raw)

    modules: list[str] = []   # прежний источник: точечная запись пакет.модуль
    declared: list[str] = []  # объявление обёртки о себе: export RUN_SCRIPT=
    paths: list[str] = []     # новый источник: путь к .py в объявляющей позиции
    for t in lines:
        for rx in _MODULE_PATTERNS:
            m = rx.search(t)
            if m and m.group(1) not in modules:
                modules.append(m.group(1))
        if _RUN_SCRIPT_RX.search(t):
            for m in _SCRIPT_PATH_RX.finditer(t):
                cand = m.group(1).replace("/", ".")
                if cand not in declared:
                    declared.append(cand)
        if not _DECLARING_RX.search(t):
            continue
        for m in _SCRIPT_PATH_RX.finditer(t):
            # `scripts/foo.py` → `scripts.foo`: путь к файлу дальше собирает
            # `_module_file`, второго способа это делать не заводим.
            cand = m.group(1).replace("/", ".")
            if cand not in paths:
                paths.append(cand)
        m = _UVICORN_RX.search(t)
        if m and m.group(1) not in paths:
            paths.append(m.group(1))

    if modules:
        # Прежнее поведение слово в слово, включая отказ на многошаговой обёртке
        # (`export MODULE=…` + `python3 -m …rollup`): взять ПЕРВЫЙ — значит с
        # ощутимой вероятностью описать агента чужим докстрингом. Чужая цель
        # хуже пустой: пустую видно в списке «нужен автор», а чужую — нет.
        return modules[0] if len(modules) == 1 else None
    # Модуля нет вовсе. Своё объявление (`export RUN_SCRIPT=`) старше пути,
    # выведенного из команды: `agent_strategy_lab_paper.sh` объявляет свой
    # скрипт экспортом, а запускает его безымянный `agent_template.sh`.
    chosen = declared or paths
    if not chosen:
        return None
    return chosen[0] if len(chosen) == 1 else None


def _module_file(module: str) -> Path | None:
    f = REPO / (module.replace(".", "/") + ".py")
    return f if f.is_file() else None


_DOC_RX = re.compile(r'(?:^|\n)\s*[ruRU]?("""|\'\'\')(?P<body>.*?)\1', re.S)


def goal_from_docstring(module: str | None) -> str:
    """Первая фраза docstring'а — формулировка автора агента, не наша."""
    if not module:
        return ""
    f = _module_file(module)
    if not f:
        return ""
    try:
        src = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _DOC_RX.search(src)
    if not m:
        return ""
    body = m.group("body").strip()
    if not body:
        return ""
    first = body.split("\n\n")[0].replace("\n", " ").strip()
    # «agent_passports — у каждого агента...» → убрать техническое имя слева.
    # Дефис ОБЯЗАН быть окружён пробелами: без этого условия «MP-144: ...»
    # превращалось в «144: ...» — номер задачи съедался вместе с префиксом.
    first = re.sub(r"^[\w.]+\s+[—–-]\s+", "", first)
    # обрезать по концу первого предложения, не разрывая «гл.3»
    cut = re.search(r"\.(?:\s|$)", first)
    if cut:
        first = first[: cut.start() + 1]
    first = re.sub(r"\s{2,}", " ", first).strip()
    return first[:300]


# Строки, которые описывают МЕХАНИЗМ запуска, а не дело агента. Такая «цель»
# ХУЖЕ пустой: она выглядит как знание и не отвечает на вопрос «зачем он есть»
# (тот же класс, что цель из докстринга служебного `log_session_change`, замер
# 28.08). Поэтому выводитель обязан уметь ОТКАЗАТЬСЯ — и у `com.spa.dashboard`
# он отказывается: там весь заголовок про то, что launchd не умеет exec'ить
# miniconda-python, и ни слова о деле.
_MECHANISM_RX = re.compile(
    r"launchd\s+wrapper|bash[- ]wrapper|wrapper\s+for\s+com\.spa|generated\s+from"
    r"|launchd\s+cannot|plist\s+must\s+call|обёртка\s+launchd|обёртка\s+для"
    r"|canonical\s+bash", re.I)

# `# scripts/foo.sh — прозa` / `# foo.sh - прозa`: техническое имя слева убрать.
_WRAPPER_NAME_RX = re.compile(r"^(?:[\w./-]+/)?[\w.-]+\.(?:sh|py)\s*[—–-]\s*")
_DECOR_RX = re.compile(r"^[=\-*_\s]*$")


def _program_file(program: str | None) -> Path | None:
    """Файл самой обёртки. `scripts/` — по умолчанию, путь в имени уважается."""
    if not program or program in ("python3", "bash", "/bin/bash"):
        return None
    cand = REPO / program if "/" in program else REPO / "scripts" / program
    return cand if cand.is_file() else None


def goal_from_wrapper_header(program: str | None) -> str:
    """Заголовочный комментарий обёртки — формулировка автора, как и docstring.

    Спрашивается ТОЛЬКО там, где docstring не дал ничего (см. `derive`): новый
    источник не может отнять уже выведенную цель, регрессия невозможна по
    построению, а не по внимательности (урок 28.08 — наивный вариант отнял цель
    у `daily_cycle` и `rates_desk_paper`).
    """
    f = _program_file(program)
    if f is None:
        return ""
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
    except OSError:
        return ""
    if f.suffix == ".py":                      # программа-скрипт: у неё свой docstring
        m = _DOC_RX.search("\n".join(lines))
        body = (m.group("body").strip() if m else "")
        block = body.split("\n\n")[0].replace("\n", " ").strip() if body else ""
    else:
        block, started = "", False
        for raw in lines:
            line = raw.strip()
            if line.startswith("#!"):
                continue
            if not line.startswith("#"):
                if started:
                    break
                continue
            text = _WRAPPER_NAME_RX.sub("", line.lstrip("#").strip())
            if _DECOR_RX.match(text):          # рамка из ===, не проза
                continue
            if _MECHANISM_RX.search(text):     # про запуск, а не про дело
                if started:
                    break
                continue
            # Перенос строки бывает двух видов, и путать их нельзя. Строчная буква
            # в начале — продолжение той же фразы («…finds cloudflared» + «binary
            # across…»), её надо доклеить. Прописная — уже НОВАЯ фраза, и склейка
            # без знака препинания сшила бы два утверждения в одно нечитаемое;
            # дописать точку самому — выдумать пунктуацию автора. Поэтому
            # останавливаемся и отдаём то, что автор написал одной строкой.
            if started and not re.search(r"\.(?:\s|$)", block) and text[:1].isupper():
                break
            started = True
            block = f"{block} {text}".strip()
            if re.search(r"\.(?:\s|$)", block):
                break
    if not block:
        return ""
    cut = re.search(r"\.(?:\s|$)", block)
    if cut:
        block = block[: cut.start() + 1]
    return re.sub(r"\s{2,}", " ", block).strip()[:300]


def quality_metric_from_produces(entry: dict) -> str:
    """Измеримая метрика из манифеста: артефакт + его SLO. Без SLO — пусто."""
    parts = []
    for p in entry.get("produces") or []:
        art, slo = p.get("artifact"), p.get("slo_hours")
        if art and slo:
            parts.append(f"{art} свежее {slo} ч")
    return "; ".join(parts)


def quality_metric_from_availability(entry: dict) -> str:
    """Метрика для служб, у которых продукт НЕ ФАЙЛ (решение владельца 29.08, вариант 1).

    «Файл свежее N часов» подходит агенту, который раз в такт пишет отчёт. Для демона,
    обёртки или headless-сессии она бессмысленна: у демона файла может не быть неделями
    и это норма, а продукт обёртки — выполненная работа. Замер 29.08: у 33 агентов из 95
    метрики не было, и это не 33 задачи, а один недостающий признак.

    Наше же правило это знало: расчёт срока годности для расписания `daemon` возвращает
    «такта нет — срока не назначить» (`slo_proposal.architect_floor`). Оно честно
    говорило «свежесть тут не метрика», а замены у него не было.

    Источники существуют, строить нечего — `data/agent_health.json` пишет по каждому
    агенту `loaded`, `pid`, `last_exit`, `log_age_min`. Отсюда две формулы:

      демон       → загружен и ДЕРЖИТ процесс (`loaded=true`, `pid≠0`);
      по расписанию → запускается и выходит кодом 0 (`loaded=true`, `last_exit=0`).

    Спрашивается ТОЛЬКО там, где `produces` пуст (см. `derive`), поэтому у агента с
    артефактом метрика не может смениться — регрессия невозможна по построению.
    """
    if entry.get("produces"):
        return ""
    sched = str(entry.get("schedule") or "").strip().lower()
    if not sched:
        return ""
    if sched == "daemon":
        return ("процесс загружен в launchd и держит pid "
                "(data/agent_health.json: loaded=true, pid≠0)")
    return (f"запускается по расписанию {entry.get('schedule')} и завершается кодом 0 "
            f"(data/agent_health.json: loaded=true, last_exit=0)")


def escalation_from_code(module: str | None, entry: dict) -> str:
    """Как об отказе узнаёт человек. Только то, что видно в коде/манифесте."""
    f = _module_file(module) if module else None
    if f:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src = ""
        if "push_critical" in src:
            return ("CRITICAL владельцу в Телеграм через push_policy "
                    "(дневной потолок; стоп-кран от него освобождён)")
    if quality_metric_from_produces(entry):
        return ("молчанием: протухший артефакт ловят сторожа свежести "
                "(artifact_freshness / agent_health) по SLO из манифеста")
    # ТРЕТИЙ ИСТОЧНИК (30.08). У службы без артефакта эскалации не выводилось вовсе —
    # 32 агента с пустым полем. Но их отказ ловится, и ловится РЕАЛЬНО: agent_health
    # проверяет загруженность в launchctl и код выхода (`* agents not loaded into
    # launchctl`, `last_exit`) и шлёт владельцу в Телеграм (`--run`). Проверено по коду
    # сторожа, а не предположено: путь существует, и его надо НАЗВАТЬ, а не оставлять
    # пустоту, которая читается как «об отказе никто не узнает».
    #
    # Спрашивается ТОЛЬКО там, где первые два источника молчат, и только если у агента
    # есть расписание (иначе мерить нечем — см. `quality_metric_from_availability`).
    if quality_metric_from_availability(entry):
        return ("молчанием: неработающий процесс ловит agent_health "
                "(не загружен в launchctl / ненулевой код выхода) и шлёт владельцу "
                "в Телеграм")
    return ""


def _declared_artifacts(module: str | None) -> list[str]:
    """`PRODUCES` из модуля агента. Читается РАЗБОРОМ (импорт исполнил бы агента).

    Зачем: 28.08 объявления довели до 71 агента из 72, но паспорта не сдвинулись с 26 —
    заполнитель читал только манифест и про объявления в коде не знал. Одно знание,
    два учёта: «71 из 72» звучало как «почти готово», пока паспорт стоял на 26.
    Пустой кортеж (`PRODUCES = ()`) — это ОТВЕТ «ничего не произвожу», и прав на запись
    он не даёт; None (объявления нет) — тоже пусто, но по другой причине.
    """
    if not module:
        return []
    try:
        sys.path.insert(0, str(REPO))
        from spa_core.monitoring.artifact_contract import declared_produces
    except Exception:                                    # noqa: BLE001
        return []                                        # нет модуля сверки — прав не выдумываем
    f = _module_file(module)
    if not f:
        return []
    try:
        return list(declared_produces(f) or [])
    except Exception:                                    # noqa: BLE001
        return []


def rights_from_manifest(module: str | None, entry: dict) -> str:
    """Что агенту МОЖНО — выведено из фактов манифеста/кода, не из пожеланий.

    Право = писать объявленные артефакты + путь эскалации. Оба берутся из того,
    что агент РЕАЛЬНО делает (produces, вызов push_critical), а не из описания.
    """
    parts: list[str] = []
    arts = [p.get("artifact") for p in (entry.get("produces") or []) if p.get("artifact")]
    if not arts:
        # Манифест молчит — спрашиваем ОБЪЯВЛЕНИЕ агента о себе (`PRODUCES`, ADR-158).
        # Порядок именно такой: курированный манифест старше, объявление лишь
        # закрывает пробел. Так у прав не может появиться регрессия из-за нового
        # источника — тот же порядок, что спас `module_of` от потери 12 целей.
        arts = _declared_artifacts(module)
    if arts:
        shown = ", ".join(arts[:3]) + (" …" if len(arts) > 3 else "")
        parts.append(f"писать {shown}")
    src = ""
    f = _module_file(module) if module else None
    if f:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src = ""
    if "push_critical" in src:
        parts.append("слать CRITICAL владельцу через push_policy")
    return "; ".join(parts)


def limits_from_code(module: str | None, entry: dict) -> str:
    """Чего агенту НЕЛЬЗЯ — прочитано из кода и манифеста, не из прозы.

    Ключевая для риск-модели SPA половина паспорта: advisory-режим, запрет LLM,
    запрет импорта execution. Всё это уже ЕСТЬ машиночитаемо (маркер LLM_FORBIDDEN,
    отсутствие импорта execution, флаг curation) — паспорт лишь называет это, а не
    выдумывает. Нет модуля для проверки ⇒ поле пустое (fail-CLOSED, не догадка).
    """
    f = _module_file(module) if module else None
    if not f:
        return ""
    try:
        src = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lims: list[str] = []
    # advisory: пишет в investment_os/ (harness форсит is_advisory) или несёт флаг
    if "is_advisory" in src or "IS_ADVISORY" in src or "/investment_os/" in src:
        lims.append("advisory — капитал не двигает")
    if "LLM_FORBIDDEN" in src or "LLM FORBIDDEN" in src:
        lims.append("LLM запрещён")
    if "spa_core.execution" not in src and "spa_core/execution" not in src:
        lims.append("не импортирует execution")
    return "; ".join(lims)


def derive(entry: dict) -> dict:
    module = module_of(entry.get("program"))
    return {
        # ПОРЯДОК ИСТОЧНИКОВ, а не заплатка: заголовок обёртки спрашивается лишь
        # там, где докстринг молчит. Так новый источник может только добавить.
        "goal": (goal_from_docstring(module)
                 or goal_from_wrapper_header(entry.get("program"))),
        # ПОРЯДОК ИСТОЧНИКОВ: доступность спрашивается лишь там, где артефакта нет.
        # Агент с продуктом сохраняет метрику по свежести слово в слово.
        "quality_metric": (quality_metric_from_produces(entry)
                           or quality_metric_from_availability(entry)),
        "escalation": escalation_from_code(module, entry),
        "rights": rights_from_manifest(module, entry),
        "limits": limits_from_code(module, entry),
    }


def _dumps(manifest: dict) -> str:
    """Сериализация манифеста КАНОНИЧЕСКИМ сериализатором генератора.

    Не `atomic_save`: его умолчания — `indent=2` и `ensure_ascii=True`, и первая
    же запись переписала бы весь файл (1946 строк → 2391) и превратила бы всю
    кириллицу в `\\uXXXX` — 96 строк там, где на origin их ноль. Дифф на 4331
    строку вместо ~270 нечитаем для ревьюера, а экранированный текст нечитаем
    вообще ни для кого; тесты этого не ловят, потому что структура JSON при этом
    верна. Формат манифеста задан РОВНО в одном месте — `dumps()` генератора, —
    и берётся оттуда, а не переписывается здесь второй раз (одно имя — один
    объект).
    """
    spec = importlib.util.spec_from_file_location(
        "_bam_dumps", REPO / "scripts" / "build_architecture_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.dumps(manifest)


def run(*, write: bool) -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    agents = data.get("agents", [])
    full = partial = empty = 0
    gaps: dict[str, list[str]] = {f: [] for f in FIELDS}
    # Агенты, у которых из источников выводится больше, чем записано в манифесте.
    # Появляются сами: кто-то дописал docstring модулю или докурировал produces —
    # и паспорт молча отстал. Это и делает `--check` гейтом, а не отчётом.
    stale: list[str] = []

    for a in agents:
        derived = derive(a)
        existing = a.get("passport") or {}
        # Существующее НЕ перетирается: если поле уже заполнено человеком,
        # оно ценнее выведенного автоматически.
        merged = {f: (str(existing.get(f) or "").strip() or derived[f]) for f in FIELDS}
        a["passport"] = merged
        have = sum(1 for f in FIELDS if merged[f])
        full += have == len(FIELDS)
        partial += 0 < have < len(FIELDS)
        empty += have == 0
        if merged != {f: str(existing.get(f) or "").strip() for f in FIELDS}:
            stale.append(a["label"])
        for f in FIELDS:
            if not merged[f]:
                gaps[f].append(a["label"])

    # Почему метрика не вывелась — это разные болезни, и лечатся они разно:
    # «манифест не докурирован» чинит куратор, «агент ничего не производит»
    # чинит автор агента. Одно число на двоих скрывало бы обе.
    uncurated = sum(1 for a in agents
                    if not (a.get("passport") or {}).get("quality_metric")
                    and a.get("curation") != "complete")
    report = {
        "total": len(agents),
        "full": full,
        "partial": partial,
        "empty": empty,
        "gaps": {f: len(v) for f, v in gaps.items()},
        "metric_gap_due_to_uncurated_manifest": uncurated,
        "stale": sorted(set(stale)),
        "needs_author": sorted(set(gaps["goal"])),
    }
    if write:
        sys.path.insert(0, str(REPO))
        from spa_core.utils.atomic import atomic_save_text
        atomic_save_text(_dumps(data), str(MANIFEST))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="только отчёт, ничего не писать")
    args = ap.parse_args()
    r = run(write=not args.check)
    print(json.dumps({k: v for k, v in r.items()
                      if k not in ("needs_author", "stale")},
                     ensure_ascii=False, indent=2))
    if r["needs_author"]:
        print(f"\nбез деловой цели ({len(r['needs_author'])}) — у обёртки не читается "
              f"python-модуль или у модуля нет docstring'а:")
        for label in r["needs_author"]:
            print("  ·", label)
        print("\nЭто НЕ ошибка скрипта, а честный список: цель такому агенту "
              "должен написать его автор или владелец.")
    if args.check and r["stale"]:
        print(f"\nМАНИФЕСТ ОТСТАЛ ОТ ИСТОЧНИКОВ ({len(r['stale'])}): у этих агентов "
              "выводится больше, чем записано.", file=sys.stderr)
        for label in r["stale"]:
            print("  ·", label, file=sys.stderr)
        print("\nЗапустите `python3 scripts/fill_agent_passports.py` и закоммитьте "
              "манифест.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
