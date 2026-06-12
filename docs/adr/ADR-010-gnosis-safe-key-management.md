# ADR-010: Gnosis Safe Key Management Architecture

| Field           | Value                                               |
|-----------------|-----------------------------------------------------|
| **Date**        | 2026-06-12                                          |
| **Status**      | Proposed                                            |
| **Author**      | Claude (SPA Architect)                              |
| **Approved by** | Pending — Owner (Yurii) sign-off required           |
| **MP ref.**     | MP-402 (Gnosis Safe + Zodiac Roles + key policy)    |
| **ADR number**  | ADR-010                                             |
| **Blocks**      | MP-403 (Live-пилот $10–50K), MP-411 (Timelock)     |

---

## Context

### Текущее состояние (Phase 0 — Paper Trading)

SPA сейчас работает полностью off-chain: один PAT (GitHub) хранится в macOS
Keychain, никаких on-chain ключей нет, реальный капитал отсутствует. Весь
execution-домен (`spa_core/execution/`) — заготовка без живых ключей.

### Проблема

Для live-пилота $10–50K собственных средств (MP-403) система должна:

1. **Подписывать on-chain транзакции** — approve + deposit в Aave/Compound/Morpho
2. **Защищать капитал от компрометации** hot-ключа
3. **Ограничивать права автоматического исполнителя** — только заранее
   одобренные контракты, методы и лимиты суммы
4. **Обеспечивать emergency stop** без зависимости от того же ключа

### Угрозы

| Угроза | Вероятность | Ущерб | Статус без Safe |
|--------|-------------|-------|-----------------|
| Компрометация hot-key (malware, утечка) | Средняя | Полная потеря AUM | Катастрофа |
| Prompt injection через DeFi-данные | Низкая | Несанкционированный вывод | Катастрофа |
| Ошибка в коде allocator/executor | Высокая | Потеря до 100% позиции | Катастрофа |
| Социальная инженерия против Owner | Низкая | Потеря всего | Катастрофа |
| Кража физического устройства | Очень низкая | Частичная (если 2FA) | Управляемо |

Без multi-sig **любая** из первых трёх угроз = полная потеря капитала.

---

## Decision

### 2.1 Gnosis Safe — конфигурация

#### Phase 1 (Live-пилот, $10–50K): Safe 2-of-3

```
Signers:
  Key-A  — Owner primary   (hardware wallet: Ledger Nano X)
  Key-B  — Owner backup    (hardware wallet: Trezor Model T, хранится отдельно)
  Key-C  — Recovery cold   (seed phrase в физическом хранилище, OFFLINE)

Threshold: 2-of-3
```

**Почему 2-of-3, а не 1-of-1 или 2-of-2:**

- `1-of-1` — единая точка отказа, неприемлемо для реального капитала.
- `2-of-2` — операционный deadlock при потере одного ключа.
- `2-of-3` — баланс: любые 2 из 3 достаточны; потеря одного ключа не блокирует
  операции, не снижает безопасность.

#### Phase 2 (Production, >$50K): Safe 3-of-5

```
Signers:
  Key-A  — Owner primary       (Ledger, всегда при Owner)
  Key-B  — Owner backup        (Trezor, безопасное место)
  Key-C  — Recovery cold #1    (seed, физическое хранилище A)
  Key-D  — Recovery cold #2    (seed, физическое хранилище B, другой город)
  Key-E  — Trusted co-signer   (после найма smart-contract инженера, MP-507)

Threshold: 3-of-5
```

**Почему 3-of-5 для production:**

- Устойчивость к компрометации/потере 2 ключей одновременно.
- Key-E вводится после найма (MP-507): bus factor = 1 — главный риск GRAND_VISION §6.
- Схема позволяет Threshold 2-of-5 поднять до 3-of-5 без пересборки Safe
  (только смена конфига через Safe UI).

---

### 2.2 Zodiac Roles Module

Zodiac Roles (`gnosis.io/zodiac`) — модуль для Safe, позволяющий назначить
адресам гранулярные права на вызов конкретных контрактов/методов/лимитов
без передачи полного контроля над Safe.

#### Роли (Phase 1)

