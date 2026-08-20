---
trackerStatus:
  type: inbox
title: Подними приоритет inbox-task-portfolio-cio-dynamic-capital-alloc на high. Шесть…
status: done
source: telegram
created: 2026-08-19
---

## Задание (из Telegram)

Подними приоритет inbox-task-portfolio-cio-dynamic-capital-alloc на high. Шесть карточек-осколков от 13.08 склей в якорную и закрой как дубли. Начни с этапа диагностики по моему ТЗ: почему 40% в Aave под 2.7%, что блокирует risk gate (9 blocks/день), где рвётся цепочка allocator→gate→execution.

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Исполнено (цикл #310)

Классификация: **задача**, исполнена в той части, что безопасна и была прямо поручена.

1. `inbox-task-portfolio-cio-dynamic-capital-alloc` — **`priority: high`** проставлен.
2. Шесть осколков от 13.08 закрыты как дубли якоря (все — куски одного твоего ТЗ, разрезанные
   интейком по границам Telegram-сообщений): `inbox-why-it-exists`, `inbox-dlya-kazhdogo-etapa-pokazat`,
   `inbox-actual-costs`, `inbox-apy-persistence-confidence`,
   `inbox-esli-tot-zhe-target-mozhno-priblizit-pro`, `inbox-100-zapuskov-na-odnom-snapshot`.
3. Этап диагностики — вердикт шага 1a **DONE, заново не делал**: он исполнен документом
   `docs/research/RS-portfolio-cio-diagnosis.md` (доставлен 19.08, коммиты `891ad092e`, `9b432abf3`).
   Ответы на три твоих вопроса вынесены таблицей в якорную карточку — коротко: аллокатор НЕ статичен
   (книга стояла из-за неменяющихся входов, `diff < $200`); «9 blocks/день» — гейты сработали
   ПРАВИЛЬНО, это пара строк на каждый недоказанный пул, а не 9 инцидентов; цепочка
   allocator→gate→execution не рвётся — рвётся НАБЛЮДАЕМОСТЬ входов (из $80k только $20k
   ранжировались по живому числу).

Дальше по документу §4: гэпы G1 (наблюдаемость) → G2 → G3 → G4; замером 19.08 уточнено, что
**G4 не воспроизводится, G2 в main пуст**.
