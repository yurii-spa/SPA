---
type: inbox
title: "Дневной цикл пишет четыре артефакта мимо своего контракта — среди них аварийный статус"
status: done
created: 2026-08-28
priority: high
source: ADR-158
acceptance_probe: artifact_contract_confirmed:com.spa.daily_cycle
status_trail:
  - "2026-09-01T22:07:10.090737+00:00 new -> done · queue.set_status · cycle-48847"
---

# `com.spa.daily_cycle` пишет мимо контракта

Найдено сверкой `spa_core/monitoring/artifact_contract.py` 28.08, после того как сканер
научился видеть настоящие идиомы записи (`_atomic_write_json`, `os.replace(tmp, dst)`).

## Замер

Объявлено в контракте (взято из курированного `produces` манифеста):
`data/allocation_rationale_history.jsonl`, `data/shadow_trigger_evaluation.json`.

Фактически модуль `spa_core/paper_trading/cycle_runner.py` пишет ещё **четыре**:

| файл | почему это важно |
|---|---|
| `emergency_status.json` | аварийный статус — соседство со стоп-краном |
| `track_persist_status.json` | состояние сохранения ТРЕКА |
| `market_regime.json` | режим рынка (MP-534), в СВОЙ `ddir` |
| `equity_curve_daily.demo_backup.json` | резервная копия кривой капитала |

Ни один не объявлен ни в `PRODUCES`, ни в `produces` манифеста.

## Почему это находка, а не придирка

Артефакт, которого нет в контракте, **никто не обязан обновлять и никто не сторожит на
свежесть**. Для `emergency_status.json` и `track_persist_status.json` это означает: если
запись перестанет происходить, ни один сторож не заметит — их нет в реестре SLO.

Отдельно: `market_regime.json` пишется в собственный каталог цикла, и в репозитории есть
второй файл с тем же именем — `data/investment_os/market_regime.json` от аналитика
`com.spa.io_market_regime`. Одноимённые файлы в разных каталогах — самостоятельная ловушка
при любом сравнении по базовому имени (предел назван в коде сверки и закреплён тестом).

## Что сделать

1. Решить по каждому из четырёх: это ПРОДУКТ (тогда в контракт и, возможно, под SLO) или
   внутреннее состояние (тогда назвать так явно — например, отдельным полем, а не молчанием).
2. `emergency_status.json` разобрать первым: у него money-path-соседство.
3. После разбора `artifact_contract` по `daily_cycle` обязан давать `confirmed`, а не
   `contradiction`.

## Не чинил

Money-path модуль; определить, что здесь продукт, а что внутреннее состояние, обязан автор.
Сверка своё сделала — назвала расхождение поимённо.

---

## Закрыто ЗАМЕРОМ, цикл #450 (2026-09-01)

Критерий карточки (п.3): «после разбора `artifact_contract` по `daily_cycle` обязан
давать `confirmed`, а не `contradiction`». Перемерено на `origin/main` (ae90e7d75):

```
com.spa.daily_cycle  →  verdict: confirmed
declared:  data/allocation_rationale.json · data/allocation_rationale_history.jsonl ·
           data/current_positions.json · data/equity_curve_daily.json ·
           data/shadow_trigger_evaluation.json · data/emergency_status.json ·
           data/market_regime.json · data/track_persist_status.json ·
           data/paper_trading_status.json
internal_writes: data/equity_curve_daily.demo_backup.json
```

Разбор по каждому из четырёх (п.1 карточки) СДЕЛАН и виден в самом объявлении:
`emergency_status.json`, `market_regime.json`, `track_persist_status.json` признаны
ПРОДУКТОМ и объявлены в `PRODUCES`; `equity_curve_daily.demo_backup.json` назван
внутренним состоянием (`INTERNAL_WRITES`) — то есть молчание заменено явным словом,
ровно как требовал п.1. Аварийный статус (п.2) разобран первым и стоит среди продуктов.

По всему флоту `contradiction = 0` (77 агентов с читаемой точкой входа).

Карточка стояла `new` четверо суток после того, как её критерий стал выполнен.
Разрыв закрыт отдельно — ADR-208: у карточки теперь есть
`acceptance_probe: artifact_contract_confirmed:com.spa.daily_cycle`, и шаг 0-офис
перемеряет критерий каждый прогон.
