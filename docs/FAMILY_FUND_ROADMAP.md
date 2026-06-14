# FAMILY_FUND_ROADMAP — Закрытый частный фонд SPA

> **Создан:** 2026-06-12 | **Автор:** architect (senior DeFi + fintech + product)  
> **Версия:** v1.0  
> **Статус:** Стратегический план — для исполнения начиная с 2028  
> **Горизонт:** Phase 0 (2028) → Phase 1 (2028–2029) → Phase 2 (2030+)  
>
> ⚠️ Этот документ — архитектурный и стратегический план. Не является юридической
> консультацией. Перед привлечением любого внешнего капитала — очная консультация
> с лицензированным юристом по украинскому праву и юрисдикции структуры.

---

## Содержание

1. [Правовая и структурная оболочка (Phase 0 — Informal)](#1-правовая-и-структурная-оболочка)
2. [Admin Cabinet — управление фондом](#2-admin-cabinet)
3. [Investor Cabinet — портал участников](#3-investor-cabinet)
4. [Public Website / Landing Page](#4-public-website--landing-page)
5. [Безопасность инфраструктуры](#5-безопасность-инфраструктуры)
6. [Техстек и архитектура](#6-техстек-и-архитектура)
7. [Roadmap Phase 0 → 1 → 2](#7-roadmap-phase-0--1--2)
8. [Агентная архитектура для управления фондом](#8-агентная-архитектура)

---

## 1. Правовая и структурная оболочка

### 1.1 Исходная позиция: Украина + DeFi

Юрий находится в Украине. Украинское законодательство об инвестиционных фондах
(ЗУ «Про інститути спільного інвестування», 2012) требует лицензии КУА
(компании по управлению активами) при любой публичной форме привлечения средств.
**Но:** для закрытого круга доверенных лиц — семьи, друзей, партнёров —
ни НКЦПФР (украинский регулятор), ни MiCA (EU) не применяются при следующих условиях:

- Нет публичной оферты (нет рекламы, нет сайта с предложением вложить деньги)
- Отношения оформлены через гражданско-правовые договоры (не ценные бумаги)
- Количество участников ≤ 10–15 человек (практический порог неформального круга)
- Капитал не превышает уровень, привлекающего регуляторное внимание (до ~$500K)

### 1.2 Варианты структур для Phase 0

#### Вариант A: Договір простого товариства (ЦКУ, ст. 1132–1143) ✅ РЕКОМЕНДОВАН
**Что это:** Несколько физлиц объединяют вклады для достижения общей цели без
образования юрлица. Регулируется Гражданским кодексом Украины напрямую.

**Плюсы:**
- Нет регистрации, нет лицензии
- Вклады могут быть деньгами, имуществом, умениями (Юрий вносит expertise)
- Прибыль делится по договору
- Выход участника — по соглашению или через процедуру ст. 1141 ЦКУ
- Работает для крипто-активов (регулятор молчит, суды не сформировали практику)

**Минусы:**
- Нет юрлица → сложность с банковским счётом (личный счёт Юрия)
- Солидарная ответственность — если не прописать иное
- При разногласии — украинский суд с туманной практикой по крипто

**Ключевые условия договора (term sheet):**
- Размер вкладов, дата внесения, форма (USDC / гривна / EUR)
- Доля участника = вклад / сумма всех вкладов на дату расчёта
- Ответственность управляющего — только за грубую небрежность (не за убытки рынка)
- Право доступа к отчётности — ежемесячно (инвестор получает statement)
- Выход — запрос за 30 дней, выплата по NAV на дату выхода
- Форс-мажор и kill-switch: при drawdown ≥5% управляющий закрывает позиции
  без согласования (задокументировать как автоматический протокол)
- Запрет на цессию долей без согласия всех участников
- Арбитраж: МАК при ТПП Украины или ICC (если участники не-резиденты)

#### Вариант B: Индивидуальные займы с profit-sharing (Договір позики + Угода про розподіл прибутку)
**Когда использовать:** Если инвестор хочет долговой, а не долевой характер участия.
Инвестор "одалживает" деньги, получает фиксированный процент + долю прибыли сверху.

**Плюсы:** Проще налогово (% по займу — доход Юрия); инвестор в позиции кредитора.

**Минусы:** Юрий несёт обязательство возврата тела + процентов даже при убытке.
**Не рекомендован** для крипто-волатильной среды — Юрий принимает на себя долговой риск.

#### Вариант C: Offshore LLC (BVI / Cayman) — для Phase 1, не Phase 0
Создание BVI LLC или Cayman Segregated Portfolio Company: $5,000–15,000 на старте,
$3,000–8,000/год в обслуживании. Имеет смысл при:
- AUM > $200K
- Участники из нескольких юрисдикций
- Нужна защита активов от украинского правового риска

**Для Phase 0 (семья/друзья, 5–10 человек) — избыточно и дорого.**

#### Вариант D: DAO Membership (токен-участие)
Выпуск ERC-20 токенов представляющих доли. **Категорически не рекомендован для Phase 0:**
- Токены → ценные бумаги по MiCA (если участники в ЕС)
- Публичная смарт-контракт инфраструктура = публичная оферта
- Налоговые и AML-риски неконтролируемы

### 1.3 Что можно и нельзя без лицензии (Украина)

| Действие | Можно | Нельзя |
|---|---|---|
| Управлять деньгами близкого круга по договору простого товариства | ✅ | |
| Размещать деньги в DeFi протоколах от своего имени | ✅ | |
| Принимать платежи в USDC на личный кошелёк | ✅ | |
| Публично предлагать инвестиции (реклама, лендинг с CTA "инвестировать") | | ❌ |
| Принимать более 100–150 инвесторов без лицензии | | ❌ |
| Называть это "фондом", "инвестиционным продуктом" в публичных каналах | | ❌ |
| Работать с инвесторами из EU без регистрации AIFM (AUM > €100M) | не актуально | |
| Работать с US persons без SEC/CFTC clearance | | ❌ жёстко |

### 1.4 Минимальный пакет документов Phase 0

| Документ | Назначение | Кто готовит |
|---|---|---|
| **Договір простого товариства** (master) | Базовый договор участия | Юрист (ЦКУ) |
| **Додаток: Risk Disclosure** | Перечень рисков; подпись инвестора | Юрий |
| **Додаток: Investment Policy Statement** | Стратегия, протоколы, лимиты | Юрий |
| **Term Sheet (1 страница)** | Доля, вклад, APY история, выход | Юрий |
| **Monthly Statement Template** | Шаблон ежемесячного отчёта | Юрий/автоматика |
| **Exit Procedure Memo** | Порядок выхода и расчёта NAV | Юрий |

### 1.5 Триггеры перехода к формальной структуре

| Триггер | Действие |
|---|---|
| AUM > $500K | Создать BVI LLC или Cayman SPC; нанять юриста-оффшориста |
| Количество инвесторов > 15 | Перейти к BVI/Cayman + term sheets с юрлицом |
| Инвестор из EU с AUM > $100K | Проверить AIFMD; возможно sub-threshold регистрация |
| Любой US person | Остановиться, проконсультироваться с US securities lawyer (SEC/CFTC) |
| Украинский регулятор присылает запрос | Немедленно к юристу, не давать ответов самостоятельно |
| Публичное упоминание в медиа с деталями структуры | Юрист + PR-протокол |
| Решение о Phase 2 (licensed fund) | Начать процесс регистрации BVI/Cayman + engagement с regulated custodian |

---

## 2. Admin Cabinet

Функциональный дашборд управляющего. Доступен только Юрию (2FA-защита).
Работает поверх существующей SPA-инфраструктуры.

### 2.1 Модули Admin Cabinet

#### 2.1.1 Capital Management (Управление капиталом)

**Данные, которые хранятся в БД:**

```
Investor:
  id, name, email, telegram_id
  join_date, exit_date (nullable)
  contribution_usdc, contribution_date
  current_shares (доля = contribution / total_aum_at_contribution)
  status: [active | exiting | exited]

Contribution:
  id, investor_id, amount_usdc, date, tx_hash (on-chain)
  type: [deposit | withdrawal | income_distribution]

NAV_Snapshot:
  date, total_aum_usdc, share_price, equity_per_share
  (записывается ежедневно из equity_curve_daily.json)
```

**Доля участника:** рассчитывается как пропорция внесённого капитала к total AUM
на дату взноса, затем корректируется с учётом последующих взносов/изъятий.
Формула: `share_value(t) = shares * NAV(t)` где NAV обновляется ежедневно из
существующего `equity_curve_daily.json`.

**UI:** Таблица инвесторов → клик → карточка инвестора (всё ниже).

#### 2.1.2 PnL Attribution по инвестору

Для каждого участника вычисляется:

```
personal_equity(t) = initial_contribution * (NAV(t) / NAV(t0))
pnl_absolute = personal_equity(t) - sum(contributions)
pnl_pct = pnl_absolute / sum(contributions) * 100
annualized_return = TWR (time-weighted return, Modified Dietz)
```

**Modified Dietz** — стандарт CFA Institute для портфелей с cash flows. Формула:

```
R = (Vend - Vstart - Σ(CF)) / (Vstart + Σ(CF * W))
где W = (t_end - t_cf) / (t_end - t_start)
```

Это единственно корректный метод при множественных довзносах и изъятиях.

#### 2.1.3 Rebalancing Log

Каждый ребалансирующий трейд из `data/trades.json` аннотируется:
- `affected_investors`: список ID участников (все активные на дату трейда)
- `yield_distributed`: USDC-доход начисленный каждому за период
- `protocol_changes`: с какого пула в какой переложили, delta

**Income distribution schedule:** опция reinvest (по умолчанию) или cash-out
(инвестор запросил вывод дохода — обрабатывается вручную Юрием через Gnosis Safe).

#### 2.1.4 Operations Dashboard (главный экран Admin)

```
┌─────────────────────────────────────────────────────────────┐
│  SPA FUND — Admin Dashboard              2026-08-14  08:15  │
├────────────────┬────────────────┬───────────────────────────┤
│  Total AUM     │  Fund APY      │  Active Investors         │
│  $135,420.00   │  4.82%         │  7                        │
├────────────────┴────────────────┴───────────────────────────┤
│  Equity Curve (30d spark)  ████████████████████▲           │
├────────────────────────────────────────────────────────────-┤
│  Positions (live from current_positions.json):             │
│  Aave V3      $54,168  40.0%  APY 3.2%  ████████          │
│  Morpho Blue  $27,084  20.0%  APY 5.1%  ████               │
│  Yearn V3     $27,084  20.0%  APY 6.8%  ████               │
│  Euler V2     $20,313  15.0%  APY 7.2%  ███                │
│  Cash buffer   $6,771   5.0%  APY 0.0%  █                  │
├────────────────────────────────────────────────────────────-┤
│  Risk Status: ✅ APPROVED  │  Kill-switch: ARMED            │
│  GoLive:      ✅ READY     │  Gap monitor: OK (0 gaps)      │
├────────────────────────────────────────────────────────────-┤
│  Pending Actions:                                           │
│  [!] Ivan K. — exit request (due: 2026-08-20, $22,450)     │
│  [i] Monthly statements: 7/7 generated                     │
│  [i] Autopush: last push 4h ago                            │
├────────────────────────────────────────────────────────────-┤
│  [ Send Blast ]  [ Generate All Statements ]  [ Export CSV ]│
└─────────────────────────────────────────────────────────────┘
```

#### 2.1.5 One-click Telegram Blast

Форма: выбрать получателей (все / группа / конкретный), выбрать шаблон
(monthly update / risk alert / milestone / custom), предпросмотр,
кнопка "Send". Сообщения отправляются через существующего Telegram бота
(TELEGRAM_BOT_TOKEN_SPA из Keychain).

**Шаблоны:**
- `monthly_update`: NAV, APY, positions summary, next expected action
- `risk_alert`: причина алерта, текущая позиция, действия управляющего
- `milestone`: достигнутые порог (e.g., "Фонд достиг $200K AUM")
- `custom`: свободный текст + опциональное вложение PDF

#### 2.1.6 PDF Statement Generator

По каждому инвестору генерируется PDF-отчёт:
- Страница 1: Сводка (equity, PnL, APY, период)
- Страница 2: Детализация (все транзакции за период)
- Страница 3: Состав портфеля (протоколы, аллокации)
- Страница 4: Risk metrics (drawdown, Sharpe, Sortino)
- Footer: Gnosis Safe адрес, disclaimer, подпись управляющего

Генерация: Python + `reportlab` или WeasyPrint из HTML-шаблона.
Автоматически каждое 1-е число месяца или по кнопке.

### 2.2 Технические требования Admin Cabinet

- Только один пользователь (Юрий) — нет multi-admin в Phase 0
- TOTP 2FA (Google Authenticator / Authy) обязательно
- Сессия истекает через 30 минут бездействия
- Все действия (blast, export, statement) логируются в audit log
- Прямой доступ к `data/*.json` SPA через read-only mount или API

---

## 3. Investor Cabinet

Портал только для чтения. Каждый инвестор видит только свои данные.

### 3.1 Что видит инвестор

#### Главная страница (Dashboard)

```
┌──────────────────────────────────────────────────────────┐
│  SPA Fund — Ваш портфель                 Иван К.  [Exit] │
├──────────────────────────────────────────────────────────┤
│  Ваша доля          Текущая стоимость    APY (с начала)  │
│     18.5%               $22,450           +4.82%         │
├──────────────────────────────────────────────────────────┤
│  Equity curve (ваша доля) 90 дней ████████████████▲      │
├──────────────────────────────────────────────────────────┤
│  PnL: +$2,450  │  Доходность: +12.2%  │  Дней: 92       │
├──────────────────────────────────────────────────────────┤
│  Состав фонда (на сегодня):                              │
│  Aave V3    40%  APY 3.2%   ████████████████             │
│  Morpho     20%  APY 5.1%   ████████                     │
│  Yearn V3   20%  APY 6.8%   ████████                     │
│  Euler V2   15%  APY 7.2%   ██████                       │
│  Cash        5%  0%         ██                           │
├──────────────────────────────────────────────────────────┤
│  [ Скачать Statement ]  [ История ]  [ Уведомления ]     │
└──────────────────────────────────────────────────────────┘
```

#### История транзакций

Таблица: дата | тип (взнос/изъятие/income accrual) | сумма USDC | NAV на дату |
доля до/после | примечание. Экспорт в CSV.

#### О фонде (прозрачность)

- Описание стратегии (текст из Investment Policy Statement)
- Протоколы в портфеле: название, Tier, ссылка на DeFiLlama, TVL, APY
- Gnosis Safe адрес — кликабельная ссылка на Etherscan для независимой верификации
- Risk policy краткое изложение (kill-switch, caps, TVL floor)
- Последний audit trail (дата последнего цикла, хеш транзакции если есть)
- Track record history (equity curve всего фонда, публичная)

#### PDF Statement

По кнопке: тот же документ что генерирует Admin, но только для данного инвестора.
Без информации об остальных участниках.

#### Уведомления (настройки)

- Email / Telegram (переключатели)
- Типы: monthly statement ready, risk alert (kill-switch armed), milestone,
  rebalance completed, exit processed

### 3.2 Чего инвестор НЕ может

- Инициировать вывод средств через портал (только запрос → Юрий обрабатывает вручную)
- Видеть данные других инвесторов
- Изменять параметры портфеля или стратегии
- Видеть Admin-функциональность даже если URL подобрать

### 3.3 Верификация on-chain

На странице "О фонде" — блок "On-chain верификация":

```
Gnosis Safe: 0x1234...abcd
Сеть: Ethereum Mainnet
Проверить баланс: [ссылка Etherscan]
Проверить транзакции: [ссылка Etherscan]
Последний снимок позиций: 2026-08-14 08:00 UTC
```

Данные в портале синхронизированы с `data/current_positions.json` (обновляется
ежедневно из cycle_runner). Инвестор может независимо сверить с on-chain данными.

---

## 4. Public Website / Landing Page

### 4.1 Концепция: приглашение, не реклама

**Ключевой принцип:** сайт не является публичной офертой. Это informational page
для людей, которые уже получили личное приглашение от Юрия. Нет CTA "инвестировать",
нет обещаний доходности, нет форм с финансовыми обязательствами.

### 4.2 Структура сайта

#### Главная страница (Публичная)

```
Header: SPA — Smart Passive Allocator
Tagline: "Автономная стратегия доходности в DeFi"
```

Секции:
1. **What is SPA** — нейтральное описание системы, автоматизированный DeFi allocator,
   детерминированная логика, без LLM в критических компонентах
2. **Track Record** — публичная equity curve (только фонд в целом, без имён инвесторов),
   APY история с подписью "paper trading [дата] — live [дата]"
3. **Security** — Gnosis Safe 2-of-3 (Ledger + Trezor + cold key),
   ссылка на Safe адрес Etherscan, kill-switch описание
4. **Methodology** — DeFiLlama feeds, RiskPolicy v1.0 описание, протоколы Tier 1/2
5. **Transparency** — ссылка на GitHub репо (если публичное), ADR документы

**Footer:** "Это частная информационная страница. Не является публичной офертой
инвестиционных услуг. Любое участие — исключительно на основании индивидуальных
договорённостей."

#### Invite-only страница (по коду)

URL: `/join/[invite_code]` — уникальный одноразовый код на каждого приглашённого.

```
"Юрий пригласил вас ознакомиться с SPA Fund"

[Краткое описание участия]
[APY история — 24 мес трека]
[Условия участия — ссылка на Term Sheet PDF]
[Risk Disclosure — обязательное прочтение + подпись]

Форма:
  Имя:        [___________]
  Email:      [___________]
  Telegram:   [___________]
  Комментарий:[___________]
  [ Я прочитал Risk Disclosure ] [checkbox]
  [ Отправить запрос на участие ]
```

Форма отправляет данные только Юрию (email + Telegram уведомление).
Не хранит финансовых данных, не создаёт юридических обязательств.

### 4.3 Trust Signals

| Сигнал | Реализация |
|---|---|
| Gnosis Safe on-chain | Верифицированный адрес + ссылка Etherscan |
| Equity curve верифицированная | Подписана хешем из GitHub commit |
| Code transparency | Ссылка на spa_core/ в GitHub (read-only view) |
| Methodology docs | Публичный MASTER_PLAN + ADR docs (sanitized) |
| No promises | Disclaimer на каждой странице с APY данными |
| Daily updates | "Last cycle: 2026-08-14 08:00 UTC — Verified ✅" |

### 4.4 Домен и хостинг

**Домен:** `spa-fund.com` или `spa-allocator.io` ($10–15/год, Namecheap/Cloudflare).
Cloudflare для DNS + DDoS protection (бесплатный план достаточен).

**Хостинг:**
- Phase 0: **Vercel** (бесплатный план). Static HTML + Next.js serverless functions
  для invite-only логики. Deploy на каждый git push.
- Phase 1: Vercel Pro ($20/мес) или Fly.io при росте нагрузки.

**Сертификат TLS:** автоматически через Cloudflare / Let's Encrypt.

---

## 5. Безопасность инфраструктуры

### 5.1 Разграничение доступа

```
Auth Levels:
  Level 0: Public site (no auth)
  Level 1: Investor portal (email + TOTP или magic link)
  Level 2: Admin Cabinet (email + TOTP + IP whitelist)
  Level 3: Execution (Ledger + Trezor физически; offline signing)
```

**Принцип разделения**: Admin Cabinet и Investor Portal — **разные поддомены**
(`admin.spa-fund.com` и `app.spa-fund.com`). Разные JWT секреты. Admin доступен
только с whitelisted IP (домашний + VPN). Инвестор не может подобрать URL до admin.

### 5.2 Secret Management

| Что | Где хранить |
|---|---|
| JWT_SECRET | macOS Keychain (уже паттерн в SPA) |
| DB_PASSWORD | macOS Keychain / Doppler (Phase 1) |
| SMTP credentials | macOS Keychain |
| Telegram Bot Token | macOS Keychain (TELEGRAM_BOT_TOKEN_SPA — уже там) |
| GitHub PAT | macOS Keychain (уже паттерн в SPA) |
| Gnosis Safe keys | Ledger hardware + Trezor hardware + cold paper key |
| PDF signing key | macOS Keychain |

**Правило:** Ни один секрет не попадает в:
- `.env` файлы в репо
- Код (hardcoded)
- Логи (проверять при каждом новом модуле)
- Claude-generated файлы (инцидент 2026-06-10 уже задокументирован)

**Phase 1:** Допольнительно — [Doppler](https://doppler.com) как centralized
secrets manager ($10/мес). Secrets ротируются автоматически.

### 5.3 2FA — обязательно для Admin

- TOTP (TOTP RFC 6238) через Google Authenticator или Authy
- Backup codes — хранить в менеджере паролей (Bitwarden), не в текстовом файле
- Восстановление только через физический ключ (не email recovery — email-аккаунт может быть взломан)
- Рассмотреть: FIDO2/WebAuthn (YubiKey) для максимальной защиты Phase 1+

### 5.4 On-chain верификация позиций

Инвестор и управляющий не должны доверять только backend-данным.

**On-chain verification pipeline (ежедневно после cycle_runner):**

```python
# spa_core/verification/on_chain_check.py (новый модуль)
# Проверяет реальный баланс Safe кошелька через Etherscan API
# Сравнивает с data/current_positions.json
# При расхождении > 0.1% → Telegram alert + запись в data/verification_log.json
```

Инвестор в портале видит: "On-chain verification: ✅ 2026-08-14 08:05 UTC
Позиции совпадают с Gnosis Safe балансом."

**Etherscan API** — бесплатный тариф 5 req/sec, достаточно для ежедневной проверки.

### 5.5 Backup и Disaster Recovery

**Сценарий: macOS умерла — что происходит?**

```
Данные:
  ├─ GitHub репо (код + data/*.json) → Восстановление: git clone за 5 минут
  ├─ Keychain секреты → ПРОБЛЕМА без бэкапа; решение ниже
  ├─ Gnosis Safe → ключи на Ledger/Trezor/cold — независимы от macOS ✅
  └─ БД инвесторов (Phase 0: JSON/SQLite) → в GitHub если pushится ежедневно

Секреты (Keychain):
  Решение: encrypted export в 1Password / Bitwarden
  Храни там: все Keychain entries (Telegram token, GitHub PAT, DB pass)
  Recovery: установить 1Password на новый Mac → импортировать → загрузить в Keychain

Процедура восстановления за 2 часа:
  1. Новый Mac/VPS
  2. brew install python3 git
  3. git clone <repo>
  4. Загрузить секреты из 1Password в Keychain
  5. launchctl load <plists>
  6. Проверить: python3 -m spa_core.paper_trading.cycle_runner --verbose
```

**DR Runbook** должен быть задокументирован в `docs/DR_PROCEDURE_v2.md`.
`docs/DR_PROCEDURE_v1.md` уже существует — обновить под fund scope.

**Ежедневный backup:**
- GitHub автопуш (уже в плане, autopush нужно починить — MP-313)
- Дополнительно: ежедневный cron рез в AWS S3 / Backblaze B2 (~$0.006/GB/мес)
  зашифрованный (age encryption или GPG)

### 5.6 Rate Limiting и DDoS Protection

- **Cloudflare Free** на домене: базовая DDoS защита, WAF с готовыми правилами
- **Rate limiting на API уровне:**
  - `/api/login` — 5 попыток / IP / 15 минут
  - `/api/investor/*` — 100 req / user / час
  - `/api/admin/*` — 30 req / сессия / минуту
- **Brute-force защита:** временная блокировка IP после 5 неудачных логинов
- **JWT rotation:** токены истекают через 30 минут, refresh через secure httpOnly cookie

### 5.7 Audit Log

Каждое действие в Admin и Investor Cabinet логируется:

```
audit_log:
  timestamp | user_id | action | ip_address | user_agent | result
  
Примеры:
  admin login success 192.168.1.1
  admin generated statement investor_3
  admin sent blast to all_investors
  investor_3 viewed dashboard
  investor_3 downloaded statement 2026-08
  investor_3 failed login (wrong TOTP) 45.12.xxx.xxx
```

Лог хранится в БД (не перезаписывается). Retention: 3 года минимум.
Подозрительная активность (5+ failed logins, нетипичный IP) → Telegram alert Юрию.

---

## 6. Техстек и архитектура

### 6.1 Принципы выбора для Phase 0

- **Минимальный когнитивный overhead:** Юрий работает в Python; бэкенд на Python
- **Минимальные расходы:** до $30/мес для ≤20 инвесторов
- **Скорость запуска:** работающий прототип за 2-4 недели
- **Upgrade path:** без переписывания до Phase 1 (добавить Postgres, добавить workers)

### 6.2 Рекомендованный стек

#### Backend: FastAPI (Python)

**Почему FastAPI, не Node/Next.js:**
- Юрий уже в Python; нет смысла учить JS стек для этой задачи
- spa_core напрямую импортируется как Python библиотека (data/*.json доступны)
- Async из коробки; хорошая документация; auto-генерация OpenAPI схемы
- Pydantic для валидации данных

**Структура API:**

```
/api/v1/
  auth/
    POST  /login          → JWT
    POST  /refresh        → refresh JWT
    POST  /logout
  admin/                  → requires admin JWT + IP check
    GET   /dashboard      → основные метрики фонда
    GET   /investors      → список инвесторов
    GET   /investor/{id}  → карточка инвестора
    POST  /statement/{id} → сгенерировать PDF
    POST  /blast          → отправить Telegram сообщение
    GET   /positions      → текущие позиции
    GET   /trades         → история трейдов
    GET   /audit-log      → audit log
  investor/               → requires investor JWT (scope: own data only)
    GET   /me             → данные текущего инвестора
    GET   /equity         → equity curve
    GET   /transactions   → история
    GET   /portfolio      → состав портфеля (fund-level, без других участников)
    GET   /statement      → скачать PDF
  public/                 → no auth
    GET   /fund/summary   → публичные метрики (APY, equity curve, track record)
```

#### Auth: самописный (email + TOTP)

**Почему не Auth0/Clerk:**
- ≤20 инвесторов; Auth0 free tier достаточен, но external dependency и vendor lock
- Clerk $25+/мес при росте
- Supabase Auth — вариант если используем Supabase в целом

**Рекомендация Phase 0:** самописный auth на PyJWT + pyotp (stdlib-совместимые).
TOTP QR code при регистрации, backup codes. Email-верификация через SMTP (Resend.com,
3,000 email/мес бесплатно). Занимает ~300 строк кода.

**Phase 1:** мигрировать на Clerk ($25/мес) или Supabase Auth для надёжности
и audit compliance.

#### База данных: SQLite → Postgres

**Phase 0:** SQLite (`fund.db` в папке проекта).
- 0 расходов
- Достаточно для ≤20 инвесторов, ≤1000 транзакций/год
- Бэкап: ежедневный `sqlite3 fund.db .dump > backup.sql` → GitHub (private repo!)
  или S3 (зашифрованный)
- Атомарные записи через SQLAlchemy ORM (WAL mode для concurrent reads)

**Migration trigger:** > 20 инвесторов ИЛИ > 5 concurrent пользователей
→ Postgres на Supabase ($25/мес) или Railway ($5/мес). Migration: Alembic.

#### Frontend: Next.js (App Router)

**Почему Next.js, не SvelteKit:**
- Vercel deployment из коробки (создан теми же людьми)
- Большая экосистема UI компонентов (shadcn/ui, Tailwind)
- Server Components — чувствительные данные не утекают в клиент
- Юрий сможет нанять React-разработчика легче чем Svelte

**Структура страниц:**
```
/             → public landing page
/join/[code]  → invite-only регистрация
/login        → логин
/investor     → investor dashboard (protected)
/investor/history     → история транзакций
/investor/portfolio   → состав портфеля
/investor/statement   → PDF statement
/admin        → admin dashboard (protected, IP-locked)
/admin/investors      → управление инвесторами
/admin/statements     → генерация отчётов
/admin/blast          → рассылка
/admin/audit          → audit log
```

#### Хостинг

| Компонент | Phase 0 | Стоимость |
|---|---|---|
| Frontend (Next.js) | Vercel Free | $0 |
| Backend (FastAPI) | Railway Starter | $5/мес |
| БД (SQLite → Postgres) | Railway / Supabase | $0 → $5/мес |
| Домен | Cloudflare | ~$10/год |
| Email (SMTP) | Resend.com | $0 (3K/мес) |
| Мониторинг | Sentry Free | $0 |
| Uptime | UptimeRobot Free | $0 |
| S3 backup | Backblaze B2 | ~$0.10/мес |
| **Total** | | **~$10–15/мес** |

**Phase 1 (>20 инвесторов, производственная нагрузка):**

| Компонент | Стоимость |
|---|---|
| Vercel Pro | $20/мес |
| Railway Production | $20/мес |
| Supabase Pro | $25/мес |
| Clerk Auth | $25/мес |
| Sentry Team | $26/мес |
| Secrets (Doppler) | $10/мес |
| **Total** | **~$130/мес** |

#### Мониторинг и алерты

- **Sentry** — ошибки в Python backend и JS frontend
- **UptimeRobot** — проверка доступности каждые 5 минут, алерт в Telegram
- **Structured logging** — JSON logs в backend, хранение в Loki (self-hosted) или
  Papertrail ($7/мес Phase 1)
- **Существующий Telegram бот** — интегрировать алерты Admin Cabinet в него же

### 6.3 Архитектурная схема

```
┌─────────────────────────────────────────────────────────────────┐
│                      macOS (Юрий)                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  launchd com.spa.daily_cycle (08:00)                    │   │
│  │    spa_core/paper_trading/cycle_runner.py               │   │
│  │    ↓ writes to data/*.json (atomic)                     │   │
│  └───────────────────────┬─────────────────────────────────┘   │
│                          │ file mount / API read               │
│  ┌───────────────────────▼─────────────────────────────────┐   │
│  │  FastAPI backend (Railway cloud / local dev)            │   │
│  │    /api/admin/*  /api/investor/*  /api/public/*         │   │
│  │    Auth: JWT + TOTP                                     │   │
│  │    DB: SQLite (Phase0) → Postgres (Phase1)              │   │
│  │    PDF gen: reportlab/weasyprint                        │   │
│  │    Telegram blast: httpx → Telegram Bot API             │   │
│  └───────────┬────────────────────────┬────────────────────┘   │
└──────────────┼────────────────────────┼────────────────────────┘
               │ HTTPS (Cloudflare TLS) │
      ┌────────▼───────┐       ┌────────▼────────┐
      │  Next.js       │       │  Next.js         │
      │  Admin Cabinet │       │  Investor Portal │
      │  admin.spa-fund│       │  app.spa-fund    │
      │  IP-locked     │       │  Email+TOTP auth │
      └────────────────┘       └──────────────────┘
                                        │
                               ┌────────▼────────┐
                               │  Инвестор       │
                               │  (браузер)      │
                               └─────────────────┘

Gnosis Safe (Ethereum) ──────────────────────────────► On-chain верификация
(2-of-3: Ledger + Trezor + cold)                       spa_core/verification/
```

### 6.4 Синхронизация данных SPA → Fund Backend

Существующий `cycle_runner.py` пишет в `data/*.json` на macOS.
Fund Backend на Railway нужны эти данные. Варианты:

**Вариант A (рекомендован Phase 0):** API endpoint на Backend читает GitHub raw content.
`push_to_github.py` уже пушит `data/*.json` ежедневно → Backend делает HTTP GET
на raw.githubusercontent.com → парсит JSON. Задержка ~автопуш + 30 сек. 

**Вариант B (Phase 1):** Dedicated sync worker — `spa_core` читает файлы и пишет
через REST API в Postgres. Более надёжно, но требует доп. инфраструктуры.

---

## 7. Roadmap Phase 0 → Phase 1 → Phase 2

### Phase 0: Close Circle Informal (2028 — $0–500K AUM)

**Период:** После 2-летнего трека (т.е. ~с 2028-08-01)  
**Инвесторы:** 3–10 человек (семья, друзья, партнёры)  
**Структура:** Договір простого товариства (ЦКУ)  
**AUM ceiling:** $500K  

| Квартал | Milestone |
|---|---|
| Q3 2028 | 2-летний трек завершён, equity curve верифицирована; первый инвестор |
| Q3 2028 | Admin Cabinet v1 + Investor Portal v1 deployed |
| Q4 2028 | 5 инвесторов, AUM $50–150K |
| Q1 2029 | Monthly statements автоматизированы; on-chain верификация ежедневная |
| Q2 2029 | 10 инвесторов, AUM $150–300K; готовность к Phase 1 оценка |

**Checklist перед первым внешним инвестором:**
- [ ] Договір простого товариства подписан (с юристом)
- [ ] Risk Disclosure подписан инвестором
- [ ] Admin Cabinet работает: NAV, PnL attribution, statements
- [ ] Investor Portal работает: dashboard, история, PDF
- [ ] Gnosis Safe: подтверждены адреса, on-chain верификация
- [ ] Backup/DR протокол протестирован (симуляция "macOS умерла")
- [ ] Audit log активен
- [ ] 2FA включён для Admin

### Phase 1: Semi-Formal Offshore (2028–2030, $200K–2M AUM)

**Триггеры входа:** AUM > $200K ИЛИ > 10 инвесторов ИЛИ non-resident инвесторы

**Структура:** BVI LLC (British Virgin Islands)
- Стоимость создания: $3,000–6,000 (через агента: Vistra, Maples, Harneys)
- Ежегодные расходы: $2,000–4,000 (registered agent + government fees)
- Банкинг: Silvergate / Deltec / Bankprov (crypto-friendly) или EMI (Nium, Airwallex)
- Учётная политика: GAAP-совместимая, независимый accountant ($5,000–15,000/год)

**Term Sheets:** индивидуальные contract notes для каждого инвестора
(Limited Partnership Agreement стиль, но без LP/GP формальности BVI LLC позволяет).

**Custody:** рассмотреть Fireblocks MPC или BitGo для institutional-grade хранения
(стоимость: $1,000–3,000/мес при AUM > $1M — только Phase 1 конец).

**Compliance минимум:**
- AML policy (внутренний документ)
- KYC для всех новых инвесторов Phase 1 (passport + proof of address)
- Ежегодный audited financial statement
- Отчётность в BVI: annual return + economic substance declaration

| Milestone Phase 1 | AUM | Действие |
|---|---|---|
| AUM $200K | BVI LLC создать | Юрист + агент |
| AUM $500K | Независимый accountant | Quarterly reviews |
| AUM $1M | Рассмотреть custody решение | Fireblocks или BitGo |
| AUM $2M | Готовность к Phase 2 оценка | Регуляторный консультант |

### Phase 2: Licensed Fund (2030+, $2M+ AUM)

**Структура-кандидаты:**

| Юрисдикция | Тип | Требования | Когда |
|---|---|---|---|
| Cayman Islands | Registered Fund (sub-$500M) | CIMA registration, audited accounts, custodian | AUM $5M+ |
| BVI | Private Fund | BVIFSC registration, 50 investors max | AUM $2M+ |
| EU (Мальта/Люксембург) | AIFMD sub-threshold | MFSA/CSSF registration, AUM < €100M | Если EU инвесторы |
| Украина | КУА лицензия | НКЦПФР, капітал КУА ≥₴7M | Если фокус на UA |

**Рекомендация:** Cayman Registered Fund — самый распространённый, максимальная
гибкость для крипто-стратегий, привычен для institutional investors, профессиональная
инфраструктура под рукой (fund admin, legal, audit).

**Custody (обязательно для Phase 2):**
Fireblocks + qualified custodian (Prime Trust, BitGo Trust Company).
Стоимость: $5,000–15,000/мес при AUM $5M+.

**Операционная команда Phase 2:**
- Fund Administrator (NAV calculation, investor register): стороннее
- Auditor: Big4 или tier-2 (Grant Thornton, BDO) с крипто-практикой
- Legal (ongoing): Cayman counsel + local Ukrainian/EU
- Prime Broker/Liquidity: Coinbase Prime, FalconX
- Insurance: спорная необходимость, но D&O insurance для управляющего — да

---

## 8. Агентная архитектура для управления фондом

**CRITICAL:** Все агенты работают в advisory/reporting режиме.
Ни один агент не имеет права на:
- Изменение аллокаций или параметров стратегии
- Отправку транзакций (это исключительно Gnosis Safe + Ledger/Trezor)
- Модификацию RiskPolicy
- Запись в `data/adapter_status.json` (execution domain)

Существующий принцип `LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}` сохраняется.

### 8.1 Investor Relations Agent

**Задача:** Автоматизация коммуникации с инвесторами.

**Триггеры:**
- Ежемесячно 1-го числа → генерация statements всем инвесторам
- После каждого цикла cycle_runner → обновление equity данных в БД
- При milestone (NAV +5%, новый высокий пик, квартальный отчёт) → Telegram blast

**Что делает:**
1. Читает `data/equity_curve_daily.json`, `data/current_positions.json`
2. Вычисляет PnL каждого инвестора (Modified Dietz)
3. Генерирует PDF statements через reportlab
4. Сохраняет в `data/statements/YYYY-MM/investor_{id}.pdf`
5. Отправляет notification через Telegram Bot API (ссылку для скачивания)
6. Логирует в audit_log

**Интерфейс:** CLI `python3 -m spa_agents.ir_agent --run-monthly`
или HTTP endpoint `POST /api/admin/run-ir-agent` (вызывается вручную или cron).

**Модель:** Claude Haiku (дёшево; задача структурированная, не требует reasoning).

### 8.2 Capital Allocation Agent

**Задача:** Учёт долей при довзносах и изъятиях.

**ВАЖНО:** этот агент НЕ трогает стратегию или аллокацию портфеля.
Только математика распределения долей по инвесторам.

**Когда вызывается:**
- При новом взносе инвестора → пересчёт долей всех участников
- При изъятии → пересчёт + запись withdrawal transaction

**Что делает:**
1. Читает текущую таблицу shares из БД
2. Рассчитывает новые доли с учётом текущего NAV
3. Записывает в БД (транзакционно)
4. Генерирует confirmation для Admin: "Иван К. внёс $10,000. Его доля: 8.3% → 11.2%. NAV per share: $1.003."

**Реализация:** pure Python, детерминированный (без LLM). Тестируется unit-тестами.

### 8.3 Compliance Monitor Agent

**Задача:** Мониторинг соответствия операций правилам Phase 0/1.

**Периодичность:** после каждого cycle_runner (ежедневно).

**Что проверяет:**
- Количество активных инвесторов vs лимиты Phase (≤10 Phase 0, ≤50 Phase 1)
- Наличие подписанных Risk Disclosure у всех инвесторов
- Свежесть statements (не старше 35 дней)
- AUM vs Phase threshold (предупреждение при приближении к $200K, $500K)
- Geo-check: есть ли инвесторы из US (если да → STOP и алерт)
- Истечение юридических документов (договір товариства, ежегодное обновление)

**Выход:** `data/compliance_status.json` + Telegram алерт при WARN/FAIL.

**LLM:** НЕ нужен. Детерминированные проверки в Python.

### 8.4 Risk Alert Agent

**Задача:** Расширение существующих алертов SPA для fund-level рисков.

**Дополнительно к существующим (gap_monitor, red_flag_monitor):**
- **Concentration alert:** если один инвестор > 60% AUM → риск single-LP withdrawal
- **NAV deviation alert:** если NAV между ежедневными снимками отклоняется > 0.5% без tradeна cycle → ошибка данных
- **Withdrawal pressure alert:** если запросы на вывод > 20% AUM за 7 дней → сигнал ликвидности
- **Protocol risk:** если TVL любого протокола в портфеле упал > 20% за 24ч → emergency alert

**Реализация:** расширение существующего `spa_core/paper_trading/` паттерна.
CLI: `python3 -m spa_core.paper_trading.fund_risk_monitor --run`

### 8.5 Statement Generator Agent

**Задача:** Высококачественные PDF statements для инвесторов и регуляторных целей.

**Типы документов:**
- Monthly Statement (автоматически)
- Quarterly Report (расширенный, 4+ страниц)
- Annual Report (финансовый, для Phase 1 audit-ready)
- Exit Statement (при выходе инвестора — финальный расчёт)
- Tax Summary (USDC income по периодам — для налоговой декларации инвестора)

**Стек:** Python + WeasyPrint (HTML → PDF) с CSS-шаблоном под branding SPA.
Шаблоны в `spa_core/reporting/templates/`.

**LLM использование:** опционально для "narrative" секции quarterly report
(абзац с описанием рыночных условий и решений управляющего). Обязательный
human review перед отправкой. НЕ для финансовых расчётов — только для текста.

### 8.6 Сводная таблица агентов

| Агент | LLM? | Периодичность | Writeable domains | Критичность |
|---|---|---|---|---|
| IR Agent | Опционально (narrative) | Ежемесячно | `data/statements/`, БД notifications | Medium |
| Capital Allocation | ❌ Детерминированный | On-demand | БД investor shares | HIGH — финансовые данные |
| Compliance Monitor | ❌ Детерминированный | Ежедневно | `data/compliance_status.json` | HIGH |
| Risk Alert | ❌ Детерминированный | Ежедневно | `data/fund_risk_alerts.json` | HIGH |
| Statement Generator | Опционально (narrative) | Ежемесячно / On-demand | `data/statements/` | Medium |

---

## Приложения

### Appendix A: Decision Tree — Когда нужна лицензия?

```
Хочу привлечь внешний капитал
         │
         ▼
Инвесторы — только семья/друзья, < 15 человек?
    ├─ ДА → Договір простого товариства → Phase 0 ✅
    └─ НЕТ
         │
         ▼
Хоть один инвестор из США?
    ├─ ДА → Стоп. Нужен US securities lawyer. SEC/CFTC territory.
    └─ НЕТ
         │
         ▼
AUM > $500K ИЛИ > 15 инвесторов?
    ├─ ДА → BVI LLC + term sheets + KYC → Phase 1
    └─ НЕТ → Продолжаем Phase 0
         │
         ▼
AUM > $2M ИЛИ хочу институциональных инвесторов?
    ├─ ДА → Cayman Registered Fund → Phase 2
    └─ НЕТ → Phase 1 достаточно
```

### Appendix B: Monthly Statement — Структура (шаблон)

```
[Страница 1 — Сводка]
SPA Fund — Statement
Период: 2028-07-01 — 2028-07-31
Инвестор: Иван Коваленко
Дата входа: 2028-08-14 | Вклад: $20,000 USDC

Метрика              За месяц    С начала
─────────────────────────────────────────
Стоимость доли       $20,845     —
PnL абсолютный       +$845       +$845
PnL %                +4.23%      +4.23%
APY (annualized)     —           +5.12%
Доля в фонде         15.4%       —

[Страница 2 — Транзакции]
Дата       | Тип      | Сумма USDC | NAV/share | Доля %
2028-08-14 | Взнос    | +20,000    | 1.0000    | 15.4%
2028-08-31 | Yield    | +845       | 1.0423    | 15.4%

[Страница 3 — Состав портфеля]
Протокол    | Аллокация | APY   | Ваша доля (USD)
Aave V3     | 40.0%     | 3.2%  | $8,338
Morpho Blue | 20.0%     | 5.1%  | $4,169
Yearn V3    | 20.0%     | 6.8%  | $4,169
Euler V2    | 15.0%     | 7.2%  | $3,127
Cash buffer |  5.0%     | 0.0%  | $1,042

[Страница 4 — Risk Metrics]
Sharpe Ratio (30d):  1.84
Max Drawdown:        -0.8%
Ulcer Index:         0.12
Kill-switch Status:  ARMED (threshold: -5%)
Gnosis Safe:         0x1234...abcd [verify on Etherscan]

[Footer]
Управляющий: Юрій Кулешов | SPA Fund
Этот документ не является публичной офертой инвестиционных услуг.
Инвестиции в DeFi несут риски полной потери средств.
```

### Appendix C: Tech Stack Summary (Phase 0)

```
Runtime:
  Backend:    Python 3.12 + FastAPI 0.111 + SQLAlchemy 2.0
  Frontend:   Next.js 14 (App Router) + Tailwind CSS + shadcn/ui
  Auth:       PyJWT + pyotp (TOTP) | Phase1: Clerk
  Database:   SQLite + WAL | Phase1: Postgres (Supabase/Railway)
  PDF:        WeasyPrint (HTML→PDF) | fallback: reportlab
  Alerts:     Telegram Bot API (existing token)
  Email:      Resend.com (SMTP)

Infrastructure:
  Frontend:   Vercel (Free)
  Backend:    Railway Starter ($5/мес)
  DNS/CDN:    Cloudflare (Free)
  Secrets:    macOS Keychain | Phase1: Doppler
  Backup:     GitHub private repo + Backblaze B2 (~$0.10/мес)
  Monitoring: Sentry Free + UptimeRobot Free

SPA Integration:
  cycle_runner → data/*.json → GitHub → Backend API reads raw.github

Cost Phase 0: ~$10–15/мес
Cost Phase 1: ~$130/мес
```

---

*Документ подготовлен: 2026-06-12. Следующий review: при приближении к go-live (2026-08-01)
и при первом обсуждении с потенциальным инвестором. Не является юридической консультацией.*
