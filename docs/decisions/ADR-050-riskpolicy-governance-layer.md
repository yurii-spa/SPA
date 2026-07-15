# ADR-050 · RiskPolicy → governance-слой; API auth; exec-bypass закрыт

- **Статус:** Accepted (owner-approved; backfilled в реестр 2026-07-15).
- **Дата:** 2026-06-28
- **Автор/утвердил:** владелец + architect-honesty sprint

## Контекст

Round-2 аудит выявил три сцепленные слабости контура:

1. **Публичный API без auth.** FastAPI-сервер (`api.earn-defi.com:8765`) раздавал endpoints без
   единой политики авторизации — read-only GET публичны by design, но не было выделенного слоя,
   различающего публичное чтение от admin-операций.
2. **Exec-bypass.** Оставалась теоретическая тропа, по которой исполнение могло бы обойти
   детерминированный гейт (расхождение между «где живёт RiskPolicy» и «где принимается решение»).
3. **RiskPolicy как единственный hard-гейт** должна быть недвусмысленно неизменяемой весь paper-период
   (инвариант #1), но governance-логика (two-tier kill-switch, authority-table) исторически смешивалась
   с `RiskConfig`-порогами, создавая соблазн «подкрутить» гейт.

Инварианты, которых касается: #1 (RiskPolicy v1.0 — единственный hard-гейт), #3 (LLM запрещён в
risk/execution), #6 (не импортировать `execution/` из read-only кода).

## Решение

1. **RiskPolicy → governance-слой.** Governance-as-Code вынесен в `spa_core/governance/`
   (`policy.py` — authority-table AUTO / HUMAN_SINGLE / HUMAN_DUAL с default-DENY;
   `kill_switch.py` — two-tier drawdown-ladder). Это **параллельный слой**: добавляет authority-
   капабилити, но `RiskConfig`-пороги RiskPolicy `v1.0` не трогает. Version-строка остаётся `"v1.0"`
   весь paper-период — two-tier и authority-table живут в governance, не в policy.
2. **API auth-слой** (`spa_core/api/auth.py`, `api_security.py`): HMAC-подписанные токены
   (`<unix_ts>.<hex_hmac_sha256>`), ключ из `SPA_API_KEY` (env → Keychain). `/api/v1/*` GET —
   публичны (read-only). `/admin/*` — требуют валидный токен. LLM запрещён в auth-домене
   (prompt-injection risk).
3. **Exec-bypass закрыт.** Исполнение не может обойти детерминированный гейт: `approved=False`
   не переопределяется ничем; read-only/paper-код не импортирует `spa_core/execution/`.

## Последствия

- ✅ RiskPolicy `v1.0` доказуемо неизменна (изменения — в governance-слое, не в policy).
- ✅ Admin-операции за auth; публичное чтение остаётся открытым (дашборд не ломается).
- ⚠️ **OWNER-действие:** установить `SPA_API_KEY` (env / Keychain) на проде, иначе admin-токены
  не подписываются. Отслеживается в памяти `edge-honesty-and-round2`.
- Соблюдать: не смешивать `RiskConfig`-пороги с governance-логикой; не импортировать `execution/`
  из read-only; LLM запрещён в auth/risk/execution.
- Затронутые файлы: `spa_core/governance/{policy.py,kill_switch.py,ssot.py}`,
  `spa_core/api/{auth.py,api_security.py}`. Связанные ADR: ADR-048 (two-tier kill-switch).
