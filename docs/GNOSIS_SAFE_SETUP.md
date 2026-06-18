# Gnosis Safe Setup Checklist

**Цель:** Задеплоить Safe 2-of-3 на Ethereum mainnet → записать адрес в Keychain → GoLive check PASS.

**Время:** ~2 часа  
**Стоимость:** ~$5–20 gas (Ethereum mainnet) + железо если ещё нет  
**ADR ссылка:** docs/adr/ADR-010-gnosis-safe-key-management.md

---

## Шаг 0: Что нужно иметь

- [ ] **Ledger Nano X** (Key-A — Owner primary hardware wallet)
- [ ] **Trezor Model T** (Key-B — Owner backup hardware wallet)  
- [ ] **ETH на одном из адресов** (~$30 на gas: deploy Safe + Zodiac module)
- [ ] Chrome/Firefox с MetaMask или прямой поддержкой Ledger/Trezor
- [ ] Ledger Live + Trezor Suite установлены и устройства инициализированы

> **Если нет hardware wallets:** можно временно использовать два MetaMask аккаунта
> для тестовой конфигурации, но перед live-пилотом ОБЯЗАТЕЛЬНО перейти на hw wallets.

---

## Шаг 1: Подготовить три адреса (Key-A, Key-B, Key-C)

### Key-A (Ledger Nano X)
```
1. Открыть Ledger Live
2. Account → Ethereum → первый адрес (m/44'/60'/0'/0/0)
3. Записать адрес: 0x____________________
```

### Key-B (Trezor Model T)
```
1. Открыть Trezor Suite
2. Ethereum → первый адрес
3. Записать адрес: 0x____________________
   (должен отличаться от Key-A!)
```

### Key-C (Cold recovery)
```
Вариант 1 — Ledger offline:
  • Отключить Ledger от компа
  • Создать новый аккаунт (Add account в Ledger Live)
  • Записать seed 24 слова на бумагу / металлическую пластину
  • Адрес записать: 0x____________________

Вариант 2 — MetaMask (менее безопасно, но OK для старта):
  • Создать новый аккаунт в MetaMask
  • Account Options → Export Private Key → сохранить ТОЛЬКО в зашифрованном файле
  • Адрес записать: 0x____________________
```

---

## Шаг 2: Задеплоить Gnosis Safe

### 2.1 Открыть Safe{Wallet}
```
https://app.safe.global/new-safe
```

### 2.2 Создать новый Safe
```
1. Нажать "Create new Safe"
2. Network: Ethereum (mainnet)
3. Name: SPA-Primary
4. Owners:
   + Add owner: Key-A адрес (назвать "Owner-Primary-Ledger")
   + Add owner: Key-B адрес (назвать "Owner-Backup-Trezor")
   + Add owner: Key-C адрес (назвать "Recovery-Cold")
5. Threshold: 2 из 3
6. Review → Submit (подписать через Ledger/Trezor/MetaMask)
```

### 2.3 Подтвердить деплой
```
После подтверждения транзакции (1–2 минуты):
Safe адрес: 0x____________________  ← ЗАПИСАТЬ ЭТО
Сохранить: app.safe.global/eth:0x...
```

---

## Шаг 3: Записать SAFE_ADDRESS в Keychain

Открыть Терминал:

```bash
# Записать адрес Safe в Keychain (заменить YOUR_SAFE_ADDRESS на реальный)
security add-generic-password \
  -s "SAFE_ADDRESS_SPA" \
  -a "$USER" \
  -w "0xYOUR_SAFE_ADDRESS_HERE"

# Проверить
security find-generic-password -s "SAFE_ADDRESS_SPA" -w
```

---

## Шаг 4: Проверить GoLive checker

```bash
cd ~/Documents/SPA_Claude
python3 scripts/golive_preflight.py
```

Ожидаемый результат:
```
✅ gnosis_safe_address: SAFE_ADDRESS found in Keychain: 0x______***
```

**Это переводит gnosis_safe_address с WARN → PASS (+1 к GoLive счёту)**

---

## Шаг 5: (Позже) Zodiac Roles Module

> Этот шаг нужен ПЕРЕД live-пилотом, но не блокирует бумажный трейдинг.

```
1. В Safe UI → Apps → Zodiac
2. Add Module → Roles Modifier
3. Deploy Roles Module (ещё одна транзакция ~$5–10 gas)
4. Настроить роли EXECUTOR / GUARDIAN per ADR-010 §2.2
5. Сгенерировать spa_executor EOA:
   python3 -c "
   from eth_account import Account
   import subprocess
   acct = Account.create()
   subprocess.run(['security','add-generic-password',
     '-s','EXECUTOR_PRIVKEY_SPA','-a','spa',
     '-w', acct.key.hex()])
   print('Executor address:', acct.address)
   "
6. Добавить адрес executor в docs/keys/pubkeys.txt
```

---

## Текущий статус

| Шаг | Статус |
|-----|--------|
| Key-A (Ledger) — адрес записан | ⬜ Не начато |
| Key-B (Trezor) — адрес записан | ⬜ Не начато |
| Key-C (Cold recovery) | ⬜ Не начато |
| Safe 2-of-3 задеплоен на mainnet | ⬜ Не начато |
| SAFE_ADDRESS в Keychain | ⬜ Не начато |
| Zodiac Roles задеплоен | ⬜ Не начато (до live-пилота) |
| spa_executor EOA сгенерирован | ⬜ Не начато (до live-пилота) |

---

*Last updated: 2026-06-18*  
*See also: docs/adr/ADR-010-gnosis-safe-key-management.md*
