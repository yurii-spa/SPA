---
trackerStatus:
  type: inbox
title: На карточку-поручение владелец не может ответить НИЧЕМ, кроме слов — пять висят с 08.08
status: done
created: 2026-08-10
---

## Что измерено (цикл #197, 2026-08-10)

Остаток пункта 2 карточки `inbox-vosem-kartochek-vse-esche-zhdut-vladelts`. Замер по журналу
отправок `data/telegram_owner_decisions.json`:

| карточка | отправлена | ответ |
|---|---|---|
| `owner-decision-reshenie-po-alertu-spa-7-day-checkpoint` | 08.08 18:15Z | нет |
| `owner-decision-kritichnaya-nahodka-petli-com-spa-telegr` | 08.08 19:02Z | нет |
| `owner-decision-kritichnaya-nahodka-petli-com-spa-digest` | 08.08 19:02Z | нет |
| `owner-decision-kritichnaya-nahodka-petli-com-spa-tier1` | 08.08 19:02Z | нет |
| `owner-decision-kritichnaya-nahodka-petli-com-spa-weekly` | 08.08 19:02Z | нет |

У всех пяти секция «Что от тебя нужно» вариантов не предлагает — это поручения («сделай то-то»)
или сообщения о находке. Разбор ведёт себя правильно: кнопок нет, текст честно говорит
«вариантов в карточке не нашёл». Но ответить на такую карточку владелец может ТОЛЬКО словами в
чат, и по факту за двое суток не ответил ни на одну. Молчание тут неотличимо от «не увидел».

## Что предлагается (не сделано, обсуждаемо)

Кнопка **«✅ Принято»** (и, возможно, «⏳ Позже») для карточек БЕЗ вариантов: нажатие — это не
выбор варианта, а подтверждение, что владелец прочитал и согласен. Записывается тем же
owner-путём, что и выбор варианта, и так же закрывает карточку.

Почему не сделано этим циклом: `record_choice` сегодня знает только варианты, ВЫЧИТАННЫЕ из
карточки (ADR-075: не предлагать того, чего в карточке нет). «Принято» — вариант, которого в
карточке нет; прежде чем его вводить, надо решить, чем он отличается от `owner-done`, который
агенту ставить запрещено (инв. #14). Это отдельная задача с отдельной приёмкой, а не довесок.

## Как понять, что готово

Ни одна отправленная владельцу карточка не остаётся без ЛЮБОГО способа ответить с телефона —
проверка тем же замером по журналу отправок.

## Попутно закрыто замером (пункт 3 той же карточки)

Ложного срабатывания `allows_multiple` у `owner-decision-posle-strahovki-dengi-ostayutsya-sirotam`
**нет**: карточка сама пишет «Варианты 1 и 3 не исключают друг друга» — и одновременно «Выбери
один вариант». Противоречие в ТЕКСТЕ карточки, а не в коде; код выбирает более осторожное
прочтение и честно предлагает ответить номерами в чат. Трогать разбор не надо.

---

## 🔎 СВЕРКА 2026-08-17 (код + прогон на ТЕХ ЖЕ пяти карточках) → `done`

Критерий — «ни одна отправленная владельцу карточка не остаётся без ЛЮБОГО способа ответить
с телефона» — проверен не пересказом, а прогоном разбора по ЖИВЫМ телам тех пяти карточек,
которые висели с 08.08.

**Код.** `spa_core/telegram/owner_decisions.py`: `prepare()` выставляет `ack=True` и собирает
клавиатуру `ACK_CHOICE` / `LATER_CHOICE` / `MORE_CHOICE` для карточек, которые выбора не предлагают
(`offers_no_choice`); «Принято» идёт узким owner-путём (`owner_answer.record_owner_answer`,
сверка личности ВНУТРИ писателя), «Позже» карточку не меняет.

**Прогон 1 — те самые пять карточек** (боевой разбор, живой маячок бота, `now = сейчас`):

```
owner-decision-reshenie-po-alertu-spa-7-day-checkpoint : options=[] ack=True keyboard=['ack','later','more']
owner-decision-kritichnaya-nahodka-petli-com-spa-telegr: options=[] ack=True keyboard=['ack','later','more']
owner-decision-kritichnaya-nahodka-petli-com-spa-digest: options=[] ack=True keyboard=['ack','later','more']
owner-decision-kritichnaya-nahodka-petli-com-spa-tier1 : options=[] ack=True keyboard=['ack','later','more']
owner-decision-kritichnaya-nahodka-petli-com-spa-weekly: options=[] ack=True keyboard=['ack','later','more']
```

Было — клавиатуры нет вовсе (ответ только словами в чат, за двое суток ноль ответов).

**Прогон 2 — сторож:** `python3 -m pytest spa_core/tests/test_owner_decision_ack_button.py -q`
→ `16 passed in 0.30s`. Границы, которые он держит и которые карточка просила НЕ размывать:

* инв. #14 не ослаблен — `test_a_stranger_cannot_accept_the_owners_card` (чужое «Принято» не
  меняет карточку ни на байт), `test_accepting_twice_is_not_two_different_answers`;
* ADR-075 не ослаблен — подтверждение НЕ появляется там, где карточка предлагает выбор
  (`test_the_confirmation_is_never_offered_instead_of_real_options`), где вопросов два
  (`CARD_TWO_QUESTIONS`), где выбор многовариантный, и где варианты написаны, но НАМИ не
  разобраны (`test_a_card_with_unreadable_options_is_not_closed_by_a_confirmation`);
* «Позже» не притворяется решением — `test_later_leaves_the_question_open_and_the_card_untouched`;
* служебные токены не могут столкнуться с номером варианта — `test_reserved_tokens_cannot_collide…`.

Пункт 3 той же карточки (`allows_multiple`) закрыт замером ещё 10.08 — код не трогали, и это
подтверждено выше по телу. Кода не менял.
