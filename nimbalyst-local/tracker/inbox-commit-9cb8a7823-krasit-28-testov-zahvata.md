---
trackerStatus:
  type: inbox
title: "main красный с 9cb8a7823: 28 тестов захвата карточек падают на UnmeasurableClaim (нет SPA_SESSION_PID)"
status: done
created: 2026-08-26
priority: high
tags: [ci, card-claim, regression]
status_trail:
  - "2026-08-26T21:05:34.623848+00:00 new -> done · queue.set_status"
---

## Что случилось и почему это важно

Коммит `9cb8a7823` (2026-08-26 21:12:39+0200, «guard(шаг 0b): захват под ярлыком без
объявленного долгоживущего процесса НЕ состоится (UnmeasurableClaim, код 2)») ввёл fail-CLOSED
отказ в `scripts/check_card_claim.py`: захват под «голым» ярлыком (`pid1`, `cycle-358` и т. п.)
без `SPA_SESSION_PID`/`SPA_SESSION_ID` в окружении теперь ОТКАЗЫВАЕТСЯ (код 2), вместо того чтобы
просто записаться.

Замер на чистом `origin/main` (worktree `d13788571`, тот же sha, что видели два открытых PR):

```
python3 -m pytest spa_core/tests/test_card_claim_guard.py spa_core/tests/test_card_claim_takeover.py \
  spa_core/tests/test_session_state_shared_root.py -q
28 failed, 169 passed
```

Все 28 падений — тесты класса `TestClaimAndRelease` / соответствующие в
`test_card_claim_takeover.py` и `test_session_state_shared_root.py`, которые сознательно зовут
`claim`/CLI без объявленного `SPA_SESSION_PID` (проверяют старое поведение «голый ярлык
принимается») — их фикстуры не обновлены под новый отказ, введённый тем же коммитом.

**Это красит `main`, а не отдельную ветку** — любой открытый PR получает красный `test`/
`test (3.12)` независимо от своего диффа (проверено на PR #42 и #45 этой сессии, ни один из
них не трогает `scripts/check_card_claim.py` или эти тест-файлы).

## Что нужно сделать

Автору `9cb8a7823` (похоже, другая параллельная сессия, коммит 19 минут назад) — обновить
`TestClaimAndRelease` и параллельные классы в `test_card_claim_takeover.py`/
`test_session_state_shared_root.py`: либо явно declare `SPA_SESSION_PID`/`SPA_SESSION_ID`
(monkeypatch, как уже сделано в соседнем классе «режим автономного цикла»), либо, если тест
специально проверяет СТАРОЕ поведение — решить, актуален ли он теперь вообще (новый отказ,
возможно, делает его сценарий невозможным по построению).

Не беру сама: коммит не мой, чужой класс тестов, дефект в чужой недавней работе — правка
задним числом без понимания полного намерения автора рискует потерять то, что коммит
специально закрывал (инв. #16 — не трогать чужие тесты вслепую).

## Как понять, что готово

`spa_core/tests/test_card_claim_guard.py spa_core/tests/test_card_claim_takeover.py
spa_core/tests/test_session_state_shared_root.py` — 0 failed на `origin/main`.

## Что будет после

Полный CI (`test`/`test (3.12)`/`test (3.11)`) снова зелёный на всех открытых PR без ручных
комментариев «не моё».


---

## ✅ Закрыто агентом 2026-08-26 (ADR-144)

Прошлая сессия чинить отказалась справедливо — «чужие тесты вслепую не трогаю» (инв. #16). Но
вслепую и не пришлось: карточка сама назвала лекарство, а в `test_card_claim_guard.py` уже жил
канонический образец — `TestGuardUnderADeclaredDurableProcess` объявляет `SPA_SESSION_PID` через
`monkeypatch` с ЯВНОЙ проверкой предусловия (красной, а не skip).

**Что сделано.** Та же фикстура добавлена туда, где тесты проверяют механику захвата, а не
поведение «голого» ярлыка: `test_card_claim_takeover.py` и `test_session_state_shared_root.py`
(модульная, autouse) и — точечно — классы `TestClaimAndRelease` и `TestCli` в
`test_card_claim_guard.py`. Ни одно утверждение не изменено.

**Гейт НЕ ослаблен, и это доказано мутацией, а не заявлено.** Фикстура намеренно НЕ повешена на
весь `test_card_claim_guard.py`: там живёт `TestClaimSaysWhenItHasNoIdentity` — положительный
контроль самого гейта. Замер: обезвредил `raise UnmeasurableClaim` →

| набор | под мутацией |
|---|---|
| `TestClaimSaysWhenItHasNoIdentity` (контроль гейта) | **3 failed** — краснеет, не замаскирован |
| `TestClaimAndRelease` + `TestCli` (починенные) | 18 passed — они и правда про другое |

Гейт восстановлен побайтово (`git diff` по `scripts/check_card_claim.py` пуст).

**Критерий приёмки карточки** («три файла — 0 failed») **ПРОВЕРЕН**: было 28 failed / 169 passed,
стало **197 passed, 0 failed**.
