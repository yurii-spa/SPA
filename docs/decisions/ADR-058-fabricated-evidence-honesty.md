# ADR-058 — fabricated track-evidence: flag (not delete) + milestones from real days only

- **Статус:** Accepted (owner Variant A, 2026-07-23)
- **Контекст-источник:** карта `owner-decision-v-zhurnalah-dohodnosti-zapisany-vydumann.md`.
- **Домен:** track evidence / honesty (money-path-adjacent данные; не меняет RiskPolicy/kill-switch).

## Контекст

Дневной цикл, не сумев прочитать живую доходность, подставлял в журналы **S7-бэктест 10.115%** как
fallback. Замер 2026-07-23 (живые данные): fabricated-строки 2026-07-28 и 2026-07-29 в
`data/paper_evidence.json` и `data/apy_milestone_log.json`; **отметка достижения 10% стояла на
fabricated-дне 28.07**. Реальные дни ~1.6–8.45% ⇒ на реальных данных 10% НЕ бралась. Инвариант #8
(не выдавать бэктест за live) + продукт «проверь нас» требуют честности.

## Решение (Variant A — пометить, не стирать)

1. Каждой fabricated-строке (apy_pct == 10.115) добавить `fabricated: true` + `fabricated_reason`
   (строки ОСТАЮТСЯ — полная проверяемость).
2. **Producer** `apy_milestone_tracker._refresh_milestones_reached` теперь **пропускает
   `fabricated`-строки** — иначе перестройка отметок каждый `record_day` переиздавала бы 10% из
   fabricated-дня (durability).
3. Отметки пересчитываются по реальным дням (конвенция producer: присутствуют только достигнутые).
   Результат: 5% → 08.07, 7% → 08.07 (реальные), **10% → исчезает (не достигнута)**.
4. Детерминированный скрипт `scripts/fix_fabricated_evidence.py` (`--dry-run` для diff; идемпотентен).

## Последствия

- (+) Ни один отчёт больше не опирается на выдуманное число; история видна целиком (флаг, не удаление).
- (−) Публикуемая «достигли 10%» падает в «не достигнуто» — честное состояние, принято владельцем.
- Тесты: `test_fix_fabricated_evidence.py` (16) — producer skip + flag/recompute/idempotent/dry-run.
- Код цикла уже не фабрикует НОВЫЕ строки; этот ADR чистит исторические + делает флаг durable.

## Связанные

`agent-track-data-git-durability-guard.md` (paper_evidence синхронизация в git — после этого фикса),
memory `fail-open-monitor-class`, ADR-056/057 (тот же honesty-класс).
