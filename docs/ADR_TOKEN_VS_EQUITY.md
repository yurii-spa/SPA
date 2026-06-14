# ADR: Token vs Equity Round — Модель монетизации SPA

**ID:** ADR-TOKEN-VS-EQUITY  
**MP-508 | Версия:** 1.0  
**Дата:** 2026-06-12  
**Статус:** ACCEPTED  
**Автор:** SPA Team  
**Решение:** Option C — Hybrid (equity seed → токен позже)

---

## Контекст

SPA (Smart Passive Aggregator) — DeFi yield optimizer, paper trading $100K USDC с целью
$1M/год дохода и оценкой $100M через управление внешним AUM (GRAND_VISION_v1.md).

На текущей стадии (paper trading, go-live планируется ~2026-08-01) необходимо принять
архитектурное решение о **модели монетизации и привлечения капитала**: token launch,
традиционный equity-раунд, или гибридный подход.

Это решение влияет на:
- Юридическую структуру и регуляторные риски
- Скорость выхода на рынок
- Возможность привлечения институционального AUM (DAO, family offices)
- Dilution команды и долгосрочный upside
- Community alignment и DeFi-нативность продукта

---

## Рассмотренные варианты

### Option A: Pure Equity

**Описание:**
Традиционный корпоративный раунд. Структура — Delaware LLC или Gibraltar Ltd.
Привлечение от VC/angel investors в обмен на equity stake. Upside для инвесторов —
через buyback, dividends, или M&A exit.

**Структура:**
- Entity: Delaware LLC → C-Corp при Series A
- Инструменты: SAFE (Simple Agreement for Future Equity), конвертируемые ноты, preferred shares
- Возврат инвесторам: performance fees (2/20 структура) → buyback или dividend
- Типичный timeline: seed $200K–$1M → Series A $3M–$10M при $10M+ AUM

**Плюсы:**
- Минимальный регуляторный риск — понятная правовая среда
- Подходит для институциональных инвесторов (family offices, VC)
- Не требует token launch инфраструктуры
- Быстрее: можно закрыть SAFE-раунд за 1–3 месяца

**Минусы:**
- Нет community alignment — DeFi-аудитория предпочитает token участие
- DAO treasuries не могут инвестировать в equity (их governance голосует за token-based deals)
- Ограниченный ликвидный рынок для exit (только M&A или buyback)
- Традиционный VC может не понимать DeFi-специфику

---

### Option B: Governance Token

**Описание:**
ERC-20 токен с governance правами и/или fee-sharing. DAO-структура. Token launch
через IDO (Initial DEX Offering) или LBP (Liquidity Bootstrapping Pool).
Инвесторы и community holders получают часть management fees через token mechanics.

**Структура:**
- Entity: Foundation (Cayman Islands или Panama) + Swiss Association
- Token: ERC-20, governance + fee-sharing
- Distribution: team (20%), investors (15%), community/ecosystem (40%), treasury (25%)
- Launch: LBP на Balancer или IDO на Uniswap v3
- Revenue sharing: % от management fees → buyback/burn или staking rewards

**Плюсы:**
- Максимальный community alignment — DeFi-нативные пользователи и DAO получают upside
- DAO treasuries могут инвестировать через governance votes в token-based протоколы
- Ликвидный secondary market с первого дня
- Token can bootstrap protocol liquidity и awareness

**Минусы:**
- **Критически высокий регуляторный риск** — SEC рассматривает большинство DeFi-токенов как securities
- Требует $500K–$2M+ на legal structure, KYC/AML, регуляторное мнение до launch
- Timeline: 12–18 месяцев подготовки минимум для compliance-first запуска
- Token launch отвлекает от core product development
- Институциональные family offices (Phase 2) не могут держать unregistered tokens
- Bear market условия делают token launch токсичным для команды (cliff, vesting)

---

### Option C: Hybrid (equity сейчас → токен позже)

**Описание:**
Двухэтапная структура: **equity seed раунд сейчас** (SAFEs, простая структура) →
**token launch позже** (после $10M AUM, полного аудита, regulatory clarity).
Two-class structure позволяет equity investors конвертироваться в tokens при launch.

