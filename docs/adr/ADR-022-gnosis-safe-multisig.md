# ADR-022: Gnosis Safe 2-of-3 Multisig для Family Fund

| Поле            | Значение                                                        |
|-----------------|-----------------------------------------------------------------|
| **Date**        | 2026-06-12                                                      |
| **Status**      | Accepted                                                        |
| **Author**      | Claude (SPA Architect)                                          |
| **Approved by** | Pending — Owner (Yurii) sign-off required                       |
| **MP ref.**     | MP-369 (Gnosis Safe 2-of-3 Family Fund governance)             |
| **ADR number**  | ADR-022                                                         |
| **Supersedes**  | Часть ADR-010 §2.1 Phase 1 (уточняет состав подписантов)       |
| **Blocks**      | MP-403 (Live-пилот $10–50K), go-live 2026-08-01                |

---

## Связанные ADR

| ADR | Тема | Статус |
|-----|------|--------|
| ADR-002 | Go-Live Transfer Rule (READY 7d+) | Accepted |
| ADR-010 | Gnosis Safe Key Management (Zodiac Roles, ключевая политика) | Proposed |
| ADR-011 | Go-Live Security Checklist | Accepted |
| ADR-019 | T2 cap 35% → 50% | Accepted |

> **Примечание:** ADR-010 описывает техническую архитектуру ключей (Zodiac Roles,
> EXECUTOR/GUARDIAN, ротацию). ADR-022 фокусируется на **governance-структуре**
> семейного фонда: составе подписантов, правилах транзакций, интеграции с SPA,
> тайм-локах на управленческие решения.

---

## 1. Context

### 1.1 Текущее состояние (Paper Trading Phase)

SPA работает в режиме **paper trading** с виртуальным капиталом $100,000 USDC.
Все on-chain транзакции отсутствуют. Система доказывает стратегию на реальных
рыночных данных без риска капитала. Go-live запланирован на **~2026-08-01**
(ADR-002: GoLiveChecker READY 7 дней подряд).

До перехода в live система не владеет никакими on-chain ключами. Реальный
execution-домен (`spa_core/execution/`) подготовлен как заготовка.

### 1.2 Проблема: единая точка отказа

Очевидное решение для хранения капитала — один EOA (Externally Owned Account)
под управлением Owner. Это создаёт **критические риски**:

| Вектор угрозы | Вероятность | Последствие при 1-of-1 EOA |
|---|---|---|
| Компрометация hot-ключа (malware, keylogger, утечка) | Средняя | Полная потеря капитала |
| Потеря устройства с ключом | Средняя | Полная блокировка капитала |
| Ошибка в автоматическом коде SPA | Высокая | Несанкционированный вывод |
| Prompt injection через DeFi-данные (ADR-010 §Context) | Низкая | Несанкционированный вывод |
| Смерть или недееспособность Owner | Очень низкая | Блокировка наследования |

Любой из первых трёх сценариев с единым ключом означает **необратимую потерю**.

### 1.3 Правовой контекст: ДПТ и семейный фонд

SPA управляет **семейным фондом** (≤15 инвесторов, все связаны семейными
отношениями или договором простого товарищества). Договор простого товарищества
(ДПТ, Гражданский кодекс Украины, ст. 1132–1143) предусматривает:

- Прозрачное управление совместным имуществом участников.
- Право каждого участника требовать отчёт об использовании средств.
- Недопустимость принятия управленческих решений одним участником по своему
  усмотрению без согласования при наличии конфликта интересов.

Хранение общего капитала на единственном ключе Owner противоречит принципу
прозрачного управления: другие участники не имеют механизма контроля
или co-signing. Multisig кошелёк решает эту проблему технически: любая
транзакция > $1,000 требует второй подписи, фиксируется on-chain и видна
всем участникам в Safe{Wallet} UI.

### 1.4 Почему именно сейчас (перед go-live)

Безопасная инфраструктура должна быть **развёрнута и протестирована до**
первого реального депозита. Ретрофит после go-live опаснее: требует
перевода средств и повышает риск ошибки. Текущий период paper trading —
идеальное время для testnet-деплоя и E2E тестирования.

---

## 2. Decision

### 2.1 Конфигурация Safe

**Gnosis Safe 2-of-3 на Ethereum Mainnet.**

