# DeFi Smart Contract Vault — Аудит и Безопасность

**Дата:** 2026-06-18  
**Контекст:** ERC-4626 vault для внешнего капитала ($1–10M AUM, 2027).  
Vault управляется off-chain optimizer (Python) через Gnosis Safe 2/3 multisig.  
Цель документа — scope и бюджет для Q4 2026 подготовки к аудиту.

---

## 1. ERC-4626 — типичные уязвимости и защита в дизайне

### 1.1 Инфляционная атака (Inflation / First-Depositor Attack)

**Механизм.** Атакующий становится первым вкладчиком: вносит 1 wei → получает 1 share. Затем «донирует» большую сумму напрямую на адрес vault (минуя `deposit()`), раздувая `totalAssets` при неизменном `totalSupply`. Следующий легитимный вкладчик получает 0 shares из-за округления вниз — атакующий выводит всё.

**Задокументированные случаи.** В феврале 2025 протокол Venus на ZKsync подвергся аналогичной атаке — атакующий получил около 86 WETH при значительном bad debt у протокола (Rivanorth, 2025).

**Защита в дизайне (выбрать одно или комбинацию):**

- **OpenZeppelin Virtual Shares + Decimals Offset** — рекомендованный production-подход. OZ ERC4626 добавляет `10^offset` виртуальных shares и assets в знаменатель/числитель exchange rate. Offset 3–6 делает атаку убыточной: при `decimalsOffset=3` атакующему нужно задонировать в 1000× больше, чтобы «сдвинуть» цену. Это стандартная реализация в `openzeppelin-contracts ≥ 4.9`. **Используй это как базу.**

- **Dead Shares (Uniswap V2 паттерн)** — mint фиксированного количества shares на `address(0)` при инициализации. Uniswap V2 минтит 1000 MINIMUM_LIQUIDITY. Снижает риск, но не устраняет полностью; эти assets «заперты» навсегда.

- **Morpho DAO паттерн** — депозит assets из treasury в vault при деплое; shares минтятся на сам vault (неоперационный адрес). Требует предвычисления адреса vault до деплоя (`CREATE2`) и предварительного `approve`. Дороже операционно, но решает проблему полностью.

- **Internal totalAssets tracking** — vault не использует `balanceOf(address(this))`, а ведёт внутренний счётчик. Донации не учитываются. Минус: не работает с rebasing-токенами.

**Вывод для SPA:** Использовать OZ ERC4626 с `_decimalsOffset = 6` — это защищает без lock-up assets и без gas overhead.

### 1.2 Sandwich-атака (MEV / Front-running)

**Механизм.** Бот наблюдает mempool, видит крупный `harvest()` (стратегия собирает yield), который увеличит `totalAssets`. Бот front-runs: депозит перед harvest → share price растёт → withdraw сразу после. Легитимные LP несут потери.

**Защита:**

- **Smooth yield accrual** — не зачислять весь yield одной транзакцией; линейная/логарифмическая раскатка yield за период (например, 7 дней). Morpho Steakhouse использует этот подход.
- **Private transactions (Flashbots / MEV Blocker)** — `harvest()` отправлять через приватный RPC, минуя публичный mempool.
- **Short-term withdrawal lockup / exit fee** — небольшая временная блокировка (1–24h) или exit fee делает sandwich-атаку нерентабельной.
- **Checkpoint snapshots** — snapshot exchange rate до harvest; shares вычисляются по pre-harvest rate.

### 1.3 Re-entrancy

**Механизм.** ERC777 hooks или внешние вызовы в `deposit`/`withdraw` позволяют атакующему рекурсивно вызвать vault до обновления state — классический re-entrancy вектор.

**Защита:**

- **Checks-Effects-Interactions (CEI)** — паттерн обязателен: сначала проверки, затем обновление storage, затем внешние вызовы.
- **`nonReentrant` модификатор** (OpenZeppelin `ReentrancyGuard`) — на все функции `deposit`, `mint`, `withdraw`, `redeem`.
- **Избегать ERC777** как underlying asset — предпочитать стандартный ERC20 (USDC, WETH).
- **SafeERC20** для всех `transfer`/`transferFrom`.
- **Кастомные хуки** (`beforeWithdraw`, `afterDeposit`) — защищать через `nonReentrant` или вообще не делать внешних вызовов внутри хуков.

### 1.4 Прочие критические уязвимости ERC-4626

