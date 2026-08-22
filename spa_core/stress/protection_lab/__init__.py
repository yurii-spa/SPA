"""Protection Lab — historical crisis replay + synthetic stress harness (advisory).

# LLM_FORBIDDEN

Зачем этот пакет существует
---------------------------
Владелец (задание 2026-08-22, ветка claude/defi-protection-lab-stress-tests):
прогнать книгу SPA через КАЖДУЮ крупную историческую катастрофу крипторынка
(Terra, Black Thursday, FTX, USDC-депег, 10.10.2025 …) и через синтетические
сценарии — и честно ответить: когда защита увидела бы опасность, что она
сделала бы, что из этого РЕАЛЬНО исполнилось бы, сколько денег потеряли бы мы
и сколько — пассивный держатель той же книги.

Чем это отличается от stress_engine.py (MP-112, v1)
---------------------------------------------------
v1 копирует пороги защиты константами (`_KILL_SWITCH_DD = 0.05` — одноуровневый,
дрейф против ADR-034/048). Этот пакет порогов НЕ ЗНАЕТ: лестница дроудауна
классифицируется настоящим `spa_core.governance.kill_switch.classify_drawdown_pct`,
депег — настоящим `RiskPolicy.check_stablecoin_depeg`. Если governance-слой
изменится, Protection Lab изменится вместе с ним автоматически.

Гарантии (guardrails)
---------------------
- ADVISORY ONLY: пакет никогда не двигает капитал, не пишет в money-path файлы
  и не импортируется из runtime-цикла. Единственная запись — отчёты в
  ``data/protection_lab/`` через ``atomic_save`` (только из CLI).
- Stdlib only, детерминизм: ни сети, ни часов (`now` не читается — все даты
  приходят из сценария), ни случайности.
- LLM запрещён: сценарий → результат считается только этим движком.
- No look-ahead: решение дня T видит рынок ТОЛЬКО по конец дня T-1
  (дневной цикл SPA; внутридневные каскады бьют раньше, чем цикл проснётся —
  это свойство системы, и лаборатория обязана его показывать, а не прятать).
- Отказ исполнения ≠ защита: верное решение выйти из замороженного протокола
  записывается как execution failure, а не как спасённые деньги.

Контракт данных
---------------
Сценарии — JSON-файлы в ``scenarios/`` (git-tracked, схема в ``schema.py``):
факты с провенансом (timeline / sources / confidence) отделены от машинной
части ``replay`` (шоки по дням). Синтетика (``synthetic.py``) строит те же
структуры — один движок на оба режима.
"""
from __future__ import annotations

IS_ADVISORY = True
RESEARCH_ONLY = True

from .schema import (  # noqa: E402
    Scenario,
    ReplaySpec,
    Shock,
    load_scenario,
    load_all_scenarios,
    validate_scenario_dict,
    SCENARIOS_DIR,
)
from .replay import (  # noqa: E402
    BookPosition,
    DEFAULT_BOOK,
    ProtectionReport,
    ReplayRun,
    run_replay,
)
from .synthetic import SyntheticSpec, build_synthetic_scenario, ADVERSARIAL_SPECS  # noqa: E402
from .report import format_report, format_summary_table  # noqa: E402

__all__ = [
    "IS_ADVISORY",
    "RESEARCH_ONLY",
    "Scenario",
    "ReplaySpec",
    "Shock",
    "load_scenario",
    "load_all_scenarios",
    "validate_scenario_dict",
    "SCENARIOS_DIR",
    "BookPosition",
    "DEFAULT_BOOK",
    "ProtectionReport",
    "ReplayRun",
    "run_replay",
    "SyntheticSpec",
    "build_synthetic_scenario",
    "ADVERSARIAL_SPECS",
    "format_report",
    "format_summary_table",
]
