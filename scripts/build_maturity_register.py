#!/usr/bin/env python3
"""Реестр зрелости SPA: спроектировано / построено / заглушка.

Отвечает на один вопрос, который до 2026-08-20 занимал целую сессию:
**что из 415 документов `docs/` реально работает, а что только описано.**

Почему это понадобилось (замер 20.08): 415 файлов / ~102 000 строк документации,
80 ADR, 45 нумерованных документов Yield Lab — и девять названных слоёв, под
которыми нет ни одного файла кода. Читающий не мог отличить построенное от
нарисованного, поэтому переспрашивал, строил заново или верил числу из
документа, у которого стоит `requires verification`.

Шкала — пять уровней агентной зрелости (книга AI1, гл. 04), и её главное правило:
**уровень нельзя назначить всей компании одной цифрой, диагностика идёт по
функциям.** Поэтому единица реестра — функция, а не документ.

  L1 — знания живут у людей: ни документа, ни кода.
  L2 — документ есть, кода нет («документы существуют, но расходятся»).
  L3 — код есть, тестов нет.
  L4 — код есть и покрыт тестами: работает внутри процесса.
  L5 — сверх L4: у функции есть живой агент в манифесте (`intent: active`),
       то есть она исполняется сама, а не когда о ней вспомнят.

Приоритизация — та же книга, гл. 06: **эффект × готовность с поправкой на риск**.
«Высокий эффект при нулевой готовности — это проект подготовки. Высокая
готовность без эффекта — учебный стенд.»

ЧЕСТНАЯ ГРАНИЦА ФАЙЛА. Колонки делятся на два класса, и они НЕ смешиваются в
выводе:
  * **ЗАМЕР** — файлы кода, тесты, агент в манифесте, `requires verification`.
    Считается кодом при каждом запуске. Соврать не может.
  * **СУЖДЕНИЕ** — эффект, готовность, вердикт. Написано человеком/агентом,
    хранится в `JUDGMENT` ниже, и в отчёте помечено как суждение.
Смешать их — значит выдать мнение за измерение; ровно этого документа мы и
избегаем.

Только stdlib. Ничего не пишет, кроме `docs/MATURITY_REGISTER.md` (атомарно).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "architecture" / "manifest.json"
OUT = REPO / "docs" / "MATURITY_REGISTER.md"

# Каталоги, в которых ищется РЕАЛИЗАЦИЯ (не тесты).
CODE_ROOTS = ("spa_core", "scripts", "landing/src", "research")
TEST_MARKERS = ("/tests/", "test_", "_test.py")

# ── Единица реестра — ФУНКЦИЯ (AI1 гл.04: диагностика по функциям) ────────────
# paths    — явные пути. ЕДИНСТВЕННОЕ, что определяет уровень.
# keywords — regex для поиска реализации под ДРУГИМ именем. Показывается
#            ОТДЕЛЬНОЙ колонкой «упоминаний» и уровень НЕ двигает.
#            Почему так (состязательный разбор 20.08): единственное случайное
#            вхождение подстроки поднимало слой с L2 на L3. `external_capital`
#            находился как ключ JSON-отчёта `external_capital_managed_usd`, а
#            `two_layer` — как ИМЯ ФАЙЛА в списке путей пушера. Оба слоя
#            печатались как «код есть», и раздел «что делать» посылал читателя
#            дописывать тесты к фантому. Упоминание — подсказка человеку, а не
#            доказательство реализации.
# agents    — regex по метке БЕЗ префикса `com.spa.`; см. _agent_matches.
SUBJECTS: list[dict] = [
    # ─── Рантайм: то, что реально крутится ────────────────────────────────
    dict(key="paper_track", name="Paper-трек и дневной цикл",
         docs=["01_project_overview.md", "30_first_30_days_plan.md"],
         paths=["spa_core/paper_trading", "spa_core/tests/test_cycle*.py",
                "spa_core/tests/test_golive*.py", "spa_core/tests/test_paper*.py"],
         keywords=r"cycle_runner|golive_checker",
         agents=r"^daily_cycle$|^cycle_gap_monitor$|^cycle_health$|^orchestrator$"),
    dict(key="riskpolicy", name="RiskPolicy v1.0 — детерминированный гейт",
         docs=["06_spa_core_invariants.md"],
         paths=["spa_core/risk", "spa_core/tests/test_risk*.py",
                "spa_core/tests/test_*policy*.py"],
         keywords=r"RiskPolicy",
         # Библиотека, а не агент: её зовёт цикл. Приписывать ей чужого живого
         # агента (раньше подстрока `risk` забирала `io_protocol_risk`) — врать.
         agents=r""),
    dict(key="killswitch", name="Стоп-кран (two-tier drawdown)",
         docs=["decisions/ADR-048-two-tier-kill-switch.md"],
         paths=["spa_core/governance", "spa_core/tests/test_kill_switch*.py",
                "spa_core/tests/test_*drawdown*.py"],
         keywords=r"kill_switch",
         agents=r"^governance_watcher$|^intraday_equity$|^threat_reactor$"),
    dict(key="adapters", name="Адаптеры протоколов и фиды",
         docs=["23_data_architecture.md"],
         paths=["spa_core/adapters", "spa_core/tests/test_adapter*.py",
                "spa_core/tests/test_defillama*.py"],
         keywords=r"ADAPTER_REGISTRY|defillama",
         agents=r"^peg_monitor$|^sky_monitor$|^base_gas_monitor$"),
    dict(key="monitoring", name="Мониторинг, тревоги, здоровье флота",
         docs=["18_monitoring_and_alerting.md"],
         paths=["spa_core/monitoring", "spa_core/tests/test_*monitor*.py",
                "spa_core/tests/test_*health*.py"],
         keywords=r"system_health|agent_health",
         agents=r"monitor|health|watchdog|freshness|resilience|self_heal|rtmr|red_flag"),
    dict(key="telegram", name="Телеграм — рабочее место владельца",
         docs=["decisions/ADR-069-alert-action-buttons.md"],
         paths=["spa_core/telegram", "spa_core/tests/test_telegram*.py",
                "spa_core/tests/test_push*.py"],
         keywords=r"telegram", agents=r"^telegram"),
    dict(key="site", name="Сайт earn-defi.com и дашборд",
         docs=["26_dashboard_specification.md"],
         paths=["landing/src", "spa_core/tests/test_*site*.py",
                "spa_core/tests/test_*dashboard*.py"],
         keywords=r"safe_site_push|site_custodian",
         agents=r"^dashboard|^golive_freshness$"),
    dict(key="api", name="API-сервер",
         docs=["25_api_specification.md"],
         paths=["spa_core/api", "spa_core/tests/test_api*.py"],
         keywords=r"APIRouter", agents=r"^apiserver$"),
    dict(key="strategy_lab", name="Strategy Lab и дески (advisory)",
         docs=["07_yield_lab_architecture.md", "38_stablecoin_yield_engine.md"],
         paths=["spa_core/strategy_lab", "spa_core/tests/test_*sleeve*.py",
                "spa_core/tests/test_*swarm*.py", "spa_core/tests/test_*lab*.py"],
         keywords=r"strategy_lab|sleeve",
         agents=r"^aggressive_lab$|^strategy_lab_paper$|^swarm|^rates_desk_paper$|^rwa_safety_board$"),
    dict(key="fleet_econ", name="Экономика цеха и паспорта агентов (AI1)",
         docs=[],
         paths=["spa_core/monitoring/fleet_economics.py",
                "spa_core/monitoring/agent_passports.py",
                "spa_core/tests/test_fleet_economics_passports.py",
                "scripts/fill_agent_passports.py",
                "scripts/tests/test_fill_agent_passports.py"],
         keywords=r"fleet_economics|agent_passports", agents=r""),
    dict(key="product_layer", name="Продуктовый слой AAA (аналитики Investment OS)",
         docs=["08_ai_investment_os_architecture.md", "10_agent_architecture.md"],
         paths=["spa_core/investment_os", "prompts/agents",
                "spa_core/tests/test_*investment_os*.py",
                "spa_core/tests/test_api_investment_os.py"],
         keywords=r"investment_os", agents=r"^io_"),

    # ─── Спроектировано — построено частично или не построено ─────────────
    dict(key="btc_cycle", name="BTC capital cycle (лестница по фазам)",
         docs=["15_btc_cycle_framework.md", "36_btc_capital_cycle_machine.md"],
         paths=[], keywords=r"btc_cycle|mvrv|realized_price", agents=r"^btc"),
    dict(key="eth_yield", name="ETH yield framework",
         docs=["16_eth_yield_framework.md"],
         paths=[], keywords=r"eth_yield", agents=r"^eth"),
    dict(key="risk_v2", name="Risk Scoring v2 (advisory)",
         docs=["14_risk_scoring_v2.md"],
         paths=[], keywords=r"risk_scoring_v2|black_swan_risk_score|market_regime_risk_score",
         agents=r""),
    dict(key="cards", name="Карточные системы: стратегии / протоколы / стейблы",
         docs=["11_strategy_card_system.md", "12_protocol_card_system.md",
               "13_stablecoin_card_system.md"],
         paths=["research/cards"], keywords=r"strategy_card|protocol_card|stablecoin_card",
         agents=r"",
         data_glob=["data/strategy_cards/**/*.md", "data/protocol_cards/**/*.md",
                    "data/stablecoin_cards/**/*.md"]),
    dict(key="discovery", name="Strategy Discovery Engine",
         docs=["35_strategy_discovery_engine.md"],
         paths=[], keywords=r"strategy_discovery", agents=r"discovery"),
    dict(key="committee", name="Investment Committee workflow",
         docs=["39_investment_committee_workflow.md"],
         paths=[], keywords=r"investment_committee", agents=r"committee"),
    dict(key="builder_os", name="Builder OS",
         docs=["09_builder_os_architecture.md", "45_builder_os_workflow.md"],
         paths=[], keywords=r"builder_os", agents=r"builder"),
    dict(key="db_schema", name="Схема БД и качество данных",
         docs=["24_database_schema.md", "40_data_quality_framework.md"],
         paths=[], keywords=r"data_quality_framework", agents=r""),
    dict(key="perf_report", name="Методология отчётности о доходности",
         docs=["41_performance_reporting_methodology.md"],
         paths=["spa_core/reporting", "spa_core/tests/test_*report*.py"],
         keywords=r"performance_report", agents=r"^digest_|^system_briefing$|^tier1_digest$"),
    dict(key="ext_capital", name="Готовность к внешнему капиталу",
         docs=["42_external_capital_readiness.md"],
         paths=[], keywords=r"external_capital", agents=r""),
    dict(key="compliance", name="Compliance surface",
         docs=["22_compliance_surface.md"],
         paths=["spa_core/compliance", "spa_core/tests/test_*compliance*.py"],
         keywords=r"compliance", agents=r""),
    dict(key="dangerous", name="Опасные стратегии и research-first-20",
         docs=["43_dangerous_strategies.md", "44_research_first_20_strategies.md"],
         paths=[], keywords=r"dangerous_strateg", agents=r""),
]

# ── СУЖДЕНИЕ (не замер) — эффект × готовность, AI1 гл.06 ─────────────────────
# effect:    high | mid | low   — что даст, если ЗАРАБОТАЕТ
# verdict:   короткая формула из гл.06 + причина
JUDGMENT: dict[str, dict] = {
    "paper_track":   dict(effect="high", verdict="работает — не трогать"),
    "riskpolicy":    dict(effect="high", verdict="работает — заморожен на v1.0 до go-live"),
    "killswitch":    dict(effect="high", verdict="работает — не трогать"),
    "adapters":      dict(effect="high", verdict="работает"),
    "monitoring":    dict(effect="high", verdict="работает"),
    "telegram":      dict(effect="high", verdict="работает"),
    "site":          dict(effect="mid",  verdict="работает — owner-gated на числа"),
    "api":           dict(effect="mid",  verdict="работает"),
    "strategy_lab":  dict(effect="mid",  verdict="работает, advisory — капитал не двигает"),
    "fleet_econ":    dict(effect="mid",  verdict="работает; паспортов полных 18 из 89 — "
                                                 "остальное курация produces, карточка заведена"),
    "btc_cycle":     dict(effect="high", verdict="ПРОЕКТ ПОДГОТОВКИ: просадка −25% NAV не проходит "
                                                 "под HARD_KILL −10%; бэктест сохранён, строить нельзя"),
    "eth_yield":     dict(effect="mid",  verdict="проект подготовки — замера нет вовсе"),
    "risk_v2":       dict(effect="mid",  verdict="проект подготовки — advisory, гейтом не станет"),
    "cards":         dict(effect="mid",  verdict="валидатор есть, карточки есть (git-tracked); "
                                                 "автоматического производителя нет"),
    "discovery":     dict(effect="mid",  verdict="проект подготовки"),
    "committee":     dict(effect="low",  verdict="преждевременно: один владелец, комитета нет"),
    "builder_os":    dict(effect="low",  verdict="преждевременно"),
    "product_layer": dict(effect="high", verdict="частично АКТИВИРОВАН: io_* работают, "
                                                 "остальное owner-gated (ADR-004)"),
    "db_schema":     dict(effect="low",  verdict="не нужно: files-first — источник правды git"),
    "perf_report":   dict(effect="mid",  verdict="частично построено"),
    "ext_capital":   dict(effect="low",  verdict="заблокировано: solicitation закрыт до legal-clearance"),
    "compliance":    dict(effect="low",  verdict="частично построено"),
    "dangerous":     dict(effect="low",  verdict="research-документ, кода и не требует"),
}

LEVEL_NAMES = {
    1: "знания у людей",
    2: "документ есть, кода нет",
    3: "код есть, но не работает по-настоящему (нет тестов или нет данных)",
    4: "код, тесты и данные — работает внутри процесса",
    5: "живой агент — исполняется сам",
}


def _rg(pattern: str, roots: tuple[str, ...]) -> list[str]:
    """Список файлов, где встречается pattern. grep -rlEI, без завязки на ripgrep."""
    existing = [str(REPO / r) for r in roots if (REPO / r).exists()]
    if not existing or not pattern:
        return []
    try:
        res = subprocess.run(
            ["grep", "-rlEI", "--include=*.py", "--include=*.js", "--include=*.jsx",
             "--include=*.astro", pattern, *existing],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    # Генератор НЕ считается реализацией: его таблица SUBJECTS содержит все
    # ключевые слова, и без этого фильтра «кода нет» превращалось в «1 файл»
    # для КАЖДОГО непостроенного слоя — ровно та подмена, которую реестр ловит.
    me = str(Path(__file__).resolve())
    return [l for l in res.stdout.splitlines()
            if l.strip() and str(Path(l).resolve()) != me]


def _is_test(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return any(m in path for m in TEST_MARKERS[:1]) or base.startswith("test_") or base.endswith("_test.py")


def _count_paths(paths: list[str]) -> tuple[int, int]:
    """(файлов реализации, файлов тестов) по явным путям."""
    code = tests = 0
    expanded: list[str] = []
    for p in paths:
        if "*" in p:
            expanded.extend(str(f.relative_to(REPO)) for f in REPO.glob(p))
        else:
            expanded.append(p)
    for p in expanded:
        full = REPO / p
        if full.is_file():
            (tests := tests + 1) if _is_test(p) else (code := code + 1)
        elif full.is_dir():
            for f in full.rglob("*"):
                if not f.is_file() or f.suffix not in (".py", ".js", ".jsx", ".astro"):
                    continue
                rel = str(f.relative_to(REPO))
                if _is_test(rel):
                    tests += 1
                else:
                    code += 1
    return code, tests


_LABEL_PREFIX = "com.spa."


def _agent_matches(pattern: str, agents: list[dict]) -> list[str]:
    """Живые агенты функции. Сопоставление — по метке БЕЗ префикса `com.spa.`.

    Ловушка, найденная состязательным разбором: шаблон `^io_` не мог совпасть
    НИ С ОДНОЙ меткой, потому что все они начинаются с `com.spa.`, и реестр
    печатал «живых агентов: 0» по строке про продуктовый слой, у которого их
    тринадцать. Якорь `^` осмыслен только по имени без префикса — здесь он
    таким и становится.
    """
    if not pattern:
        return []
    rx = re.compile(pattern, re.I)
    out = []
    for a in agents:
        if a.get("intent") != "active":
            continue
        label = a.get("label", "")
        name = label[len(_LABEL_PREFIX):] if label.startswith(_LABEL_PREFIX) else label
        if rx.search(name):
            out.append(label)
    return out


def _tracked() -> set[str]:
    """Файлы под контролем версий. Уровень не имеет права зависеть от того,
    запускали ли на этой машине то, что реестр же и предписывает: артефакты в
    `.gitignore` есть на боевом хосте и отсутствуют в CI, и файл не может быть
    верен в обоих местах сразу."""
    try:
        res = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {l.strip() for l in res.stdout.splitlines() if l.strip()}


def _load_agents() -> list[dict]:
    if not MANIFEST.exists():
        return []
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8")).get("agents", [])
    except (OSError, ValueError):
        return []


def measure(subject: dict, agents: list[dict]) -> dict:
    code_n, test_n = _count_paths(subject.get("paths", []))
    hits = _rg(subject.get("keywords", ""), CODE_ROOTS)
    mentions = len([h for h in hits if not _is_test(h)])

    live = _agent_matches(subject.get("agents") or "", agents)

    globs = subject.get("data_glob") or []
    tracked = _tracked() if globs else set()
    data_n = 0
    for g in globs:
        for f in REPO.glob(g):
            if f.is_file() and str(f.relative_to(REPO)) in tracked:
                data_n += 1

    rv = 0
    for d in subject.get("docs", []):
        f = REPO / "docs" / d
        if f.exists():
            rv += len(re.findall(r"requires verification", f.read_text(encoding="utf-8")))

    if code_n == 0:
        level = 2 if subject.get("docs") else 1
    elif test_n == 0:
        level = 3
    elif globs and data_n == 0:
        # Код есть и покрыт тестами, но НИЧЕГО не производит — им никто не
        # пользуется. Называть такое «работает внутри процесса» нельзя:
        # валидатор карточек при нуле карточек — учебный стенд, а не функция.
        level = 3
    elif live:
        level = 5
    else:
        level = 4
    return dict(code=code_n, tests=test_n, live=len(live), rv=rv,
                mentions=mentions, data=data_n, has_data_check=bool(globs),
                level=level)


def _check_doc_refs() -> list[str]:
    """Каждый упомянутый документ обязан существовать.

    Реестр печатал ссылку на `ADR-069-telegram-owner-workspace.md`, которого нет
    (решение называется `ADR-069-alert-action-buttons.md`). Битая ссылка в файле,
    заявленном как ЗАМЕР, — то же самое, что выдуманное число.
    """
    missing = []
    for subj in SUBJECTS:
        for d in subj.get("docs", []):
            if not (REPO / "docs" / d).is_file():
                missing.append(f"{subj['key']}: docs/{d}")
    return missing


def build() -> str:
    missing = _check_doc_refs()
    if missing:
        raise SystemExit("реестр ссылается на несуществующие документы:\n  "
                         + "\n  ".join(missing))
    agents = _load_agents()
    rows = []
    for s in SUBJECTS:
        m = measure(s, agents)
        j = JUDGMENT.get(s["key"], {})
        rows.append((s, m, j))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_level: dict[int, int] = {}
    for _, m, _ in rows:
        by_level[m["level"]] = by_level.get(m["level"], 0) + 1

    out = [
        "# Реестр зрелости SPA — спроектировано / построено / заглушка",
        "",
        f"> **Генерируется** `scripts/build_maturity_register.py` · замер от **{now}**.",
        "> Руками не править — правка уедет при следующем запуске. Менять надо таблицу"
        " `SUBJECTS` / `JUDGMENT` в генераторе.",
        ">",
        "> **Зачем.** Отличить работающее от нарисованного, не читая 415 файлов `docs/`.",
        "> Шкала — пять уровней агентной зрелости (AI1, гл. 04); единица реестра —"
        " **функция**, а не документ,",
        "> потому что уровень нельзя назначить всей системе одной цифрой.",
        "",
        "## Шкала",
        "",
        "| L | Что значит |",
        "|---|---|",
    ]
    for lv in sorted(LEVEL_NAMES):
        out.append(f"| **L{lv}** | {LEVEL_NAMES[lv]} |")
    out += [
        "",
        "## Сводка",
        "",
        "| Уровень | Функций |",
        "|---|---|",
    ]
    for lv in sorted(by_level):
        out.append(f"| L{lv} — {LEVEL_NAMES[lv]} | **{by_level[lv]}** |")
    out += [
        "",
        "## Реестр",
        "",
        "Уровень определяют ТОЛЬКО явные пути функции. Колонка «упоминаний» —"
        " сколько файлов кода просто",
        "содержат ключевое слово; она уровень НЕ двигает (случайное вхождение —"
        " ключ JSON, имя файла в списке —",
        "поднимало слой с L2 на L3 и посылало читателя дописывать тесты к фантому).",
        "",
        "Колонки **ЗАМЕР** считаются кодом при каждом запуске. Колонки **СУЖДЕНИЕ**"
        " написаны человеком —",
        "они могут быть спорными, и это видно по заголовку. Смешивать их нельзя:"
        " иначе мнение читается как измерение.",
        "",
        "| Функция | L | ЗАМЕР: код | тесты | данных | живых агентов | упоминаний |"
        " `requires verification` | СУЖДЕНИЕ: эффект | вердикт (AI1 гл.06) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    order = {"high": 0, "mid": 1, "low": 2}
    rows.sort(key=lambda r: (-r[1]["level"], order.get(r[2].get("effect", "low"), 3)))
    for s, m, j in rows:
        docs = " · ".join(f"`{d}`" for d in s["docs"]) if s["docs"] else "—"
        out.append(
            f"| **{s['name']}**<br/><sub>{docs}</sub> | L{m['level']} | {m['code']} |"
            f" {m['tests']} | {m['data'] if m['has_data_check'] else '—'} |"
            f" {m['live']} | {m['mentions'] or '—'} | {m['rv'] or '—'} |"
            f" {j.get('effect', '?')} | {j.get('verdict', '?')} |"
        )

    designed = []
    try:
        designed = json.loads(MANIFEST.read_text(encoding="utf-8")).get("designed_architectures", [])
    except (OSError, ValueError):
        pass
    if designed:
        out += ["", "## Спроектированные архитектуры (из `architecture/manifest.json`)", "",
                "| Название | Активация | Сторож |", "|---|---|---|"]
        for d in designed:
            out.append(f"| {d.get('name','?')} | {d.get('activation','?')} | {d.get('watch','')} |")

    out += [
        "",
        "## Что с этим делать",
        "",
        "1. **L4–L5 не трогать** — это работающая система; изменения здесь стоят дорого"
        " и требуют ADR.",
        "2. **L2 с высоким эффектом — «проект подготовки», а не пилот** (AI1 гл. 06:"
        " «высокий эффект при",
        "   нулевой готовности — это проект подготовки»). Записать результат замера и"
        " не строить, пока",
        "   готовность нулевая. Так поступлено с BTC-движком.",
        "3. **L2 с низким эффектом — оставить документом.** Не всякий описанный слой"
        " обязан быть построен;",
        "   вредна не документация, а неотличимость документации от работающего кода.",
        "4. **L3 — долг**: код есть, тестов нет. Самое дешёвое место, где реестр"
        " превращается в работу.",
        "",
        "## Известные расхождения (замер против того, что о себе говорят документы)",
        "",
        "- `docs/00_index.md` утверждает, что набор P3 (23, 24, 25, 26, 39, 40, 41, 42,"
        " 43, 44) «self-label `STUB`».",
        "  Замер: слова `STUB` нет ни в одном из этих файлов. Утверждение индекса не"
        " подтверждено — правим",
        "  не документы, а индекс, и только после того, как решим их судьбу по этому"
        " реестру.",
        "",
    ]
    return "\n".join(out)


def _levels(markdown: str) -> dict[str, int]:
    """name → уровень из таблицы реестра. Разбирает то, что сам же и печатает."""
    out: dict[str, int] = {}
    for m in re.finditer(r"^\| \*\*(?P<name>[^*]+)\*\*<br/><sub>.*?\| L(?P<lv>\d) \|",
                         markdown, re.M):
        out[m.group("name")] = int(m.group("lv"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="не писать файл; код 1, если он разошёлся с замером")
    args = ap.parse_args()

    text = build()
    if args.check:
        # СВЕРЯЕТСЯ ТОЛЬКО УРОВЕНЬ, а не число файлов.
        # Счётчики кода и тестов меняются от любого коммита; сторож, который
        # краснеет на каждом коммите, живёт до первой помехи и потом его
        # отключают (`.claude/rules/deployment.md`: «гасить проверку, которая
        # мешает, — запрещено», значит и делать её мешающей нельзя).
        # Смысловая ложь — только одна: функция, у которой замер даёт L2,
        # записана в файле как построенная. Это и проверяем.
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if not cur:
            print("MATURITY_REGISTER.md отсутствует — сгенерировать", file=sys.stderr)
            return 1
        drift = []
        for name, level in _levels(text).items():
            was = _levels(cur).get(name)
            if was is None:
                drift.append(f"{name}: нет строки в файле (замер: L{level})")
            elif was != level:
                drift.append(f"{name}: в файле L{was}, замер L{level}")
        if drift:
            print("MATURITY_REGISTER.md разошёлся с замером по УРОВНЯМ:", file=sys.stderr)
            for d in drift:
                print("  ·", d, file=sys.stderr)
            return 1
        print(f"OK — уровни совпадают с замером ({len(_levels(text))} функций)")
        return 0

    sys.path.insert(0, str(REPO))
    from spa_core.utils.atomic import atomic_save_text
    atomic_save_text(text, str(OUT))
    print(f"записан {OUT.relative_to(REPO)} ({len(text.splitlines())} строк)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