По данным Solodit, из 265 зафиксированных findings по ERC-4626, **169 имеют HIGH/MEDIUM severity** (Composable Security, 2024). Топ уязвимостей помимо инфляции:

| Уязвимость | Вектор | Митигация |
|---|---|---|
| **Oracle manipulation** | Spot price → мискалькуляция shares | TWAP, sanity checks, circuit breakers |
| **Decimal mismatch** | Underlying (6 dec) ≠ shares (18 dec) → ценовой mismatch | Нормализовать decimals в `convertToShares/Assets` |
| **Non-standard tokens** | Fee-on-transfer, rebasing | Проверять actual received amount; `_decimalsOffset` |
| **Rounding errors** | Integer division → dust accumulation | Multiply-before-divide; round в пользу vault |
| **Logic bugs** в deposit/mint/withdraw/redeem | Несинхронизированные `shares`/`assets` | `assert(balanceOf() >= expected)` после операции |
| **totalAssets() manipulation** | Прямой transfer → раздувает знаменатель | Internal accounting вместо `balanceOf()` |
| **MEV fee extraction** | Front-run перед `harvest()` | Smooth accrual + private mempool |

---

## 2. Gnosis Safe + Zodiac Roles Module: Ограничение оператора

### Концепция

Zodiac Roles Modifier — onchain permissions module для smart accounts (Safe). Позволяет создавать роли с **гранулярными разрешениями** на уровне адреса → функции → параметров. Модуль аттачится к Safe как Zodiac module и позволяет внешнему адресу (Python bot / operator EOA) выполнять разрешённые транзакции **без подписей мультисига**.

Это решает проблему: оператор может вызывать `rebalance()` автономно, но не может вызвать `withdraw()` или `changeOwner()`.

### Архитектура для SPA Vault

```
Gnosis Safe (2/3 multisig)
    └── Zodiac Roles Modifier (module)
          ├── Role: OPERATOR
          │     ├── allow: vault.rebalance(pool, amount)
          │     ├── allow: vault.harvest()
          │     ├── allow: vault.setTargetAllocation(pool, pct)
          │     ├── conditions: amount ≤ MAX_REBALANCE_AMOUNT (e.g. 10%)
          │     └── allowances: max N calls per 24h (rate limiting)
          │
          └── Role: ADMIN (только multisig)
                ├── allow: vault.setFee()
                ├── allow: vault.upgradeVault()
                ├── allow: vault.withdrawAll()
                └── allow: vault.pause()
```

### Конкретные возможности Zodiac Roles v4

- **Fine-grained parameter conditions** — можно ограничить `amount` не превышающим порог через conditions system (`bitmask`, `withinAllowance`, `equalsTo`).
- **Allowances (rate limits)** — лимиты на частоту вызовов. Например, `rebalance()` не чаще 1 раза в 6 часов.
- **Transaction unwrapping** — если нужно вызвать через batched transactions или Multicall, Zodiac умеет «разворачивать» и проверять каждый вложенный вызов.
- **Delegate calls** — можно запретить delegate calls полностью, только regular calls.
- **ETH value restriction** — запретить отправку ETH в вызовах (для USDC-vault это критично).

### Критически важно НЕ разрешать оператору

- `withdraw()` / `withdrawAll()` — только multisig
- `changeOwner()` / `setAdmin()`
- `setFee()` без timelock
- `upgradeImplementation()` (если upgradeable)
- Любые функции, меняющие whitelist протоколов

### Рекомендации

1. Использовать **Zodiac Roles v4** (актуальная версия, май 2026).
2. Оператор — отдельный EOA (не multisig signer), ключ в HSM или secure enclave.
3. Реализовать on-chain event log каждого вызова оператора (emit `OperatorAction(pool, amount, timestamp)`).
4. Тестировать permissions через Zodiac Pilot (web UI) перед деплоем.

---

## 3. Timelock: Нужен ли и какой период?

### Для чего нужен timelock в vault

Timelock вводит задержку между **одобрением** изменения (multisig) и его **исполнением**. За это время:
- LP могут exit при несогласии
- Сообщество может сигнализировать о проблемах
- Создаётся окно для реакции на компрометацию multisig

### Минимальные периоды по категориям (2024–2025 best practice)

