# Dispatch Report — 2026-05-31 — SPA-V356 (orchestrator run)

**Статус: УСПЕХ. Код внесён, протестирован, запушен (6/6).**

## Состояние на входе
- Последний завершённый спринт: **v3.55** (SPA-V355 — MEV-protection статус в `adapter_status.json` + дашборд).
- v3.55 заканчивается на «5» → периодический architect review **требуется**.
- HIGH-backlog заблокирован на user_action (SPA-BL-012); feed-health домен заморожен (SPA-BL-011); SPA-BL-010 (MEV) done.

## Architect review (выполнен оркестратором напрямую)
- `spa_core/dev_agents/architect.py` падает в sandbox (`ModuleNotFoundError: anthropic`) — применён прецедент v3.51: review проведён оркестратором.
- **Вывод:** весь HIGH-backlog (BL-004/005/006, SPA-BL-007/008/009, FEAT-001/002) упирается в user-action секреты — критический путь к go-live, недоступен автономному прогону. Feed-health заморожен (SPA-BL-011). Единственная разблокированная код-работа — продолжение MEV-домена из dispatch-ноты v3.55. KANBAN housekeeping не требуется (карточки актуальны после v3.51).
- **Решение:** взят SPA-V356 = per-adapter MEV-routing applicability (вариант «а» из ноты v3.55; вариант «б» feed-health заморожен). Status pass НЕ применялся.

## SPA-V356 — что сделано
- `spa_core/execution/adapter_status.py`: helper `_adapter_mev_routed(module)` (never-raise; `inspect.getsource` → ищет ссылки на `send_raw_transaction_auto`/`broadcast_protected_hash`/`send_protected`); per-adapter поле `mev_routed` (присутствует на всех путях); блок `mev_protection` дополнен `routed_adapters`/`unrouted_adapters`; `collect_adapter_status()` вызывается один раз.
- `spa_core/tests/test_adapter_status.py`: новый класс `TestMevRoutingApplicability` (9 тестов); существующие 6 в `TestMevProtectionStatus` не тронуты.
- `index.html`: null-safe суффикс `N/M adapters routed` в MEV-бейдже (`Array.isArray` guard для старых фидов).
- `data/adapter_status.json` перегенерирован.
- Money-moving код (`mev_protection.py` / `eth_signer.py` / адаптеры) НЕ тронут — только читался.

## Результат маршрутизации
- routed: yearn-v3, euler-v2, maple, sky-susds
- unrouted: **pendle-pt** (BLOCKED/NotImplemented, 0 ссылок на mev_protection)

## Верификация (независимо перепроверено оркестратором)
- `pytest test_adapter_status` — **81 PASS / 0 FAIL**; полный набор (`+test_mev_protection +test_mev_wiring`) — **139 PASS / 0 FAIL** (9 новых). Baseline-фейлов нет.
- `py_compile adapter_status.py` — OK. `KANBAN.json` валиден (first done = `SPA-V356-001`, sprint=v3.56). `adapter_status.json` валиден — у каждого адаптера `mev_routed`, блок mev_protection с routed/unrouted списками.

## Push
`push_v356.html` → `http://localhost:8765/` через Chrome → **6/6 ok** (KANBAN.json, SPA_sprint_log.md, adapter_status.py, test_adapter_status.py, index.html, data/adapter_status.json).

## Bookkeeping
Done-карта `SPA-V356-001` добавлена первой в `columns.done`; top-level meta → v3.56. Запись в `SPA_sprint_log.md` сверху. Бэкапы `.bak.v356` (KANBAN.json, SPA_sprint_log.md).

## Следующий спринт (для следующего прогона)
**SPA-V357:** (а) per-adapter MEV-routing построчно в Go-Live таблице (колонка/бейдж на строку); ЛИБО (б) проброс T1-адаптеров aave/compound в `_ADAPTER_SPECS` (роутятся через `_send_raw_tx`, но отсутствуют в дашборде). HIGH go-live путь по-прежнему user-action-blocked (SPA-BL-012); feed-health заморожен (SPA-BL-011).
