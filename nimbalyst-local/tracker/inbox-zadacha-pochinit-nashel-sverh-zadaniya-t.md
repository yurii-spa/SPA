---
trackerStatus:
  type: inbox
title: "задача - починить \"• нашёл сверх задания: тесты на main снова красные из-за одн…"
status: done
source: telegram
created: 2026-08-05
---

## Задание (из Telegram)

задача - починить "• нашёл сверх задания: тесты на main снова красные из-за одного сторожа дат — карточка «agent-frozen-date-ratchet-red-on-main»."

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Обработано 2026-08-05 (цикл #119) — вердикт: УЖЕ СДЕЛАНО

Проверка истории (§1a) до создания работы: дефект починен **волной 3** ещё до того, как задание
дошло — коммит `d1faaf6f5`, и починен правильным способом.

Перепроверил сам, отчёту на слово не поверил (чистый чекаут `origin/main d1faaf6f5`):

- `spa_core/tests/test_frozen_date_ratchet.py` — **5 passed** (падал
  `test_no_new_file_joins_the_frozen_date_class`);
- база `frozen_date_baseline.json` — 251 запись, `snapshot: 2026-08-05` = **НЕ выросла**
  (гасить падение ростом базы правило `.claude/rules/deployment.md` прямо запрещает);
- оба файла (`test_apy_series.py`, `test_apy_series_accumulator.py`) получили обоснованные
  маркеры `# FROZEN-DATE-OK` — законный вариант 3 протокола: в обоих сама дата является
  предметом проверки, а в аккумуляторе часы вдобавок инжектируются (`accumulate(today=...)`);
- CI на `main @ d1faaf6f5`: **SPA Tests · SPA CI · SPA Proof Gate · SPA Lint — все зелёные**.

Дубль-карточку не заводил. Порождённая работа: `agent-frozen-date-ratchet-red-on-main` → `done`.
