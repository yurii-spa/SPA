---
trackerStatus:
  type: inbox
title: "§41 приёмки ТЗ CIO (auto-execution limits): замеры сделаны, ловушка названа — мерить обе поверхности решения, не только гейт"
status: done
source: nimbalyst
created: 2026-09-07
claimed_by: cycle-22542
claimed_at: 2026-09-07T02:12:01Z
status_trail:
  - "2026-09-07T02:39:39.271089+00:00 new -> done · queue.set_status · cycle-22542"
---

## Что это

Подготовка к §41 приёмки ТЗ «Portfolio CIO» (`auto-execution limits`), сделанная
циклом #509 попутно к §42. Задача НЕ начата — здесь замеры, которые следующему
циклу не надо делать заново, и одна ловушка, в которую он иначе попадёт.

## Критерий владельца, дословно

> **41. Auto-execution limits.** Если будет разрешен auto-execution, предусмотреть:
> `max trade amount` · `max % portfolio per rebalance` · `max daily turnover` ·
> `allowed protocols` · `allowed vaults` · `allowed tiers` · `allowed chains` ·
> `allowed assets` · `minimum expected net gain` · `minimum confidence` ·
> `minimum persistence` · `maximum acceptable risk delta`.
> **Все policy-configurable.**

Требований ДВА, как и в §42: «ограничение есть» и «ограничение
policy-configurable». Их надо мерить по отдельности.

## 🪤 ЛОВУШКА — прочитать до начала работы

**Ограничение может связывать на ОДНОЙ поверхности решения и не связывать на
другой, и замер по одной из них даст ВЕРНЫЙ ответ на НЕ ТОТ вопрос.**

Замер 07.09 на настоящем `_apply_risk_policy_gate`: T3 суммарно **25 %**
проходит гейт с НУЛЁМ нарушений, хотя `RiskConfig.max_total_t3_allocation = 0.15`
объявлено (ADR-020). Отсюда напрашивается вывод «объявленное поле не связывает» —
и он был бы НЕВЕРЕН: поле читают `allocator.py:703` (`T3_TOTAL_CAP` +
`_enforce_t3_total_cap`), `policy_enforcer.py:35`, `allocation_auditor.py:225`,
`allocation_rationale.py:279`. Потолок связывает у АЛЛОКАТОРА, а не у гейта.

То же и с сетями: гейт на смену `chain` не реагирует НИКАК, но у аллокатора есть
`SINGLE_CHAIN_CAP`, `L2_TOTAL_CAP`, `BASE_CHAIN_CAP` (ADR-136).

**Вывод для следующего цикла: каждое из 12 ограничений мерить на ОБЕИХ
поверхностях** (аллокатор — предлагает; гейт — допускает) **и называть в отчёте,
на какой именно оно связывает.** Замер только по гейту объявил бы «сети и тиры
не ограничены» — ложная находка, и ровно того класса, который здесь ловят.

## Что уже измерено (не переделывать)

Ось «применяется ли ограничение вообще» — варьируем ВЕЛИЧИНУ, смотрим, меняется
ли вердикт. На гейте (`_apply_risk_policy_gate`, временный каталог состояния,
живой `data/` не тронут):

| величина владельца | меняется ли вердикт гейта | замечание |
|---|---|---|
| актив пула (`asset`) | **НЕТ** | подтверждает ADR-247: актив не спрашивается ни разу |
| сеть (`chain`) | **НЕТ** у гейта | но у аллокатора потолки есть (ADR-136) — см. ловушку |
| тир | **ДА** | неизвестный тир (`T9`) и `T3` молча получают потолок T2 = 20 % |
| незнакомое имя протокола | **НЕТ** | финансируется без вопроса к реестру (ADR-247, частично) |

Ось «policy-configurable» — перебор порогов `TriggerParams` через
`rebalance_economics.evaluate` на сцене «покупка с двойным запасом выгоды».
СВЯЗЫВАЮТ (ужесточение переворачивает `ACT` → `HOLD`): `min_gain_pp`,
`max_turnover_per_move`, `max_payback_days`, `max_turnover_per_week`,
`min_leg_frac`. НЕ проверены на этой сцене (она их не достаёт — нужна СВОЯ сцена
на каждый, иначе «не изменил вердикт» будет выдано за «ручка мёртвая»):
`min_hold_days` (нужен `position_age_days`), `act_cooldown_days` (нужен
`days_since_last_act`), `reversal_escalation` / `reversal_window_days` (нужны
`last_move_legs` + `days_since_last_move`), `below_median_cap_factor`.

## Что видно уже сейчас (проверить, а не принять на веру)

- `max daily turnover` — у владельца ДНЕВНОЙ, у нас `max_turnover_per_week`
  (недельный) и `max_turnover_per_move` (на ход). Дневного, похоже, нет вовсе;
  `daily_limits.py` (DL-01…DL-05) — про убыток, просадку, концентрацию и
  вменяемость APY, но НЕ про оборот.
