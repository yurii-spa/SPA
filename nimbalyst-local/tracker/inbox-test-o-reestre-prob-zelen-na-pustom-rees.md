---
trackerStatus:
  type: inbox
title: Тест о реестре проб зелен на ПУСТОМ реестре — предмет взят из того, что мог опустеть
status: new
source: nimbalyst
created: 2026-10-03
---

## Что измерено

Цикл #763 ([ADR-553](../../docs/decisions/ADR-553-the-fourth-door-a-scene-premise-from-the-live-registry.md),
заказ G95 п. 2) назвал **четвёртую дверь** необъявленного окружения в тестах — после
календаря, pid и git-окружения. Это предпосылка сцены, взятая из ЖИВОГО реестра проб.
Вред у неё ТИХИЙ: на пустом реестре утверждение «у каждой зарегистрированной пробы есть
X» истинно, тест обходит ноль проб и печатает `passed`.

Дифференциальный замер (`python3 -m spa_core.monitoring.live_registry_scene_census`):
из **1218** тестов до реестра доходят **307**, из них **5** зелены на ПУСТОМ реестре,
причём перечисляющее чтение сделано КАДРОМ ТЕСТА, а не самим реестром.

## Предмет ЭТОЙ карточки — ОДНА находка, самая чистая

`spa_core/tests/test_card_acceptance.py::TestRegisteredProbesAreReal::test_every_registered_probe_returns_a_known_verdict`

```python
for name in list(ca.PROBES):
    ...
    verdict, detail = ca.run_probe(spec)
    self.assertIn(verdict, (ca.SATISFIED, ca.NOT_SATISFIED, ca.UNMEASURED))
```

Докстрока класса обещает ровно то, чего тест не может: «проба, чей производитель
переименовали, обязана падать в „не измерено“, **а не молча исчезать из реестра**».
Исчезновение из реестра он не поймает ПО ПОСТРОЕНИЮ — предмет перечисления взят из того
же реестра, который и мог бы опустеть.

## Что надо сделать

Решить, **что именно этот тест обязан закреплять, если не состав реестра**, и сделать
предпосылку ВХОДОМ. Образец инъекции рядом: `probes_by_s49_criterion` обходит реестр,
но ему реестр можно передать аргументом вместо чтения модульного глобала.

Пакетом с остальными четырьмя находками — НЕЛЬЗЯ (заказ G123 п. 1): у каждой свой ответ
на вопрос «что закрепляем», и пять решений под одной правкой есть ровно тот дефект,
против которого написан G94 п. 1.

## Как понять, что готово

`live_registry_scene_census` перестаёт относить этот nodeid к `vacuous_over_members`
(вердикт становится `breaks_on_substitution` или `claim_independent_of_members` — но НЕ
`not_reached`: перестать читать реестр значило бы снять проверку, а не починить её),
и при этом тест по-прежнему краснеет, если какая-то проба возвращает неизвестный вердикт.

## Остальные четыре находки — свои карточки, не эта

`test_acceptance_probe_writer.py::…::test_validator_accepts_exactly_the_registered_names` ·
`…::test_unregistered_name_is_refused_and_names_the_alternatives` ·
`test_cio_acceptance_rollup.py::test_a_probe_losing_its_registration_loses_its_declaration` ·
`…::test_declaration_values_that_are_not_names_are_ignored`