**Структура (Этап 1 — сейчас):**
- Entity: Delaware LLC
- Инструменты: SAFE @ $2M–$5M cap (no discount, MFN)
- Target raise: $200K–$500K (angels, DeFi-нативные инвесторы)
- Use of funds: legal structure, audit, team expansion, marketing
- SAFE terms: стандартный YC SAFE с token side letter (право на конвертацию при token event)

**Структура (Этап 2 — при $10M+ AUM):**
- Delaware LLC → Foundation wrapper (или separate token entity)
- Token launch: LBP или private sale → community round
- Equity investors конвертируются в tokens по согласованному rate
- DAO-структура для управления протоколом

**Плюсы:**
- Минимизирует регуляторный риск на ранней стадии — equity понятно всем
- Максимальная скорость: SAFE-раунд можно закрыть за 1–2 месяца
- Сохраняет опциональность: можно отказаться от токена при неблагоприятном regulatory environment
- Institutional investors (family offices) комфортно с equity на seed
- Token side letter даёт DeFi-нативным инвесторам желаемый upside
- Позволяет сначала доказать track record, потом делать token launch с реальными метриками

**Минусы:**
- Сложная структура: нужно заранее договориться о конвертации
- DAO-investors в Phase 1 всё равно не смогут инвестировать в equity (только в токены/grants)
- При отказе от токена: equity investors теряют DeFi-нативный upside (risk)
- Требует качественного legal counsel для структурирования SAFE + token side letter

---

### Option D: Bootstrap (без внешнего капитала)

**Описание:**
Полный bootstrap на собственном капитале. DAO treasury partnerships без equity —
revenue sharing через smart contracts, не через ownership. Органический рост
через performance fees с первых managed AUM.

**Структура:**
- Нет внешних инвесторов
- Revenue: 2% management fee + 20% performance fee от managed AUM
- DAO partnerships: on-chain fee sharing через smart contract (не equity)
- Break-even: при $1M AUM → $20K/год management fee + performance

**Плюсы:**
- Ноль dilution
- Полный контроль над продуктом и стратегией
- Нет давления от инвесторов на timeline

**Минусы:**
- Крайне медленный рост без капитала на масштабирование
- Сложно нанять team без equity/salary funding
- При $1M AUM break-even по операционным расходам — нет средств на рост
- DAO partnerships без equity/token структуры сложно закрыть
- **Не достигает $1M/год дохода** за разумный timeframe без внешнего AUM

---

## Анализ по критериям

| Критерий | Option A (Pure Equity) | Option B (Gov Token) | Option C (Hybrid) ⭐ | Option D (Bootstrap) |
|---|---|---|---|---|
| **Regulatory risk** | 🟢 Низкий | 🔴 Критический | 🟡 Низкий→Средний | 🟢 Минимальный |
| **Time-to-market** | 🟢 1–3 месяца | 🔴 12–18 месяцев | 🟢 1–2 месяца (seed) | 🟢 Немедленно |
| **DAO investor appeal** | 🔴 Нет (equity≠DAO) | 🟢 Высокий | 🟡 Средний (token later) | 🟡 Средний (rev share) |
| **Institutional appeal** | 🟢 Высокий | 🔴 Низкий | 🟢 Высокий | 🟡 Средний |
| **Team dilution** | 🟡 Умеренный | 🔴 Высокий (tokenomics) | 🟡 Умеренный | 🟢 Нулевой |
| **Community alignment** | 🔴 Слабый | 🟢 Максимальный | 🟡 Средний (опция) | 🟡 Слабый |
| **Capital for growth** | 🟢 Есть | 🟢 Есть | 🟢 Есть | 🔴 Нет |
| **Legal complexity** | 🟢 Низкая | 🔴 Очень высокая | 🟡 Умеренная | 🟢 Минимальная |
| **Exit options** | 🟡 M&A/buyback | 🟢 Liquid token | 🟢 Оба варианта | 🔴 Ограниченные |
| **$1M/год цель** | 🟢 Реалистично | 🟡 Реалистично | 🟢 Реалистично | 🔴 Затруднено |

**Итоговый рейтинг:**
- Option C (Hybrid): 🟢×6 🟡×3 🔴×1 — **ПОБЕДИТЕЛЬ**
- Option A (Pure Equity): 🟢×5 🟡×2 🔴×3
- Option D (Bootstrap): 🟢×4 🟡×3 🔴×3
- Option B (Gov Token): 🟢×3 🟡×1 🔴×6

