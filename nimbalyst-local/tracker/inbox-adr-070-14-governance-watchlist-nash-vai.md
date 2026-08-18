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

---

## ЗАМЕР И ИСПОЛНЕНИЕ 2026-08-18 — четвёртая часть сделана как B7

**Перепроверка сверки от 17.08: подтверждена.** Части 1–3 на месте
(`SNAPSHOT_SPACES` = 2 наших пространства, шестёрка чужаков — данными в
`REMOVED_NOT_INVESTABLE`, дыры названы в `GOVERNANCE_SOURCE_UNCONFIRMED`).
ADR-071 в дереве действительно НЕТ.

**Числа (замер против дерева, не «частично»):**
- watchlist сейчас: **2** — `aave-v3`, `compound-v3`
  (`spa_core/alerts/governance_watcher.py:148-151`);
- имён в watchlist, которых мы не держим и держать не собираемся: **0**;
- held: **7** — `aave_v3`, `compound_v3`, `euler_v2`, `maple`,
  `morpho_steakhouse`, `spark_susds`, `yearn_v3`;
- held БЕЗ канала наблюдения: **5**; из них названы с причиной — **3**
  (`maple`, `morpho_steakhouse`, `spark_susds`), **безымянных — 2:
  `euler_v2` и `yearn_v3`**;
- вайтлист (`ADAPTER_REGISTRY`): 36; покрыто каналом 2.

**Четвёртая часть исполнена как проверка B7** в
`spa_core/monitoring/architecture_conformance.py` (шапка модуля + `run_checks`),
ссылка — на РЕАЛЬНЫЕ документы: решение ADR-070 п.14, рамка сторожа ADR-066.
Имя `B6` в этом модуле занято курацией, а ADR-071 не существует — ссылку в
пустоту не воспроизводим. Тесты: `spa_core/tests/test_architecture_conformance_governance.py`.

**ОСТАЛОСЬ (решение владельца):** B7 на живом дереве сейчас честно WARN —
`euler_v2` и `yearn_v3` держат капитал, канала нет и дыра даже не названа.
Заполнить их в `GOVERNANCE_SOURCE_UNCONFIRMED` без живой сети нельзя, не
выдумывая причину; сессия сознательно оставила находку красной, а не погасила её.
