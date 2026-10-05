---
trackerStatus:
  type: inbox
title: "Хвост ADR-564: пять дефектов фабрики исследований после повторного разбора"
status: done
created: 2026-10-04
acceptance_probe: research_evidence_tail_closed
status_trail:
  - "2026-10-05T00:37:19.525485+00:00 new -> in-progress · queue.set_status"
  - "2026-10-05T01:19:31.164353+00:00 in-progress -> done · queue.set_status/closed_by:RM-EVIDENCE-01 tail session (Claude, 2026-10-05)/evidence:acceptance probe research_evidence_tail_closed = satisfied (declared before work, was not_satisfied on all six links); independent review CLOSE AFTER FIXES -> re-review CLOSE; ADR-564 section 'Tail cl"
---

Хвост ADR-564 (RM-EVIDENCE-01): пять дефектов, названных независимым повторным разбором и не починенных
прицепом. Капитал не затрагивают; сегодня ни один кандидат не на бумаге.

1. **N4 (LOW).** `run.py`: наблюдение записывается (`_process_candidate`) ДО того, как Шерлок ставит кандидата на
   паузу (`_sherlock_review_all`) — в день, когда доказательства истекли, может засчитаться один период.
   Починка: перепроверять последнее решение перед засчётом либо сначала рецензия.
2. **Граница доверия (LOW).** Запись проверки (`registry/fact_reviews/*.json`) может добавить любой, у кого есть
   коммит, под любым именем проверяющего; `evidence_contract.role_entry` принимает OBSERVED по любой нативной для
   цепочки цитате, не связывая её с личностью роли. Починка: белый список проверяющих + тип заявки, подходящий роли.
3. **Начальный URL не нормализуется** (`http_client.fetch`): `/api/../x` проходит проверку префикса (только для URL,
   собранного вызывающим кодом).
4. **Окончание льготы OUSG — константа** (`scanners/rwa.py`): у фактов нет структурного `effective_until`.
5. **Ставка из on-chain индекса кредитного протокола больше не даёт независимости** (следствие H5): нужен явный класс
   «состояние, вычисленное контрактом», чтобы такие ставки снова считались независимым свидетелем.
