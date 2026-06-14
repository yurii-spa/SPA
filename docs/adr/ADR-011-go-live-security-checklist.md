# ADR-011: Go-Live Security Checklist

| Field           | Value                                               |
|-----------------|-----------------------------------------------------|
| **Date**        | 2026-06-12                                          |
| **Status**      | Proposed                                            |
| **Author**      | Claude (SPA Architect)                              |
| **Approved by** | Pending — Owner (Yurii) sign-off required           |
| **MP ref.**     | MP-402 (security policy), MP-403 (live pilot)       |
| **ADR number**  | ADR-011                                             |
| **Depends on**  | ADR-002 (go-live transfer rule), ADR-010 (key mgmt) |

---

## Context

Переход от paper trading к live execution с реальным капиталом $10–50K —
необратимое действие с реальными финансовыми последствиями. Этот документ
определяет **минимально необходимый security checklist** для этого перехода.

Все пункты должны быть отмечены `[x]` и подписаны Owner перед выполнением
`python3 -m spa_core.golive.activate`.

Ни один пункт не может быть пропущен или помечен «N/A» без нового ADR.

---

## Checklist

### Группа A: Smart Contract Safety

**A1** `[ ]` Safe 2-of-3 задеплоен на mainnet и адрес записан в ADR-010.

**A2** `[ ]` Zodiac Roles module задеплоен, роли EXECUTOR и GUARDIAN настроены
согласно ADR-010 §2.2.

**A3** `[ ]` EXECUTOR права ограничены whitelist'ом: только USDC как актив,
только whitelisted контракты протоколов (Aave V3, Compound V3, Morpho Blue,
Yearn V3, Euler V2). Ни одного `delegatecall` или `ETH transfer` в whitelist.

**A4** `[ ]` MAX_SINGLE_TX ≤ 20% AUM и MAX_DAILY_VOLUME ≤ 40% AUM установлены
в Zodiac Roles и верифицированы on-chain через Tenderly Simulator.

**A5** `[ ]` Zodiac Delay (Timelock) настроен: min_delay ≥ 24ч для лимитов,
≥ 48ч для whitelist изменений, ≥ 72ч для threshold.

**A6** `[ ]` E2E тест на Sepolia fork выполнен успешно:
  - Deposit USDC через cycle_runner → Safe → Aave V3
  - Withdraw USDC из Aave V3 → Safe
  - GUARDIAN revoke EXECUTOR → подтверждено что hot-key потерял права
  - Recovery через Key-B + Key-C (без Key-A)

**A7** `[ ]` Все контрактные адреса протоколов в whitelist сверены с официальными
docs (Aave: aave.com/docs, Compound: docs.compound.finance, Morpho: morpho.xyz/docs)
— нет ни одного устаревшего или неофициального адреса.

**A8** `[ ]` На mainnet Safe выполнена тестовая транзакция с минимальной суммой
($1 USDC) через cycle_runner → Safe → Aave V3 → обратно в Safe.
Транзакция проверена на Etherscan.

**A9** `[ ]` Версии смарт-контрактов зафиксированы:
  - Safe: версия _______ (проверено через `getSingleton()`)
  - Zodiac Roles: версия _______
  - Timelock: версия _______

---

### Группа B: Key Management

**B1** `[ ]` Hardware wallet Key-A (Ledger Nano X) получен, BIP39 seed записан
на бумаге/металле и хранится отдельно от устройства. Устройство PIN-защищено
и BIP39 passphrase установлен.

**B2** `[ ]` Hardware wallet Key-B (Trezor Model T) получен, BIP39 seed записан
и хранится в физически другом месте, чем Key-A. PIN и passphrase установлены
(другой passphrase чем у Key-A).

**B3** `[ ]` Cold seed Key-C сгенерирован на offline-устройстве (Ledger без
подключения к ПК или air-gapped machine), записан на металлическую пластину
(CryptoSteel или аналог), помещён в физический сейф. Устройство после генерации
сброшено к заводским настройкам.

**B4** `[ ]` Публичные адреса всех 3 signer'ов записаны в `docs/keys/pubkeys.txt`
(ТОЛЬКО адреса, никаких приватных ключей или seed-фраз).

