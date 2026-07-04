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
