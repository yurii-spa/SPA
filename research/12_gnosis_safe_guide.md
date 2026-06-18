# Gnosis Safe + Hardware Wallets — Операционный гайд для DeFi Fund Manager

> **Контекст:** Safe 2/3 multisig на Ethereum mainnet, Ledger + Trezor (ожидаются), $100K–500K AUM (2026) → до $5M (2027), Python-автоматизация через Safe API.  
> **Дата исследования:** 2026-06-18  
> **Статус:** Операционный гайд — конкретные шаги, не теория.

---

## Содержание

1. [Настройка Gnosis Safe 2/3 — пошагово](#1-настройка-gnosis-safe-23--пошагово)
2. [Ledger + Trezor как 2 из 3 ключей — хранение seed phrase](#2-ledger--trezor-как-2-из-3-ключей--хранение-seed-phrase)
3. [Третий ключ — что использовать](#3-третий-ключ--что-использовать)
4. [Zodiac Roles Module — Python-оператор только на rebalance](#4-zodiac-roles-module--python-оператор-только-на-rebalance)
5. [Safe Transaction Service API — автоматизация propose + мониторинг](#5-safe-transaction-service-api--автоматизация-propose--мониторинг)
6. [Timelock для критических операций](#6-timelock-для-критических-операций)
7. [Testnet Checklist перед mainnet](#7-testnet-checklist-перед-mainnet)
8. [Incident Response — потерян один hardware wallet](#8-incident-response--потерян-один-hardware-wallet)
9. [Gas Management — автоматическое пополнение ETH](#9-gas-management--автоматическое-пополнение-eth)
10. [Ключевые операционные риски при $100K+ AUM](#10-ключевые-операционные-риски-при-100k-aum)

---

## 1. Настройка Gnosis Safe 2/3 — пошагово

### Предварительные требования

- Три Ethereum-адреса (два hardware wallet + третий ключ — см. раздел 3)
- ETH для газа: ~$50–80 на mainnet деплой при нормальном gas price (20–30 gwei)
- Временный браузерный кошелёк для деплоя (MetaMask / Rabby) — он станет Owner #1
- Проверить gas price перед деплоем: [etherscan.io/gastracker](https://etherscan.io/gastracker) — деплоить при <25 gwei

### Шаг 1 — Сгенерировать три независимых адреса

**КРИТИЧНО:** никогда не используй один и тот же seed phrase для двух владельцев Safe. Каждый ключ — отдельное устройство, отдельная seed phrase.

```
Owner A: Ledger Nano X (или Ledger Flex)  → адрес 0xAAA...
Owner B: Trezor Safe 5 (или Trezor Model T) → адрес 0xBBB...
Owner C: третий ключ (см. раздел 3)          → адрес 0xCCC...
```

Перед деплоем: скопируй все три адреса, проверь на Etherscan что они пустые (нет истории транзакций с main-seed горячего кошелька — если есть, создай новый аккаунт на устройстве).

### Шаг 2 — Деплой Safe на Ethereum Mainnet

1. Открой [app.safe.global](https://app.safe.global)
2. Нажми **"Create new Safe"**
3. В верхнем правом углу — выбери сеть **Ethereum** (убедись, не Gnosis Chain)
4. Подключи временный MetaMask — он нужен только для деплоя, потом можно убрать
5. Дай имя Safe: например `SPA-Production-2of3`
6. **Добавь владельцев:**
   - Нажми **"Add owner"** → вставь адрес Ledger (Owner A)
   - Нажми **"Add owner"** → вставь адрес Trezor (Owner B)  
   - Нажми **"Add owner"** → вставь адрес третьего ключа (Owner C)
   - Подпись MetaMask (деплоер) автоматически добавляется как первый owner — **убери его** после деплоя, он не должен оставаться
7. **Установи threshold: 2** (2-of-3)
8. Проверь итоговый список: три адреса, threshold = 2
9. Нажми **"Create"**, подпиши транзакцию в MetaMask, оплати газ
10. Дождись подтверждения (2–4 минуты)

### Шаг 3 — Удалить временный деплоер-кошелёк

После деплоя MetaMask-кошелёк может оказаться в списке owners. Если это так:

1. Открой Safe → Settings → Owners
2. Нажми **"Remove owner"** напротив MetaMask-адреса
3. Установи новый threshold (должен остаться 2)
4. Эта транзакция сама требует 2 подписи — подпишите с Ledger + Trezor

### Шаг 4 — Верификация деплоя

```bash
# Проверь на Etherscan что контракт — GnosisSafeProxy
# https://etherscan.io/address/YOUR_SAFE_ADDRESS#code
# Contract → должен быть "GnosisSafe" или "SafeProxy"

# Через Safe API
curl https://safe-transaction-mainnet.safe.global/api/v1/safes/YOUR_SAFE_ADDRESS/ | python3 -m json.tool
# Ожидай: "owners": ["0xAAA...", "0xBBB...", "0xCCC..."], "threshold": 2
```

### Шаг 5 — Первый тест (обязателен!)

Переведи **0.01 ETH** на адрес Safe, затем:
1. Создай транзакцию отправки 0.005 ETH на тестовый адрес
2. Подпиши с Ledger
3. Подпиши с Trezor
4. Убедись что транзакция исполнилась
5. Если всё работает — переводи основной капитал

> **Правило:** Никогда не переводи весь капитал до прохождения теста 2-of-3 с реальными hardware devices.

### Стоимость операций

| Операция | Стоимость (при 20 gwei) |
|---|---|
| Деплой Safe | $40–80 |
| Обычная транзакция | $15–45 |
| Добавление/удаление owner | $20–35 |
| Добавление модуля (Zodiac) | $25–50 |

---

## 2. Ledger + Trezor как 2 из 3 ключей — хранение seed phrase

### Выбор устройств

**Не используй оба устройства одного производителя.** Если Ledger выпустит критическую уязвимость прошивки — оба ключа могут быть скомпрометированы одновременно. Разные производители = дополнительная защита от vendor-level compromise.

Рекомендуемые модели:
- **Ledger:** Nano X или Ledger Flex (Bluetooth для удобства подписания, но отключай его при critical ops)
- **Trezor:** Trezor Safe 5 или Model T (touchscreen, open-source firmware)

**Ключевое различие для seed backup:**
- **Ledger** не поддерживает Shamir Backup (SLIP-39)
- **Trezor** поддерживает Shamir Backup — рекомендуется использовать для Trezor

### Протокол хранения seed phrase

#### Для Ledger (24 слова, стандартный BIP-39)

```
Правило #1: Никогда не фотографируй seed phrase
Правило #2: Никогда не вводи seed phrase в компьютер, телефон, облако
Правило #3: Никогда не храни seed phrase и устройство в одном месте

Шаги:
1. Запиши 24 слова на бумаге ручкой (в комплекте с Ledger есть листы)
2. Переведи на металлическую пластину (Cryptotag, Bilodal, ColdTi)
   — бумага горит, металл выдерживает пожар
3. Храни металл в сейфе в ДРУГОМ физическом месте (не там, где устройство)
4. Добавь passphrase (25-е слово): Settings → Security → Passphrase
   — Passphrase хранится ОТДЕЛЬНО от seed (в голове или другом сейфе)
   — Без passphrase seed даёт доступ к пустому кошельку-decoy
```

#### Для Trezor — Shamir Backup (рекомендуется)

Shamir Secret Sharing (SLIP-39) разбивает seed на N шардов так, что любые M из них восстанавливают ключ. Для Trezor рекомендуется схема **3-of-5**:

```
Сгенерируй 5 шардов, любые 3 восстанавливают ключ:
Шард 1: хранишь сам (сейф дома)
Шард 2: хранишь сам (сейф в офисе / депозитарная ячейка)
Шард 3: доверенное лицо (семья, партнёр) — без объяснений что это
Шард 4: нотариус или юридический депозит
Шард 5: запасной (отдельное физическое хранилище)

Итог: потеря 2 шардов = ключ всё ещё восстановим
       компрометация 2 шардов = ключ всё ещё защищён
```

#### Общие правила (оба устройства)

- **Покупай только у официального производителя** — никаких Amazon, AliExpress, б/у устройств
- Проверяй устройство при получении: нет следов вскрытия, стикеры целые
- Устройство и seed phrase хранятся в **разных физических локациях**
- Никогда не подключай hardware wallet к чужому компьютеру или публичному WiFi
- Firmware обновляй только с официального сайта производителя
- Используй **разные seed phrases** для каждого устройства

---

## 3. Третий ключ — что использовать

### Варианты и их оценка

| Вариант | Плюсы | Минусы | Рекомендация |
|---|---|---|---|
| Третий hardware wallet (Coldcard, Keystone) | Высокая безопасность, air-gapped | Нужен третий человек или локация | ✅ Лучший для $500K+ |
| Институциональный MPC (Fireblocks, Coinbase Prime) | Профессиональная защита, recovery | $10K+ setup, корпоративный contract | ✅ Лучший для $5M+ |
| Gnosis Safe (nested multisig) | Programmatic, гибко | Сложнее управлять, gas | ✅ Хорош для governance |
| Hot wallet (MetaMask + Hardware) | Удобно | Single point of failure | ⚠️ Только временно |
| Чистый hot wallet | — | Критически небезопасно | ❌ НИКОГДА |

### Рекомендация для SPA ($100K–500K)

**Вариант A (минимальный бюджет):** Третий hardware wallet другого производителя — Coldcard Q или Keystone 3 Pro. Air-gapped, QR-подпись, не нужно USB-соединение. Хранится у доверенного лица или в депозитарной ячейке. Используется только для экстренного восстановления.

**Вариант B (при $500K+):** Nested Safe — создать второй Safe 1/2 (ты + партнёр/юрист) и использовать его адрес как третий владелец основного Safe. Это даёт onchain-audit trail для использования третьего ключа.

```
Рекомендуемая схема для SPA прямо сейчас (до прихода устройств):
Owner A: Ledger (ты, основной)
Owner B: Trezor (ты, резервный)
Owner C: Coldcard или другой air-gapped device (физически отдельно)
```

### Правило диверсификации производителей

Не более одного устройства от каждого производителя в 2-of-3 схеме. Это защищает от сценария массовой компрометации прошивки одного вендора.

---

## 4. Zodiac Roles Module — Python-оператор только на rebalance

### Концепция

Zodiac Roles Modifier — smart contract module, который крепится к Safe и позволяет назначить роль любому адресу с гранулярными разрешениями: какой контракт вызывать, какую функцию, с какими параметрами. Python-оператор получает роль `rebalancer` — может вызывать только approve/deposit/withdraw у whitelisted DeFi-протоколов, но **не может** вызвать transfer ETH на произвольный адрес или добавить нового владельца Safe.

### Шаг 1 — Установить Zodiac Roles Modifier

1. Открой [app.safe.global](https://app.safe.global) → твой Safe
2. Перейди в **Apps** → найди **Zodiac**
3. В Zodiac App выбери **Roles Modifier**
4. Нажми **"Add Module"**
5. Транзакция установки модуля требует 2 подписи (2-of-3 Safe) — подпиши с Ledger + Trezor
6. После подтверждения запомни адрес задеплоенного Roles Modifier контракта

Либо через SDK:

```bash
# Установка SDK
npm i --save zodiac-roles-sdk @zodiac-os/sdk

# Инициализация
npx zodiac init  # открывает браузер для авторизации
```

### Шаг 2 — Создать роль для Python-оператора

```typescript
// zodiac.config.ts
import { defineConfig } from "@zodiac-os/sdk/cli/config";

export default defineConfig({
  contracts: {
    mainnet: {
      // Aave V3 Pool
      aave_pool: "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",
      // Compound V3 Comet USDC
      compound_comet: "0xc3d688B66703497DAA19211EEdff47f25384cdc3",
      // Morpho Steakhouse USDC
      morpho_vault: "0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB",
      // USDC token (для approve)
      usdc: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    },
  },
});
```

```typescript
// permissions.ts — что разрешено Python-оператору
import { allow } from "@zodiac-os/sdk/allow";
import { constellation, push } from "@zodiac-os/sdk";

const PYTHON_OPERATOR_ADDRESS = "0xYOUR_OPERATOR_HOT_WALLET";

const eth = constellation({
  workspace: "SPA-Production",
  label: "Rebalancer Role Setup",
  chain: 1,
});

const rolesMod = eth.roles["SPA-Roles"]({
  roles: {
    rebalancer: {
      members: [PYTHON_OPERATOR_ADDRESS],
      permissions: [
        // USDC approve для DeFi протоколов (не произвольный адрес!)
        allow.mainnet.usdc.approve(
          "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"  // только Aave Pool
        ),
        allow.mainnet.usdc.approve(
          "0xc3d688B66703497DAA19211EEdff47f25384cdc3"  // только Compound
        ),
        allow.mainnet.usdc.approve(
          "0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB"  // только Morpho
        ),
        // Deposit в Aave
        allow.mainnet.aave_pool.supply(
          "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  // asset = USDC only
          undefined,  // amount — any (allow any)
          undefined   // onBehalfOf — any
        ),
        // Withdraw из Aave
        allow.mainnet.aave_pool.withdraw(
          "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  // asset = USDC only
          undefined,  // amount — any
          undefined   // to — any (но контракт вернёт в Safe)
        ),
        // Deposit в Compound
        allow.mainnet.compound_comet.supply(
          "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
          undefined
        ),
        // Withdraw из Compound  
        allow.mainnet.compound_comet.withdraw(
          "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
          undefined
        ),
        // Morpho deposit/withdraw
        allow.mainnet.morpho_vault.deposit(undefined, undefined),
        allow.mainnet.morpho_vault.redeem(undefined, undefined, undefined),
      ],
    },
  },
});

await push({ rolesMod });
```

**Что оператор НЕ может:**
- Вызывать `transfer` или `transferFrom` USDC на произвольный адрес
- Добавлять/удалять owners в Safe
- Менять threshold
- Вызывать любые функции не из whitelist
- Выводить ETH

### Шаг 3 — Проверить permissions в Roles App

1. Открой [roles.gnosisguild.org](https://roles.gnosisguild.org)
2. Подключи Safe
3. Убедись что роль `rebalancer` видна и permissions соответствуют whitelist

### Шаг 4 — Python-оператор выполняет транзакцию через роль

```python
# Python-оператор использует Roles Modifier ABI напрямую
# Функция: execTransactionWithRole(to, value, data, operation, roleKey, shouldRevert)

from web3 import Web3
from eth_account import Account

ROLES_MODIFIER_ADDRESS = "0xROLES_MODIFIER_CONTRACT"
OPERATOR_PRIVATE_KEY = "..."  # из env, не хардкодить

w3 = Web3(Web3.HTTPProvider("https://mainnet.infura.io/v3/YOUR_KEY"))
account = Account.from_key(OPERATOR_PRIVATE_KEY)

ROLES_ABI = [...]  # ABI из https://github.com/gnosisguild/zodiac-modifier-roles

roles_contract = w3.eth.contract(
    address=ROLES_MODIFIER_ADDRESS,
    abi=ROLES_ABI
)

# Пример: deposit 10000 USDC в Aave
REBALANCER_ROLE_KEY = w3.keccak(text="rebalancer")  # bytes32

tx = roles_contract.functions.execTransactionWithRole(
    to="0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",  # Aave Pool
    value=0,
    data=aave_pool_contract.encodeABI("supply", [USDC_ADDRESS, 10000_000000, SAFE_ADDRESS, 0]),
    operation=0,  # Call
    roleKey=REBALANCER_ROLE_KEY,
    shouldRevert=True
).build_transaction({
    "from": account.address,
    "gas": 300000,
    "gasPrice": w3.eth.gas_price,
    "nonce": w3.eth.get_transaction_count(account.address),
})

signed = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
```

> ⚠️ **Zodiac Roles v2 vs v4:** Текущая версия SDK (2026) — v4. Если используешь контракты из старых деплоев, проверь версию и при необходимости выполни миграцию по [docs.roles.gnosisguild.org/sdk/v3-v4-migration](https://docs.roles.gnosisguild.org/sdk/v3-v4-migration).

---

## 5. Safe Transaction Service API — автоматизация propose + мониторинг

### Архитектура автоматизации

```
Python Cycle Runner
    │
    ├── Zodiac Roles (для routine rebalance) → directly executes via role
    │
    └── Safe Transaction Service API (для non-routine / critical)
            ├── proposeTransaction → создаёт pending tx
            ├── Ledger/Trezor owner видит pending → подписывает вручную
            └── после 2 подписей → executeTransaction
```

### Python SDK: safe-eth-py (официальный)

```bash
pip install safe-eth-py==7.21.0
```

```python
from safe_eth.eth import EthereumNetwork
from safe_eth.safe.api import TransactionServiceApi

# Mainnet Transaction Service
SAFE_ADDRESS = "0xYOUR_SAFE_ADDRESS"
SAFE_TX_SERVICE_URL = "https://safe-transaction-mainnet.safe.global"

# Нужен API key из https://developer.safe.global
import os
API_KEY = os.environ["SAFE_TX_SERVICE_API_KEY"]

tx_service = TransactionServiceApi(
    network=EthereumNetwork.MAINNET,
    api_key=API_KEY
)

# Получить список pending транзакций
pending = tx_service.get_transactions(SAFE_ADDRESS)
for tx in pending:
    print(f"Pending: {tx['safeTxHash']} — {tx['dataDecoded']}")
```

### JavaScript/TypeScript SDK (Safe API Kit — официальный)

```typescript
import SafeApiKit from '@safe-global/api-kit'
import Safe from '@safe-global/protocol-kit'
import { MetaTransactionData, OperationType } from '@safe-global/types-kit'

const SAFE_ADDRESS = "0xYOUR_SAFE_ADDRESS"
const RPC_URL = "https://mainnet.infura.io/v3/YOUR_KEY"
const OPERATOR_PRIVATE_KEY = process.env.OPERATOR_KEY!  // из env

// Инициализация API Kit
const apiKit = new SafeApiKit({
  chainId: 1n,
  apiKey: process.env.SAFE_API_KEY
})

// Инициализация Protocol Kit для подписания
const protocolKit = await Safe.init({
  provider: RPC_URL,
  signer: OPERATOR_PRIVATE_KEY,
  safeAddress: SAFE_ADDRESS
})

// Propose транзакции (например, смена owner)
async function proposeOwnerChange(newOwner: string) {
  const safeTransactionData: MetaTransactionData = {
    to: SAFE_ADDRESS,
    value: '0',
    // encodeABI для addOwnerWithThreshold
    data: safeInterface.encodeFunctionData('addOwnerWithThreshold', [newOwner, 2]),
    operation: OperationType.Call
  }

  const safeTransaction = await protocolKit.createTransaction({
    transactions: [safeTransactionData]
  })

  const safeTxHash = await protocolKit.getTransactionHash(safeTransaction)
  const signature = await protocolKit.signHash(safeTxHash)

  // Отправить в сервис
  await apiKit.proposeTransaction({
    safeAddress: SAFE_ADDRESS,
    safeTransactionData: safeTransaction.data,
    safeTxHash,
    senderAddress: OPERATOR_ADDRESS,
    senderSignature: signature.data
  })

  console.log(`Transaction proposed: ${safeTxHash}`)
  return safeTxHash
}

// Мониторинг pending транзакций
async function monitorPending() {
  const pending = await apiKit.getPendingTransactions(SAFE_ADDRESS)
  for (const tx of pending.results) {
    console.log(`Pending: ${tx.safeTxHash}`)
    console.log(`  Confirmations: ${tx.confirmations?.length}/${tx.confirmationsRequired}`)
    console.log(`  To: ${tx.to}`)
  }
}
```

### REST API напрямую (без SDK)

```bash
# Base URL для Ethereum Mainnet
BASE_URL="https://safe-transaction-mainnet.safe.global/api/v1"

# Получить info о Safe
curl "$BASE_URL/safes/$SAFE_ADDRESS/"

# Получить pending транзакции
curl "$BASE_URL/safes/$SAFE_ADDRESS/multisig-transactions/?executed=false"

# Получить историю транзакций
curl "$BASE_URL/safes/$SAFE_ADDRESS/multisig-transactions/?executed=true&limit=20"

# Получить incoming ETH transfers
curl "$BASE_URL/safes/$SAFE_ADDRESS/incoming-transfers/"
```

### Мониторинг через Safe Events Webhook

Для real-time алертов настрой Safe{Core} hooks или используй polling:

```python
import time
import requests

def monitor_safe(safe_address: str, interval_seconds: int = 60):
    """Polling-мониторинг pending транзакций Safe"""
    base_url = f"https://safe-transaction-mainnet.safe.global/api/v1/safes/{safe_address}"
    known_hashes = set()

    while True:
        try:
            resp = requests.get(
                f"{base_url}/multisig-transactions/",
                params={"executed": "false"},
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            resp.raise_for_status()
            pending = resp.json()["results"]

            for tx in pending:
                tx_hash = tx["safeTxHash"]
                if tx_hash not in known_hashes:
                    known_hashes.add(tx_hash)
                    confirmations = len(tx.get("confirmations") or [])
                    required = tx["confirmationsRequired"]
                    # Отправить Telegram alert
                    send_telegram_alert(
                        f"⚠️ New Safe pending tx: {tx_hash[:10]}...\n"
                        f"To: {tx['to']}\n"
                        f"Confirmations: {confirmations}/{required}"
                    )
        except Exception as e:
            print(f"Monitor error: {e}")

        time.sleep(interval_seconds)
```

---

## 6. Timelock для критических операций

### Когда нужен Timelock

| Операция | Нужен Timelock? | Минимальная задержка |
|---|---|---|
| DeFi rebalance (deposit/withdraw) | Нет | — |
| Смена owner Safe | Да | 24–48h |
| Изменение threshold | Да | 24–48h |
| Обновление permissions в Zodiac Roles | Да | 24h |
| Вывод всех средств | Да | 48–72h |
| Смена адреса Roles Modifier | Да | 48h |

### Вариант A — Safe Guard (SafeGuard) на уровне транзакций

SafeGuard — смарт-контракт, который Safe вызывает в `checkTransaction()` перед каждой транзакцией. Если транзакция не была запланирована за минимальное время до исполнения — Guard ревертит.

**Реализация на Safe Forum:** Сообщество Safe создало простой Timelock Guard — описание на [forum.safe.global/t/an-easy-to-use-timelock-for-the-safe-wallet/6624](https://forum.safe.global/t/an-easy-to-use-timelock-for-the-safe-wallet/6624).

Принцип работы:
1. Транзакция создаётся через Safe UI как обычно
2. Guard проверяет: была ли эта транзакция scheduled за X часов до текущего момента?
3. Если нет — ревертит с ошибкой "TimelockGuard: not yet"
4. Если да — пропускает

**Плюсы SafeGuard:** простота, без отдельного контракта, настраивается per-Safe.  
**Минусы:** требует аудита guard-контракта перед установкой; если guard buggy — может заблокировать Safe навсегда (тестируй на Sepolia!).

### Вариант B — Zodiac Delay Modifier (рекомендуется для SPA)

⚠️ **ВНИМАНИЕ:** В мае 2026 произошёл exploit Zodiac Delay Module у Gnosis Pay (атакующий смог инициировать транзакции из Safe-кошельков с установленным Delay модулем). **Не устанавливай Zodiac Delay Modifier без аудита текущей версии контракта.** Проверяй версию на [zodiac.wiki](https://www.zodiac.wiki) и security bulletins от Gnosis Guild.

### Вариант C — OpenZeppelin TimelockController (отдельный контракт)

Паттерн: Safe является admin TimelockController, все критические операции проходят через timelock.

```
Схема:
Safe (2/3) → proposeTransaction → TimelockController
                                      ↓ (после MIN_DELAY)
                                  executeTransaction
```

Деплой OpenZeppelin TimelockController:
```bash
# Используй OZ Defender или hardhat
# MIN_DELAY: 86400 (24h) или 172800 (48h)
# PROPOSERS: [SAFE_ADDRESS]
# EXECUTORS: [SAFE_ADDRESS]  
# ADMIN: address(0) — renounce admin после настройки
```

Для $100K–500K AUM **рекомендуется Вариант C** (OZ TimelockController) — хорошо аудированный, широко используемый в production (Compound, Uniswap).

---

## 7. Testnet Checklist перед mainnet

Используй **Ethereum Sepolia** для тестирования. Sepolia поддерживает Safe Transaction Service.

### Pre-deployment

- [ ] Три тестовых Ethereum-адреса сгенерированы (MetaMask accounts достаточно для testnet)
- [ ] Получил Sepolia ETH (faucet: [sepoliafaucet.com](https://sepoliafaucet.com))
- [ ] Задокументированы адреса всех трёх owners

### Safe Deployment

- [ ] Safe задеплоен на Sepolia: [app.safe.global](https://app.safe.global) → выбрать Sepolia
- [ ] Threshold = 2, owners = 3 — проверено через Safe API
- [ ] Деплоер-кошелёк удалён из owners (если добавлялся)
- [ ] Тестовая транзакция: 0.001 ETH из 3 разных аккаунтов → 2 подписи → исполнена

### Zodiac Roles

- [ ] Roles Modifier установлен на Sepolia Safe
- [ ] Роль `rebalancer` создана с whitelist permissions
- [ ] Python-оператор (тестовый адрес) добавлен в роль
- [ ] Тест: оператор успешно вызвал whitelisted функцию через Roles Modifier
- [ ] Тест: оператор **НЕ СМОГ** вызвать transfer ETH (revert ожидается)
- [ ] Тест: оператор **НЕ СМОГ** изменить owners Safe (revert ожидается)

### Safe API Automation

- [ ] Python скрипт успешно fetches pending транзакции через Transaction Service
- [ ] Python скрипт успешно propose транзакцию
- [ ] Второй owner подписал через Safe UI → транзакция исполнена
- [ ] Мониторинг алерты работают (Telegram notification получен)

### Timelock (если используется)

- [ ] TimelockController задеплоен на Sepolia
- [ ] Safe является proposer + executor
- [ ] Тест: транзакция proposed → до MIN_DELAY execute → revert
- [ ] Тест: транзакция proposed → после MIN_DELAY → execute → success
- [ ] Тест: cancel pending транзакции через Safe

### Hardware Wallet Integration

- [ ] Ledger подписал транзакцию через Safe UI на Sepolia → успешно
- [ ] Trezor подписал транзакцию через Safe UI на Sepolia → успешно
- [ ] 2-of-3 работает с реальными hardware devices (не MetaMask-симуляция)
- [ ] Протестирован сценарий: один из 3 owners offline → транзакция всё равно исполнена (через 2 оставшихся)

### Incident Response Drill

- [ ] Удаление одного owner из Safe через 2-of-3 подписи — протестировано на Sepolia
- [ ] Добавление нового replacement owner — протестировано
- [ ] Замена threshold — протестировано

---

## 8. Incident Response — потерян один hardware wallet

### Сценарий: потерян/сломан один из hardware wallets

При 2-of-3 схеме потеря одного ключа не блокирует Safe — оставшиеся два ключа могут продолжать работу и заменить потерянный.

### Немедленные действия (первые 24 часа)

```
Шаг 1: Паника OFF. Средства в Safe БЕЗОПАСНЫ — нужны 2 ключа для транзакции,
        потеря 1 ничего не даёт атакующему (если seed не скомпрометирован).

Шаг 2: Оцени ситуацию:
  a) Устройство физически потеряно, seed phrase под контролем → низкий приоритет
  b) Устройство украдено, но seed phrase защищён → средний приоритет (может быть brute force)
  c) Seed phrase скомпрометирован → КРИТИЧНО, действуй немедленно
```

### Если seed phrase НЕ скомпрометирован

```
1. Запомни: у тебя есть время. Не паникуй.

2. Через оставшиеся 2 ключа (2-of-3):
   - Создай транзакцию в Safe: Settings → Owners → Remove Owner
   - Укажи адрес потерянного устройства
   - Подпиши двумя оставшимися ключами

3. После удаления старого owner:
   - Сгенерируй новый replacement ключ (новое hardware устройство)
   - Добавь новый адрес: Settings → Owners → Add Owner
   - Подпиши двумя ключами

4. Threshold не меняется (остаётся 2-of-3)
```

### Если seed phrase СКОМПРОМЕТИРОВАН (критично!)

```
НЕМЕДЛЕННО (в течение минут, не часов):

1. С оставшихся двух ключей создай транзакцию:
   - УДАЛИ скомпрометированный owner address
   - Подпиши немедленно двумя оставшимися keys

2. Если атакующий уже предлагает транзакции из Safe (видно в Transaction Queue):
   - Не паникуй: ему нужна ВТОРАЯ подпись которой у него нет
   - Просто не подписывай эти транзакции
   - Удали скомпрометированного owner (п.1)

3. После удаления:
   - Проверь Transaction History — были ли исполнены несанкционированные транзакции
   - Если да — фиксируй факт для страховки/регуляторов

4. Создай новый replacement key и добавь в Safe
```

### Код Python для мониторинга (автоматический алерт)

```python
# Добавить в monitoring: алерт при появлении новых pending транзакций
# из неизвестных источников

def check_for_suspicious_pending(safe_address: str):
    """Алерт если pending tx создана не известным оператором"""
    KNOWN_PROPOSERS = {
        "0xAAA...": "Ledger",
        "0xBBB...": "Trezor",  
        "0xCCC...": "Operator",
    }
    
    pending = get_pending_transactions(safe_address)
    for tx in pending:
        proposer = tx.get("proposer", "").lower()
        if proposer not in {k.lower() for k in KNOWN_PROPOSERS}:
            send_telegram_alert(
                f"🚨 SUSPICIOUS: Unknown proposer {proposer} created tx {tx['safeTxHash'][:10]}!\n"
                f"DO NOT SIGN. Check immediately."
            )
```

### После инцидента

- [ ] Новый hardware wallet заказан у официального производителя
- [ ] Seed phrase для нового устройства сгенерирован и защищён (процедура из раздела 2)
- [ ] Новый owner добавлен в Safe
- [ ] Incident documented (дата, причина, предпринятые шаги)
- [ ] Обновить CLAUDE.md / CURRENT_STATE.md с новым составом signers

---

## 9. Gas Management — автоматическое пополнение ETH

### Проблема

Safe нужен ETH для газа при исполнении транзакций. Операторский кошелёк (через Zodiac Roles) также нужен ETH для вызова функций Roles Modifier.

### Архитектура gas management

```
Gas бюджет Safe: держать 0.1–0.5 ETH на Safe (достаточно для 3–30 транзакций)
Gas бюджет Operator: держать 0.05–0.1 ETH на hot wallet оператора
```

### Вариант A — Gelato Automation (рекомендуется)

Gelato — децентрализованная automation network, интегрируется с Safe через Gelato Safe Module.

```
1. Задеплой Gelato Safe Module на свой Safe
2. Пополни Gelato 1Balance (USDC на Polygon или ETH на Ethereum)
3. Gelato автоматически топит ETH на safe/operator при падении ниже порога
4. Цена: ~0.5–2% от gas затрат как relayer fee
```

Ограничение: Gelato 1Balance в 2026 требует предоплату — нельзя автоматически конвертировать USDC из Safe в ETH для газа (это требовало бы доверия).

### Вариант B — Простой onchain keeper (для Python-оператора)

```python
# gas_keeper.py — запускается как cron или через launchd

import os
from web3 import Web3

w3 = Web3(Web3.HTTPProvider(os.environ["RPC_URL"]))

OPERATOR_ADDRESS = os.environ["OPERATOR_ADDRESS"]
SAFE_ADDRESS = os.environ["SAFE_ADDRESS"]

# Пороги
OPERATOR_MIN_ETH = w3.to_wei(0.05, 'ether')   # 0.05 ETH
SAFE_MIN_ETH = w3.to_wei(0.1, 'ether')         # 0.1 ETH

def check_and_alert():
    """
    НЕ пополняет автоматически — это небезопасно.
    Только алертит, что нужно пополнить вручную.
    """
    operator_balance = w3.eth.get_balance(OPERATOR_ADDRESS)
    safe_balance = w3.eth.get_balance(SAFE_ADDRESS)
    
    if operator_balance < OPERATOR_MIN_ETH:
        eth_amount = w3.from_wei(operator_balance, 'ether')
        send_telegram_alert(
            f"⚠️ GAS LOW: Operator wallet {eth_amount:.4f} ETH\n"
            f"Address: {OPERATOR_ADDRESS}\n"
            f"Action required: send 0.1 ETH from Safe manually"
        )
    
    if safe_balance < SAFE_MIN_ETH:
        eth_amount = w3.from_wei(safe_balance, 'ether')
        send_telegram_alert(
            f"⚠️ GAS LOW: Safe {eth_amount:.4f} ETH\n"
            f"Address: {SAFE_ADDRESS}\n"
            f"Action required: send ETH from external source"
        )

if __name__ == "__main__":
    check_and_alert()
```

```bash
# launchd cron (каждые 6 часов)
# com.spa.gaskeeper.plist
```

### Правила безопасности gas management

1. **Не храни большой ETH запас на hot wallet оператора** — только на gas. Максимум 0.1 ETH.
2. **Пополняй gas вручную** через Safe → оператор, когда получаешь alert. Автоматическое пополнение = риск drain через компрометацию автоматики.
3. **Источник ETH для Safe:** купи ETH отдельно и переведи на Safe адрес с обычного кошелька. Никогда не конвертируй USDC в ETH через деплой swap внутри Safe без аудита.
4. **ETH buffer на Safe:** держи 0.2–0.5 ETH. При $4000/ETH это $800–2000 или 0.2–0.5% от $100K AUM — приемлемо.

---

## 10. Ключевые операционные риски при $100K+ AUM

### Матрица рисков

| Риск | Вероятность | Последствие | Митигация |
|---|---|---|---|
| Компрометация одного hardware wallet seed | Низкая | Средняя | 2-of-3 threshold, Shamir backup |
| Phishing при подписании транзакции | Средняя | Высокая | Всегда верифицировать адрес на экране HW wallet |
| Buggy third-party module exploit | Средняя | Критическая | Не устанавливать неаудированные модули |
| Потеря доступа к 2+ ключам одновременно | Очень низкая | Критическая | Тестировать recovery регулярно |
| DNS/UI hijack Safe фронтенда | Низкая | Высокая | Bookmarking, проверка URL, использование CLI |
| Operator hot wallet компрометация | Средняя | Низкая (Zodiac) | Zodiac Roles ограничивает возможности |
| Smart contract bug в Safe | Очень низкая | Критическая | Safe v1.4.1+ — хорошо аудирован |
| Gas manipulation (front-running) | Средняя | Низкая | Slippage limits в Roles permissions |

### Конкретные риски и защита

#### Риск 1: Blind Signing

Ledger и Trezor исторически показывают hexdata при подписании DeFi транзакций — невозможно прочитать что подписываешь. В 2026 обе компании ввели Clear Signing для популярных протоколов.

**Митигация:**
- Включи Clear Signing на устройстве (Settings → Display → Clear Signing)
- Используй Tenderly для симуляции транзакции перед подписанием
- Проверяй destination address и ETH value на экране hardware wallet, не только в браузере

#### Риск 2: Third-party Module Exploits (Реальный инцидент 2026)

В мае 2026 уязвимый SquidRouterModule был проэксплуатирован — ~$3.2M потеряно. Атакующий воспользовался тем, что модуль давал права как trusted user.

**Митигация:**
- Устанавливай ТОЛЬКО аудированные модули (официальные Zodiac, Gelato)
- Перед установкой любого модуля читай последние security advisories
- Используй Tenderly или Hardhat для симуляции эффекта модуля
- Мониторь модули через `getModules()` — alert если появился неизвестный модуль

```python
# Мониторинг модулей
def check_safe_modules(safe_address: str):
    resp = requests.get(f"{TX_SERVICE}/safes/{safe_address}/")
    modules = resp.json().get("modules", [])
    KNOWN_MODULES = {"0xROLES_MODIFIER", "0xTIMELOCK"}
    
    for module in modules:
        if module.lower() not in {m.lower() for m in KNOWN_MODULES}:
            send_telegram_alert(f"🚨 UNKNOWN MODULE DETECTED: {module}")
```

#### Риск 3: Фронт Safe Transaction Queue

Если атакующий предложит транзакцию с тем же nonce, что и легитимная — одна из них будет отвергнута при исполнении.

**Митигация:**
- Мониторь очередь транзакций
- Никогда не подписывай транзакции из неожиданных источников
- Если в очереди есть подозрительные транзакции — не подписывай ничего до выяснения

#### Риск 4: Single Vendor Firmware Compromise

Если Ledger выпустит compromised firmware — оба ключа A и B (если оба Ledger) скомпрометированы.

**Митигация (уже в схеме):** Один Ledger + один Trezor = разные производители = защита.

#### Риск 5: Социальная инженерия

Атакующий притворяется коллегой в Telegram/Discord и просит подписать "срочную" транзакцию.

**Митигация:**
- Установи правило: никогда не подписывать без проверки через независимый канал (звонок, видеозвонок)
- Все транзакции проверяются через Safe UI, не через внешние ссылки
- Владельцы Safe не публикуют свои адреса публично

#### Риск 6: Ключ оператора (hot wallet для Zodiac Roles)

Если скомпрометирован private key Python-оператора — атакующий может делать rebalance в whitelisted протоколы. Но не может вывести средства на произвольный адрес.

**Митигация:**
- Operator key хранить в HashiCorp Vault, macOS Keychain или AWS Secrets Manager — не в .env файле
- Регулярная ротация (раз в 3 месяца)
- Zodiac Roles — добавить allowance (rate limit): например, максимум $50K на одну транзакцию

### Checklist операционной безопасности

**Ежедневно:**
- [ ] Проверить balance ETH на Safe и operator wallet
- [ ] Проверить equity curve и positions через дашборд
- [ ] Убедиться что нет неожиданных pending транзакций в Safe

**Еженедельно:**
- [ ] Проверить список modules Safe (нет неизвестных)
- [ ] Проверить список owners Safe (не изменился)
- [ ] Проверить firmware версии на Ledger/Trezor (update если необходимо)

**Ежемесячно:**
- [ ] Проверить что seed phrase backup доступен (без открытия — просто убедиться что хранилище на месте)
- [ ] Тестовое подписание транзакции с каждым hardware wallet
- [ ] Ротация operator private key

**Квартально:**
- [ ] Full incident response drill (симуляция потери ключа на testnet)
- [ ] Аудит Zodiac Roles permissions (убедиться что только нужные функции разрешены)
- [ ] Проверка security bulletins: Safe, Zodiac, Ledger, Trezor

---

## Итоговая архитектура (рекомендуемая для SPA)

```
┌─────────────────────────────────────────────────────────────┐
│                    SPA Fund Safe (2/3)                      │
│   Owner A: Ledger Nano X / Flex                             │
│   Owner B: Trezor Safe 5 / Model T                          │
│   Owner C: Coldcard Q (air-gapped, у доверенного лица)      │
│                                                             │
│   Installed Modules:                                        │
│   ├── Zodiac Roles Modifier v4                              │
│   │     role: rebalancer → Python Operator (hot wallet)    │
│   │     permissions: supply/withdraw в Aave/Compound/Morpho│
│   │                                                         │
│   └── OZ TimelockController (для critical ops)             │
│         MIN_DELAY: 48h                                      │
│         proposer + executor: Safe address                   │
└─────────────────────────────────────────────────────────────┘
         │                              │
         │                              │
   Routine ops                    Critical ops
   (через Zodiac Roles)           (через TimelockController)
   ↓                              ↓
Python cycle_runner          2/3 подписи → 48h delay
executes directly            → исполнение
без Safe signatures
```

---

## Источники

- [How to Set Up a Safe Multi-Sig Wallet: Step-by-Step Guide — Cyfrin](https://www.cyfrin.io/blog/how-to-set-up-a-safe-multi-sig-wallet-step-by-step-guide)
- [Zodiac Roles Modifier — Official Docs](https://docs.roles.gnosisguild.org/)
- [Zodiac Roles SDK — Getting Started](https://docs.roles.gnosisguild.org/sdk/getting-started)
- [Lower Safe Threshold for Routine Transactions — Tutorial](https://docs.roles.gnosisguild.org/tutorials/lower-threshold-routine-transactions)
- [Safe API Kit — Propose and Confirm Transactions](https://docs.safe.global/sdk/api-kit/guides/propose-and-confirm-transactions)
- [safe-eth-py v7.21.0 — PyPI](https://pypi.org/project/safe-eth-py/)
- [Safe Transaction Service API — Safe Docs](https://docs.safe.global/core-api/transaction-service-overview)
- [Multisig Best Practices — Polygon Labs](https://polygon.technology/blog/multisig-best-practices-to-maximize-transaction-security)
- [Set Up Safe Multisig in 20 Minutes — Markaicode](https://markaicode.com/safe-multisig-ethereum-enterprise/)
- [Gnosis Safe Users Hit by $3M Exploit (SquidRouterModule) — 2026](https://www.cryptotimes.io/2026/05/25/gnosis-safe-users-hit-by-3m-exploit-tied-to-fake-token-scheme/)
- [Zodiac Delay Module Exploit — The Block](https://www.theblock.co/post/403147/gnosis-will-cover-all-user-losses-amid-exploit-related-to-gnosis-pay-co-founder-koppelmann-says)
- [Timelock Guard for Safe Wallet — Safe Community Forum](https://forum.safe.global/t/an-easy-to-use-timelock-for-the-safe-wallet/6624)
- [MPC Wallet vs Multisig — Safe Global](https://safe.global/blog/mpc-wallet-vs-multisig-what-s-the-difference-)
- [Shamir Backup SLIP-39 — Hardware Wallet Comparison](https://www.spark.money/tools/bitcoin-hardware-wallet-comparison)
- [Gelato Safe Module — GitHub](https://github.com/gelatodigital/gelato-safe-module)
