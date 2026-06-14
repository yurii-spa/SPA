# ARCHITECTURE.md — Архитектура системы SPA
> **Версия:** 1.0 | **Дата:** 2026-06-13
> Читать при создании новых модулей, рефакторинге, onboarding новых агентов.

---

## 🏗️ СТРУКТУРА МОДУЛЕЙ

```
spa_core/
├── adapters/          READ-ONLY: Protocol adapters (Aave, Compound, Morpho, etc.)
│   ├── __init__.py    ADAPTER_REGISTRY — реестр всех адаптеров
│   ├── defillama_feed.py  DeFiLlama APY/TVL feed (cache TTL 300s)
│   └── config.py      Конфигурация через env
│
├── analytics/         READ-ONLY: 313+ аналитических модулей (advisory, no side effects)
│   └── test_*.py      НЕЛЬЗЯ — тесты в spa_core/tests/
│
├── tests/             Тесты для analytics/ (548+ файлов)
│   └── test_<module>.py  Соответствие: analytics/<module>.py → tests/test_<module>.py
│
├── allocator/         StrategyAllocator — целевые веса (TVL floor, T2 cap)
│   └── allocator.py
│
├── paper_trading/     Ядро paper-trading цикла
│   ├── cycle_runner.py        MAIN: ежедневный цикл (launchd 08:00)
│   ├── engine.py              Движок расчётов
│   ├── golive_checker.py      26 критериев GoLive (статус: 16/26 pass)
│   ├── gap_monitor.py         Непрерывность трека
│   ├── multi_strategy_runner.py  Tournament: параллельный запуск S0-S13
│   └── drawdown_analytics.py  MP-115
│
├── strategies/        Tournament стратегии S0–S13
│   ├── strategy_registry.py
│   └── tournament_evaluator.py  Sharpe/Calmar/Ulcer/Rachev
│
├── risk/              КРИТИЧЕСКИЙ ДОМЕН: LLM FORBIDDEN
│   ├── policy.py      RiskPolicy v1.0 (детерминированный)
│   └── versions/      Snapshots при каждом изменении
│
├── execution/         КРИТИЧЕСКИЙ ДОМЕН: НЕ импортировать из read-only кода
│   └── ...
│
├── golive/            Активация live trading
│   └── activate.py    Требует ввода "I CONFIRM LIVE TRADING"
│
└── family_fund/       Инвесторский портал
    ├── registry.py
    ├── pnl_attribution.py
    ├── telegram_blast.py
    └── http_server.py (port 8765, pure stdlib)
```

---

## 📐 ПАТТЕРН ANALYTICS-МОДУЛЯ

Все модули в `spa_core/analytics/` следуют единому паттерну:

```python
# spa_core/analytics/my_module.py
"""
MyModule — краткое описание что делает модуль
Advisory only. No side effects. Pure stdlib.
"""
import json
import os
import datetime
from typing import Dict, Any

MODULE_NAME = "my_module"
LOG_PATH = os.path.join(os.path.dirname(__file__), "../../data/my_module_log.json")
LOG_LIMIT = 100

def analyze(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Основная функция анализа.
    
    Returns:
        {
            "status": "OK" | "WARNING" | "ERROR",
            "verdict": "HUMAN_READABLE_VERDICT",
            "details": {...},
            "timestamp": "ISO8601"
        }
    """
    # ... логика ...
    return {
        "status": "OK",
        "verdict": "VERDICT_STRING",
        "details": {},
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }

def _write_log(result: Dict[str, Any]) -> None:
    """Атомарная запись в ring-buffer лог."""
    try:
        with open(LOG_PATH) as f:
            log = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log = {"entries": []}
    
    entries = log.get("entries", [])
    entries.append(result)
    if len(entries) > LOG_LIMIT:
        entries = entries[-LOG_LIMIT:]
    log["entries"] = entries
    
    tmp = LOG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LOG_PATH)

if __name__ == "__main__":
    import sys
    # CLI: --check (default, no write) | --run (compute + write)
    write_mode = "--run" in sys.argv
    result = analyze({})
    if write_mode:
        _write_log(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)  # Always exit 0 (advisory module)
```

**CLI-интерфейс (обязателен для всех модулей):**
```bash
python3 -m spa_core.analytics.<module> --check   # вычислить, не писать
python3 -m spa_core.analytics.<module> --run     # вычислить + записать в data/
```

---

## 🧪 СТРУКТУРА ТЕСТОВ

```python
# spa_core/tests/test_my_module.py
import unittest
from spa_core.analytics.my_module import analyze

class TestMyModule(unittest.TestCase):
    
    def test_normal_case(self):
        result = analyze({"key": "value"})
        self.assertEqual(result["status"], "OK")
        self.assertIn("verdict", result)
        self.assertIn("details", result)
        self.assertIn("timestamp", result)
    
    def test_edge_case_empty_input(self):
        result = analyze({})
        self.assertIn(result["status"], ["OK", "WARNING", "ERROR"])
    
    # ... минимум 65 тестов ...

if __name__ == "__main__":
    unittest.main()
```