| Изменение | Минимум | Рекомендация |
|---|---|---|
| Параметры стратегии (fee, allocation caps) | 24h | 48h |
| Добавление нового протокола в whitelist | 48h | 72h |
| Смена оператора / роли | 24h | 48h |
| Upgrade контракта (proxy) | 72h | 7 days |
| Emergency withdraw / circuit breaker | 0h (instant) | 0h с 2/3 multisig |

**Примеры:**
- Compound — 48h timelock на все governance proposals
- MakerDAO — 12h minimum (ранний период), затем увеличен
- Morpho Vault V2 — timelock + in-kind redemption для non-custodial статуса (ChainSecurity audit, 2024)
- Типичный best practice для $1–10M vault: **48h для параметров, 7 дней для upgrades**

### Нужен ли timelock на SPA Vault?

**Да, обязателен** — без timelock vault считается custodial (владелец multisig может в любой момент изменить параметры в ущерб LP). Для институциональных LP (Family Fund) это блокер.

**Рекомендация:**
- Реализовать через OpenZeppelin `TimelockController`
- Минимальный delay: `MIN_DELAY = 48 hours` для parameter changes
- Для upgrade: `MIN_DELAY = 7 days`
- Emergency pause (circuit breaker): instant с 2/3 multisig, но без возможности withdraw — только freeze

---

## 4. Bug Bounty: Immunefi для $1–5M TVL

### Стандарт Immunefi: Scaling Bug Bounty

Immunefi рекомендует: **критический payout = 10% от assets at risk (FAR)**. Это делает раскрытие уязвимости финансово выгоднее эксплойта даже для blackhat (с учётом laundering costs и jail risk).

### Расчёт бюджета для SPA ($1–5M TVL)

| TVL | Критический bounty (10% FAR) | Recommended reserve (2–3×) |
|---|---|---|
| $1M | $100,000 | $200,000–$300,000 |
| $3M | $300,000 | $600,000–$900,000 |
| $5M | $500,000 | $1,000,000–$1,500,000 |

**Но реально для нового проекта с $1–5M TVL:**

- **Critical max: $50,000–$100,000** (5–10% FAR при $1M start)
- **High: $10,000–$25,000**
- **Medium: $1,000–$5,000**
- **Pre-fund резерв: 2–3× max critical** — держать на multisig escrow

### Структура программы на Immunefi

- Immunefi берёт **10% от выплаченного bounty** (платит проект, не исследователь)
- Платформа **бесплатная** для листинга, fee только при выплате
- Средний подтверждённый payout на Immunefi: ~$2,000; critical smart contract bugs: ~$13,000
- Минимальный critical bounty для привлечения топ-исследователей: **≥ $50,000**

### Когда запускать

- **После первого аудита** (не до)
- Программа запускается публично после fix всех Critical/High findings
- Рекомендуется: **2–3 месяца после деплоя** в mainnet

### Бюджет для Q4 2026 подготовки

| Статья | Сумма |
|---|---|
| Immunefi платформа (setup) | $0 |
| Escrow резерв (3× critical) | $150,000–$300,000 |
| Immunefi fee (10% от выплат) | ~$5,000–$30,000 (зависит от находок) |

---

## 5. Аудиторские компании: Spearbit vs Trail of Bits vs OpenZeppelin

### Ценовые ориентиры 2026 (публичные данные ARDC / DAO proposals)

| Компания | Ставка | Источник |
|---|---|---|
| Trail of Bits | **$25,000/engineer-week** | Arbitrum ARDC proposal |
| OpenZeppelin | **$25,000/engineer-week** | Arbitrum ARDC proposal |
| Spearbit | **$32,500–$48,000/team-week** (3–5 researchers) | ARDC proposal |
| Dedaub | **$3,500/engineer-day** (min 2 auditors) | ARDC proposal |
| Runtime Verification | **$20,000/week**, 3 weeks per 1,000 LOC | RV website |
| Quantstamp | **$130,000 retainer** = 10 audit weeks (400h) | Venus DAO |
| Certora x Aave (2025) | $2.39M/year для 4.5 FTE | Aave governance |

### Специализация компаний

**Trail of Bits (ToB)**
- Gold standard для cryptographic, ZK work, fuzzing (Echidna, Slither авторы)
- Создают кастомные инструменты под каждый проект
- Named engineers, dedicated PM, weekly updates
- Лучший выбор если vault использует ZK-proofs или complex cryptography
- Для yield vault: хорошо, но premium sticker price

