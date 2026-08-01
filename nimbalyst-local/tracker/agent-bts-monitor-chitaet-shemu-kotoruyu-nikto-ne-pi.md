---
trackerStatus:
  type: agent-task
title: Сторож базисной торговли (каждые 15 мин) отчитывается «ok, 0 возможностей» о фиде, который он НИ РАЗУ не прочитал — читает ключи, которых продюсер не пишет
status: done
priority: high
source: session-2026-08-02-cycle78
created: 2026-08-02
claimed_by: cycle78
claimed_at: 2026-08-01T23:08:31Z
---

## Как найдено

Автономный цикл #78, очередь пуста → мандат. Сканировал живые LaunchAgent'ы на покрытие
тестами их точки входа; `com.spa.bts-monitor` (каждые 900с) и `com.spa.bts-feed` (каждые 900с)
попали в список «0 тестов на runner». В живом логе агента бросилась в глаза пара строк подряд.

## Что измерено (дословно, живые логи и файлы, ДО правок)

Фид (`/tmp/spa_bts-feed.log`, 2026-08-02T01:01:57 local):

```
spa.feeds.bts INFO Fetched funding rates for 4 assets: ETH, BTC, SOL, ARB
spa.feeds.bts.runner INFO BTS feed: stale=False assets=4
```

Сторож (`/tmp/spa_bts-monitor.log`, тот же цикл агента, 00:54:42):

```
spa.monitoring.bts_monitor: No rates in funding data
spa.monitoring.bts_monitor: BTS monitor run complete: {'opportunities': 0, 'new_excellent': 0, 'errors': [], 'status': 'ok'}
spa.analytics.bts_exit_monitor: BTS exit monitor: 0 signals
spa.bts_monitor_runner: BTS exit monitor: {'signal_count': 0, 'clear': True, 'signals': [], 'status': 'ok'}
```

Живой файл продюсера `data/perp_funding_rates.json`:

```
top keys: ['timestamp', 'fetched_at', 'stale', 'assets']
stale: False   fetched_at: 1785625317.5   timestamp: 2026-08-01T23:01:57Z
assets: ['ETH', 'BTC', 'SOL', 'ARB']
assets['ETH'] = {'funding_rate_1h': …, 'funding_rate_annual': -0.02175809, 'mark_price': 1847.96, …}
```

Что читает сторож (`spa_core/monitoring/bts_monitor.py`):

- `scan()` → `funding_data.get("rates", {})` — ключа **`rates` в файле нет и не было никогда**;
- `_load_funding_data()` → `data.get("generated_at", "")` — ключа **`generated_at` тоже нет**
  (продюсер пишет `fetched_at` эпохой и `timestamp` в ISO), поэтому проверка возраста
  (`STALE_AFTER_S = 1800`) **не выполняется ни разу**: `gen_at` пустой ⇒ весь блок пропущен.

