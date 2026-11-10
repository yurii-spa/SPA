---
trackerStatus:
  type: inbox
title: "Исполнить ответ владельца 27.10: срок годности решения 10 мин и допуск свежести 60/15 с — в колонку TriggerParams и к её читателю"
status: new
source: nimbalyst
created: 2026-11-10
priority: high
acceptance_probe: decision_expiry_answer_executed
twin_key: "sha256:d492e6c015d0ac099b006adaff87ce3eeedf584a1fd87e7055533a3308626320"
intake_kind: task
---

## Что случилось и почему это важно

27.10 владелец ответил на вопрос «Перепроверка перед сделкой: назови два числа» (карточка
`owner-decision-pereproverka-pered-sdelkoi-nazovi-dva-ch`, ADR-836, запись в реестре ADR-839):
**вариант А — допуск свежести входа 60 с на бумаге / 15 с вживую; срок годности решения 10 мин.**
Это и есть ответ на §27 и §28 ТЗ «Portfolio CIO» сразу. Замер цикла #1089 (ADR-971, прибор
`spa_core/analytics/decision_expiry_census.py`): ответ **не исполнен 13 дней** — в колонке
владельца `TriggerParams` (v1.1, 15 ручек) ручки срока годности нет, и читатель колонки
(ADR-487 `load_owner_tolerance`) даже при появлении ручки взял бы её ИМЯ, а не ЗНАЧЕНИЕ
(`tolerance_s` у него литерал `None` — измерено сценой). Карточка
`inbox-vosemnadtsat-otvetov-vladeltsa-27-10-isp` числит этот ответ «НЕ исполнен» с 28.10.

## Что нужно сделать

Это задача агента — решение владелец уже принял, переспрашивать нельзя (ADR-285).

1. Добавить в `TriggerParams` (`spa_core/allocator/rebalance_economics.py`) две ручки ответа
   владельца: допуск свежести входа (60 с в колонке `paper`, 15 с в колонке `pilot`) и срок
   годности решения (600 с в обеих). Имена — с подсказками `_TOLERANCE_HINTS` ADR-487
   (`ttl`/`fresh`), иначе читатель колонки ручку не увидит. Новая версия контракта и
   `version_date` = дата ответа владельца (ADR-060 §3 — смена порогов только новым ADR).
2. Научить читателя колонки (`pre_trade_recheck_census.load_owner_tolerance`) брать ЗНАЧЕНИЕ
   ручки в `tolerance_s` (сегодня — литерал `None`), чтобы прибор ADR-487 начал судить
   старость входа по числу владельца. Это monitoring, не money-path.
3. Это money-path (`spa_core/allocator/`): по `.claude/rules/risk-engine.md` — прогон
   `pre_cutover_gate`, таблица «правило до → после → ответ владельца → проверка» (ADR-839),
   пороги RiskPolicy не трогаются. Тесты в обе стороны: колонка `paper` 60/600, `pilot` 15/600,
   читатель с ручкой — число, без ручки — `None`.
4. Ворота принуждения («нельзя выполнять без нового расчёта» у двери исполнения) в ЭТУ
   карточку НЕ входят: на бумаге окно между решением и исполнением ≤ 2 с против срока 600 с
   (ADR-971, ось E) — исполнять нечего до реального исполнения (инв. #6).

## Как понять, что готово

Проба `decision_expiry_answer_executed` (реестр `card_acceptance.PROBES`) отвечает `satisfied`:
ручка срока годности есть в колонке И читатель берёт её значение. Сегодня — `not_satisfied`.

## Что будет после

Прибор §28 (`decision_expiry_census`) перестаёт печатать `owner_answer_unexecuted`, прибор
ADR-487 начинает судить `freshness_judgeable=True`; строка этого ответа в карточке
`inbox-vosemnadtsat-otvetov-vladeltsa-27-10-isp` закрывается ссылкой на ADR исполнения.