**OpenZeppelin**
- Авторы библиотек, которые vault будет использовать → глубокое знание базы
- Лучший для vault на OZ Contracts basis
- Имеют аудиты Scroll, Aave, Compound, Morpho
- Недавно: audit Very Liquid Vaults (yield-vault специализация)
- **Рекомендован как первый аудит** для ERC-4626 vault

**Spearbit / Cantina**
- Marketplace model: named researchers, competitive rates
- Специализируются на DeFi primitives, lending, vaults
- Spearbit audited Yield Vaults проекты в portfolio
- Немного дороже ToB/OZ на командную неделю
- Хорошо как **второй независимый аудит**

**Дополнительно для рассмотрения:**
- **ChainSecurity** — аудитор Morpho Vault V2 (ERC-4626 + timelock + non-custodial); специалисты в yield vaults
- **Dedaub** — хорошее соотношение качество/цена, ставка $3.5k/день
- **Runtime Verification** — если нужна формальная верификация в комплекте

### Что проверяют при аудите yield vault

1. Корректность `totalAssets()` и share price calculation
2. Защита от inflation attack
3. Reentrancy во всех entry points
4. Access control (кто может вызвать что)
5. Arithmetic: rounding, overflow, precision
6. Integration с external protocols (Aave, Compound и т.д.)
7. Upgrade patterns (если upgradeable)
8. Emergency mechanisms (pause, circuit breaker)
9. Oracle dependencies
10. Gas optimization (DoS via gas limit)

### Сколько стоит аудит SPA Vault (est. 500–1,500 LOC)

По RV rule: 500–1,500 LOC ≈ **2–5 weeks** (1 аудитор).

| Вариант | Состав | Стоимость |
|---|---|---|
| OpenZeppelin (1 аудит) | 2 engineers × 2 weeks | **$100,000** |
| Trail of Bits (1 аудит) | 2 engineers × 2 weeks | **$100,000** |
| Spearbit (1 аудит) | team × 2 weeks | **$65,000–$96,000** |
| Re-audit (любая компания) | 1 engineer × 1 week | **$25,000** |
| Dedaub (alternative) | 2 engineers × 2 weeks (10 days) | **$70,000** |
| **TOTAL (OZ + Spearbit, 2 audits + re-audit)** | | **~$250,000–$300,000** |

---

## 6. Два аудита: достаточно ли, или нужно три?

### Best Practice рынка 2024–2025

**Для $1–10M TVL vault: два аудита от независимых компаний + публичный конкурс достаточны.**

Три аудита от разных компаний стандартны для:
- TVL > $50M
- Cross-chain bridges
- Rollup contracts
- Enterprise / institutional (банки, фонды)

### Рекомендованный security lifecycle для SPA

```
Q4 2026: Design review (thread model, architecture)
         └─► Audit #1 (OpenZeppelin или ChainSecurity) — ERC-4626 base
Q4 2026: Fix all Critical/High → Re-audit #1 (same firm)
Q1 2027: Audit #2 (Spearbit или Dedaub) — независимый взгляд
         └─► Fix Medium+ → Re-audit #2
Q1 2027: Code4rena / Sherlock contest ($37,500–$75,000 pool) — crowd review
Q2 2027: Bug bounty launch (Immunefi)
Q2 2027: Mainnet deploy
```

**Почему именно так:**

- Первый аудит ловит структурные проблемы
- Второй независимый аудит даёт разные «глаза» — разные фирмы находят разные баги (blind spots существуют)
- Конкурс (crowd audit) дёшево даёт Coverage широты, которую два аудита не дают
- Bug bounty — постоянная защита после деплоя

### Данные по эффективности

По данным Pharos Production (2026 State of Smart Contract Audits), **многофирменный audit cycle сейчас стандарт для любого TVL > $50M**. Для $1–10M — два аудита + конкурс считаются достаточными и cost-efficient.

---

## 7. Formal Verification: Нужна ли для vault этого размера?

### Позиция рынка 2025

- Formal verification adoption пересекла inflection point в 2025: **~1/3 высококапитализированных проектов** добавляют как минимум одну Certora/Halmos invariant suite
- Multi-firm audit + FV стандарт для TVL > $50M (Aave, Compound, Morpho)
- Для $1–10M TVL: FV **не обязательна**, но **рекомендована частично**

### Что изменилось: Certora Prover стал Open Source

В 2025 Certora открыла исходный код Certora Prover — теперь **лицензия бесплатна**. Это меняет cost-benefit уравнение.

