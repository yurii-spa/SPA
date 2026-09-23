---
trackerStatus:
  type: owner-decision
title: "Критичная находка петли: com.spa.director_server загружен, в манифесте ОТСУТСТВУЕТ (класс swarm"
status: done
source: nimbalyst
created: 2026-09-21
finding_key: "B1:unknown:com.spa.director_server"
status_trail:
  - "2026-09-23T06:14:44.335923+00:00 needs-owner -> done · queue.set_status"
---

## Что случилось и почему это важно
Сторож петли (architecture_conformance) нашёл КРИТИЧНОЕ расхождение с архитектурой:
com.spa.director_server загружен, в манифесте ОТСУТСТВУЕТ (класс swarm_dwell 2026-08-05)

## Что от тебя нужно
Посмотреть находку и решить: чиним / принимаем осознанно (тогда фиксируем решение в манифесте или ADR). Рекомендация агента — чинить: критичные находки этого класса уже стоили нам молчаливых отказов.

## Как понять, что готово
Находка исчезает из data/architecture_conformance.json при следующем прогоне.

## Что будет после
Мост сам закроет эту карточку, когда находка исчезнет; сторож продолжит следить, чтобы она не вернулась.

_finding_key: `B1:unknown:com.spa.director_server` · источник: architecture_conformance · ADR-066_