```
Safe threshold:  2-of-3  (любые 2 из 3 подписантов)
Chain:           Ethereum Mainnet (chain_id = 1)
Asset:           USDC (ERC-20, address: 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48)
```

#### Состав подписантов

| Ключ | Роль | Тип | Хранение |
|------|------|-----|----------|
| **Key-A** | Yurii — primary hot wallet | Software EOA | macOS Keychain (`EXECUTOR_PRIVKEY_SPA`), используется SPA автоматически |
| **Key-B** | Yurii — hardware wallet | Ledger Nano X | При Owner, PIN + passphrase, offline до момента подписания |
| **Key-C** | Trust Contact | Software / HW кошелёк доверенного лица | У юриста или доверенного члена семьи |

> **Примечание о Key-C.** Trust Contact — третье лицо вне системы SPA:
> юрист, старший член семьи или другой доверенный человек. Key-C используется
> только при недоступности обоих ключей Owner (аварийное восстановление или
> подтверждение наследования). Trust Contact **не имеет права** инициировать
> транзакции самостоятельно — только соподписывать.

### 2.2 Правило подписей

| Тип операции | Подписей требуется | Инициатор |
|---|---|---|
| Ребалансировка < $1,000 USDC | **1-of-3** (single-sig) | SPA автоматически (Key-A) |
| Ребалансировка ≥ $1,000 USDC | **2-of-3** (multisig) | SPA предлагает tx → Owner подтверждает Key-B |
| Emergency kill-switch (вывод из всех протоколов) | **1-of-3** | Любой из Key-A, Key-B, Key-C |
| Governance change (смена allocator params > 5% allocation) | **2-of-3 + 48h timelock** | Owner → Trust Contact |
| Смена подписанта Safe | **2-of-3** | Owner + Trust Contact |
| Первый депозит в Maple Finance | **2-of-3** | Owner (Key-B) + подтверждение |

Порог $1,000 установлен с учётом текущего размера фонда ($100K). При масштабировании
порог пересматривается новым ADR.

---

## 3. Rationale

### 3.1 Почему Gnosis Safe

Gnosis Safe — **де-факто стандарт** мультиподписи в DeFi:

- **$100B+ TVL** под управлением (крупнейший мультисиг в экосистеме Ethereum).
- **Open source** (MIT/LGPL): аудитируемый код без вендор-локина.
- **Многократно аудирован**: Trail of Bits, G0 Group, Chainalysis, OpenZeppelin.
- **Широкая поддержка**: Safe{Wallet} UI, Gnosis Safe Transaction Service API,
  интеграция в Etherscan, Tenderly, Gnosis Safe SDK.
- **EIP-4337 (Account Abstraction)**: Safe поддерживает AA в будущем —
  возможность газ-субсидий и batch-транзакций без миграции.
- **Safe Transaction Service**: REST API для создания, подписания и
  выполнения мультиподписных транзакций off-chain без требования синхронных
  подписей всех участников.

### 3.2 Почему 2-of-3, а не другие конфигурации

| Конфигурация | Безопасность | Операбельность | Решение |
|---|---|---|---|
| **1-of-1 EOA** | Единая точка отказа | Полная автономия | ✗ Отклонено |
| **1-of-2** | Недостаточная защита | Высокая | ✗ Отклонено |
| **2-of-2** | Deadlock при потере ключа | Плохая | ✗ Отклонено |
| **2-of-3** ← | Потеря 1 ключа не блокирует | Хорошая | ✓ **Выбрано** |
| **3-of-3** | Deadlock при потере 1 из 3 | Плохая | ✗ Отклонено |
| **3-of-5** | Максимальная | Сложная | Phase 2, >$50K |

**2-of-3 оптимально для семейного фонда:**

- Потеря любого одного ключа не блокирует операции (два других достаточны).
- Атакующему нужно скомпрометировать 2 из 3 ключей, хранящихся в разных местах
  разными людьми — значительно сложнее, чем компрометация 1 ключа.
- Trust Contact как третий подписант обеспечивает юридически значимое
  «свидетельство» транзакций и механизм наследования.
- Для повседневного ребаланса < $1K — автоматика через Key-A (single-sig),
  без необходимости Human-in-the-loop.

### 3.3 Альтернативы, которые были рассмотрены

**Вариант A — 1-of-1 EOA Owner.** Отклонён: критические риски (§1.2), нарушение
принципов ДПТ.