### Рекомендация для SPA Vault

**Полная коммерческая FV (Certora/RV) — избыточна при $1–5M TVL.** Годовой контракт Certora (как у Aave) стоит $2.39M — несоразмерно.

**Целесообразно (и бесплатно/дёшево):**

1. **Halmos / Foundry symbolic execution** — бесплатный open-source FV через Foundry (`forge` + invariant tests). Можно доказать: `convertToAssets(convertToShares(x)) ≈ x`, `totalAssets ≥ Σ positions`, `no share dilution`.

2. **a16z ERC4626 Property Tests** — готовый набор fuzzing тестов специально для ERC-4626 стандарта (GitHub: `a16z/erc4626-tests`). Используй обязательно.

3. **Echidna fuzzing** — инструмент от Trail of Bits, бесплатный, идеален для invariant testing vault. Может запустить аудиторская команда как часть engagement.

4. **Certora Prover (самостоятельно)** — теперь open source; написать specs для 3–5 ключевых свойств vault. Требует времени на обучение.

### Что именно верифицировать

| Инвариант | Метод |
|---|---|
| `totalSupply > 0 → totalAssets ≥ totalSupply × virtualOffset` | Halmos/Certora |
| `deposit(x) → balanceOf += shares; shares > 0` | Echidna |
| `withdraw(shares) → assets ≤ totalAssets` (solvency) | Certora |
| `no inflation attack possible after seed` | a16z ERC4626 tests |
| `operator cannot call withdraw()` (Zodiac) | Unit tests |

### Вывод

FV в виде Certora commercial engagement **не нужна** при $1–5M TVL. Достаточно: **a16z ERC4626 property tests + Echidna fuzzing + Halmos для 3–5 ключевых инвариантов**. Это бесплатно и даст 80% защиты от логических багов.

---

## 8. On-Chain Proof-of-Track: Merkle Root Decision Log

### Концепция

Для институциональных LP важно **верифицировать**, что off-chain optimizer принимал решения по заявленной логике (RiskPolicy) — а не произвольно. Merkle root decision log позволяет:

1. Хранить все решения off-chain (дёшево, приватно)
2. Публиковать only **Merkle root** on-chain (32 bytes per batch)
3. Любой может верифицировать конкретное решение с помощью **inclusion proof** (sibling hashes)

### Архитектура

```
Off-chain (Python SPA)
    ├── каждый цикл: записать DecisionRecord
    │     {timestamp, strategy, action, pool, amount, risk_check_result, policy_hash}
    ├── batch N записей в Merkle leaf set
    │     leaf = keccak256(abi.encode(DecisionRecord))
    └── build Merkle tree → compute root

On-chain (Smart Contract / Safe exec)
    └── anchor root: emit MerkleAnchor(batchId, root, timestamp, cycle_count)
```

### Смарт-контракт: минимальная реализация

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract DecisionLog {
    struct Anchor {
        bytes32 merkleRoot;
        uint256 timestamp;
        uint256 cycleCount;
        string metadataURI; // IPFS/Arweave link to full batch data
    }
    
    mapping(uint256 => Anchor) public anchors;
    uint256 public batchCount;
    address public immutable vault;
    
    event MerkleAnchor(
        uint256 indexed batchId,
        bytes32 merkleRoot,
        uint256 timestamp,
        uint256 cycleCount
    );
    
    modifier onlyVault() {
        require(msg.sender == vault, "Unauthorized");
        _;
    }
    
    function anchor(
        bytes32 merkleRoot,
        uint256 cycleCount,
        string calldata metadataURI
    ) external onlyVault {
        uint256 batchId = batchCount++;
        anchors[batchId] = Anchor({
            merkleRoot: merkleRoot,
            timestamp: block.timestamp,
            cycleCount: cycleCount,
            metadataURI: metadataURI
        });
        emit MerkleAnchor(batchId, merkleRoot, block.timestamp, cycleCount);
    }
    
    // Verify inclusion of a decision
    function verify(
        uint256 batchId,
        bytes32 leaf,
        bytes32[] calldata proof
    ) external view returns (bool) {
        bytes32 root = anchors[batchId].merkleRoot;
        return MerkleProof.verify(proof, root, leaf);
    }
}
```

### Python сторона (SPA integration)

```python
import hashlib
import json