**Роль EXECUTOR (Hot Key)**
```
Address:  spa_executor EOA (генерируется локально, pubkey в репо, privkey в Keychain)
Rights:
  - Aave V3 Pool: supply(asset=USDC, amount≤MAX_SINGLE_TX), withdraw(asset=USDC, amount≤MAX_SINGLE_TX)
  - Compound V3 Comet: supply(asset=USDC, amount≤MAX_SINGLE_TX), withdraw(...)
  - Morpho Blue: supplyCollateral(...), withdrawCollateral(...) — только USDC-пулы из whitelist
  - Yearn V3 USDC vault: deposit(amount≤MAX_SINGLE_TX), withdraw(...)
  - Euler V2: deposit(...), withdraw(...)
  - Maple: requestRedeem(...) — НЕ deposit (только через Owner + Operator)
Limits:
  - MAX_SINGLE_TX = 20% AUM (например, $10K при пилоте $50K)
  - MAX_DAILY_VOLUME = 40% AUM (сумма всех tx за 24ч)
  - Только whitelisted asset: USDC (address hardcoded в module)
  - Запрещено: ETH-transfer, ERC20.transfer (только через approved протоколы)
Cooldown: нет (ребаланс может быть ежедневным)
```

**Роль OPERATOR (Owner + 1)**
```
Address:  2-of-3 Safe signers (т.е. сам Safe — требует порог подписей)
Rights:   Все права EXECUTOR + обновление whitelist EXECUTOR + изменение MAX_SINGLE_TX
          + первый deposit в Maple (нет в EXECUTOR-whitelist)
```

**Роль GUARDIAN (Emergency)**
```
Address:  Key-A ИЛИ Key-B (любой из 2 аппаратных кошельков, 1-of-2 для скорости)
Rights:   ТОЛЬКО:
  - Revoke EXECUTOR role (экстренная блокировка автоматики)
  - Trigger RiskPolicy kill-switch (close all — команда на вывод из всех протоколов)
  - НЕТ прав на deposit или изменение whitelist
Rationale: Один подписант достаточен для STOP, но не для START — асимметрия прав.
```

**Роль ADMIN (Safe Owners только)**
```
Rights:   Всё, включая:
  - Добавление/удаление Zodiac модулей
  - Изменение threshold Safe
  - Обновление контрактных адресов (после timelock, см. §2.3)
  - Смена ролей EXECUTOR/OPERATOR/GUARDIAN
  - Обновление RiskPolicy (через ADR + Owner)
```

#### Принцип наименьших привилегий

```
ADMIN ⊃ OPERATOR ⊃ EXECUTOR
GUARDIAN — независимая ветка (только STOP, не входит в иерархию прав)
```

Автоматический `cycle_runner` получает ключ EXECUTOR — минимально необходимые
права для ежедневного ребаланса. Даже при полной компрометации hot-key
атакующий может только перераспределить позиции внутри whitelisted протоколов
в пределах дневного лимита, но не вывести средства напрямую.

---

### 2.3 Timelock

Все изменения в ADMIN-роли (whitelist контрактов, смена threshold, обновление
Zodiac module) проходят через Timelock с задержкой:

| Тип операции | Timelock | Обоснование |
|---|---|---|
| Обновление whitelist контрактов EXECUTOR | **48 часов** | Реагирование на эксплойт в новом протоколе |
| Изменение MAX_SINGLE_TX / MAX_DAILY_VOLUME | **24 часа** | Предотвращение внезапного повышения лимитов |
| Смена threshold Safe (например, 2→3) | **72 часа** | Фундаментальное изменение безопасности |
| Добавление нового Zodiac модуля | **72 часа** | Новый модуль = новая поверхность атаки |
| Обновление RiskPolicy (`spa_core/risk/policy.py`) | **48 часов + ADR** | Детерминированная политика, изменение = audit event |
| Emergency actions (GUARDIAN role) | **0 часов** | STOP должен быть мгновенным |

**Реализация (Phase 1):** OZ TimelockController или встроенный Delay-модуль
Safe (Zodiac Delay). Минимальный delay — 24ч (конфигурируется при деплое).
Не снижать ниже 24ч в любой фазе без нового ADR.

---

### 2.4 Hot Key vs Cold Key разделение