То же самое дословно в `spa_core/analytics/bts_exit_monitor.py` (`rates` в
`evaluate_conditions`, `generated_at` в `_is_funding_stale`) — это близнец, и чинить его
надо тем же заходом (иначе повторится механизм цикла #37/#47: починили одну копию, оставили вторую).

История: `git log -S'"rates"' -- spa_core/feeds/perp_funding_feed.py` — **ноль коммитов**.
Продюсер не писал `rates` никогда; оба файла (фид и сторож) появились одним
коммитом-импортом `b9cf63fb5`. Истории «раньше работало» не существует.

Живые артефакты сторожа:

```
data/basis_trade_opportunities.json → {"stale_feed": true, "opportunities": [],
                                       "summary": {"excellent_count": 0, "enter_count": 0, "total_analyzed": 0}}
data/bts_monitor_status.json        → {"opportunities_found": 0, "new_excellent": 0,
                                       "status": "ok", "errors": []}
```

`stale_feed: true` при **свежем** фиде (`stale: false`, возраст ~7 минут) — потому что
`run()` считает `stale = len(opps) == 0`, т.е. выдаёт «фид протух» за «возможностей нет».

## Почему это класс #29/#31/#35–#38/#40/#75/#76, а не мелочь

Живой агент 96 раз в сутки публикует `status: "ok"`, `errors: []`, `clear: True` —
утверждения о проверке, которой не было. Ни одна возможность базисной торговли не может быть
найдена **по построению**, и ни один exit-сигнал не может сработать: оба монитора читают
пустой словарь. При этом наверху всё выглядит здоровым: `uptime_monitor` видит свежий
`basis_trade_opportunities.json` каждые 15 минут и считает агента живым — он и правда жив,
просто ничего не измеряет.

**Почему это не поймали тесты:** `tests/test_bts_monitor.py` (30 тестов) и
`tests/test_bts_exit_monitor.py` (25 тестов) строят фикстуру `_make_funding_data()` с ключами
`generated_at` + `rates`, т.е. **пиннят формат, которого ни один продюсер в системе не пишет**.
55 зелёных тестов над контрактом, не существующим в проде.

## Радиус (проверено grep'ом, до правок)

- `data/basis_trade_opportunities.json` — читает только `spa_core/monitoring/uptime_monitor.py`
  (heartbeat-свежесть, 3600с). Больше никто.
- `data/bts_monitor_status.json`, `data/bts_exit_signals.json` — не читает **никто**.
- `data/bts_kill_switch.json`, `data/bts_active_trades.json` — не пишет **никто** (файлов нет).
  `_load_active_trades()` не вызывается ни разу — мёртвый код.
- Капитал, RiskPolicy, глобальный kill-switch, сайт — **не затронуты**: оба модуля advisory
  по докстрингу и по факту (пишут только свои JSON + Telegram на NEW EXCELLENT).

## Acceptance criteria

1. Сторож читает **настоящую схему продюсера** (`assets`, `fetched_at`/`timestamp`), при этом
   легаси-схема (`rates`, `generated_at`) продолжает читаться ⇒ **ни один существующий тест
   не меняется** (инвариант #16).
2. «Не смог измерить» больше не выдаётся за «измерил, пусто»: `status: "ok"` только когда скан
   реально выполнен; иначе `unchecked` со **словесной причиной вербатим**.
3. `stale_feed` описывает ФИД, а не число возможностей.
4. Падение exit-монитора больше не публикует `clear: True` («выходить не надо») — это отказ.
5. Общая логика схемы — в ОДНОМ месте, оба модуля берут её оттуда (нет близнеца).
6. Тесты: герметичные, красные на коде origin; прогон `tests/` + `spa_core/tests/` срезами CI,
   `--collect-only` дельта, mypy, `lint_llm_forbidden`; живой read-only смоук на КОПИИ данных.
7. Порогов (`STALE_AFTER_S`, `FUNDING_REVERSAL_THRESHOLD`, `SPREAD_FLOOR_BPS`,
   `ALERT_COOLDOWN_S`), severity, транспорта алертов и глобального kill-switch — **не касаться**.

## Результат (цикл #78, 2026-08-02) — ЗАКРЫТА

### Что сделано

- **Новый общий читатель `spa_core/feeds/funding_schema.py`** — ОДНО место, знающее формат
  продюсера: `read_rates` (канонический `assets`, легаси `rates`, «ключ есть, но пуст» = ИЗМЕРЕНО,
  «ни одного ключа / не словарь» = НЕ ИЗМЕРЕНО с перечислением того, что в файле БЫЛО) и
  `feed_age_seconds` (`fetched_at` эпохой → `timestamp` → `generated_at`). Положен рядом с
  продюсером намеренно: близнецов больше нет.
- **`bts_monitor.py`:** `scan_with_reasons()` (старый `scan()` — тонкая обёртка, сигнатура та же);
  `status: "ok"` ТОЛЬКО когда скан реально выполнен, иначе `"unchecked"` + `unchecked[]` вербатим;
  `stale_feed` берётся из ФИДА, а не из `len(opps) == 0`; в артефакт добавлен `summary.measured`.
  Убран мёртвый вызов `_detect_new_excellent([])`, результат которого выбрасывался.
- **`bts_exit_monitor.py`:** `evaluate_with_reasons()`; возраст фида читается из настоящих ключей;
  **упавший прогон больше не публикует `clear: True`** — теперь `clear: null` + `measured: false` +
  причина вербатим; нечитаемый/не-словарь `bts_kill_switch.json` = НЕ ИЗМЕРЕНО (отсутствующий
  файл = «не взведён», как и было — это документированная семантика, её не трогал).
- **Транспорт алертов ОСТАВЛЕН ВЫКЛЮЧЕННЫМ → карточка владельцу.** Живой смоук на КОПИИ прод-данных
  показал: первый же ожившый прогон захотел отправить 3 сообщения «BTS EXCELLENT … Annual PnL $N»
  (EXCELLENT = ≥100bps net против ЗАШИТОЙ 5%-спот-базы, поэтому проходит почти всё; сумма считается
  от зашитых $20 000, которых в стратегии нет). Включение спящего owner-facing канала — не
  автономное решение → `SPA_BTS_ALERTS_ARMED` (по умолчанию выкл), факт подавления пишется
  вербатим в `suppressed_alerts` (никогда молча), карточка
  `owner-decision-storozh-bazisnoi-sdelki-ozhil-i-hochet-s` + notify.

### Поведение ДО/ПОСЛЕ (репро на коде origin его же API, затем на фиксе)

| # | Вход | origin | после |
|---|---|---|---|
| 1 | `scan()` на живой схеме | `[]` | `['SOL','ETH','BTC']` |
| 2 | `run()` на живой схеме | `status ok, 0 opportunities` | `status ok, 3` |
| 3 | `stale_feed` при СВЕЖЕМ фиде | `True` | `False` |
| 4 | `run()` на нечитаемой схеме | `status ok, errors []` | `status unchecked` + 2 причины вербатим |
| 5 | exit при ETH funding −10% | `0 signals, clear True` | `FUNDING_REVERSAL + SPREAD_COMPRESSED` |
| 6 | exit при фиде возрастом 4000с | `[]` | `STALE_DATA` |
| 7 | exit, который УПАЛ | `clear: True` | `clear: null`, `measured: false` |

### Проверка

- **+39 герметичных тестов** (`spa_core/tests/test_bts_monitor_honesty.py`); на чистом `origin/main`
  (с подложенным новым читателем) — **25 красных / 14 зелёных**, из зелёных 10 пиннят сам новый
  читатель, 4 — положительные контроли поведения, которое НЕ должно измениться (легаси-payload
  по-прежнему `ok`, «фид сам сказал stale» = stale, отсутствующий фид = stale, пустая карта
  активов = измеренный ноль).
- **7 мутационных контролей**, каждый краснит РОВНО свой тест. Один (глушение ветки «kill-switch
  файл не словарь») сначала не покраснил ничего — это была настоящая дыра покрытия, добавлен
  отдельный тест на валидный JSON неверной формы (+1 к числу выше).
- **Инвариант #16: ни один существующий тест не изменён** — 62 прежних (`tests/test_bts_monitor.py`
  37 + `tests/test_bts_exit_monitor.py` 25) зелёные как есть, правки строго аддитивные
  (`scan()` / `evaluate_conditions()` / `_is_funding_stale()` / `_kill_switch_active()` сохранили
  сигнатуры как обёртки).
- Срезы CI: `tests/` **12 940 passed / 1 failed** (`test_evidence_seeded` — предсуществующее,
  величина #77 без изменений); `spa_core/tests/` **90 758 passed / 0 failed** (у #77 было 90 719 ⇒
  **ровно +39**, 921с); `scripts/tests/ + gross_of + research/cards` **493 passed** (как #74–#77);
  `--collect-only` 104 760 → **104 799 = ровно +39**, те же 4 предсуществующие ошибки сборки.
- mypy на изменённых файлах: **4 предсуществующие ошибки → 3**, новых нет (тот же класс
  `no-any-return` на обёртках `atomic_load`); ci-lite-набор ключевых модулей — чисто.
  `lint_llm_forbidden` — 163 файла / 0 нарушений.
- **Живой read-only смоук на КОПИИ прод-данных** (транспорт включён, гейт выключен):
  `TELEGRAM MESSAGES THAT WOULD LEAVE: []`, `status ok`, `unchecked []`,
  `suppressed_alerts: ['2 new EXCELLENT (BTC, SOL) NOT sent to Telegram …']`. Живые `data/**` не
  трогались (работа шла на копии в `mktemp -d`).

### НЕ трогал

RiskPolicy · глобальный kill-switch (`spa_core/governance/`) · пороги `STALE_AFTER_S`,
`FUNDING_REVERSAL_THRESHOLD`, `SPREAD_FLOOR_BPS`, `ALERT_COOLDOWN_S`, `EXCELLENT >= 100bps`,
`DEFAULT_SPOT_YIELD`, `DEFAULT_CAPITAL_USD` · severity сигналов · `basis_trade_analyzer` ·
`perp_funding_feed` (продюсер прав, читатель был неправ) · живой трек · launchd/деплой ·
`landing/**` · `data/**` не публиковал.
