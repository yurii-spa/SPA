---
trackerStatus:
  type: inbox
title: купить зонт в пятницу
status: done
source: telegram
created: 2026-10-24
fate_reason: "заработанное освобождение: предмет уехал в вопрос владельцу о том же тексте (16.10)"
carried_to: nimbalyst-local/tracker/owner-decision-utochnenie-po-zametke-kupit-zont-v-pyatn-3.md
status_trail:
  - "2026-10-27T23:15:24.511300+00:00 new -> done · queue.set_status"
  - "2026-11-18T05:23:06.499429+00:00 done -> done · queue.set_status/closed_by:agent:orchestrator cycle-60184 (цикл #1189, ADR-1051)/evidence:носитель: текст задания дословно тот же, вопрос по нему владельцу задан и снят (owner-decision-utochnenie-po-zametke-kupit-zont-v-pyatn-3, 16.10/25.10); замер и причина в теле карточки · cycle-60184"
---

## Задание (из Telegram)

купить зонт в пятницу

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Судьба карточки разобрана — цикл #1189 (2026-11-18, ADR-1051)

**Дорога — заработанное освобождение (`carried_to`), цель та же, что у
`inbox-kupit-zont-v-pyatnitsu-5`, и по той же измеренной причине:** текст задания
дословно совпадает, а вопрос по нему владельцу уже задан и снят — 
`owner-decision-utochnenie-po-zametke-kupit-zont-v-pyatn-3` (16.10, ретракция ADR-807
25.10: «личное напоминание, не работа по SPA»).

⚠️ Цель прецедента `-7`/`-8` (карточка приказа «Portfolio CIO») не копируется: она к
предмету не относится.