```
HOT KEYS (подключены к интернету / автоматизированы)
  spa_executor EOA
    - privkey в macOS Keychain (ключ: EXECUTOR_PRIVKEY_SPA)
    - НИКОГДА не хранить в файлах, env-переменных, .env, логах, артефактах
    - Генерация: python3 -c "from eth_account import Account; print(Account.create().key.hex())"
      (только в memory, сразу записать в Keychain через `security add-generic-password`)
    - Лимиты: EXECUTOR роль (§2.2)
    - Ротация: каждые 90 дней ИЛИ при подозрении на компрометацию

WARM KEYS (hardware wallets, offline до момента подписания)
  Key-A Owner primary  (Ledger Nano X)
    - Pin + passphrase
    - BIP44 путь: m/44'/60'/0'/0/0
    - Pubkey: записать в docs/keys/pubkeys.txt (ТОЛЬКО pubkey, не privkey)
  Key-B Owner backup   (Trezor Model T)
    - Pin + passphrase (другой passphrase чем у Key-A)
    - Хранить отдельно от Key-A (другое физическое место)

COLD KEYS (seed phrase, полностью offline)
  Key-C Recovery cold
    - 24-word BIP39 seed (Ledger генерация offline)
    - Записать на металлической пластине (CryptoSteel или аналог)
    - Хранить в физическом сейфе
    - НИКОГДА не вводить в компьютер, подключённый к интернету
    - Проверка доступности: раз в квартал (убедиться что пластина цела)
```

---

### 2.5 Key Rotation Policy

| Ключ | Плановая ротация | Внеплановая (при компрометации) |
|---|---|---|
| `EXECUTOR_PRIVKEY_SPA` (hot key) | Каждые **90 дней** | **Немедленно**: revoke EXECUTOR role → generate new EOA → assign new EXECUTOR role (через OPERATOR, 2-of-3) |
| Key-A (Owner primary, Ledger) | **Ежегодно** или при потере/подозрении | Удалить signer из Safe → добавить новый через оставшихся 2 сигнеров |
| Key-B (Owner backup, Trezor) | **Ежегодно** или при потере/подозрении | Аналогично Key-A |
| Key-C (Recovery cold) | **Каждые 2 года** или после использования | Генерация нового cold seed offline → обновить Safe signer |

**Процедура ротации hot key (EXECUTOR):**

```bash
# 1. Revoke EXECUTOR role через Zodiac Roles (Safe tx, 2-of-3)
#    [Safe UI → Zodiac → Roles → spa_executor → Revoke]

# 2. Остановить cycle_runner
launchctl stop com.spa.daily_cycle

# 3. Удалить старый ключ из Keychain
security delete-generic-password -s EXECUTOR_PRIVKEY_SPA

# 4. Сгенерировать новый EOA (ТОЛЬКО в памяти)
python3 -c "
from eth_account import Account
import os
acct = Account.create()
# Немедленно сохранить в Keychain, не печатать
import subprocess
subprocess.run(['security','add-generic-password',
  '-s','EXECUTOR_PRIVKEY_SPA','-a','spa',
  '-w', acct.key.hex()], check=True)
print('New address:', acct.address)
"

# 5. Assign EXECUTOR role новому адресу через Safe (2-of-3)
#    [Safe UI → Zodiac → Roles → Add member → new address]

# 6. Обновить docs/keys/pubkeys.txt новым адресом (ТОЛЬКО адрес, не ключ)
# 7. Запустить cycle_runner
launchctl start com.spa.daily_cycle

# 8. Залогировать ротацию в docs/TOKEN_ROTATION_RUNBOOK.md
```

---

### 2.6 Multisig Recovery Procedure

**Сценарий: потеря Key-A (Owner primary)**

```
1. Убедиться, что Safe работает (threshold 2-of-3 → Key-B + Key-C достаточно)
2. Использовать Key-B + Key-C для подписи Safe tx:
   a. removeOwner(prevOwner, Key-A, 2)  — удалить скомпрометированный ключ
   b. addOwnerWithThreshold(новый Key-A, 2)  — добавить новый
3. Обновить pubkeys.txt и этот ADR
4. Уничтожить физически старое устройство Key-A если потеря из-за кражи
```

**Сценарий: потеря двух ключей одновременно (Phase 1, экстренный)**

```
Если потеряны Key-A и Key-B — доступен только Key-C (cold).
Key-C один НЕ достигает threshold 2-of-3.
→ Средства заблокированы до восстановления второго ключа.

ПРЕДОТВРАЩЕНИЕ: Key-A и Key-B хранить в физически разных местах.
```

---

## Rationale

### Почему именно Gnosis Safe

Safe — де-факто стандарт multi-sig в DeFi. Аудирован Chainalysis, Trail of Bits,
G0 Group. Более $100B в управлении. Поддержка в Safe{Wallet}, Etherscan, Tenderly.
Альтернативы (собственный multi-sig, 4337 AA) имеют выше риск ошибок реализации
и меньше экосистемной поддержки.

### Почему Zodiac Roles, а не прямой 2-of-3

