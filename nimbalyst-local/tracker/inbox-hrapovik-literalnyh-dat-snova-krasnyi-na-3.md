---
trackerStatus:
  type: inbox
title: Храповик литеральных дат снова КРАСНЫЙ на main — фикстура XSS-правки 10.11 вошла в закрытый класс
status: new
source: nimbalyst
created: 2026-11-14
domain: тесты / CI (НЕ money-path)
priority: high
twin_key: "sha256:8dd672243bf512319ba5eb596a518536ebdce2f4a90dc4de0f1dfa1dc7aac141"
---

## Что нашли (замер 2026-11-14, цикл #1130, дифференциально)

`spa_core/tests/test_frozen_date_ratchet.py::test_no_new_file_joins_the_frozen_date_class`
падает **на чистом `origin/main` 76d7b7425**:

```
E   assert not ['test_admin_pages_escape_untrusted.py']
```

Файл приехал **2026-11-10** коммитом `6b890da80` («landing/admin: analytics, index, agents render
API data as text») — то есть фикстура XSS-правки закрепила литеральную дату рядом с понятием
свежести и вошла в ЗАКРЫТЫЙ класс храповика.

**Замер дифференциальный, а не «красен сегодня»:** тест красен и в одноразовом дереве на самом
`origin/main` (`/private/tmp/spa_base_1130`, `1 failed, 22 passed`), и в рабочем дереве цикла
(`1 failed, 148 passed` в пакете храповиков) — то есть краснота принадлежит `main`, а не правке
цикла #1130.

## Почему это важно

Храповик из `.claude/rules/deployment.md` устроен так, что база может только УМЕНЬШАТЬСЯ: дописать
файл в `spa_core/tests/frozen_date_baseline.json`, чтобы погасить падение, **ЗАПРЕЩЕНО** (инв. #16) —
чинить надо фикстуру. Пока этого не сделано, храповик красен на `main` и его краснота тонет в
общем красном наборе CI (34…42 дефекта, ADR-888/1004), то есть перестаёт быть сигналом.

Это ВТОРОЙ экземпляр того же класса: первый закрыт карточкой
`agent-frozen-date-ratchet-red-on-main` (цикл #118, два файла волны A1).

## Как починить (порядок предпочтения из правила)

1. **Время — вход, а не окружение:** функция, судящая о свежести, принимает `now`; тест передаёт
   фиксированный `now` И фиксированные отметки.
2. Относительные отметки — `spa_core/tests/_freshness.py::ts(hours_ago=N)`.
3. Литеральная дата ТОЛЬКО если сама дата является предметом — тогда пометка
   `# FROZEN-DATE-OK: <причина>`; пометка без причины храповиком отвергается, а причина
   `injected-clock` СВЕРЯЕТСЯ С КОДОМ (`test_injected_clock_claim.py`, ADR-477/897).

## Как понять, что готово

`SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_frozen_date_ratchet.py -q` —
зелёный на чистом `origin/main`, и `frozen_date_baseline.json` НЕ вырос ни на одну строку.

## Чего карточка НЕ утверждает

Что это единственный новый член класса: замер снят на вершине 76d7b7425 и называет РОВНО то, что
назвал храповик. Население класса за период между #118 и #1130 не мерилось.

## Соседи в очереди (сверено замером, а не по названию)

- `inbox-hrapovik-literalnyh-dat-snova-krasnyi-na.md` — `done` (`test_owner_order_starvation.py`).
- `inbox-hrapovik-literalnyh-dat-snova-krasnyi-na-2.md` — **`new`, но его находка ИСЧЕЗЛА**: оба
  названных там файла сегодня несут пометку с причиной (`test_cio_failure_modes.py` — 2 пометки,
  `test_decision_reproducibility.py` — 1), и храповик их больше не называет. То есть карточка-2
  закрыта ПО ИСХОДУ, а статус за этим не поехал; дубль с ней эта карточка не образует — предмет
  РАЗНЫЙ (`test_admin_pages_escape_untrusted.py`, приехал 10.11).
- `agent-frozen-date-ratchet-red-on-main.md` — `done`, первый экземпляр класса (цикл #118).

Статус карточки-2 этот цикл НЕ двигал: он брал в работу другой предмет (заказ G997 п. 1а), а
закрытие чужой карточки без объявленной ДО работы пробы — ровно то, против чего написано
`.claude/rules/acceptance.md`.