**Вариант B — Multisig без Trust Contact (2-of-2: Key-A + Key-B).** Отклонён:
при одновременной недоступности обоих устройств Owner (болезнь, командировка,
несчастный случай) — deadlock. Отсутствует механизм наследования.

**Вариант C — Fully custodial (Coinbase Custody, Fireblocks).** Отклонён:
вендор-локин, KYB/KYC compliance overhead, не соответствует принципу
non-custodial DeFi architecture SPA.

**Вариант D — On-chain timelock без Safe.** Отклонён: нет механизма
multi-party signing, нет экосистемной поддержки для DeFi протоколов.

---

## 4. Consequences

### 4.1 Положительные

- **Устранение single point of failure**: ни один ключ не контролирует фонд
  единолично.
- **Прозрачность**: все транзакции видны в Safe{Wallet} UI и Etherscan.
- **Соответствие ДПТ**: механизм co-signing обеспечивает юридически значимое
  согласование.
- **Ограниченный blast radius**: автоматика SPA работает только с правами
  < $1K single-sig; крупные операции требуют ручного подтверждения.
- **Механизм наследования**: Key-C у Trust Contact позволяет восстановить
  доступ при недееспособности Owner.

### 4.2 Операционные накладные расходы

- Транзакции ≥ $1K требуют **ручного подтверждения** Owner через Safe{Wallet}
  или Ledger Live. Ожидаемое время: 5–15 минут.
- Governance changes проходят **48h timelock** — изменения не вступают в силу
  мгновенно.
- При ребалансировке ≥ $1K SPA генерирует proposal в Safe Transaction Service.
  Owner видит его в Safe{Wallet} UI, подписывает Key-B, транзакция исполняется.

### 4.3 Технические изменения

- `spa_core/execution/safe_tx_builder.py` — новый модуль-скелет для построения
  Safe TX proposals (см. §6).
- `spa_core/paper_trading/cycle_runner.py` — без изменений (paper режим, Safe
  не задействован).
- Переключение live: `SPA_EXECUTION_MODE=live` env var (ADR-002 §Как включить live).

---

## 5. Deployment Plan

### 5.1 Phase 0 — Подготовка (текущий этап, до 2026-07-15)

**USER ACTIONS (должны быть выполнены Owner):**

```
[ ] Купить Ledger Nano X (Key-B hardware wallet)
[ ] Определить Trust Contact (Key-C) и договориться о хранении ключа
[ ] Создать Ethereum кошелёк для Trust Contact (или предоставить адрес его HW wallet)
[ ] Задокументировать адреса Key-A, Key-B, Key-C в docs/keys/pubkeys.txt
    (ТОЛЬКО адреса/pubkeys — никаких приватных ключей в файлах)
```

### 5.2 Phase 1 — Testnet деплой (Sepolia, ~2026-07-15)

```bash
# 1. Открыть Safe{Wallet} на Sepolia
# Перейти: https://app.safe.global → Switch network → Sepolia
# Create new Safe → Add owners: Key-A, Key-B, Key-C → Threshold: 2

# 2. Верифицировать контракт
# После деплоя Safe, Safe{Wallet} UI показывает Safe address
# Верификация: https://sepolia.etherscan.io/address/<SAFE_ADDRESS>#code

# 3. Тестовый депозит (Sepolia USDC faucet)
# https://faucet.circle.com (тестовые USDC на Sepolia)

# 4. Тест мультиподписи
# Создать tx из Key-A → Safe{Wallet} показывает pending tx
# Подписать с Key-B → tx исполняется
# Проверить баланс Sepolia USDC в Safe

# 5. Тест Safe Transaction Service API (Sepolia)
curl https://safe-transaction-sepolia.safe.global/api/v1/safes/<SAFE_ADDRESS>/

# 6. Тест propose через safe_tx_builder.py
SPA_EXECUTION_MODE=live python3 -c "
from spa_core.execution.safe_tx_builder import SafeTxBuilder
builder = SafeTxBuilder(safe_address='<SEPOLIA_SAFE_ADDRESS>', chain_id=11155111)
tx = builder.build_allocate_tx(adapter='aave_v3', amount_usd=100.0)
print('TX proposal:', tx)
"

# 7. E2E тест kill-switch (emergency single-sig)
# Из Key-A → Safe → emergency_withdraw (все протоколы → Safe)
```

