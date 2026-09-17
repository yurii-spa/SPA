---
trackerStatus:
  type: inbox
title: "earn-defi: свой расчёт realized price вместо лицензии Coin Metrics (ADR-286 §6, решение 09.09 без задачи)"
status: in-progress
source: nimbalyst
created: 2026-09-16
adr: ADR-286 §6
repo: earn-defi
acceptance_probe: earn_defi_own_realized_price_reconciles
status_trail:
  - "2026-09-17T15:03:39.031027+00:00 new -> in-progress · queue.set_status"
---

## Что случилось и почему это важно

09.09 владелец выбрал (карточка `owner-decision-earn-defi-litsenziya-na-dannye-do-deneg`, ADR-286 §6):
**не покупать коммерческую лицензию Coin Metrics, а считать реализованную цену BTC (realized price /
realized cap) самим из публичного блокчейна.** Решение записано в ADR, но задача из него не родилась:
в трекере SPA карточки нет, в `~/Documents/earn-defi/docs/DECISIONS.md` после D-58 записи о своём
расчёте нет, модуля в `earn_defi/` нет (замер 16.09). Пока расчёта нет, BTC-движок остаётся
исследовательским и не может перейти к деньгам (лицензия CC BY-NC 4.0).

## Что сделать

1. В репо `~/Documents/earn-defi`: модуль расчёта realized cap / realized price из UTXO-набора
   (собственная нода ИЛИ публичный BigQuery-датасет `bigquery-public-data.crypto_bitcoin`) — источник
   назвать в конфиге, метод — в `docs/methodology.md`.
2. Приёмка по ADR-286 §6: **наши числа совпадают с эталонными на истории** — сверка с
   `CapMVRVCur`-производной Coin Metrics Community на ≥ 365 днях, порог расхождения тот же, что у
   shadow-сверки D-23 (3 %); третий исход (нет наблюдения) отдельным значением.
3. Записать D-xx в `docs/DECISIONS.md` earn-defi и обновить `docs/licenses.md` (снять
   «требуется лицензия», назвать свой источник).
4. Пробу приёмки объявить ДО взятия в работу (`orchestrator_queue.py probe`); подходящей в
   `PROBES` сейчас нет — первая работа по карточке: написать её с контролем в обе стороны.

## Как понять, что готово

Своя серия realized price на ≥ 365 дней расходится с эталоном ≤ 3 %, движок читает её вместо
Coin Metrics, D-xx записан.

## Откуда

Вопрос владельца 16.09 («арендовать или писать самим недели, но будет своё») — это и есть выбор
из этой карточки; задача была «в воздухе» с 09.09 (нарушение протокола сессии п. 4).
