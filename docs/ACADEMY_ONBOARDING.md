# Academy: Real-Money Onboarding — Руководство

Небольшое invite-gated, **non-custodial** приложение, которое проводит человека
от «нет кошелька» до реального supply→withdraw на Base — безопасно, в пределах
учебного лимита **$150**, и с **on-chain доказательством** каждого шага.

- Backend: `spa_core/academy/` — отдельный FastAPI sub-app, монтируется на
  `/academy` (своя CORS, свои credentialed-cookie, своя SQLite `data/academy.db`).
- Frontend: `landing/src/pages/academy/onboarding` + `landing/src/components/academy/`.
- ADR: `docs/adr/ADR-ACAD-001.md`. Инварианты — там же (LLM запрещён, ключи не
  хранятся, зачёт = блокчейн-доказательство, `events` append-only).

---

## Быстрый старт (dev)

```bash
# 0. Зависимости (только для academy-пути; основной runtime остаётся stdlib-only)
~/miniconda3/bin/python3 -m pip install "argon2-cffi>=23.1,<25" eth-account eth-utils

# 1. Создать + мигрировать dev-БД (НЕ трогает прод academy.db)
export SPA_ACADEMY_DB=/tmp/academy_dev.db
python3 scripts/init_academy_db.py --db "$SPA_ACADEMY_DB" --create
#   schema_version = 1

# 2. Owner-аккаунт (пароль из env, не в argv/history)
ACAD_PW='choose-a-strong-one' \
  python3 -m spa_core.academy.manage create-owner \
  --email you@example.com --password-env ACAD_PW

# 3. Invite-код для ученика
python3 -m spa_core.academy.manage gen-invite --max-uses 1   # → печатает код

# 4. Поднять API (academy монтируется на /academy внутри основного сервера)
export SPA_ACADEMY_DEV=1          # relaxed cookie Secure + разрешает localhost:4321
python3 -m spa_core.api.server    # или запустить весь apiserver

# 5. Astro dev-сервер сайта
cd landing && npm run dev         # http://localhost:4321/academy/onboarding
```

Полезные команды управления:

```bash
python3 -m spa_core.academy.manage list-users
python3 -m spa_core.academy.manage reset-password --email you@example.com --password-env ACAD_PW
```

> **Никогда** не запускай dev против прод-`academy.db`. `SPA_ACADEMY_DB` не имеет
> дефолта — незаданная переменная падает с ошибкой, чтобы шальной процесс не создал
> БД в неверном месте.

---

## Модули M0–M8

Каждый модуль: краткая теория (RU) + практика + блок «что бы здесь сделал SPA»
(привязка к kill-rules / refusal-first). Контент — `spa_core/academy/content/modules.py`.

| # | Модуль | Практика (verifier) | Зачёт |
|---|---|---|---|
| M0 | Тестовая сеть Base Sepolia | on_chain_tx | подтверждённая свежая tx на Sepolia |
| M1 | Кошелёк и сид-фраза | siwe | верифицированная привязка кошелька (подпись) |
| M2 | Сети и газ | balance | на Base-кошельке есть ETH на газ |
| M3 | Первая транзакция | on_chain_tx | свежий исходящий USDC-Transfer со своего адреса |
| M4 | Подписи и approvals | event_log | approve (>0) + revoke (=0) на Aave Pool, revoke позже |
| M5 | Депозит в Aave | balance | Aave v3 `Supply` USDC на свой адрес |
| M6 | Вывод из Aave | balance | Aave v3 `Withdraw` USDC + учёт газа |
| M7 | Инциденты и защита | quiz_only | лучший результат квиза ≥ 80% (≥10 вопросов) |
| M8 | Капстоун | capstone | свежий Supply+Withdraw после старта + рефлексия в заметках |

Порог квиза — 80% (`math.ceil`, так что 8/10 на M7 проходит). Правильные ответы
живут только на сервере (`quiz_bank.py`) и никогда не сериализуются клиенту.

---

## On-chain верификация

- Диспетчер: `POST /verify/{lesson_id}` → `spa_core/academy/onchain/verifiers.py`.
- **Read-only, детерминированно, без ключей, без state-changing RPC.**
- **fail-CLOSED:** любой сбой RPC → `unavailable` (никогда молчаливый pass).
- **Свежесть:** tx засчитывается только если `block.timestamp > started_at` —
  нельзя переиграть старую до-курсовую транзакцию как доказательство.
- **Anti-replay:** `used_tx_hashes` (PK `tx_hash+chain`) — один tx не засчитать
  дважды / другим пользователем / для другого урока.
- **Учебный лимит $150:** сумма сверх лимита — *advisory-флаг*, не reject
  (ученик предупреждён, но честно пройденный урок не теряет).
- **Газ:** `get_gas_summary(db, user_id)` суммирует `gas_wei` по всем verified-
  уроках → `{total_gas_wei, total_gas_eth, total_gas_usd_est}`; используется в
  капстоуне (M8) и в сертификате.

### Мок для тестов

Вся сеть в тестах замокана (`monkeypatch` на `spa_core.academy.onchain.rpc.call`)
— NO network. Пример настройки verified-прогресса и газа —
`spa_core/tests/test_academy_verifiers_m4m8.py`. RPC-endpoint'ы конфигурируются
через `SPA_ACADEMY_RPC_BASE` / `SPA_ACADEMY_RPC_SEPOLIA` (опционально — на случай
флапа публичных RPC).

---

## Экспорт, админ, сертификат (stage 9)