---

## Рекомендация: Option C — Hybrid

### Обоснование

**Option C принят** как оптимальный баланс между скоростью, риском и долгосрочным потенциалом:

1. **Регуляторная защита:** Delaware LLC + SAFE — это наиболее понятная и безопасная
   структура для текущего регуляторного климата в США (SEC enforcement активен, Gensler legacy).
   Token launch откладывается до момента, когда либо появится regulatory clarity
   (DOGE/crypto-friendly SEC), либо достигнут достаточный AUM для compliance investment.

2. **Скорость:** SAFE-раунд можно закрыть за 4–8 недель с правильными инвесторами.
   Это позволяет сфокусироваться на core product (track record, audit, AUM growth),
   а не на токен-инфраструктуре.

3. **Сохранение опциональности:** Token side letter в SAFE даёт DeFi-нативным
   инвесторам желаемый exposure к токену при launch, при этом юридически equity-раунд
   полностью чист.

4. **Institutional AUM:** Family offices и DAO treasury managers на Phase 2/3 готовы
   работать с управляющим с Delaware LLC. Equity структура = credibility для этого сегмента.

5. **Path to $1M/год:** При $10M AUM (2% mgmt fee + 20% perf fee на ~8% net yield):
   $200K/год mgmt + ~$160K/год perf = ~$360K/год. Seed капитал помогает достичь
   этого AUM быстрее через marketing, legal, team.

### Альтернатива при изменении условий

Если к Q2 2027 произойдёт:
- SEC публикует safe harbor для DeFi utility tokens, **ИЛИ**
- MiCA (EU) создаёт clear pathway для DeFi governance tokens, **ИЛИ**
- AUM достигает $10M+ с подтверждённым track record

→ Перейти к token feasibility study и инициировать ADR для пересмотра этого решения.

---

## Следующие шаги

### Немедленно (сейчас → Июль 2026)

- [ ] Продолжать paper trading, строить track record (цель: 60 дней real track)
- [ ] Финализировать go-live подготовку (GoLiveChecker criteria)
- [ ] Завершить DD-пакет базовую версию (technical architecture doc, risk policy doc)
- [ ] Начать нетворкинг для seed (warm intro через DeFi-нативных знакомых)

### При $100K real AUM (ориентир: Октябрь–Декабрь 2026)

- [ ] **Зарегистрировать Delaware LLC**
- [ ] Подготовить SAFE с token side letter (стандартный YC SAFE + crypto addendum)
- [ ] Закрыть seed раунд: **$200K–$500K @ $2M–$5M cap**
  - Target investors: DeFi-нативные angels, крипто-family offices, DAO delegates
  - Use of funds: legal/compliance ($50K), audit ($100K), BD/marketing ($50K), операционные ($100K+)
- [ ] Сформировать advisory board (DeFi protocol advisors + compliance advisor)

### При $500K real AUM (ориентир: 2027)

- [ ] **Token feasibility study:** анализ regulatory landscape, costs, timing
- [ ] Если регуляторная среда позволяет: подготовка к token launch
  - Структура: Foundation wrapper + ERC-20 governance token
  - Equity-to-token конвертация для seed investors согласно side letter terms
- [ ] Если регуляторная среда неблагоприятна: Series A equity round от institutional VC

### Долгосрочно ($10M+ AUM / 2027–2028)

- [ ] Выбор между: Series A ($3M–$10M) для масштабирования ИЛИ token launch + DAO
- [ ] Independent audit (trail leading to $100M valuation target — GRAND_VISION_v1.md)
- [ ] Рассмотрение white-label для institutional partners

---

## Связанные документы

- `GRAND_VISION_v1.md` — финансовая цель $1M/год, оценка $100M
- `MASTER_PLAN_v1.md §1` — финансовая модель
- `docs/OUTREACH_STRATEGY_v1.md` (MP-502) — outreach по сегментам
- `docs/adr/ADR-002-golive-transfer-rule.md` — правило перехода в live
- `KANBAN.json` → MP-502, MP-508

---

*ADR принят: 2026-06-12. Пересмотр: при изменении regulatory landscape или достижении $500K AUM.*
