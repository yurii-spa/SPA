---
trackerStatus:
  type: inbox
title: Гейт кнопок судит по ПОДСТРОКЕ, если умения в маячке окажутся строкой
status: new
created: 2026-10-08
---

## Что случилось и почему это важно

`spa_core/telegram/alert_actions.py::handler_available` читает умения бота так:
`declared = doc.get('capabilities') or []`, а затем `any(c in declared for c in ...)`.
Если в маячке `data/telegram_bot_capabilities.json` поле `capabilities` окажется
СТРОКОЙ, а не списком, то `c in declared` станет проверкой подстроки и ответит ДА —
то есть кнопки владельцу предложат по совпадению букв, а не по объявленному умению.
Это fail-OPEN у гейта, и он тише красного.

Сегодня ветка в проде НЕДОСТИЖИМА: писатель маячка всегда пишет список (замер 08.10 —
`['alert_actions', 'owner_decisions']`). Форма найдена циклом #807 сценой пробы
`owner_control_plane_reachable` (ADR-662): проба читает нестроковый список как пустой,
гейт — как совпадение, и проба честно отвечает `unmeasured` «два ответа расходятся».

## Что нужно сделать

1. В `handler_available` читать умения ТИПОМ: `declared = doc.get('capabilities')`,
   и если это не `list`, вести себя как при отсутствии умения (кнопок не вешать) —
   fail-CLOSED, как и остальные ветки этой функции.
2. Положительный контроль в обе стороны: строка `'alert_actions'` в поле ⇒ кнопок НЕТ;
   список `['alert_actions']` ⇒ кнопки есть. Сцена уже написана и ждёт в
   `spa_core/tests/test_probe_owner_control_plane.py::test_a_capability_field_of_the_wrong_TYPE_makes_the_probe_REFUSE`
   (её утверждение придётся перевернуть — это и есть признак починки).
3. Порог кнопок (`BEACON_MAX_AGE_S`, 6 ч) НЕ трогать: он к находке не относится, и
   равнять его с 300-секундным порогом сторожа запрещено (ADR-400).

## Как понять, что готово

`handler_available` на маячке со строковым `capabilities` отвечает `False`, и проба
`owner_control_plane_reachable` на той же сцене отвечает `not_satisfied` вместо
`unmeasured` (расхождения больше нет).

## Что будет после

Снимется единственный известный fail-OPEN у гейта, который решает, предлагать ли
владельцу кнопки под тревогой.
