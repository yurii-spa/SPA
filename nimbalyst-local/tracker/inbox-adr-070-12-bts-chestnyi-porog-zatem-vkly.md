---
trackerStatus:
  type: inbox
title: "ADR-070.12: BTS честный порог, затем включить TG"
status: new
source: nimbalyst
created: 2026-08-07
adr: ADR-070
---

Порог от НАШЕЙ доходности, убрать выдуманные k, потом SPA_BTS_ALERTS_ARMED=1 (решение владельца 2026-08-07, ADR-070 п.12)


---

## СВЕРКА 2026-08-17 — сделана первая половина, вторая ждёт владельца

Задание состоит из трёх шагов подряд: (1) порог от НАШЕЙ доходности,
(2) убрать выдуманные k, (3) **потом** `SPA_BTS_ALERTS_ARMED=1`.

**✅ Шаги 1 и 2 — в коде и под тестами.**

* Новый модуль `spa_core/monitoring/bts_baseline.py` (`read_our_yield`,
  `OurYieldRead`), импортируется `bts_monitor.py:55`.
* Порог тревоги — наша измеренная доходность; вердикт тревоги вынесен в
  отдельное поле `alert_gate` (`bts_monitor.py:669`), чтобы неизмеренный порог не
  делал измеренный спред ложью; ворота — `_alert_gate` (стр. 513).
* Выдуманные числа названы и обезврежены: `DEFAULT_CAPITAL_USD = 20000.0`
  помечен в коде как `# LEGACY literal — this sleeve holds no capital`
  (стр. 79), а публикуемое `annual_pnl_usd` = `None` с причиной (стр. 168,
  185–186, 479).
* Прогон: `python3 -m pytest spa_core/tests/test_bts_monitor_honesty.py -q` →
  **`39 passed in 0.34s`**.

**❌ Шаг 3 — НЕ сделан, и это правильно: он не агентский.**

```
$ grep -rn "SPA_BTS_ALERTS_ARMED" --include=*.plist .
(ничего)
```

В `scripts/com.spa.bts-monitor.plist` секции `EnvironmentVariables` нет вовсе.
Признак `BTS_ALERTS_ARMED_ENV` в коде объявлен (`bts_monitor.py:111`) и обе его
стороны закреплены тестами (`test_bts_monitor_honesty.py:323,334`), но взвод
требует правки plist + `launchctl bootout/bootstrap` на Маке — действие владельца
(`.claude/rules/deployment.md` п.6, инвариант #12).

## СВЕРКА 2026-08-18 — перепроверено прогоном, закрыт последний «ноль вместо не знаю»

Перепроверка шагов 1–2 своим прогоном + мутационный контроль:

* убрать порог (`if excess > 0` → `if True`) — краснеет
  `test_an_opportunity_below_our_own_yield_is_not_alert_worthy`;
* сделать порог непроходимым (`if False`) — краснеют три теста, включая
  положительный контроль «выше порога — реально шлёт»;
* пропускать при неизмеренном пороге — краснеют
  `test_unmeasurable_hurdle_refuses_every_alert` и `test_a_stale_track_is_an_unmeasurable_hurdle`.

**Найдено и починено:** при НЕизмеренном пороге счётчики публиковались как `0`
(`alert_gate.alert_worthy`, `summary.alert_worthy_count`) — то есть «тебе нечего сообщить»
там, где правда «мы не знаем». Теперь при неизмеренном пороге это `null` + дословная
причина в новых полях `alert_gate.alert_worthy_unchecked` / `summary.alert_worthy_unchecked`
(`bts_monitor._hurdle_unchecked`). Измеренный ноль остаётся нулём и отличим от null.

**Замер порога на копии `data/` в контейнере (2026-08-18):** порог НЕ измерен —
`evidenced track is stale: newest day 2026-08-02 is 1454401s old (limit 172800s)`.
Практический смысл для владельца: если взвести Телеграм при таком треке, не уйдёт
НИ ОДНО сообщение (fail-CLOSED), а `bts_monitor_status.json` скажет почему.
Числа порога: окно 30 дней = окно evidenced-трека для go-live; минимум 7 дней;
предел свежести 48 ч = два дневных цикла. Величина самого порога источника не имеет
кроме нашего трека — литерал не подставляется нигде.

**Что нужно от владельца, чтобы карточка закрылась:** добавить
`EnvironmentVariables → SPA_BTS_ALERTS_ARMED=1` в
`scripts/com.spa.bts-monitor.plist` и перезагрузить метку.
Карточку не закрываю и в `owner-done` не двигаю (инвариант #14).

---

## Независимая сверка 2026-08-18 (третья пара глаз, прогон свой)

- шаги 1–2: `pytest spa_core/tests/test_bts_monitor_honesty.py -q` → **39 passed**;
  `bts_baseline.py` на месте, импорт в `bts_monitor.py:55` — подтверждено чтением кода;
- шаг 3 (взвод тревог): `grep -rn "SPA_BTS_ALERTS_ARMED" --include=*.plist .` → **пусто**,
  то есть `SPA_BTS_ALERTS_ARMED=1` в плистах нет по-прежнему.

**Остаток числом: 1 шаг из 3**, и он не агентский — правка `scripts/com.spa.bts-monitor.plist`
+ `launchctl bootout/bootstrap` на Маке (правило доставки п.6, инвариант #12). Карточка
остаётся открытой; в `owner-done` не двигается (инвариант #14).
