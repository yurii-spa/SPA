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

**Что нужно от владельца, чтобы карточка закрылась:** добавить
`EnvironmentVariables → SPA_BTS_ALERTS_ARMED=1` в
`scripts/com.spa.bts-monitor.plist` и перезагрузить метку.
Карточку не закрываю и в `owner-done` не двигаю (инвариант #14).