def make_leaf(decision: dict) -> bytes:
    """Canonical encoding of a decision record"""
    encoded = json.dumps(decision, sort_keys=True, separators=(',', ':'))
    return hashlib.sha3_256(encoded.encode()).digest()

def build_merkle_tree(leaves: list[bytes]) -> tuple[bytes, list]:
    """Build Merkle tree, return (root, proof_sets)"""
    # Standard binary Merkle tree implementation
    # Use OpenZeppelin's format: sort pairs before hashing
    ...

# Per daily cycle:
decision = {
    "timestamp": "2026-06-18T08:00:00Z",
    "cycle_id": 8,
    "strategy": "S2",
    "action": "rebalance",
    "pool": "aave_v3_usdc",
    "amount_usdc": 12000,
    "risk_approved": True,
    "policy_hash": "sha256:abc123...",
    "equity_before": 100234.50,
    "equity_after": 100286.70
}
leaf = make_leaf(decision)
```

### Периодичность anchoring

- **Ежедневно** (после каждого цикла) — дорого (~$0.50–$2 per anchor на Ethereum mainnet)
- **Еженедельно** (батч 7 дней) — оптимально для начала
- **Arweave/IPFS для raw data** — хранить полный batch json на Arweave, anchor только root on-chain

### Преимущества для институциональных LP

- Доказывает, что optimizer следовал RiskPolicy (не мог изменить решение задним числом)
- Auditor может верифицировать любое историческое решение
- Регуляторная прозрачность: MiFID II-стиль audit trail

### Ограничения

- Не доказывает **правильность** решений, только их **неизменность**
- Off-chain данные (IPFS/Arweave) могут стать недоступны — нужен собственный хостинг
- Anchoring costs: ~$100–200/год при weekly frequency на Ethereum

---

## 9. Сводный бюджет и план Q4 2026 — Q2 2027

### Финансовый план безопасности

| Статья | Срок | Стоимость |
|---|---|---|
| **Audit #1** (OpenZeppelin / ChainSecurity) | Q4 2026 | **$80,000–$120,000** |
| **Re-audit #1** (same firm, после фиксов) | Q4 2026 | **$20,000–$30,000** |
| **Audit #2** (Spearbit / Dedaub, независимый) | Q1 2027 | **$65,000–$100,000** |
| **Re-audit #2** (same firm) | Q1 2027 | **$15,000–$25,000** |
| **Code4rena / Sherlock contest** | Q1 2027 | **$37,500–$75,000** (pool) |
| **Immunefi bug bounty escrow** | Q2 2027 | **$150,000–$300,000** |
| **Zodiac Roles deployment + audit** (модуль) | Q4 2026 | **$5,000–$15,000** |
| **Formal verification (DIY: Echidna + Halmos)** | Q4 2026 | **$0–$10,000** (время команды) |
| **Decision Log contract deployment** | Q1 2027 | **$2,000–$5,000** |
| **Arweave storage (2 years)** | Q2 2027 | **$500–$2,000** |
| **ИТОГО** | | **~$375,000–$680,000** |

### Минимально жизнеспособный security stack (MVP)

Если бюджет ограничен — минимум для launch при $1–5M TVL:

| Статья | Стоимость |
|---|---|
| Audit #1 (Dedaub или boutique firm) | $60,000–$80,000 |
| Re-audit | $15,000–$25,000 |
| Audit #2 (другая фирма) | $50,000–$70,000 |
| Code4rena small contest | $37,500 |
| Immunefi escrow | $100,000–$150,000 |
| **ИТОГО MVP** | **~$262,500–$362,500** |

### Временной план

```
Июнь–Июль 2026:   ├── Написать vault контракт (Solidity)
                   ├── Написать Zodiac Roles конфигурацию
                   └── Написать invariant tests (a16z + Echidna)

Август 2026:       ├── RFP → выбрать Audit #1 firm
                   └── Заморозить код (commit hash), начать аудит

Сентябрь 2026:     ├── Получить Audit #1 report
                   ├── Fix Critical + High findings
                   └── Re-audit #1

Октябрь–Ноябрь 2026:  ├── RFP → Audit #2 (независимая компания)
                       └── Audit #2 + Re-audit #2

Декабрь 2026:      └── Code4rena/Sherlock contest

Январь–Февраль 2027:  ├── Fix contest findings
                       └── Deploy Decision Log contract

Март 2027:         ├── Immunefi bug bounty launch
                   └── Testnet deploy с реальными LP

