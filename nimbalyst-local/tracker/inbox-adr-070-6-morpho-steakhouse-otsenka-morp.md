---
trackerStatus:
  type: inbox
title: "ADR-070.6: morpho_steakhouse = оценка morpho_blue"
status: new
source: nimbalyst
created: 2026-08-07
adr: ADR-070
---

Один vault — один риск; CI на main гаснет честно (решение владельца 2026-08-07, ADR-070 п.6)

## Замер (цикл #167, 2026-08-08) — что именно краснеет и почему

Полный прогон на ЧИСТОМ `origin/main` (4973428bf) даёт эти три падения БЕЗ чьих-либо правок —
это и есть «CI гаснет честно» из решения владельца, а не новая поломка:

- `tests/test_risk_scoring_completeness.py::test_every_registry_protocol_has_a_risk_score`
  → `adapters with no risk_score: ['morpho_steakhouse']`
- `::test_registry_is_not_empty_and_expected_size` → `assert 35 >= 36` (реестр адаптеров 36,
  записей в `PROTOCOL_RISK_SCORES` 35)
- `::test_exported_json_snapshot_is_consistent` → `morpho_steakhouse missing from exported JSON`
  (`data/protocol_risk_map.json`)

Радиус, ради контекста: `morpho_steakhouse` — **самая крупная позиция книги (40 %)**, и именно у
неё нет записи в карте рисков. Слой advisory (Risk Scoring v2) НЕ гейтит исполнение (инв. #1),
поэтому это не отказ money-path, но советующий слой слеп ровно на крупнейшем протоколе.

Молча не чинил: запись в `spa_core/risk/protocol_risk_map.py` — risk-слой, автономному циклу
запрещён. Решение владельца уже есть (ADR-070 п.6: «один vault — один риск», брать оценку
`morpho_blue`), не хватает только исполнения — карточка остаётся `new` как задача.

---

## ЗАБЛОКИРОВАНО (цикл #189, 2026-08-10): решение исполнить нельзя как написано

Взялся исполнять — упёрся в противоречие, которого раньше никто не назвал.

`morpho_blue` = **0.30 / T2**. `morpho_steakhouse` в `ADAPTER_REGISTRY` — **T1**, а контракт
тир↔оценка (тот самый `tests/test_risk_scoring_completeness.py`, тесты 4 и 7) требует для T1
оценку **< 0.25** и совпадения тира карты с тиром реестра. Значит:

* запись `{T1, 0.30}` роняет тест 4;
* запись `{T2, 0.30}` роняет тест 7;
* запись `{T1, <0.25}` проходит оба, но **нарушает само решение** — это уже не «оценка
  morpho_blue», а тихое утверждение, что Steakhouse безопаснее Morpho Blue.

Третьей формы не существует. «Один вольт — один риск» на деле означает демоушен
`morpho_steakhouse` T1 → T2, а тир — вход гейта концентрации (`spa_core/risk/policy.py:410`):
потолок доли падает **40 % → 20 %**. Это money-path, автономно запрещён.

Карточка владельцу с тремя вариантами и рекомендацией:
`owner-decision-reshenie-adr-070-p-6-ispolnit-nelzya-odi`.
Эта карточка остаётся `new` — задача жива, ждёт буквы варианта.