**B5** `[ ]` EXECUTOR hot key сгенерирован в памяти и сохранён ИСКЛЮЧИТЕЛЬНО в
macOS Keychain под ключом `EXECUTOR_PRIVKEY_SPA`. Нигде не записан в файл,
переменную окружения, лог или историю terminal. Проверено: `grep -r 'EXECUTOR_PRIVKEY'
~/Documents/SPA_Claude` — нет результатов кроме кода чтения из Keychain.

**B6** `[ ]` Проверена политика ротации:
  - Дата следующей ротации EXECUTOR: `___________` (через 90 дней)
  - Дата напоминания добавлена в KANBAN.json (аналог MP-071 для PAT)

**B7** `[ ]` SECRETS POLICY соблюдена (инцидент 2026-06-10):
  - `grep -r 'ghp_\|0x[0-9a-f]\{64\}' ~/Documents/SPA_Claude` — нет приватных ключей
  - Нет push_*.html артефактов
  - Нет токенов/ключей в CLAUDE.md, docs/, data/

**B8** `[ ]` Процедура emergency revoke протестирована: использован Key-A для
revoke EXECUTOR роли через Zodiac UI, затем восстановлена роль через Safe
2-of-3. Время операции замерено: _______ минут.

**B9** `[ ]` Multisig recovery procedure из ADR-010 §2.6 прочитана и понята
Owner. Физически проверено что Key-B и Key-C доступны независимо от Key-A.

---

### Группа C: Operational Monitoring

**C1** `[ ]` Telegram-алерт (spa_core/alerts/) настроен и верифицирован:
  - CRITICAL алерт доставляется в реальном времени
  - RiskPolicy kill-switch алерт
  - Gap в equity curve алерт
  - Anomalous transaction алерт (нехарактерный объём или адрес)

**C2** `[ ]` gap_monitor.py работает без пропусков 30 дней подряд до перехода.
Файл `data/gap_monitor.json`: `gaps: []`, `max_gap_days: 0`.

**C3** `[ ]` GoLiveChecker статус READY 7 дней подряд (ADR-002). Поле в
`data/golive_status.json`: `consecutive_ready_days ≥ 7`.

**C4** `[ ]` cycle_runner работает стабильно ≥ 30 дней: нет крашей, все 6
критериев GoLiveChecker зелёные, `data/risk_policy_blocks.json` содержит
объяснения блокировок (не пуст и не содержит аномальных паттернов).

**C5** `[ ]` Дашборд доступен: httpserver (com.spa.httpserver) и cloudflared
(com.spa.cloudflared) работают. Инвестор может посмотреть equity curve
и позиции в реальном времени.

**C6** `[ ]` На live-аккаунте настроен wallet monitoring:
  - Etherscan address alerts для Safe address
  - Etherscan address alerts для EXECUTOR address
  - Telegram-уведомление при любой транзакции с Safe

**C7** `[ ]` RiskPolicy kill-switch (drawdown ≥ 5%) протестирован в isolated
environment: при симуляции drawdown ≥ 5% система блокирует новые позиции.

**C8** `[ ]` Определено время реакции Owner при CRITICAL алерте: _______ минут.
Если Owner недоступен более 4 часов — fallback процедура: ___________________

**C9** `[ ]` Логи cycle_runner за последние 30 дней проверены Owner:
  - `/tmp/spa_cycle.log` — нет неожиданных паттернов
  - `/tmp/spa_cycle_err.log` — нет неустранённых ошибок

---

### Группа D: Legal & Regulatory

**D1** `[ ]` Юридическая структура для управления собственными средствами
определена. Для пилота $10–50K собственных средств (не клиентских):
  - Достаточно физического лица (Owner) или ИП/ФЛП
  - Документ `docs/LEGAL_STRUCTURE_v1.md` актуален
  - Налоговые обязательства по DeFi yield в юрисдикции Owner понятны

**D2** `[ ]` Активы на Safe — исключительно собственные средства Owner.
Никаких клиентских денег до получения лицензии (если требуется в юрисдикции).

**D3** `[ ]` Owner понимает что paper trading track record ≠ лицензия на
управление клиентскими деньгами. External AUM — только после legal review.

**D4** `[ ]` Налоговый учёт: способ учёта DeFi-доходов определён.
Trades в `data/trades.json` содержат достаточно данных для tax reporting
(timestamp, amount, protocol, tx_hash).

