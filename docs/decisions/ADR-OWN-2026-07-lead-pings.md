# ADR-OWN-2026-07 · Мгновенный Telegram-пинг о КРУПНЫХ заявках (owner-approved)

- **Статус:** ACCEPTED
- **Дата:** 2026-07-16
- **Владелец:** Yurii (решение Q-OWN-16, ответ в чате 2026-07-16: «Крупные — сразу, остальные — в дайджест»).

## Контекст

Заявки с `/pilot` и early-access (`/api/pilot/request`, `spa_core/api/routers/interest.py`) до сих пор
попадали в **ежедневный дайджест** владельца — не отдельным мгновенным пингом. Так было сделано, потому
что прямая отправка в Telegram ломала архитектурный guard «единая Telegram-власть»
(`spa_core/telegram/push_policy.py` — единственный путь Tier-1-пуша; `test_no_rogue_telegram_senders`).
Заявка не терялась, но владелец узнавал о ней не сразу. Владелец захотел быструю реакцию на серьёзные
лиды, но не хотел шума от каждого случайного захода.

## Решение

**Крупная (материальная) заявка → мгновенный per-lead Tier-1 пинг; остальные → дайджест (как раньше).**

1. **Новый whitelist-key `pilot_request`** в `push_policy.TIER1_WHITELIST` + **`ONESHOT_KEYS`.**
   Заявки — это *повторяющиеся one-shot события*, а не постоянное состояние. Edge-trigger (push только на
   переходе ok→bad, потом «still bad → silent») заглушил бы 2-ю заявку. One-shot путь: всегда пушить под
   daily-ceiling, НЕ записывая persistent bad-state → каждая крупная заявка пингуется.
2. **Материальность — детерминированный классификатор** `_is_material_lead()` (interest.py). Поля суммы
   нет (zero-PII бренд), поэтому «крупная/B2B» выводится из доступных сигналов. MATERIAL, если ЛЮБОЕ:
   - **B2B/институционал** — домен email НЕ из списка бесплатных провайдеров (компания/фонд/family-office);
   - **early-access** — `source == "early_access"` (явная приверженность);
   - **aggressive-тир** — крупнейшая тикет-полоса интереса.
   Иначе (бесплатная почта без маркеров приверженности) → digest.
3. **Daily-ceiling сохраняется** — one-shot путь всё ещё под потолком (10/сутки): флуд крупных заявок
   свернётся в одно «more events — open /alerts», защита от флаппинга не отключена.

## Инварианты соблюдены
- Единая Telegram-власть: `interest.py` шлёт ТОЛЬКО через `push_policy` (не прямой `telegram_client`).
- stdlib, детерминизм, fail-SAFE (`_notify_owner_telegram` best-effort, никогда не роняет страницу).
- Zero-PII на публичных поверхностях: email уходит владельцу в приватный Telegram + `pilot_requests.jsonl`,
  на `/admin` по-прежнему только COUNT.
- Тесты: `test_push_policy.py` (+3 one-shot), `test_lead_ping_routing.py` (новый, 8), `test_pilot_request.py`.

## Настройка / выключение
- Порог материальности тюнится в `_is_material_lead` (список бесплатных доменов / сигналы).
- Убрать `pilot_request` из `TIER1_WHITELIST` → все заявки снова только в дайджест.

## Связано
- Q-OWN-16 (`nimbalyst-local/tracker/own-16-instant-lead-ping.md`), agent-task `agent-lead-pings`.
- Единая Telegram-власть: `docs/TELEGRAM_BOT_ARCHITECTURE.md`, `push_policy.py`.