### 5.3 Phase 2 — Mainnet деплой (~2026-08-01, перед go-live)

```bash
# 1. Деплой Safe 2-of-3 на Ethereum Mainnet
# https://app.safe.global → Ethereum → Create new Safe
# Owners: Key-A (Yurii hot), Key-B (Yurii Ledger), Key-C (Trust Contact)
# Threshold: 2

# 2. Верификация контракта
# https://etherscan.io/address/<MAINNET_SAFE_ADDRESS>#code

# 3. Добавить подписантов
# Safe{Wallet}: Settings → Owners → Verify все 3 адреса корректны

# 4. Тестовая транзакция $10 USDC (internal tx, Safe → Safe)
# Убедиться что 2-of-3 механизм работает с реальными ключами

# 5. Обновить docs/keys/pubkeys.txt
echo "<MAINNET_SAFE_ADDRESS>" >> docs/keys/pubkeys.txt
# (только адрес, не ключи)

# 6. Записать Safe address в spa_core/execution/safe_tx_builder.py config
# Или через env: SAFE_ADDRESS=0x... (предпочтительно)

# 7. Первый реальный депозит (Owner ACTION, НЕ автоматика)
# Перевести $100K USDC в Safe вручную через Safe{Wallet} UI
# Подтвердить с Key-B (2-of-3 required)

# 8. Активировать live mode
python3 -m spa_core.golive.activate
# Вводит: "I CONFIRM LIVE TRADING"
```

### 5.4 Верификация деплоя (checklist)

```
[ ] Safe address записан в docs/keys/pubkeys.txt
[ ] Safe{Wallet} UI показывает 3 owner'а с правильными адресами
[ ] Threshold = 2
[ ] Тестовая 2-of-3 tx выполнена на Mainnet
[ ] Emergency single-sig (kill-switch) протестирован на Sepolia
[ ] safe_tx_builder.py возвращает корректные proposals (не отправляет!)
[ ] SPA_EXECUTION_MODE=paper режим не трогает Safe API
[ ] GoLiveChecker READY 7 дней подряд (ADR-002)
[ ] Owner подписал раздел "Owner Approval" этого ADR
```

---

## 6. Интеграция с SPA

### 6.1 Paper Trading (текущий режим) — Safe не задействован

```
cycle_runner.py → StrategyAllocator → RiskPolicy gate
                                      ↓
                              виртуальный rebalance-трейд
                              (data/trades.json, is_demo: false)
                              Safe НЕ вызывается
```

`cycle_runner.py` не изменяется. Safe Transaction Service API не вызывается
в paper режиме. `safe_tx_builder.py` в paper режиме является **no-op**:
`SafeTxBuilder.is_paper_mode()` возвращает `True`, все методы возвращают
пустой dict без сетевых вызовов.

### 6.2 Live Mode — все аллокации через Safe

```
cycle_runner.py → StrategyAllocator → RiskPolicy gate (approved=True)
                                      ↓
                              SPA_EXECUTION_MODE=live
                              ↓
                       SafeTxBuilder.build_allocate_tx(adapter, amount_usd)
                              ↓
                     Safe Transaction Service API: proposeTx()
                              ↓
                    amount < $1000 → Key-A автоподпись → executed
                    amount ≥ $1000 → pending в Safe{Wallet} → Owner подтверждает Key-B
```

### 6.3 Env var: SPA_EXECUTION_MODE

```python
# spa_core/adapters/config.py (планируемое добавление)
import os

SPA_EXECUTION_MODE = os.environ.get("SPA_EXECUTION_MODE", "paper")
# Значения: "paper" | "live"
# Default: "paper" (безопасный дефолт — никогда не отправлять реальные tx случайно)

SAFE_ADDRESS = os.environ.get("SAFE_ADDRESS", "")
SAFE_CHAIN_ID = int(os.environ.get("SAFE_CHAIN_ID", "1"))
```

Правило: **`SPA_EXECUTION_MODE=live` устанавливается только вручную** Owner'ом
после прохождения всех условий ADR-002 и подписания §9 этого ADR.
Никакой автоматизации, которая могла бы переключить этот флаг.

### 6.4 Execution Gate в cycle_runner

