---
trackerStatus:
  type: agent
title: Портфель нарушает два инварианта прямо сейчас — 15% в advisory-протоколах и 5% в Sky/spark при запрете (D3+D4)
status: in-progress
source: owner-decision-2026-08-02 (W4, «чинить отдельно и сразу»)
created: 2026-08-02
priority: critical
domain: money-path (RiskPolicy НЕ трогаем; pre_cutover_gate + ADR-061)
---

## Что случилось и почему это важно

Замер 2026-08-02 живой книги ($100k paper):

- **D3 — 15 % капитала в advisory-протоколах.** `susde` ($10 000) и `extra_finance_base` ($5 000)
  имеют `IS_ADVISORY=True`. Live-путь аллокатора их корректно исключает
  (`_default_live_apy_provider`, allocator.py:163), а **registry-merge путь — нет**: он проверяет
  только поле `research_only` в JSON-реестре, а не флаг класса адаптера. Нарушен инвариант 9
  (advisory не двигает капитал).
- **D4 — 5 % в `spark_susds` при прямом запрете.** `SparkSusdsAdapter.is_eligible()` возвращает
  **False** (GSM Pause Delay < 48 ч — инвариант 10 «Sky/sUSDS = 0 % до подтверждения»). Аллокатор
  `is_eligible()` не спрашивает вообще ни у одного адаптера.

## Что нужно сделать

1. Registry-merge в `allocator._load_adapters` исключает адаптеры, у класса которых
   `IS_ADVISORY`/`RESEARCH_ONLY` — зеркало live-пути (единый список исключений, не две логики).
2. ~~Аллокатор консультируется с `is_eligible()`~~ → **сужено при реализации:** гейт по
   `is_gsm_compliant()` (явный инвариант активации), НЕ по общему `is_eligible()`. Причина:
   `is_eligible = gsm ∧ MIN_APY ≤ apy ≤ MAX_APY`, а эти полосы — per-adapter проверка вменяемости
   фида (spark 4–9 %, fluid 3–10 %), не политика (RiskPolicy 1–30 %). Гейт по ней молча установил бы
   APY-floor, которого нет ни в одном ADR. Первая версия правки гейтила по `is_eligible`, и
   существующий тест `test_live_apy_drives_ranking_not_the_stale_literal` это поймал — правился код,
   не тест (правило 16). Обоснование зафиксировано в ADR-061 §Решение п.4.

## ⚠️ Обязательная оговорка по выкатке

**Нельзя выкатывать в отрыве от D1/D2** (`agent-apy-evidence-provenance.md`). Замер: если убрать
advisory+spark на сегодняшних входах, greedy зальёт освободившиеся 20 % в литералы `frax 7.5 %` и
`scrvusd 7.0 %` (выдуманные числа) ⇒ доля капитала на неподтверждённых числах вырастет с 15 % до
30 %. Карточки раздельные, выкатка — один проверенный набор.

## Как понять, что готово

Тест: advisory-адаптер не может получить вес ни одним из двух путей; `is_eligible()==False` ⇒ вес 0;
книга после правки не содержит `susde` / `extra_finance_base` / `spark_susds`; `policy.py`
byte-identical; `policy_enforcer` пропускает новую книгу; `pre_cutover_gate` зелёный.

## Статус реализации (2026-08-02)

Реализовано в изолированном worktree вместе с D1/D2, ADR-061. Замер: обе позиции-нарушителя
(`susde`+`extra_finance_base` 15 %, `spark_susds` 5 %) больше не финансируются; `policy_enforcer`
пропускает новую книгу; тесты `test_allocator_evidence_gate.py` зелёные. **Ждёт go владельца на пуш.**
Побочно: `fluid_fusdc` заблокирован тем же GSM-гейтом, а `gsm_hours` никто не производит →
карточка `agent-gsm-hours-never-produced.md` (needs-owner).

## Что будет после

Владельцу показывается diff + получившаяся книга ДО пуша (sensitive-мутация трека). Решение
зафиксировано в ADR-060 (§ приёмка) и ADR-061.
