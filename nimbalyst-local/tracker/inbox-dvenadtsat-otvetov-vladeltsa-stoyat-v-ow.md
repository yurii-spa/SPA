---
trackerStatus:
  type: inbox
title: "Двенадцать ответов владельца стоят в owner-done и не доехали до канона: шаг 2 по ним не отработал"
status: done
source: nimbalyst
created: 2026-10-01
acceptance_probe: named_cards_closed_at_origin:inbox-dvenadtsat-otvetov-vladeltsa-stoyat-v-ow
status_trail:
  - "2026-10-03T03:56:47.054937+00:00 new -> done · queue.set_status · cycle-63205"
---

## Находка (замер цикла #744, 2026-10-01)

В трекере владельца **12** карточек стоят в статусе `owner-done`. По определению самого
трекера (`.nimbalyst/trackers/owner-decision.yaml`) это статус **НЕтерминальный**
(`category: started`): владелец ответил, а инжест ответа — работа агента, и снимает её
только переход в `ingested`. Старейшая стоит с **2026-08-29** (33 дня).

Шаг 2 протокола оркестратора обязывает каждый цикл инжестить `owner-done` (ADR + переход
`ingested`). Двенадцать карточек говорят, что по этим ответам шаг не отработал.

| создана | карточка |
|---|---|
| 2026-08-29 | `owner-decision-tier-steakhouse-2026-08-29` |
| 2026-09-01 | `owner-decision-novyi-porog-storozha-prosadki-gotov-i-pr` |
| 2026-09-05 | `owner-decision-chetyre-tysyachi-dollarov-edut-v-token-f` |
| 2026-09-07 | `owner-decision-ii-ne-puskayut-k-dengam-no-proverka-koto` |
| 2026-09-08 | `owner-decision-utrennie-soobscheniya-v-telegram-glavnoe` |
| 2026-09-09 | `owner-decision-earn-defi-litsenziya-na-dannye-do-deneg` |
| 2026-09-09 | `owner-decision-earn-defi-tablitsa-rezhimov-ne-bet-buy-and-hold` |
| 2026-09-09 | `owner-decision-gde-granitsa-reshai-sam-i-sprosi-menya` |
| 2026-09-09 | `owner-decision-pyat-reshenii-po-itogam-nochnogo-audita` |
| 2026-09-10 | `owner-decision-zapisyvat-li-v-dnevnoe-reshenie-vse-zhiv` |
| 2026-09-12 | `owner-decision-kriterii-gotovnosti-c012-podtverzhdaet-a` |
| 2026-09-12 | `owner-decision-skript-zhivogo-agenta-zapuskaetsya-tolko` |

## Чего этот замер НЕ говорит, и почему карточка, а не правка

«Карточка стоит в `owner-done`» и «решение владельца не доехало до канона» — **разные
утверждения**, и второе этим замером НЕ измерено. Проверка «цитирует ли какой-нибудь ADR
имя файла карточки» даёт `НЕТ-ADR` у всех двенадцати — и она ЛОЖНА как ответ на нужный
вопрос: решение карточки `gde-granitsa-reshai-sam-i-sprosi-menya` живёт в **ADR-285** и в
разделе `CLAUDE.md` «Граница „решай сам“ / „спроси меня“», просто ADR не называет файл.
Это ровно тот дефект, против которого написано `.claude/rules/site-numbers.md`: зелёный
ответ сторожа на СВОЙ вопрос не есть ответ на нужный.

Поэтому двигать статусы пачкой запрещено: это была бы самосертификация по форме. Работа
состоит в том, чтобы по КАЖДОЙ карточке прочитать ответ владельца и предъявить место в
каноне (ADR или правило), и только затем `set-status ingested`.

## Приёмка

Пробы под этот исход в реестре `card_acceptance.PROBES` сегодня нет (32 имени, ближайшие —
`owner_visibility_numbers_delivered`, `portfolio_decision_owner_covers_capital`). Значит
первая работа по карточке — написать пробу с контролем в обе стороны (ADR-333,
`.claude/rules/acceptance.md` п. 3): она обязана быть зелёной, когда у каждой карточки
`owner-done` назван адрес решения в каноне, и красной на каждом порванном звене — карточка
без адреса, адрес на несуществующий файл, адрес, который файл не подтверждает.

Объявить пробу ДО первой правки — иначе очередь откажет (`set-status` ⇒ `REFUSED`).

## Почему это не предмет владельца

Ни деньги, ни публичные числа, ни необратимое (граница ADR-285): владелец УЖЕ ответил по
каждой из двенадцати. Остаток — запись ответа в канон, то есть работа агента.

---

## ОПРОВЕРГНУТО замером цикла #757 (2026-10-03) — ADR-544

Находка ложна, и ложным её сделал сторож. Проверка каждой из двенадцати карточек по
`origin/main` (88ff132d7): **все двенадцать стоят в `ingested`.** Шаг 2 протокола
отработал по каждому ответу владельца.

| карточка | прод-дерево | origin/main |
|---|---|---|
| `tier-steakhouse-2026-08-29` | owner-done | **ingested** |
| `novyi-porog-storozha-prosadki-gotov-i-pr` | owner-done | **ingested** |
| `chetyre-tysyachi-dollarov-edut-v-token-f` | owner-done | **ingested** |
| `ii-ne-puskayut-k-dengam-no-proverka-koto` | owner-done | **ingested** |
| `utrennie-soobscheniya-v-telegram-glavnoe` | owner-done | **ingested** |
| `earn-defi-litsenziya-na-dannye-do-deneg` | owner-done | **ingested** |
| `earn-defi-tablitsa-rezhimov-ne-bet-buy-and-hold` | owner-done | **ingested** |
| `gde-granitsa-reshai-sam-i-sprosi-menya` | owner-done | **ingested** |
| `pyat-reshenii-po-itogam-nochnogo-audita` | owner-done | **ingested** |
| `zapisyvat-li-v-dnevnoe-reshenie-vse-zhiv` | owner-done | **ingested** |
| `kriterii-gotovnosti-c012-podtverzhdaet-a` | owner-done | **ingested** |
| `skript-zhivogo-agenta-zapuskaetsya-tolko` | owner-done | **ingested** |

**Не доехал не ответ владельца, а ИНЖЕСТ — обратно в прод-дерево.** `nimbalyst-local/`
в прод-дерево не синхронизируется НИКОГДА (ADR-152, §1 протокола): сессии пушат прямо на
origin, а хост-копия остаётся там, где её оставил бот, записавший ответ владельца.
Замер #744 читал прод-дерево и поэтому измерил возраст НЕ ТОГО.

**Почему это не было поймано сразу.** Единственный прибор, способный опровергнуть вывод,
— `check_tracker_drift` — на этих же карточках говорил `tree_newer` («копия дерева
новее origin»), опираясь на разницу отметок в **68–175 микросекунд** между двумя
писателями ОДНОГО события. Дефект сторожа найден и починен этим же циклом: введена
вторая ось порядка (след переходов), при разногласии осей вердикт снимается
(fail-CLOSED). Замер: 8 ложных `tree_newer` сняты, 19 новых решений добавлено.

Осторожность самой карточки («двигать статусы пачкой запрещено») оказалась ровно той,
что предотвратила вред: буквальное исполнение написало бы 12 дублирующих ADR и откатило
бы 12 инжестов.

Содержимое уехало в `docs/decisions/ADR-544-the-order-axis-answered-a-neighbouring-question.md`;
остаток класса — пункт 3 заказа G118 (прод-дерево не получает инжест никогда).