- `GET /export` — полный takeout своих данных (профиль, прогресс с evidence,
  заметки, квизы, кошельки, **только свои** events, gas_summary). 5/час.
- `GET /admin/users|progress|events` — owner-only, кросс-пользовательская картина;
  `password_hash` никогда не возвращается; `events` — `?since=&limit=` (≤ 1000).
- `GET /certificate` — сертификат, но только когда **все 9 модулей verified**
  (иначе 404). Приватный по умолчанию.
- `POST /certificate/publish` — публикация: `public_token`, детерминированный
  snapshot, `cert_hash = sha256(canonical_json)`, анкоринг в append-only
  `events` (`cert_anchor` с `prev_hash`-цепочкой). Идемпотентно.
- `GET /certificate/public/{token}` — публичный snapshot **без auth** (для шеринга),
  отдаёт замороженные на момент публикации данные + `cert_hash`.

Публичный URL сертификата:
`https://earn-defi.com/academy/onboarding/certificate/{public_token}`.

---

## Безопасность (сводка)

| Механизм | Реализация |
|---|---|
| Пароли | argon2id (`argon2-cffi`), constant-time auth, авто-rehash |
| Сессии | opaque cookie + per-session CSRF-токен (double-submit), TTL, revoke |
| CSRF | мутирующий запрос обязан эхо-нуть `X-CSRF-Token` (constant-time) |
| Rate-limit | login 5/15м (IP+email), register 5/15м, verify 10/ч, quiz 20/ч, export 5/ч |
| SIWE | строгая EIP-4361 валидация domain/chain/nonce/freshness; single-use nonce; глобальная уникальность verified (addr,chain) |
| Seed-guard | middleware отклоняет тело с приватным ключом / seed-фразой (400), контент НЕ логируется |
| Изоляция | отдельный FastAPI-app, своя CORS/cookie; mount под `try/except` — битая/отсутствующая `academy.db` не роняет основной API |

**Инвариант №1:** сервер **никогда** не хранит приватные ключи или seed-фразы.
Вход — только по подписи (SIWE). Никакой загрузки ключей, нигде.

---

## Тесты

```bash
python3 -m pytest spa_core/tests/test_academy_{db,auth,api,ratelimit,seedguard,\
progress_notes_quiz,siwe,onchain,verifiers_m4m8,final}.py -v
```

Все — против throwaway tmp-file БД, без сети и без реального `data/`.

## Production deploy checklist

The Academy backend is a FastAPI sub-app mounted at `/academy` inside the **live** apiserver
(`spa_core/api/server.py`, port 8765, served at `api.earn-defi.com` via the cloudflared tunnel — the
same process the public dashboard depends on). Follow this checklist so bringing it up never disturbs
the dashboard or the daily paper track.

### When to restart the apiserver
- **NOT during the daily cycle window.** The cycle runs at **06:00 UTC** (evidence: `last_cycle_ts` in
  `data/paper_trading_status.json`; note the plists use `Hour=8` in **local/CEST** = 06:00 UTC — the docs
  that say "08:00 UTC" are mislabelled). Avoid `±15 min` around 06:00 UTC.
- **NOT during a `site_freshness.yml` run** (cron `15 */6 * * *` → 00:15 / 06:15 / 12:15 / 18:15 UTC).
  The monitor reads the live API; a restart mid-run can produce a spurious `UNAVAILABLE`/`STALE` alert.
- Pick a quiet minute outside both windows.

### Bring-up steps (idempotent)
1. Deps present: `python3 -c "import argon2, eth_account"` (argon2-cffi, eth-account).
2. DB exists: `python3 scripts/init_academy_db.py --db ~/Documents/SPA_Claude/data/academy.db --create`
   (first time only; `--create` is required — a bare run refuses to make a new file).
3. `SPA_ACADEMY_DB` is exported in `scripts/agent_apiserver.sh` (the launchd wrapper) so a plain
   kickstart brings the mount up. The mount is **fail-safe**: if the env is unset or the app import
   fails, `server.py` logs `Academy sub-app not mounted` and the main API keeps running.
4. Restart: `launchctl kickstart -k gui/$(id -u)/com.spa.apiserver`.

### Smoke test (MANDATORY, right after restart)
- **Old surfaces still alive:**
  - `curl -s -o /dev/null -w '%{http_code}' https://api.earn-defi.com/api/v1/golive` → **200**
  - `curl -s -o /dev/null -w '%{http_code}' https://api.earn-defi.com/api/rates-desk/full-chain/equity_track` → **200**
  - dashboard loads real numbers (earn-defi.com/dashboard).
- **Academy up:** `curl -s https://api.earn-defi.com/academy/health` → `{"ok":true,"service":"academy"}`.
- If the old surfaces are NOT 200 → the restart broke the main API — roll back immediately (below).

### Rollback plan (revert to the prior process)
1. **Unmount the Academy sub-app without touching the main API:** comment out (or set an env guard on)
   the `SPA_ACADEMY_DB` export in `scripts/agent_apiserver.sh` → kickstart. `create_academy_app()` then
   raises, the mount is skipped (fail-safe), `/academy/*` returns 404, and the main API is unchanged.
2. **Full revert:** `git show <prev-sha>:scripts/agent_apiserver.sh > scripts/agent_apiserver.sh`
   (restore the wrapper without the export) → kickstart. The apiserver returns to its pre-academy state.
3. The Academy DB (`data/academy.db`) is independent — leaving or removing it does not affect the main
   API. It is captured by `daily_backup` (`_SQLITE_FILES`), so a wipe is recoverable from backup.
4. Verify the smoke test's "old surfaces" block is 200 after any rollback.
