# BaseAnalytics Migration Plan

_Создан: 2026-06-19 | MP-1405 | Sprint v10.21_

---

## Background

**Аудит v10.19 обнаружил критический технический долг:**
- `spa_core/analytics/` содержит **728 файлов** (727 + `__init__.py`)
- **0 из 728** модулей наследуют `BaseAnalytics`
- **597 файлов с классами** нуждаются в миграции
- Каждый модуль реализует свою версию `save()`/`load()`/атомарной записи — дублирование кода тысячами строк

**Цель:** устранить дублирование персистенции данных через централизацию в `BaseAnalytics`.

---

## What BaseAnalytics Provides

`spa_core/base.py` — `BaseAnalytics(ABC)`:

| Метод | Описание |
|---|---|
| `__init__(base_dir=".")` | Устанавливает `self.base_dir` — корень для путей |
| `_path(relative)` | `os.path.join(self.base_dir, relative)` — абсолютный путь из относительного |
| `_ensure_dir(path)` | `os.makedirs(dirname, exist_ok=True)` — создаёт директорию |
| `save(data=None, path=None)` | Атомарное сохранение через `atomic_save()` в `OUTPUT_PATH` |
| `load(path=None)` | Загрузка из `OUTPUT_PATH` через `atomic_load()` |
| `to_dict()` | **Абстрактный** — обязателен к реализации в каждом подклассе |

Атомарность обеспечивается `spa_core/utils/atomic.py` (`atomic_save`, `atomic_load`) —
используется `tempfile.mkstemp + os.replace`, никогда не оставляет частичных записей.

---

## Migration Strategy

**Принцип: не ломать существующий код.**

Фазовый подход: миграция в порядке убывания тестового покрытия и количества импортов.
Модуль без тестов — **НЕ мигрируется** до появления тестов (риск регрессии).

```
Фаза 1 (v10.21-22) — топ-5 наиболее импортируемых с тестами
Фаза 2 (v10.23-30) — пакетная миграция по категориям (~60/неделя)
Фаза 3 (v10.31+)  — остаток + автоматическая верификация
```

---

## Migration Pattern

### До миграции (типичный модуль):

```python
import json, os
from pathlib import Path

DATA_FILE = Path("data/myfile.json")
MAX_ENTRIES = 100

class MyAnalytics:
    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file

    def save_result(self, result) -> None:
        """Ручная реализация: tmp + os.replace (дублируется в 597 файлах)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        existing.append(result)
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self):
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
```

### После миграции (Phase 1 — минимальная, без регрессии):

```python
from spa_core.base import BaseAnalytics

class MyAnalytics(BaseAnalytics):
    OUTPUT_PATH = "data/myfile.json"    # <-- добавляется

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        super().__init__()              # <-- добавляется (base_dir=".")
        self.data_file = data_file

    def to_dict(self) -> dict:          # <-- добавляется (ABC требует)
        return {"history": self.load_history()}

    # Существующие методы остаются без изменений:
    def save_result(self, result) -> None: ...
    def load_history(self): ...
```

**Phase 1 правило:** только добавляем `(BaseAnalytics)`, `OUTPUT_PATH`, `super().__init__()`, `to_dict()`.
Удаление дублирующего save/load кода — Phase 2 и 3 (после верификации через тесты).

---

## Phase 1 — Top 10 Priority Modules (v10.21-22)

Приоритет по: (импорты в продовом коде) × (наличие тестов).

| # | Модуль | Импортов | Тест-файлов | Phase 1 |
|---|---|---|---|---|
| 1 | `apy_milestone_tracker` | 6 | 1 (50 тестов) | ✅ Мигрировать |
| 2 | `protocol_risk_scorer` | 4 | 1 | ✅ Мигрировать |
| 3 | `liquidity_stress_simulator` | 4 | 1 | ✅ Мигрировать |
| 4 | `rebalance_trigger_engine` | 3 | 1 | ✅ Мигрировать |
| 5 | `apy_tracker` | 2 (+2 api) | 2 | ✅ Мигрировать |
| 6 | `market_regime_gate` | 5 | 1 | Phase 2 |
| 7 | `defi_cycle_phase_detector` | 11 | 1 | Phase 2 |
| 8 | `protocol_liquidity_depth_analyzer` | 7 | 1 | Phase 2 |
| 9 | `conc_lp_il_model` | 5 | 1 | Phase 2 |
| 10 | `rs002_live_apy_engine` | 5 | 1 | Phase 2 |

