# Regulatory Analysis: DeFi Yield Platform
## SPA — Smart Passive Aggregator

**Date:** 2026-06-18  
**Scope:** Операционная юрисдикция Украина, инвесторы Европа/СНГ, non-US  
**Горизонт:** Family fund $100K–500K (2026) → внешний AUM (2027+)  
**Disclaimer:** *Это информационный анализ, не юридическая консультация. Перед принятием решений — проконсультируйся с лицензированным юристом по финансовому праву в соответствующей юрисдикции.*

---

## Содержание

1. [Юридическая структура](#1-юридическая-структура)
2. [MiCA 2024 — Лицензирование](#2-mica-2024--лицензирование)
3. [Family Fund Exemptions](#3-family-fund-exemptions)
4. [Disclaimers на Landing Page](#4-disclaimers-на-landing-page)
5. [AML/KYC при онбординге инвесторов](#5-amlkyc-при-онбординге-инвесторов)
6. [Geo-blocking: обязательные юрисдикции](#6-geo-blocking-обязательные-юрисдикции)
7. [Смарт-контракт vault — регуляторика](#7-смарт-контракт-vault--регуляторика)
8. [Минимально необходимые документы](#8-минимально-необходимые-документы)
9. [Дорожная карта: что делать и когда](#9-дорожная-карта-что-делать-и-когда)
10. [Источники](#10-источники)

---

## 1. Юридическая структура

### Текущее состояние (2026): нет внешних инвесторов

Пока SPA работает только с виртуальным капиталом или капиталом основателей — **никакой юридической структуры не требуется**. Регуляторика включается в момент, когда появляются инвесторы.

### Для Family Fund ($100K–500K, 2026)

**Наименее сложный вариант — украинское ТОВ (ООО):**

- Зарегистрировать ТОВ специально под управление средствами семейного круга
- Оформить Договір про спільну діяльність (Joint Activity Agreement) или инвестиционный договор с каждым участником
- Это **не фонд** в юридическом смысле — просто договорные отношения между физлицами/юрлицами
- Минимальный порог регуляторного риска, если участников < 10 и все — известные лица, не публичное привлечение

**Альтернатива для формального оформления — эстонская OÜ или литовская UAB:**

- Быстрая регистрация (1–5 дней), €700–1 500
- Банковский счёт открывается проще, чем для украинских юрлиц
- Если в будущем понадобится MiCA лицензия — базовая компания уже в ЕС
- Подходит для управления криптоактивами как CASP под MiCA

### Для внешнего AUM (2027+, не-CIS инвесторы)

**Рекомендуемая структура (2-уровневая):**

```
Управляющая компания (OpCo)
  → Эстония/Литва: UAB/OÜ + будущая CASP-лицензия MiCA Class 1
  → Или: украинское ТОВ (операционно) + EU entity для инвесторов

Фондовый SPV (FundCo)
  → Открытое товарищество: Cayman Islands Limited Partnership (Cayman LP)
    OR British Virgin Islands (BVI) Business Company
    OR Эстонский AIF (Alternative Investment Fund) — если <€500M, нет плеча, lock-up 5 лет
  → Инвесторы входят через subscription agreement
```

**Почему Cayman/BVI как фонд-SPV:**
- Стандарт для hedge/crypto фондов, привычен для EU-инвесторов
- Освобождение от EU AIFMD при условии отсутствия маркетинга EU-инвесторам через "national private placement regimes" (NPPR) — различается по стране
- Стоимость регистрации Cayman LP: $10 000–20 000 USD; ежегодное обслуживание: $5 000–10 000 USD

**Почему Estonian AIF (Альтернативный Инвестиционный Фонд):**
- Если AUM < €100M — sub-threshold AIFM, только регистрация без полной авторизации
- Если AUM < €500M И нет плеча И lock-up ≥ 5 лет — также sub-threshold
- Легальный доступ к EU-инвесторам без полного AIFMD-лицензирования
- Ниже стоимость, чем CASP MiCA (регистрация ~€5 000–15 000)

### Украина: что с регуляторикой сейчас

- Закон о виртуальных активах (№ 2074-IX, 2022) **не вступил в силу** — нет действующего лицензирования VASP
- Законопроект №10225-d (апрель 2025) выровнен под MiCA, первое чтение пройдено
- Регистрация VASP в Украине — до 1 июля 2026 (для тех, кто уже оказывал услуги)
- **Практически:** до принятия нового закона оперировать из Украины можно на основании общих норм гражданского/хозяйственного права; для инвесторов вне Украины — использовать EU-entity

### Вывод: минимально-необходимая структура по фазам

| Фаза | Структура | Стоимость |
|------|-----------|-----------|
| Paper trading (сейчас) | Ничего не нужно | — |
| Family fund 2026 | ТОВ (Украина) + договора инвесторов | ~$500–2K |
| EU-инвесторы 2026–2027 | Estonian OÜ / Lithuanian UAB + MiCA CASP Class 1 | ~€20K–50K |
| External AUM 2027+ | +Cayman/BVI SPV ИЛИ Estonian AIF (sub-threshold) | +$10K–20K |

---

## 2. MiCA 2024 — Лицензирование

### Что такое MiCA и когда применяется

MiCA (Regulation EU 2023/1114) — единый EU-регуляторный фреймворк для крипто-активных сервис-провайдеров (CASPs). Полностью вступил в силу **30 декабря 2024**. Переходный период для действующих VASP — до **1 июля 2026**.

### Покрывает ли MiCA SPA?

**Ключевой вопрос:** является ли SPA Crypto-Asset Service Provider?

| Сценарий | Покрытие MiCA | Лицензия |
|----------|---------------|----------|
| Только свой капитал (paper/own funds) | ❌ Нет | Не нужна |
| Семейный фонд (close circle, нет публичного привлечения) | ⚠️ Серая зона | Возможно нет |
| Управление портфелем для внешних инвесторов-EU | ✅ Да | CASP Class 1 |
| Рекомендации по крипто-активам + портфельное управление | ✅ Да | CASP Class 1, €50K min capital |

**Portfolio Management of Crypto-Assets** = CASP Class 1, минимальный капитал €50 000.

**Важное исключение:** Если SPA структурируется как **AIFM (Alternative Investment Fund Manager)** под AIFMD — отдельная CASP-лицензия MiCA **не нужна**. AIFMD-лицензированный управляющий может управлять портфелем крипто-активов без дополнительного MiCA-авторизования.

### Что MiCA НЕ покрывает

- **Полностью децентрализованные протоколы** (Recital 22 MiCA) — ESMA ещё уточняет определение в 2026
- Финансовые инструменты под MiFID II
- Собственный капитал (not managing for others)

### Временные рамки и стоимость MiCA CASP Class 1

- Процесс авторизации: **3–6 месяцев**
- Минимальный капитал: **€50 000** (Class 1: advisory + portfolio management)
- Документационный пакет: ~€19 900–35 000 (outsourced)
- Ежегодные затраты: MLRO (~€12K), local EU director (~€34K), офис (~€5K)
- **Итого первый год: ~€100 000–120 000**

### Практический совет

Для начала (2026) — структурировать family fund через договорные отношения без MiCA-лицензии. Начать подготовку к MiCA CASP Class 1 за 6 месяцев до планируемого привлечения EU-инвесторов (т.е. начать подготовку **Q4 2026** для запуска Q2 2027).

---

## 3. Family Fund Exemptions

### EU AIFMD — исключения

**Исключение 1: Корпоративная "family" (Article 3(1) AIFMD)**

AIFMD не применяется к управляющим, если ВСЕ инвесторы фонда — это:
- Сама управляющая компания (AIFM)
- Материнские компании AIFM
- Дочерние компании AIFM
- ...и никто из них сам не является AIF

→ Это работает для корпоративной семьи (холдинговые структуры), но **НЕ для биологической семьи**.

**Исключение 2: Sub-threshold AIFM**

- AUM < €100M → только регистрация (не полная авторизация), упрощённая отчётность
- AUM < €500M при условии: нет кредитного плеча + lock-up ≥ 5 лет для первичных инвестиций → также регистрация

При $100K–500K AUM — **полностью под sub-threshold** даже при росте до €100M.

**Исключение 3: "Family office" test**

EU-регуляторы (включая ESMA, Linklaters, FCA) прямо указывают: *"joint ventures or family office vehicles are not expected to be considered AIFs"* при условии, что они **инвестируют собственные деньги**, не привлекают капитал от внешних инвесторов.

→ Если "family fund" = несколько членов семьи, договорившихся совместно инвестировать через общее юрлицо — это **не AIF**, регуляторное лицензирование не требуется.

### Практические границы "close circle" exemption

| Параметр | Безопасно | Риск |
|----------|-----------|------|
| Количество инвесторов | 5–10 человек | >50 |
| Привлечение | Частное (устное/договорное) | Публичное (реклама, landing page) |
| Статус инвесторов | Квалифицированные / HNW / знакомые | Розничные незнакомые |
| Минимальная сумма | ≥€100K (де-факто accredited) | <€1K (retail) |
| Наличие маркетинга | Нет | Есть |

### Рекомендация: структура семейного фонда 2026

1. Оформить через ТОВ или простое партнёрство (договір про спільну діяльність)
2. Строго ограничить круг участников: < 10 человек, все идентифицированы
3. Каждый участник подписывает: Договір інвестора + Risk Disclosure
4. Никакого публичного маркетинга и привлечения незнакомых лиц
5. При необходимости использовать квалификационный порог: мин. инвестиция €100K+ (de facto accredited investor)

---

## 4. Disclaimers на Landing Page

### Обязательные блоки (MiCA + EU best practices)

**Блок 1: Основной инвестиционный дисклеймер**

```
⚠️ RISK WARNING: Investing in crypto-assets and DeFi protocols involves 
significant risks, including complete loss of capital. Crypto-assets are 
highly volatile and unregulated in many jurisdictions. Past performance 
does not guarantee future results.
```

**Блок 2: Регуляторный статус**

```
[SPA] is NOT regulated by the European Securities and Markets Authority 
(ESMA), the European Banking Authority (EBA), or any national competent 
authority in the European Union. This service does not constitute an offer 
or solicitation to invest in any jurisdiction where such activities are 
not permitted.
```

*Примечание: если получите CASP-лицензию — текст меняется на подтверждение регуляции.*

**Блок 3: Geo-restriction**

```
This service is NOT available to: US Persons (as defined under Regulation S 
of the U.S. Securities Act of 1933), residents of Russia, Belarus, Iran, 
North Korea, Cuba, Syria, and other sanctioned jurisdictions. By accessing 
this service, you confirm that you are not a US Person and are not located 
in a restricted jurisdiction.
```

**Блок 4: DeFi-специфичные риски**

```
Additional risks include: smart contract vulnerabilities and exploits, 
oracle manipulation, liquidity risk, protocol governance risk, regulatory 
risk, and technology failure. Funds deployed in DeFi protocols are not 
covered by any deposit protection scheme.
```

**Блок 5: Не финансовый совет**

```
Nothing on this website constitutes financial, investment, legal, or tax 
advice. You should consult qualified professionals before making investment 
decisions.
```

**Блок 6: GDPR (обязателен для EU-пользователей)**

```
We collect and process personal data in accordance with GDPR (Regulation 
EU 2016/679). See our Privacy Policy for details.
```

### Техническая имплементация

- Все дисклеймеры — в footer сайта (постоянно видны)
- При первом визите — cookie/consent banner (decline non-essential по умолчанию)
- Перед любым инвестиционным действием — отдельный экран подтверждения рисков
- Дисклеймер "Not available to US Persons" — на главной странице и в форме регистрации

---

## 5. AML/KYC при онбординге инвесторов

### Применимые стандарты

- **FATF Recommendation 15**: VASPs обязаны применять AML/CFT-меры
- **FATF Recommendation 16 (Travel Rule)**: при переводах между VASP >$1 000 — передача данных отправителя/получателя
- **EU AMLD5/6**: KYC обязателен для криптобирж и кастодиальных провайдеров
- **EU Transfer of Funds Regulation** (30 дек. 2024): Travel Rule для ВСЕХ крипто-переводов между CASPs без порога

### Минимальный KYC для family fund (не-CASP)

Даже без формальной лицензии — базовый KYC защищает от правовых рисков:

| Шаг | Действие | Инструмент |
|-----|----------|-----------|
| 1. Идентификация | Копия паспорта + selfie | Вручную или Sumsub/Veriff ($0.5–2/чел) |
| 2. Проверка адреса | Подтверждающий документ (счёт за ЖКХ < 3 мес.) | Вручную |
| 3. Санкции | Проверка по OFAC SDN + EU Consolidated List + UN | Бесплатно: OFAC/EU сайты; или API |
| 4. PEP | Политически значимые лица | Бесплатно: ACAMS / World-Check (платно) |
| 5. Источник средств | Декларация об источнике (самоподписанная) | Форма PDF |
| 6. Ongoing | Ежегодная актуализация данных | CRM/ручной |

### Расширенный KYC для внешних инвесторов (при CASP-лицензии)

- Верификация через liveness check (биометрия)
- Enhanced Due Diligence (EDD) для PEP и high-risk jurisdictions
- Мониторинг транзакций on-chain (Chainalysis, Elliptic — платно)
- Отчётность в FIU (Financial Intelligence Unit) при подозрительных операциях

### CIS-инвесторы: специальные соображения

- **Россия/Беларусь**: EU 20-й пакет санкций (апрель 2026) — **ПОЛНЫЙ ЗАПРЕТ** на крипто-транзакции с российскими и белорусскими CASPs и DeFi-платформами. EU-регулируемые сервисы обязаны блокировать
- **Другие СНГ**: Казахстан, Грузия, Армения, Азербайджан — не санкционированы, но требуют стандартный AML
- **Украина**: не под санкциями, но war zone — требует усиленный source-of-funds

---

## 6. Geo-blocking: обязательные юрисдикции

### Категория 1: ОБЯЗАТЕЛЬНЫЙ полный блок

| Юрисдикция | Причина | Правовая основа |
|-----------|---------|----------------|
| **США** (US persons) | Нет регистрации SEC/CFTC; Regulation S | US Securities Act 1933 |
| **Россия** | EU санкции (20-й пакет, апрель 2026) | EU Regulation 833/2014 + amendments |
| **Беларусь** | EU санкции | EU Regulation 765/2006 + amendments |
| **Иран** | OFAC полное эмбарго | OFAC Iran Sanctions |
| **Северная Корея** | OFAC полное эмбарго | OFAC DPRK Sanctions |
| **Куба** | OFAC полное эмбарго | OFAC Cuba Sanctions |
| **Сирия** | OFAC полное эмбарго | OFAC Syria Sanctions |

### Категория 2: РЕКОМЕНДУЕТСЯ заблокировать (высокий риск)

| Юрисдикция | Причина |
|-----------|---------|
| Мьянма (Бирма) | FATF grey list + US/EU sanctions |
| Венесуэла | OFAC secondary sanctions + FATF |
| Никарагуа | OFAC secondary sanctions |

### Что такое "US Person" (важно — шире, чем кажется)

US Person по Regulation S включает:
- Граждан США (независимо от страны проживания)
- Резидентов США (green card holders)
- Компании, зарегистрированные в США
- Трасты и estate с US-бенефициарами

**Практические меры geo-blocking:**

1. **IP-блокировка**: заблокировать IP-диапазоны USA, Russia, Belarus, Iran, DPRK, Cuba, Syria
2. **Self-declaration**: при регистрации — чекбокс "Я не являюсь US Person и не нахожусь в санкционированной юрисдикции"
3. **Contractual representation**: в договоре инвестора — заверение о не-US-статусе
4. **ID-проверка**: во время KYC — верификация паспорта (не US/RU/BY/IR/etc.)
5. **Wallet screening**: проверка on-chain адресов на санкционные связи

**Важно:** IP-блокировка одна не достаточна (VPN). Нужна комбинация: IP + self-declaration + ID verification.

---

## 7. Смарт-контракт Vault — регуляторное одобрение

### Текущее состояние (2026)

**Прямого "регуляторного одобрения" для деплоя смарт-контрактов не существует** (в Европе и Украине). Однако правовая квалификация деятельности вокруг контракта определяет, нужны ли лицензии.

### ESMA: 5 категорий смарт-контрактов (2024)

ESMA опубликовала классификацию, делящую смарт-контракты на 5 типов. Ключевое разграничение:

- **Полностью децентрализованный протокол** (no identifiable issuer, no upgradeable admin key) → **вне MiCA** (Recital 22)
- **Протокол с идентифицируемым оператором** (fees collector, upgrade key, governance token controller) → **может попадать под MiCA**

### Тест "декентрализованности" для SPA vault

| Признак | SPA сейчас | Риск |
|---------|-----------|------|
| Кто деплоит контракт? | SPA team | ⚠️ Есть оператор |
| Кто собирает комиссию? | SPA | ⚠️ Есть бенефициар |
| Есть ли admin key / upgradeable proxy? | Likely yes | ⚠️ Centralized control |
| Голосование токенхолдеров? | Нет | ⚠️ SPA team = decision maker |

→ **Вывод:** SPA vault с командой-оператором, собирающей fees — скорее всего **НЕ считается полностью децентрализованным** → не освобождается автоматически от MiCA.

### Howey Test (US) — применяется даже для non-US платформ

Если vault выпускает токены (shares/LP tokens) для внешних инвесторов:
- Инвестиция денег ✓
- В общее предприятие ✓
- С ожиданием прибыли ✓
- Из усилий других (SPA team) ✓
→ Потенциально **securities** по US law → ещё одна причина блокировать US persons

### Практические выводы для SPA

**На этапе paper trading:**
- Нет on-chain vault с внешним капиталом → нет проблемы
- Деплой контракта для собственных нужд (paper trading simulation) — нет регуляторных требований

**Перед деплоем production vault с внешним капиталом:**
1. Получить юридическое заключение по квалификации vault tokens в целевых EU-юрисдикциях
2. Если tokens = securities → нужна регистрация проспекта ИЛИ exemption (qualified investors only, <€1M)
3. Если tokens = utility / non-security → MiCA white paper (если публичное предложение >150 persons или >€1M)
4. Рассмотреть структуру **без публичного токена**: off-chain фонд с on-chain стратегией, LP tokens не выпускать

**Наименее рискованный вариант:** off-chain фонд (договорные отношения) + on-chain execution без публичных токенов → не требует securities registration и minimal MiCA exposure.

---

## 8. Минимально необходимые документы

### Для family fund (2026, pre-CASP)

**Обязательно:**

1. **Договір інвестора / Investment Agreement**
   - Стороны, предмет, срок
   - Размер и форма инвестиции (USDC/USD)
   - Условия входа/выхода, lock-up period
   - Распределение прибыли / fee structure (management fee + performance fee)
   - Риски (с подписью "ознакомлен")
   - Форс-мажор (DeFi-specific: smart contract failure, protocol hack)
   - Применимое право и юрисдикция споров

2. **Risk Disclosure Document**
   - Перечень всех категорий рисков: рыночный, ликвидности, смарт-контрактный, регуляторный, операционный
   - Специально: "DeFi протоколы не покрыты FDIC/deposit guarantee"
   - Отдельный параграф: "Исторические данные — симуляция (paper trading); реальный трек-рекорд с [дата]"
   - Подпись инвестора

3. **KYC-анкета / Onboarding Form**
   - Персональные данные
   - Копия ID + подтверждение адреса
   - Декларация источника средств
   - Декларация о не-US-статусе и не-санкционированной юрисдикции
   - Согласие на обработку персональных данных (GDPR)

4. **Внутренняя AML-политика**
   - Даже без лицензии — иметь written policy
   - Screening checklist: OFAC, EU Consolidated List, UN
   - Red flags и escalation procedure

### Для CASP MiCA (при получении лицензии)

Дополнительно к вышеперечисленному:

5. **MiCA Whitepaper** (если выпускаются крипто-активы для клиентов)
6. **CASP Client Agreement** (стандартный шаблон для услуг portfolio management)
7. **Conflicts of Interest Policy**
8. **Complaints Handling Procedure**
9. **Business Continuity Plan**
10. **Governance Framework** (с EU-резидентным директором, MLRO)

### Privacy Policy (обязательна для EU-пользователей)

- GDPR-compliant
- Что собирается, как используется, права субъектов данных
- Контакт DPO (Data Protection Officer) если обрабатываются данные в промышленных масштабах

---

## 9. Дорожная карта: что делать и когда

### Q3 2026 (сейчас → до go-live)

- [x] Завершить 30 дней честного трека (до ~10 июля 2026)
- [ ] **Зарегистрировать ТОВ** (или решить использовать физлицо) для семейного фонда
- [ ] **Подготовить пакет документов** family fund: Договір інвестора + Risk Disclosure + KYC-форма
- [ ] **Добавить disclaimers** на дашборд/landing page (US persons, risk warning, not regulated)
- [ ] **Внедрить geo-blocking**: IP-блокировка US/RU/BY/IR/KP/CU/SY на уровне сервера
- [ ] Проверить все инвесторские адреса по OFAC SDN / EU sanctions list (бесплатно)

### Q4 2026

- [ ] Получить юридическую консультацию (1–2 часа с crypto lawyer в Эстонии или Литве) по структуре family fund: ~€500–1 500
- [ ] Принять решение: Estonian OÜ для EU-инвесторов? → если да, зарегистрировать
- [ ] Начать изучение требований MiCA CASP Class 1 (если цель — EU инвесторы в 2027)

### Q1 2027

- [ ] Если go-live состоялся → онбординг первых внешних инвесторов с полным KYC
- [ ] Решение о MiCA CASP авторизации: начать процесс (3–6 месяцев)

### Q2–Q3 2027

- [ ] Получить MiCA CASP Class 1 лицензию (если цель — EU scale)
- [ ] Или структурировать через Cayman LP + NPPR для EU-инвесторов (альтернатива)
- [ ] Деплой on-chain vault: только после юридического due diligence

---

## Краткое резюме ключевых выводов

| Вопрос | Ответ (кратко) |
|--------|----------------|
| Минимальная структура для family fund | ТОВ + договора; никакой лицензии не требуется при <10 участниках |
| MiCA лицензия нужна? | Не сейчас; нужна при внешних EU-инвесторах в 2027 (CASP Class 1, €50K) |
| Family fund exemption | Да: sub-threshold AIFMD (AUM < €100M); "family vehicle" test если только своё |
| Обязательные disclaimers | Risk warning, not regulated, not US persons, DeFi risks, not financial advice |
| Минимальный AML | ID + sanctions screen + PEP check + source of funds декларация |
| Обязательный geo-block | US, Russia, Belarus, Iran, DPRK, Cuba, Syria |
| Smart contract vault | Нет прямого approval; но если есть оператор — под MiCA; без публичного токена — минимальный риск |
| Минимальные документы | Договір інвестора + Risk Disclosure + KYC-анкета + внутренняя AML политика |

---

## 10. Источники

1. [ESMA: Markets in Crypto-Assets Regulation (MiCA)](https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica)
2. [MiCA Regulation Guide 2026 — AdamSmith](https://adamsmith.lt/en/mica-license-2025/)
3. [MiCA Regulation and EU Crypto Rules: What Changes in 2026 — SumSub](https://sumsub.com/blog/crypto-regulations-in-the-european-union-markets-in-crypto-assets-mica/)
4. [EU Crypto AML Platform Guide 2026 — AMLBot](https://blog.amlbot.com/eu-crypto-aml-platform-guide/)
5. [AIFMD Authorisation Exemptions — Linklaters](https://www.linklaters.com/en/insights/publications/aifmd/authorisation-requirements/authorisation-exemptions)
6. [Sub-threshold AIFM — FCA (UK)](https://www.fca.org.uk/publication/documents/authorisation-options-under-aifmd.pdf)
7. [Blockchain & Cryptocurrency Laws Ukraine 2026 — GLI](https://www.globallegalinsights.com/practice-areas/blockchain-cryptocurrency-laws-and-regulations/ukraine/)
8. [Ukraine Virtual Assets Law — NSSMC](https://www.nssmc.gov.ua/en/virtualni-aktyvy-v-zakoni-v-ukraini-predstavlenyi-dovhoochikuvanyi-dokument-dlia-zapusku-rynku/)
9. [Expert Guide Crypto Regulation Ukraine — CMS Law](https://cms.law/en/int/expert-guides/cms-expert-guide-to-crypto-regulation/ukraine/)
10. [EU 20th Russia Sanctions Package — TRM Labs](https://www.trmlabs.com/resources/blog/eu-adopts-20th-sanctions-package-on-russia----including-a-sweeping-ban-on-all-crypto-asset-transactions-with-russian-and-belarusian-providers)
11. [KYC and AML for Crypto Exchanges — ChainUP](https://www.chainup.com/academy/kyc-aml-crypto-exchanges-compliance-guide/)
12. [SEC/CFTC Joint Guidance on Digital Assets — Ropes & Gray (March 2026)](https://www.ropesgray.com/en/insights/alerts/2026/03/sec-and-cftc-issue-landmark-joint-guidance-on-classification-of-crypto-assets-under-federal-securities-laws)
13. [Howey Test — Securities Law Blog](https://securities-law-blog.com/category/the-howey-test/)
14. [Crypto Compliance in 2026 — Grant Thornton](https://www.grantthornton.com/insights/articles/banking/2026/crypto-compliance-in-2026)
15. [AIFMD II Luxembourg Implementation — Ogier](https://www.ogier.com/news-and-insights/insights/aifmd-ii-a-practical-guide-to-implementation-in-luxembourg/)

---

*Prepared by Claude (deep research) | 2026-06-18 | SPA Project*  
*⚠️ Не является юридической консультацией. Проверь актуальность перед применением.*
