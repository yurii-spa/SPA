---
trackerStatus:
  type: inbox
title: купить зонт в пятницу
status: done
source: telegram
created: 2026-10-17
fate_reason: "заработанное освобождение: предмет уехал в вопрос владельцу о том же тексте (16.10)"
carried_to: nimbalyst-local/tracker/owner-decision-utochnenie-po-zametke-kupit-zont-v-pyatn-3.md
status_trail:
  - "2026-10-24T15:10:16.415374+00:00 new -> done · queue.set_status"
  - "2026-11-18T05:23:05.930601+00:00 done -> done · queue.set_status/closed_by:agent:orchestrator cycle-60184 (цикл #1189, ADR-1051)/evidence:носитель: тот же текст владельца уже стал вопросом owner-decision-utochnenie-po-zametke-kupit-zont-v-pyatn-3 (16.10, снят ретракцией ADR-807 25.10) — предмет лежит там; замер и причина в теле карточки · cycle-60184"
---

## Задание (из Telegram)

купить зонт в пятницу

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Судьба карточки разобрана — цикл #1189 (2026-11-18, ADR-1051)

**Дорога — заработанное освобождение (`carried_to`), и цель ИЗМЕРЕНА, а не
скопирована у соседа.** Этот же текст владельца уже становился вопросом:
`owner-decision-utochnenie-po-zametke-kupit-zont-v-pyatn-3` (создан 16.10 из
`inbox-kupit-zont-v-pyatnitsu-3.md`, цитирует задание ДОСЛОВНО) и снят 25.10 ретракцией
ADR-807 с причиной «личное напоминание, не работа по SPA». Предмет этой карточки — ровно
тот же, и он лежит ТАМ.

⚠️ Цель прецедента `inbox-kupit-zont-v-pyatnitsu-7/-8` скопирована НЕ БЫЛА намеренно: там
`carried_to` указывает на карточку приказа «Portfolio CIO», к которой зонт отношения не
имеет (заказ G1038 назвал это прямо).