**Не мигрируются без тестов:** `strategy_rs002_tracker` (6 импортов, 0 тестов),
`strategy_rs001_tracker` (4 импорта, 0 тестов) — сначала написать тесты.

---

## Phase 2 — Batch Migration by Category (v10.23-30)

Пакетная миграция (~60 модулей в спринт) по функциональным категориям:

| Категория | Примеры | Sprint |
|---|---|---|
| APY & Yield analytics | `apy_forecaster`, `apy_volatility_forecaster`, `apy_normalization_engine` | v10.23 |
| Protocol scoring & risk | `protocol_upgrade_risk_assessor`, `protocol_insider_activity_monitor` | v10.24 |
| Portfolio & allocation | `capital_efficiency_tracker`, `capital_rotation_advisor` | v10.25 |
| Liquidity & slippage | `slippage_model_advisor`, `slippage_simulator`, `bridge_risk_assessor` | v10.26 |
| Strategy & tournament | `rs001_live_apy_engine`, `rs002_live_apy_engine`, `signal_aggregator` | v10.27 |
| Reporting & benchmarks | `benchmark_tracker`, `yield_benchmark_comparator` | v10.28 |
| Market & regime | `market_regime_gate`, `volatility_regime_detector` | v10.29 |
| Remaining | Все остальные | v10.30 |

---

## Phase 3 — Automated Verification (v10.31+)

После завершения Phase 2 — автоматическая верификация соответствия:

```bash
# Проверить процент унаследовавших BaseAnalytics:
python3 -m spa_core.paper_trading.analytics_conformance --category inherited

# Ожидаемый вывод после Phase 3:
# Inherited BaseAnalytics: 597/597 (100.0%)
# Missing to_dict(): 0
# Missing OUTPUT_PATH: 0
```

Создать `spa_core/paper_trading/analytics_conformance.py` в v10.31 —
сканирует все классы в `spa_core/analytics/` и отчитывается о conformance.

---

## Verification Per Phase

После каждой фазы запускать:

```bash
# Тесты мигрированных модулей:
python3 -m pytest spa_core/tests/test_apy_tracker.py tests/test_apy_milestone_tracker.py \
  spa_core/tests/test_protocol_risk_scorer.py spa_core/tests/test_liquidity_stress_simulator.py \
  spa_core/tests/test_rebalance_trigger_engine.py -v

# Verify imports:
python3 scripts/verify_phase1_migration.py

# Интеграционный smoke-test:
python3 -m spa_core.paper_trading.cycle_runner --verbose 2>&1 | tail -20
```

---

## Risk Mitigation

1. **ABC enforcement** — `to_dict()` абстрактный: если забыть реализовать,
   `TypeError` при первом инстанциировании (fail-fast в тестах).
2. **Backward compatibility** — все существующие методы (`save_scores()`, `load_history()`,
   `save_result()` и т.д.) остаются в Phase 1, удаляются только в Phase 3 после верификации.
3. **super().__init__()** — вызывается без аргументов (использует `base_dir="."` по умолчанию).
   Классы с `data_file: Path` — сохраняют свою параметризацию без изменений.
4. **Atomic writes** — `BaseAnalytics.save()` использует `atomic_save()` из `spa_core/utils/atomic.py`.
   До Phase 3 существующие кастомные методы сохранения остаются и сохраняют атомарность.

---

## Timeline

| Sprint | Работа | Модулей |
|---|---|---|
| v10.21 | MP-1405: этот документ + тест плана | — |
| v10.22 | MP-1406: Phase 1 — топ-5 модулей | 5 |
| v10.23-30 | MP-1407-1414: Phase 2 пакетная миграция | ~480 |
| v10.31 | MP-1415: analytics_conformance.py + Phase 3 старт | — |
| v10.32-40 | MP-1416-1424: Phase 3 — остаток | ~112 |
| v10.41 | MP-1425: финальный аудит 597/597 | — |

**Общий объём:** ~20 спринтов для полной миграции 597 файлов.

---

_Источник истины: `KANBAN.json` (MP-1405, MP-1406, …). Обновляется в конце каждого спринта._
