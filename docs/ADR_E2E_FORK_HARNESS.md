# ADR: E2E Fork-Harness (MP-401)

**Status:** Accepted  
**Date:** 2026-06-12  
**Author:** Claude (MP-401)  
**Scope:** `spa_core/testing/fork_harness.py`

---

## Контекст

SPA имеет execution layer (`spa_core/execution/`), который будет выполнять реальные
on-chain транзакции после go-live (ADR-002). До получения RPC-ключей (MP-017) и
до завершения 30-дневного paper-track нет возможности запустить E2E тесты против
реального mainnet. Нужен механизм, который:

1. Работает **всегда** (без внешних зависимостей) — для CI в paper-period.
2. Легко переключается в **live режим** после MP-017 без изменения интерфейса.
3. Не нарушает invariant: **LLM_FORBIDDEN** в risk/execution/monitoring.

---

## Решение: Anvil (Foundry) + два режима

### Почему Anvil

| Критерий | Anvil | Hardhat | Ganache |
|---|---|---|---|
| Форк mainnet | ✓ (--fork-url) | ✓ | ✓ |
| Детерминированность | ✓ (--fork-block-number) | ✓ | частично |
| Скорость | ~очень быстро | медленнее | медленнее |
| Зависимости | один бинарник | Node.js + npm | Node.js + npm |
| Поддержка | Foundry (активно) | Nomic Foundation | устарел |
| stdlib-совместимость | subprocess (stdlib) | subprocess | subprocess |

Anvil запускается одним бинарником без внешних npm-зависимостей — совместимо с
требованием «только stdlib» в runtime-коде SPA. Управление через `subprocess.Popen`.

---

## Два режима

### Режим 1: dry-run (всегда доступен)

```
python3 -m spa_core.testing.fork_harness --dry-run [--data-dir data]
```

- **Нет сетевых вызовов.** Только читает JSON-файлы из `data/`.
- **Нет subprocess.** Anvil не нужен.
- Проверяет согласованность состояния системы по файлам:
  `adapter_orchestrator_status.json`, `target_allocation.json`,
  `kill_switch_status.json`, `current_positions.json`.
- Пишет результат в `data/fork_harness_status.json` атомарно.
- **Используется в CI сейчас** (paper-period, до MP-017).

### Режим 2: live (после MP-017)

```
python3 -m spa_core.testing.fork_harness --live \
  --rpc-url $MAINNET_RPC_URL \
  --fork-block 19000000 \
  --port 8545
```

- Запускает `anvil --fork-url $RPC --fork-block-number N --port 8545`.
- Ждёт старта (таймаут 10 с).
- Запускает сценарии с реальными EVM-вызовами через форк mainnet.
- SIGTERM при завершении (контекстный менеджер `AnvilProcess.__exit__`).
- **Fallback:** если anvil не найден или RPC не задан — автоматически переключается
  в dry-run с пометкой `mode="dry-run (live unavailable)"`.

---

## Архитектура кода

```
spa_core/testing/fork_harness.py
├── ForkConfig          — dataclass конфигурации (rpc_url, port, block, etc.)
├── AnvilProcess        — subprocess менеджер; start/stop/is_running
│                         dry-run если rpc_url="" или anvil не найден
├── ForkScenario        — базовый класс сценария
│   ├── run_dry(data_dir)  → {ok, checks, notes, scenario}
│   └── run_live(...)      → делегирует в run_dry до MP-017
├── AaveWithdrawScenario    — Aave V3: наличие позиции, TVL≥$5M, статус ok
├── AllocationRebalanceScenario — target_allocation: cash≥5%, T2≤35%
├── KillSwitchScenario  — kill_switch: triggered=False; позиции если triggered
├── run_e2e_dry(data_dir, scenarios) → dict; пишет fork_harness_status.json
└── run_e2e_live(config, data_dir, scenarios) → dict; управляет AnvilProcess
```

---

## Безопасность

- **LLM_FORBIDDEN:** `fork_harness.py` — тестовый/аналитический код, не risk/execution/monitoring.
  LLM-вызовы в нём не предусмотрены и не используются.
- **Read-only:** dry-run сценарии только читают файлы. Запись только в
  `data/fork_harness_status.json` (атомарно).
- **No secrets in code:** RPC URL передаётся через CLI-флаг `--rpc-url`,
  не хардкодится. В CI использовать переменные среды (не в коде).

---

## Интеграция в CI (после go-live)

После получения RPC-ключей (MP-017) добавить в CI-пайплайн:

```yaml
# .github/workflows/e2e.yml
- name: Install Foundry
  uses: foundry-rs/foundry-toolchain@v1

- name: Run E2E fork-harness
  env:
    MAINNET_RPC_URL: ${{ secrets.MAINNET_RPC_URL }}
  run: |
    python3 -m spa_core.testing.fork_harness \
      --live \
      --rpc-url "$MAINNET_RPC_URL" \
      --fork-block 21000000 \
      --data-dir data
```

**До MP-017 (сейчас):**
```yaml
- name: Run E2E fork-harness (dry-run)
  run: python3 -m spa_core.testing.fork_harness --dry-run --data-dir data
```

---

## Добавление новых сценариев

```python
from spa_core.testing.fork_harness import ForkScenario, DEFAULT_SCENARIOS

class MyNewScenario(ForkScenario):
    name = "my_scenario"
    description = "..."
    required_contracts = ["MyContract"]

    def run_dry(self, data_dir):
        checks = []
        # ... проверки по JSON-файлам ...
        return {"ok": True, "checks": checks, "notes": [], "scenario": self.name}

    def run_live(self, data_dir, rpc_url, port=8545):
        # ... реальные EVM-вызовы после MP-017 ...
        pass
```

Добавить экземпляр в `DEFAULT_SCENARIOS` или передать в `run_e2e_dry(scenarios=[...])`.

---

## Альтернативы рассмотренные и отклонённые

| Альтернатива | Причина отклонения |
|---|---|
| Tenderly fork API | Платная, требует внешний сервис, нет в stdlib |
| Hardhat Node | Требует Node.js + npm — противоречит stdlib-правилу |
| Mock/monkey-patch | Не проверяет реальный on-chain state |
| Mainnet testnet (Sepolia) | Нет USDC liquidity, не форк mainnet |

---

## Связанные документы

- `MASTER_PLAN_v1.md` → MP-401 (E2E fork-harness)
- `MASTER_PLAN_v1.md` → MP-017 (RPC-ключи — prerequisite для live режима)
- `docs/adr/ADR-002-golive-transfer-rule.md` (go-live условия)
- `spa_core/execution/` (execution layer, который тестирует harness)
- `spa_core/risk/policy.py` (RiskPolicy v1.0 — лимиты проверяемые в сценариях)

---

*Обновлено: 2026-06-12 (MP-401 scaffold)*