Ежедневный ребаланс требует автоматизации — Owner не должен подписывать каждую
транзакцию вручную. Zodiac Roles решает это без снижения безопасности: EXECUTOR
ограничен whitelist протоколов и дневным лимитом. При компрометации — максимальный
ущерб ограничен 40% AUM за 24ч, что покрывается kill-switch.

### Альтернативы

- **1-of-1 EOA** — отклонено: single point of failure, недопустимо для реального капитала.
- **2-of-2 Safe без Zodiac** — отклонено: каждый ребаланс требует ручной подписи, неоперабельно.
- **Account Abstraction (ERC-4337)** — отложено: слабая экосистемная поддержка в DeFi протоколах на 2026-06.
- **Полностью ручной trading** — отклонено: противоречит автономной природе SPA.

---

## Risk Analysis

### 4.1 Single Point of Failure сценарии

| Сценарий | Phase 1 (2-of-3) | Митигация |
|---|---|---|
| Потеря Key-A | Операбельно (Key-B + Key-C) | Восстановить Key-A в течение 7 дней |
| Потеря Key-B | Операбельно (Key-A + Key-C) | Восстановить Key-B в течение 7 дней |
| Потеря Key-C | Операбельно (Key-A + Key-B) | Создать новый cold key, обновить Safe |
| Потеря Key-A + Key-B | **Deadlock** — средства заблокированы | Хранить в разных местах, страхование |
| Компрометация EXECUTOR hot key | Ограниченный ущерб (≤40% AUM/день) | Немедленный revoke через GUARDIAN (Key-A или Key-B alone) |
| Owner теряет доступ к обоим hw wallets | Deadlock | Key-C в надёжном месте — последний резерв |

### 4.2 Key Compromise сценарии

**Компрометация EXECUTOR (наиболее вероятный сценарий):**

Атакующий получает `EXECUTOR_PRIVKEY_SPA`. Возможные действия:
- Вывести позиции из разрешённых протоколов → USDC остаётся в Safe (не в EOA!)
- Максимум: 40% AUM за 24ч перед обнаружением

Митигация: GUARDIAN может revoke EXECUTOR role с 1 из 2 hw wallets (мгновенно,
без timelock). Автоматическая детекция аномальных транзакций через monitoring
(MP-506: Hypernative/Forta) → алерт в Telegram.

**Компрометация Safe owner key:**

Атакующий получает Key-A. Не достигает threshold (2-of-3). Может подписать
первую часть транзакции, но не завершить её. Действие: немедленно использовать
Key-B + Key-C для удаления Key-A из Safe.

### 4.3 Operational Complexity vs Security

| Параметр | Простота | Безопасность | Выбор |
|---|---|---|---|
| Threshold 1-of-3 | Высокая | Низкая | ✗ |
| Threshold 2-of-3 | Средняя | Высокая | **Phase 1** ✓ |
| Threshold 3-of-5 | Низкая | Очень высокая | **Phase 2** ✓ |
| Zodiac EXECUTOR daily limit | Средняя overhead | Ограничивает blast radius | ✓ |
| Timelock 48h на конфиг | Замедляет изменения | Защищает от срочных ошибок | ✓ |

Основной tradeoff: Zodiac Roles + Timelock добавляют **~2-4ч на настройку** и
**24-72ч задержку** на изменение конфига. Для long-term DeFi yield optimizer
это приемлемо — мгновенная реакция нужна только для STOP (GUARDIAN, 0 timelock).

---

## Implementation Phases

### Phase 0: Сейчас (Paper Trading, до ~2026-08-01)

**Состояние:** Без on-chain ключей. Один PAT в Keychain для GitHub.

Задачи Phase 0 для подготовки к Phase 1:
- [ ] Купить Ledger Nano X (Key-A) + Trezor Model T (Key-B)
  — USER ACTION, должно быть сделано до MP-403
- [ ] Сгенерировать Key-C cold seed offline, записать на металл
- [ ] Открыть Safe кошелёк на mainnet (Safe{Wallet} UI) — пустой, без средств
- [ ] Деплоить Zodiac Roles module в тестовой сети (Sepolia)
- [ ] Задокументировать pubkeys в `docs/keys/pubkeys.txt`

### Phase 1: Live-пилот $10–50K (около 2026-08-01, после GoLiveChecker READY 7d+)

**Конфигурация:** Safe 2-of-3 + Zodiac Roles (EXECUTOR/GUARDIAN) + Timelock 24-48ч

