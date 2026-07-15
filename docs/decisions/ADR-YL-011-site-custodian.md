# ADR-YL-011 · Site Custodian — защита earn-defi.com от stale-чисел

- **Статус:** Accepted (backfilled 2026-07-15)
- **Дата:** 2026-07 (реализовано в блоках 1–5, коммиты `site-custodian`)
- **Автор/утвердил:** оркестратор

## Контекст

Публичный сайт earn-defi.com билдится из `landing/` через CF Pages. Числа доходности/трека
на сайте могли устаревать (stale snapshot) относительно живого состояния системы, что для
honesty-first бренда — репутационный риск. Нужен независимый механизм, который гарантирует
свежесть публикуемых чисел и блокирует деградировавшие деплои.

## Решение

- **Auto-deploy свежего снапшота** после каждого daily-цикла (block-1).
- **Независимый freshness-monitor** + degraded kill-rule (block-2/3): если снапшот несвежий —
  сигнализировать; STRICT-режим (`STRICT_SNAPSHOT_FRESHNESS=1`) может блокировать, по умолчанию
  WARN-only (чтобы freshness-check не морозил весь CF-билд — урок: exit-1 в prebuild рушит сайт).
- **Weekly content-consistency audit** (block-4): пинит числа CLAUDE/CURRENT_STATE/README к
  `golive_status.json` + kill_switch пороги.
- Freshness-workflow использует `secrets.SPA_PAT` (не `GITHUB_`-префикс — зарезервирован).

## Последствия

- ✅ Публичные числа не дрейфуют от живого состояния; деградация ловится.
- ⚠️ Любой exit-1 в CF-prebuild блокирует весь сайт → freshness-check оставлен WARN-only вне STRICT.
- Инвариант «никакого stale/выдуманного APY на сайте» теперь машинно поддержан.
