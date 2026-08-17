---
trackerStatus:
  type: inbox
title: "ADR-070.14: governance watchlist = наш вайтлист"
status: new
source: nimbalyst
created: 2026-08-07
adr: ADR-070
---

Убрать balancer/curve/lido/maker/uniswap-v3/yearn; добавить источники held (aave/pendle/maple/morpho) + вайтлист по наличию каналов; семантическую проверку watchlist∩held — в conformance (ADR-071 B6) (решение владельца 2026-08-07, ADR-070 п.14)


---

## СВЕРКА 2026-08-17 — три части из четырёх сделаны, четвёртая отсутствует

Задание распадается на четыре проверяемых требования.

**✅ 1. Убрать `balancer`/`curve`/`lido`/`maker`/`uniswap-v3`/`yearn`.**
`spa_core/alerts/governance_watcher.py:148-151` — `SNAPSHOT_SPACES` содержит
ровно два наших пространства (`aave-v3` → `aave.eth`, `compound-v3` →
`comp-vote.eth`). Шестёрка вынесена ДАННЫМИ в
`REMOVED_NOT_INVESTABLE` (стр. 157–164), чтобы «не вернулись» держал тест, а не
удалённый комментарий; сид-предложения из `BOOTSTRAP_PROPOSALS` тоже вычищены
(тест `test_removed_protocols_are_gone_from_the_fallback_seed_too`).

**✅ 2. Добавить источники held (aave/pendle/maple/morpho).** Сделано честно:
у pendle/maple/morpho источника НЕТ, и вместо угаданного слага заведён
`GOVERNANCE_SOURCE_UNCONFIRMED` (стр. 177) с дословной причиной и
кандидатом, который НЕ используется для запросов
(`test_a_candidate_slug_is_never_used_as_a_live_source`). Это соответствует
запрету fake-fallback (`.claude/rules/adapters.md`), а не обходит задание.

**✅ 3. Вайтлист по наличию каналов + измерение held.** `held_measured` /
`held_reason` (стр. 404–439): нечитаемый файл ⇒ «не измерено» с причиной,
никогда «дыр нет». 132 теста в трёх файлах
(`test_governance_watchlist_is_ours.py`, `test_governance_watcher.py`,
`test_governance_watcher_coverage.py`) — **`132 passed in 0.79s`**.

**❌ 4. «Семантическую проверку watchlist ∩ held — в conformance (ADR-071 B6)» —
НЕ сделано.** В `spa_core/monitoring/architecture_conformance.py` нет ни одного
упоминания governance / watchlist / held (`grep` пуст). Самого документа
`docs/decisions/ADR-071*` в репозитории тоже не существует — реестр ADR
перескакивает с ADR-070 на ADR-072.

Пересечение сегодня проверяется ТЕСТАМИ модуля, но не conformance-слоем,
как просило задание. Карточку не закрываю; для закрытия нужно либо завести
проверку в `architecture_conformance`, либо владельцу подтвердить, что тестов
достаточно (и тогда снять ссылку на несуществующий ADR-071 B6).