**D5** `[ ]` Страхование: Owner принял осознанное решение о том, застрахован ли
on-chain капитал (Nexus Mutual / Unslashed / самострахование через резерв).
Для пилота $10–50K: минимальный порог. Решение задокументировано здесь:
```
Решение по страхованию: _______________________________________________
Дата: _______________  Подпись: Owner
```

---

### Группа E: Emergency Procedures

**E1** `[ ]` Emergency stop процедура документирована в `docs/emergency.md`
и доступна Owner offline (распечатана или сохранена в password manager).
Включает: как revoke EXECUTOR за < 5 минут с одного hardware wallet.

**E2** `[ ]` Kill-switch последовательность определена:
  1. GUARDIAN: revoke EXECUTOR role (немедленно)
  2. Safe: вывести USDC из всех протоколов вручную (2-of-3)
  3. Перевести USDC из Safe на cold wallet (Key-C address)
  4. Остановить все launchd сервисы: `launchctl stop com.spa.*`
  5. Уведомить через Telegram

**E3** `[ ]` Максимальное время до выполнения kill-switch (с момента
обнаружения угрозы) определено и принято Owner: _______ минут.
Owner имеет доступ к hardware wallet Key-A в любое время.

**E4** `[ ]` Backup план при недоступности интернета: Infura/Alchemy RPC
endpoints настроены как fallback. Транзакция может быть отправлена через
mobile hotspot или из другой локации.

**E5** `[ ]` Процедура при подозрении на компрометацию EXECUTOR hot key:
  1. НЕ паниковать, НЕ пытаться "спасти" деньги переводом — это может
     быть front-run атака
  2. Немедленно revoke EXECUTOR через GUARDIAN (1 hardware wallet)
  3. Проверить последние транзакции на Etherscan
  4. Оценить ущерб, затем действовать
  Зафиксировано в: `docs/emergency.md`

**E6** `[ ]` Disaster Recovery:
  - `data/` реплицируется в GitHub через auto_push (com.spa.autopush)
  - SQLite track в iCloud backup (MP-109)
  - При полной потере ПК — восстановление возможно за _______ часов
    (задокументировано в `docs/DR_PROCEDURE_v1.md`)

**E7** `[ ]` Проверена независимость GUARDIAN от EXECUTOR: если hot key
`spa_executor` полностью скомпрометирован, Owner всё равно может выполнить
emergency stop используя только hardware wallet (без доступа к macOS Keychain).

---

## Sign-off

Все пункты выше отмечены `[x]` Owner.

```
Дата проверки:  _______________
Owner:          Yurii

Итоговый статус checklist:
  Группа A (Smart Contract):      ___ / 9  пунктов
  Группа B (Key Management):      ___ / 9  пунктов
  Группа C (Operational):         ___ / 9  пунктов
  Группа D (Legal/Regulatory):    ___ / 5  пунктов
  Группа E (Emergency):           ___ / 7  пунктов
  ИТОГО:                          ___ / 39 пунктов

Решение о go-live:  ☐ РАЗРЕШИТЬ   ☐ ОТЛОЖИТЬ до: _______________

Комментарии Owner: __________________________________________________
```

---

## Notes для будущих ревизий

При переходе к Phase 2 (External AUM) этот checklist дополняется:

- [ ] Аудит #1 пройден без критических находок (MP-405)
- [ ] Bug bounty активен (MP-410)
- [ ] Real-time security monitoring (Hypernative/Forta) активен (MP-506)
- [ ] Второй аудит другой фирмой (MP-506)
- [ ] Юридическое structure review для управления клиентским AUM
- [ ] Safe 3-of-5 настроен (ADR-010 Phase 2)

---

## References

- [ADR-002: Go-Live Transfer Rule](./ADR-002-golive-transfer-rule.md)
- [ADR-010: Gnosis Safe Key Management](./ADR-010-gnosis-safe-key-management.md)
- `docs/emergency.md`
- `docs/DR_PROCEDURE_v1.md`
- `docs/LEGAL_STRUCTURE_v1.md`
- `docs/TOKEN_ROTATION_RUNBOOK.md`
- [`spa_core/paper_trading/golive_checker.py`](../../spa_core/paper_trading/golive_checker.py)
- [`spa_core/risk/policy.py`](../../spa_core/risk/policy.py)
- MASTER_PLAN_v1.md §4 (Phase 4 gate conditions)
