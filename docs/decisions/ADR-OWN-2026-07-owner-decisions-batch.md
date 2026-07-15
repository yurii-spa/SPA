# ADR-OWN-2026-07 · Пакет закрытых решений владельца (июль 2026)

- **Статус:** Accepted (backfilled 2026-07-15 из `docs/OWNER_DECISIONS_NEEDED.md`)
- **Дата:** 2026-07-11 … 2026-07-12
- **Автор/утвердил:** владелец

## Контекст

Автономные циклы (roadmap-ship + UI/UX) накапливали owner-gated вопросы (числа / нейминг / legal /
инфра / нарратив) в `docs/OWNER_DECISIONS_NEEDED.md`. Владелец ответил пачкой. Фиксируем закрытые
решения задним числом как ADR, чтобы память проекта не зависела от одного накопительного файла.

## Решение (закрытые пункты)

- **Q-OWN-01 · точка контакта /pilot** — построена ФОРМА заявки (email+сообщение → owner Telegram +
  счётчик в /admin, commit 0f6231eb). Реальный mailbox не создаётся (owner-side, опционально).
- **Q-OWN-02 · FAQ vs paper-стадия** — вариант A: FAQ (minimum/lock-up/fees) переписан под честную
  paper-стадию (commit c46b809d): «research paper-track, не оферта, условия — на go-live».
- **Q-OWN-03 / Q-OWN-12 · admin auth** — `/admin/*` за Cloudflare Access по owner-email (проверено
  вживую 302 → cloudflareaccess.com). Phase 3 разблокирован.
- **Q-OWN-04 · консолидация дашбордов** — `/dashboard` = единственный публичный canonical; `/cockpit/*`
  и `/board/*` → операторские (убраны из sitemap, robots Disallow).
- **Q-OWN-05 · per-sleeve forward-вердикты** — скрыты до улучшения трека (флагман BELOW_FLOOR не
  светится публично; aggregate-честность сохранена; реверсится из git).
- **Tier naming** — Conservative / Balanced / Aggressive везде. **APY display** — «up to {max}%»
  (Aggressive up-to-20%), реализованный ~3.3% как честный контекст. **URL** —
  /strategies/{conservative,balanced,aggressive}. Homepage ведёт реальным работающим тиром (хвост показан).

## Открытые (НЕ закрыты — мигрируют в `board/owner/`, Этап 2)

Q-OWN-06 (ETHERSCAN_API_KEY prod), Q-OWN-07 (retention secrets), Q-OWN-08 (единая расшифровка SPA),
Q-OWN-11 (/pilot человек + invest@ mailbox), Q-OWN-13 (early-access framing).

## Последствия

- ✅ Публичный сайт приведён к честной paper-рамке; воронка не выдаёт себя за действующий фонд.
- Источник правды по этим решениям — теперь этот ADR + `board/owner/` (для открытых), а не только
  накопительный `OWNER_DECISIONS_NEEDED.md`.