**Деплой-последовательность:**

```
1. Деплоить Safe 2-of-3 на mainnet
   Signers: Key-A, Key-B, Key-C
   Threshold: 2

2. Деплоить Zodiac Roles Module
   [Safe UI → Apps → Zodiac → Add Module → Roles]
   Создать роли: EXECUTOR, GUARDIAN

3. Назначить EXECUTOR role:
   Member: spa_executor EOA address
   Permissions: USDC-supply/withdraw в Aave/Compound/Morpho/Yearn/Euler
   Limits: MAX_SINGLE_TX=20% AUM, MAX_DAILY_VOLUME=40% AUM

4. Назначить GUARDIAN role:
   Members: Key-A address, Key-B address (1-of-2 достаточно)
   Permissions: revoke EXECUTOR, trigger kill-switch

5. Деплоить Zodiac Delay module (Timelock)
   MIN_DELAY: 24h для лимитов, 48h для whitelist, 72h для threshold

6. Провести E2E тест на Sepolia fork (MP-405 E2E harness):
   - Deposit $100 USDC через cycle_runner → Safe → Aave
   - Withdraw $100 USDC
   - GUARDIAN revoke EXECUTOR → убедиться что hot-key потерял права
   - Recovery процедура

7. Перевести $10K USDC в Safe
8. Включить live mode: python3 -m spa_core.golive.activate
```

### Phase 2: Production (>$50K, после 6 мес live-пилота)

**Конфигурация:** Safe 3-of-5 + Full Zodiac Roles + Timelock 48-72ч + External audit

```
Additions:
  - Key-D: второй cold seed (другое физическое место)
  - Key-E: trusted co-signer (нанятый smart-contract инженер, MP-507)
  - Роль OPERATOR: расширенные права для multi-protocol operations
  - Внешний аудит Safe/Zodiac конфигурации (Tier-1 фирма, MP-405)
  - Bug bounty (Immunefi, MP-410)
  - Real-time мониторинг (Hypernative/Forta, MP-506)
```

---

## Decision Outcome

**Рекомендованная конфигурация (к запуску MP-403):**

| Параметр | Значение | Обоснование |
|---|---|---|
| Safe threshold | **2-of-3** | Баланс resilience vs complexity |
| Signer set | Key-A (hw primary) + Key-B (hw backup) + Key-C (cold) | Разные типы хранения, разные места |
| EXECUTOR limits | 20% AUM single / 40% AUM daily | Blast radius ограничен при компрометации |
| GUARDIAN threshold | 1-of-2 (Key-A или Key-B) | Скорость emergency stop важнее |
| Timelock EXECUTOR whitelist | **48 часов** | Время на реакцию при подозрительном изменении |
| Timelock threshold change | **72 часа** | Фундаментальный параметр безопасности |
| Hot key rotation | **90 дней** | Стандартная лучшая практика DeFi |
| Max single protocol exposure | **40% T1 / 20% T2** | RiskPolicy v1.0 — без изменений |

**Блокирующие условия для перехода к Phase 1:**
1. GoLiveChecker READY 7 дней подряд (ADR-002)
2. Ledger Nano X + Trezor Model T физически в руках Owner
3. Key-C cold seed на металлической пластине в сейфе
4. E2E тест на Sepolia fork пройден без ошибок
5. Этот ADR approved Owner'ом (раздел ниже заполнен)

---

## Owner Approval

```
Дата approval:      _______________
Owner подпись:      Yurii

Конфигурация:       Safe 2-of-3, Zodiac Roles EXECUTOR/GUARDIAN
EXECUTOR address:   0x_______________________________________
Safe address:       0x_______________________________________
Deployment date:    _______________
```

---

## References

- [Gnosis Safe Docs](https://docs.safe.global/)
- [Zodiac Roles Module](https://zodiac.wiki/index.php/Category:Module)
- [ADR-002: Go-Live Transfer Rule](./ADR-002-golive-transfer-rule.md)
- [ADR-011: Go-Live Security Checklist](./ADR-011-go-live-security-checklist.md)
- [`spa_core/risk/policy.py`](../../spa_core/risk/policy.py) — RiskPolicy v1.0
- [`spa_core/golive/activate.py`](../../spa_core/golive/activate.py)
- `docs/TOKEN_ROTATION_RUNBOOK.md`
- MASTER_PLAN_v1.md §4 (Phase 4: Execution Infrastructure)
- GRAND_VISION_v1.md §6 (Bus Factor Risk)