**Запуск тестов:**
```bash
python3 -m unittest spa_core.tests.test_my_module -v
python3 -m unittest discover -s spa_core/tests -p "test_*.py" -v
```

---

## 📊 PUSH-СИСТЕМА

```
scripts/
├── push_v468.sh        Самый старый в репо
├── push_v469.sh
├── ...
├── push_v680.sh        Последний (2026-06-13)
├── push_v680b.sh       Если было 2 спринта на v680
├── run_all_pushes.sh   Мастер-скрипт (запускает все unlogged)
│   ├── .push_log       Лог успешных пушей
│   └── .push_failed    Лог неудачных
└── push_all_session.sh (устаревший, использовать run_all_pushes.sh)
```

**push_to_github.py** — главный инструмент:
```bash
# Один файл:
python3 push_to_github.py --file /abs/path/file.py --message "feat: ..."

# Несколько файлов:
python3 push_to_github.py --files /path/a.py /path/b.json --message "feat: ..."

# Dry-run (без пуша):
python3 push_to_github.py --files ... --message "..." --dry-run
```

**ВАЖНО:** Все пути — абсолютные. Относительные схлопываются в basename.

---

## 📋 KANBAN.JSON — СХЕМА И ПРАВИЛА

```json
{
    "last_updated": "YYYY-MM-DD",
    "updated_by": "sprint vX.YZ",
    "sprint_current": "vX.YZ",
    "sprint_next": "vX.YZ-1",
    "done_count": 553,
    "real_track_start": "2026-06-10",
    "golive_decision_date": "2026-08-01",
    
    "columns": {
        "backlog": [...],     // Задачи к выполнению (P0/P1/P2)
        "in_progress": [...], // Задачи в работе (обычно пусто)
        "review": [...],      // Задачи на ревью
        "done": [...]         // Выполненные задачи (371+)
    },
    
    "tasks": [...],           // Дополнительный массив (24 задачи)
    "sprint_log": [...],      // Лог спринтов (последние 5)
    
    "_vNNN_dispatch_note": "...",  // Заметки спринтов (НЕ удалять, не читать в цикле)
    "_vNNN_reconcile_note": "..."  // Заметки о reconcile
}
```

**Правила обновления KANBAN:**
1. Перечитать файл с диска прямо перед записью (не кэш из начала сессии)
2. `done_count` — аддитивный инкремент, не фиксированное значение
3. Атомарная запись (tmp + os.replace)
4. При параллельном обновлении: допустимое расхождение ±5

---

## 🔄 ПАРАЛЛЕЛЬНЫЙ PIPELINE

Стандартная конфигурация: **2 спринта в параллели**.

```
Agent A (sprint vX.80)  ──►  push_v680.sh
Agent B (sprint vX.80b) ──►  push_v680b.sh
```

Оба агента:
- Работают на разных MP-задачах
- Обновляют KANBAN независимо (аддитивно)
- Создают разные push-скрипты

---

## 🏷️ ИМЕНОВАНИЕ СПРИНТОВ

```
Sprint naming: vMAJOR.MINOR
  MAJOR: инкрементируется при крупных milestone'ах
  MINOR: инкрементируется с каждым спринтом

Текущий: v6.80 (по KANBAN.json)

Dispatch notes keys: _v680_dispatch_note, _v681_dispatch_note, ...
```

---

## 🔐 DOMAINS ISOLATION

```
read-only domain:                    execution domain:
  adapters/                             execution/
  analytics/                            (НЕ импортировать из read-only)
  paper_trading/ (частично)
  family_fund/

Граница: spa_core/execution/ — ЗАПРЕЩЁН для импорта из read-only кода
         data/adapter_status.json — принадлежит execution domain
```

---

## 💰 PAPER TRADING CYCLE (launchd 08:00)

```
cycle_runner.py --verbose
  Step 1: Adapter orchestrator → snapshot APY/TVL
  Step 2: multi_strategy_runner → S0–S13 tournament
  Step 2b: EmergencyBreakers (EB-01..EB-05) → CLEAR/PAUSE/HALT
  Step 3: StrategyAllocator → target allocation
  Step 4: RiskPolicy gate → approve/reject
  Step 5: delta > threshold → virtual rebalance trade
  Step 6: Yield accrual on positions
  Step 7: Write equity_curve_daily.json, current_positions.json
  Step 8: GoLiveChecker → golive_status.json (26 criteria)
  Step 9: promotion_engine.py → advisory promotions
```

---

*Источник: docs/governance/ARCHITECTURE.md v1.0 (2026-06-13)*