```python
# Планируемый код в cycle_runner.py (go-live)
from spa_core.adapters.config import SPA_EXECUTION_MODE
from spa_core.execution.safe_tx_builder import SafeTxBuilder

if SPA_EXECUTION_MODE == "live":
    builder = SafeTxBuilder(
        safe_address=SAFE_ADDRESS,
        chain_id=SAFE_CHAIN_ID
    )
    for trade in rebalance_trades:
        if trade["action"] == "allocate":
            proposal = builder.build_allocate_tx(
                adapter=trade["adapter"],
                amount_usd=trade["amount_usd"]
            )
            # proposal — dict для Safe TX Service API; НЕ исполняется здесь
            # safe_tx_service_client.propose(proposal)  ← отдельный модуль
        elif trade["action"] == "withdraw":
            proposal = builder.build_withdraw_tx(
                adapter=trade["adapter"],
                amount_usd=trade["amount_usd"]
            )
else:
    # paper mode: виртуальный трейд, Safe не вызывается
    _record_virtual_trade(trade)
```

---

## 7. Governance Rules

### 7.1 Transaction Thresholds

| Операция | Порог | Подписей | Timelock | Примечание |
|---|---|---|---|---|
| Routine rebalance | < $1,000 | 1-of-3 (Key-A auto) | Нет | SPA автоматически |
| Large rebalance | ≥ $1,000 | 2-of-3 | 24h | Owner подтверждает Key-B |
| New protocol whitelist | Любой | 2-of-3 | 48h | ADR required |
| Allocation policy change > 5% | Любой | 2-of-3 | **48h** | ADR required |
| Emergency kill-switch | Любой | 1-of-3 | **0h** | Немедленно |
| Смена состава Safe owners | Любой | 2-of-3 | 72h | Trust Contact уведомлён |
| Вывод средств из Safe (полный) | Любой | 2-of-3 | 72h | Не автоматизировано |

### 7.2 Governance Changes — 48h Timelock (расширение ADR-019)

ADR-019 принял повышение T2 cap с 35% до 50%. Начиная с ADR-022,
**любое изменение allocation parameters > 5% AUM** проходит дополнительную
защиту:

```
Правило: Если abs(new_param - old_param) > 5% от AUM threshold →
         изменение требует 2-of-3 multisig + 48h timelock через Safe Delay Module

Примеры, требующие timelock:
  - T2 cap: 50% → 56%                       ✓ требует timelock
  - Per-protocol cap: 20% → 26%             ✓ требует timelock
  - TVL floor: $5M → $2M                    ✓ требует timelock
  - Kill-switch drawdown threshold: 5% → 8% ✓ требует timelock

Примеры, НЕ требующие timelock:
  - APY bounds adjustment (1%→2% min)       ✗ не allocation parameter
  - Cash buffer: 5% → 6%                    ✗ изменение < 5%
```

**Реализация timelock**: Zodiac Delay Module (см. ADR-010 §2.3). Минимальный
delay 48h не снижается без нового ADR. Операции GUARDIAN (kill-switch) — без
timelock (асимметрия: STOP мгновенный, START — с задержкой).

### 7.3 Emergency Kill-Switch (приоритет над всеми правилами)

При срабатывании RiskPolicy drawdown gate (≥5% portfolio drawdown) или ручном
решении Owner:

```
1. cycle_runner обнаруживает drawdown ≥ 5% OR kill_switch_flag = True
2. builder.build_withdraw_tx() для каждого протокола (all positions → 0)
3. Транзакция single-sig (Key-A, without Safe threshold) через Zodiac GUARDIAN role
   (ADR-010 §2.2: GUARDIAN = 1-of-2 hw wallets для мгновенного STOP)
4. Все средства возвращаются в Safe (USDC на Safe balance)
5. SPA_EXECUTION_MODE автоматически не сбрасывается — Owner решает вручную
```

Критический принцип: **kill-switch не требует 2 подписей** — замедление
emergency exit недопустимо при активном drawdown.

---

## 8. Safe Transaction Service — API Integration

### 8.1 Endpoints

| Сеть | Base URL |
|---|---|
| Ethereum Mainnet | `https://safe-transaction-mainnet.safe.global` |
| Sepolia (testnet) | `https://safe-transaction-sepolia.safe.global` |

### 8.2 Основные эндпоинты