Апрель–Май 2027:   └── Mainnet launch при $1M TVL cap (поднимать постепенно)
```

---

## 10. Ключевые выводы

1. **ERC-4626:** Использовать OpenZeppelin implementation с `_decimalsOffset ≥ 3`. Это single best protection против inflation attack. Добавить `nonReentrant` + CEI паттерн обязательно.

2. **Gnosis Safe + Zodiac Roles v4** — правильный инструмент для разграничения: оператор только rebalance, мультисиг для всего остального. Обязательно добавить rate limits через Allowances.

3. **Timelock:** Обязателен. Минимум 48h для parameter changes, 7 дней для upgrades. Без timelock vault custodial — неприемлемо для внешних LP.

4. **Immunefi:** Запустить после двух аудитов. Critical bounty = 10% FAR. При $1M TVL: $100,000 cap, prefund 2–3× = $200,000–$300,000.

5. **Аудиторы:** OpenZeppelin или ChainSecurity как первый аудит (специализация на ERC-4626); Spearbit или Dedaub как второй независимый. Бюджет: $80–120K + $65–100K.

6. **Количество аудитов:** Два аудита + конкурс = достаточно для $1–10M TVL. Три аудита стандарт для $50M+.

7. **Formal Verification:** Certora commercial engagement избыточен при $1–5M TVL. Использовать бесплатные инструменты: a16z ERC4626 property tests, Echidna, Halmos. Запустить до аудита — аудиторам понравится.

8. **Proof-of-Track:** Merkle root anchoring практически реализуем (~500 LOC Python + 100 LOC Solidity). Anchoring раз в неделю стоит ~$100/год. Даёт институциональную прозрачность и защиту от arbitrary decision-making.

---

## Источники

- [A Novel Defense Against ERC4626 Inflation Attacks — OpenZeppelin](https://www.openzeppelin.com/news/a-novel-defense-against-erc4626-inflation-attacks)
- [ERC-4626 Vulnerabilities and How to Avoid Them — Rivanorth](https://rivanorth.com/blog/erc-4626-vulnerabilities-and-how-to-avoid-them-in-your-project)
- [ERC-4626: Easy To Understand Essentials — Composable Security](https://composable-security.com/blog/erc-4626-easy-to-understand-essentials/)
- [ERC4626 Vaults: Secure Design, Risks & Best Practices — Speedrun Ethereum](https://speedrunethereum.com/guides/erc-4626-vaults)
- [Zodiac Roles Modifier Documentation — Gnosis Guild](https://docs.roles.gnosisguild.org/)
- [zodiac-modifier-roles GitHub — Gnosis Guild](https://github.com/gnosisguild/zodiac-modifier-roles)
- [2026 Smart Contract Audit Costs — 7BlockLabs](https://www.7blocklabs.com/blog/smart-contract-audit-cost-range-2026-and-trail-of-bits-smart-contract-audit-cost-benchmarks)
- [Top 10 Best Smart Contract Auditing Companies in 2026 — Sherlock](https://sherlock.xyz/post/top-10-best-smart-contract-auditing-companies-in-2026)
- [State of Smart Contract Audits 2026 — Pharos Production](https://pharosproduction.com/insights/engineering/state-of-smart-contract-audits-2026/)
- [A DeFi Security Standard: The Scaling Bug Bounty — Immunefi](https://immunefi.com/blog/industry-trends/a-defi-security-standard-the-scaling-bug-bounty/)
- [Morpho Vault V2 Audit — ChainSecurity](https://www.chainsecurity.com/security-audit/morpho-vault-v2)
- [ERC-4626 Inflation Attack on Vault — Zellic/Perennial](https://reports.zellic.io/publications/perennial/findings/critical-vaultsol-erc-4626-inflation-attack-on-vault)
- [Building Tamper-Evident Audit Trails — DEV Community / VeritasChain](https://dev.to/veritaschain/building-tamper-evident-audit-trails-for-algorithmic-trading-a-developers-guide-4ie2)
- [ERC-4626 Tokens in DeFi: Exchange Rate Manipulation Risks — OpenZeppelin](https://www.openzeppelin.com/news/erc-4626-tokens-in-defi-exchange-rate-manipulation-risks)
- [Certora Open-Sources Prover — Decrypt](https://decrypt.co/307487/certora-open-sources-the-certora-prover-bringing-industrial-grade-formal-verification-to-the-web3-community)
