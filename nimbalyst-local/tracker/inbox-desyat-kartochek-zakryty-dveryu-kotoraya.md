---
trackerStatus:
  type: inbox
title: Десять карточек закрыты дверью, которая их пропустить не должна была — судьба десяти НЕ разобрана (ADR-1049)
status: new
source: nimbalyst
created: 2026-11-18
twin_key: "sha256:cafbac5444a20b3d5fb1e83225f25d231516ce32f2bb1996aabfe581095caea6"
---

## Что случилось и почему это важно

Храповик приёмки (`spa_core/tests/test_inbox_acceptance_ratchet.py::test_no_new_card_is_in_work_without_a_criterion`)
КРАСЕН на `origin/main` и измерен дифференциально на чистом дереве (цикл #1186, `f5cab0fa4`:
1 failed / 5 passed). Состав — **десять** inbox-карточек в статусе `done` без машинного
критерия приёмки, ни одной нет в базе освобождений (`scripts/inbox_acceptance_baseline.json`,
458 имён):

- `inbox-dogonyayuschii-dnevnoi-tsikl-storozh-pro`
- `inbox-hrapovik-zamorozhennyh-dat-krasen-na-chi`
- `inbox-imena-upavshih-testov-na-main-zhivut-tol`
- `inbox-kupit-zont-v-pyatnitsu-5`
- `inbox-kupit-zont-v-pyatnitsu-6`
- `inbox-neprimenennyi-otvet-vladeltsa-1-adresat-2`
- `inbox-pribory-brosayut-odnorazovyi-stend-87-gb`
- `inbox-shest-kartochek-zaperty-pustym-claimed-a`
- `inbox-sto-tridtsat-devyat-broshennyh-derevev-t`
- `inbox-strazh-provenansa-chitaet-pravku-stroki`

Цикл #1187 закрыл ДВЕРЬ (ADR-1049: непрочитанная база — отказ, а не пропуск), но **судьбу
этих десяти не разобрал**, и это сказано вслух, а не выдано за починку.

## Что уже измерено — не перемерять

1. **Гипотеза заказа G1036 п. 11 (`_base is None` fail-OPEN) как ПРИЧИНА этих десяти НЕ
   ПОДТВЕРЖДЕНА и не опровергнута** — `unmeasured` с названной причиной: предупреждение
   fail-OPEN уходило в `stderr` сессии (не хранится), а журнал переходов
   `data/tracker_status_audit.jsonl` пишет ФАКТ записи и НЕ пишет вердикт гейта.
2. **Опровергнуто замером:** ни одно из десяти имён никогда не жило в базе (полная история
   файла в зеркале: 4 коммита — 13.09 рождение, 14.09, 16.09, 08.11); дверь ОТКАЗЫВАЕТ
   сегодня в обоих деревьях (прод и worktree), база читается, 458 имён; гейт существовал
   всё время закрытий (пришёл 13.09, `0b9b403f2`), синхронизация `spa_core/` в прод в срок.
3. **Производитель записей:** все десять — из ПРОД-дерева, `argv: "-c"`,
   `cwd: /Users/yuriikulieshov/Documents/SPA_Claude`, десять РАЗНЫХ pid за 24 дня
   (03.10 … 27.10). Это сессии, звавшие библиотеку одноразовым `python3 -c`, а не CLI
   очереди (в следе нет сегмента `cycle-NNNN`) и не интейк.

## Что надо сделать

Разобрать СУДЬБУ десяти, не трогая храповик. Три дороги, и у каждой своя цена — выбрать по
карточке, а не одной мерой на всех:

- **вернуть в приём** (`done -> new`, таблица переходов это разрешает): честно для тех, чья
  работа не доказана ничем; цена — очередь `new` растёт;
- **заработанное освобождение** `carried_to=<существующий путь>`: для карточек-НОСИТЕЛЕЙ,
  чей предмет уехал в другую карточку или заметку (кандидаты — `inbox-kupit-zont-v-pyatnitsu-5/6`
  как тестовые заметки владельца и `inbox-neprimenennyi-otvet-vladeltsa-1-adresat-2`, рождённая ботом);
- **третья названная ретракция** по образцу ADR-807 (`intake_retraction_verdict`), если
  измерится, что класс «карточка, которая работой НИКОГДА не была» населён и у него есть
  машинный признак.

**ЗАПРЕЩЕНО:** дописывать имена в `scripts/inbox_acceptance_baseline.json` (инв. #16, база
только уменьшается) и объявлять пробу задним числом у закрытой карточки
(`.claude/rules/acceptance.md` п. 2 — самосертификация).

## Как понять, что готово

`SPA_ENV=ci python3 -m pytest spa_core/tests/test_inbox_acceptance_ratchet.py -q` зелёный на
чистом дереве БЕЗ правок базы и без новых `acceptance_probe:` у этих десяти карточек, а у
каждой из десяти в теле записана причина выбранной дороги.