```bash
# Проверить Safe
GET /api/v1/safes/{safe_address}/

# Предложить транзакцию (propose)
POST /api/v1/safes/{safe_address}/multisig-transactions/
Content-Type: application/json
Body: {
  "to": "<protocol_contract>",
  "value": "0",
  "data": "<encoded_function_call>",
  "nonce": <next_nonce>,
  "safeTxGas": 0,
  "baseGas": 0,
  "gasPrice": "0",
  "gasToken": "0x0000000000000000000000000000000000000000",
  "refundReceiver": "0x0000000000000000000000000000000000000000",
  "contractTransactionHash": "<safe_tx_hash>",
  "sender": "<key_a_address>",
  "signature": "<key_a_signature>",
  "origin": "SPA v4.68"
}

# Получить pending транзакции (Owner видит в UI)
GET /api/v1/safes/{safe_address}/multisig-transactions/?executed=false

# Подписать существующую транзакцию (Key-B через Safe{Wallet})
POST /api/v1/multisig-transactions/{safe_tx_hash}/confirmations/
```

### 8.3 Команды для деплоя Safe

```bash
# Деплой через Safe{Wallet} UI (рекомендуемый путь):
# https://app.safe.global → Create new Safe

# Программный деплой через Safe SDK (Node.js):
# npm install @safe-global/protocol-kit @safe-global/api-kit
npx ts-node -e "
const { SafeFactory } = require('@safe-global/protocol-kit');
const factory = await SafeFactory.create({ ethAdapter });
const safe = await factory.deploySafe({
  safeAccountConfig: {
    owners: ['<KEY_A>', '<KEY_B>', '<KEY_C>'],
    threshold: 2
  }
});
console.log('Safe deployed at:', safe.getAddress());
"

# Верификация деплоя:
cast call <SAFE_ADDRESS> "getOwners()(address[])" --rpc-url https://eth.llamarpc.com
cast call <SAFE_ADDRESS> "getThreshold()(uint256)"  --rpc-url https://eth.llamarpc.com
```

### 8.4 Мониторинг

```bash
# Проверить баланс Safe
cast call 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  "balanceOf(address)(uint256)" <SAFE_ADDRESS> \
  --rpc-url https://eth.llamarpc.com

# Pending транзакции
curl https://safe-transaction-mainnet.safe.global/api/v1/safes/<SAFE_ADDRESS>/multisig-transactions/?executed=false

# Просмотр в UI
# https://app.safe.global/eth:<SAFE_ADDRESS>
```

---

## 9. Owner Approval

```
Дата approval:      _______________
Owner подпись:      Yurii Kulieshov

Safe address (Mainnet):   0x_______________________________________
Key-A address (hot):      0x_______________________________________
Key-B address (Ledger):   0x_______________________________________
Key-C address (Trust):    0x_______________________________________
Deployment date:          _______________
Testnet E2E passed:       _______________

Trust Contact name:        ___________________________________
Trust Contact confirmed:  [ ] Yes — он/она получил Key-C и понимает правила
```

---

## 10. References

- [Gnosis Safe Documentation](https://docs.safe.global/)
- [Safe Transaction Service API](https://safe-transaction-mainnet.safe.global/)
- [Safe SDK: @safe-global/protocol-kit](https://github.com/safe-global/safe-core-sdk)
- [Zodiac Roles Module](https://zodiac.wiki/)
- [ADR-002: Go-Live Transfer Rule](./ADR-002-golive-transfer-rule.md)
- [ADR-010: Gnosis Safe Key Management](./ADR-010-gnosis-safe-key-management.md)
- [ADR-011: Go-Live Security Checklist](./ADR-011-go-live-security-checklist.md)
- [ADR-019: T2 cap 35% → 50%](./ADR-019-t2-cap-increase.md)
- [`spa_core/execution/safe_tx_builder.py`](../../spa_core/execution/safe_tx_builder.py)
- [`spa_core/risk/policy.py`](../../spa_core/risk/policy.py) — RiskPolicy v1.0
- [`spa_core/golive/activate.py`](../../spa_core/golive/activate.py)
- `docs/TOKEN_ROTATION_RUNBOOK.md`
- MASTER_PLAN_v1.md §4 (Phase 4: Execution Infrastructure)
- GRAND_VISION_v1.md §6 (Bus Factor Risk)

---

*Создан: 2026-06-12. MP-369. SPA Sprint v4.68.*