- `max trade amount` — у владельца СУММА, у нас только доли капитала.
- `minimum persistence` — ADR-248 уже измерил: длительность преимущества не
  считает никто.
- `allowed protocols` / `allowed vaults` / `allowed chains` — знать, что
  `spa_core/execution/router.py` несёт `allowed_chains` и `blacklisted_protocols`,
  но это execution-домен, и read-only путь его НЕ импортирует (инвариант 6).
  «Ограничение есть в дереве» и «ограничение стои́т на пути решения» — разное.

## Что от исполнителя

Замер по образцу ADR-247/248/249: модуль в `spa_core/monitoring/`, обе записи
манифеста, именная ветка шага 0-офис, вызов из моста, положительный контроль как
условие ВСЕГО отчёта, мутации по координате. Исходы на ограничение предлагаются
такие: `BINDING` (применяется И порог — объявленное поле политики) ·
`LITERAL` (применяется, но порог литерал) · `DECLARED_INERT` (поле объявлено, а
величина не спрашивается — опасная середина, аналог `CONFLATED` из §42) ·
`ABSENT` · `UNCHECKED` с причиной.

**Money-path не трогать:** ни один порог не менять, недостающее ограничение не
строить — это решение владельца.

---

## ИСПОЛНЕНО — цикл #510 (2026-09-07)

Замер §41 построен по заказу выше. Ловушка из этой карточки подтвердилась и
оказалась НЕ единственной — вторая нашлась уже в самой пробе (см. ниже).

**Доставлено:**

- `spa_core/monitoring/cio_auto_execution_limits.py` — замер 12 ограничений на
  ТРЁХ поверхностях решения (`allocator` предлагает · `economics` судит цену
  хода · `gate` допускает), две оси (величина / порог), пять исходов
  (`BINDING` · `LITERAL` · `DECLARED_INERT` · `ABSENT` · `UNCHECKED`);
- `spa_core/tests/test_cio_auto_execution_limits.py` — 29 проверок;
- `architecture/manifest.json` — ОБЕ записи (`artifacts[]` + `produces[]`);
- `scripts/consume_office_reports.py` — именная ветка шага 0-офис
  (`_READ_SCHEMA` + `_PRODUCER` + печать);
- `spa_core/monitoring/findings_bridge.py` — вызов из моста;
- **ADR-250** — решение и полный разбор.

**Результат: 4 · 2 · 0 · 6.**

| исход | сколько | какие |
|---|---|---|
| `BINDING` (есть + ручка владельца) | 4 | max % per rebalance · allowed tiers · allowed chains · min expected net gain |
| `LITERAL` (есть, порог в коде) | 2 | allowed protocols · minimum confidence |
| `DECLARED_INERT` | 0 | — |
| `ABSENT` | 6 | max trade amount · max daily turnover · allowed vaults · allowed assets · minimum persistence · maximum acceptable risk delta |

**Главное — не счёт, а ПОЛУСВЯЗАННЫЕ (ровно предмет этой карточки):** у гейта
потолок тира стоит НА ПРОТОКОЛ, а не на тир (T3 суммарно 25 % = 15 % + 10 % на
два пула проходит с нулём нарушений); незнакомый тир `T9` не отвергается, а
молча получает потолок T2 = 20 %; сеть у гейта не судится вовсе. Все три
ограничения держатся тем, что цель приходит от НАШЕГО аллокатора.

**Поправка к заготовке этой карточки.** Здесь было сказано, что ось
policy-configurable не достаёт до `min_hold_days`, `act_cooldown_days`,
`reversal_*` — «нужна СВОЯ сцена на каждый». Оказалось достаточно ОДНОЙ сцены,
если подать `position_age_days` и `days_since_last_act` явно и с запасом: на ней
связывают СЕМЬ порогов `TriggerParams`, а не пять. Не проверены на ней остались
`reversal_escalation` / `reversal_window_days` / `below_median_cap_factor`.

**Вторая ловушка, которую заготовка не предвидела** (и которая опаснее первой,
потому что тише): проба «происхождение потолка» при неразобранном источнике
возвращала пустой ответ, и `allowed tiers` с `allowed chains` МОЛЧА съезжали с
`BINDING` на `LITERAL` — отчёт объявил бы «порог зашит в коде» ровно про те
потолки, которые читаются из `RiskConfig`. Fail-OPEN в сторону ЛОЖНОЙ находки.
Поймано прогоном с корнем, где лежит только `data/` (мост зовёт
`run(root=args.root)`, и такой корень возможен). Теперь это названная причина
отказа всего отчёта.

**Money-path не тронут:** ни один порог не изменён, ни одно недостающее
ограничение не построено. Три вопроса владельцу — карточка
`owner-decision-avtotorgovlya-iz-12-tvoih-ogranichitelei`.
