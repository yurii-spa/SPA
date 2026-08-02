# W4 Handoff — Allocator / enforcer (money-path) — свежее окно

> **Дата передачи:** 2026-07-23. Предыдущая сессия закрыла W1–W3 (мониторы, gate, honesty-данные).
> Это окно берёт **W4 — money-path**: самое рисковое. Читать этот файл ПЕРВЫМ, затем связанные ниже.

## Что уже сделано (W1–W3, всё на origin/main, протестировано)

| Волна | Что | ADR | Коммит |
|---|---|---|---|
| W1 | Единый реестр свежести артефактов (`spa_core/monitoring/artifact_freshness.py`) + агент `com.spa.artifact_freshness` (задеплоен) | — | `7ebe3e3a` |
| W2 | gap-monitor порог 10→8 UTC | — | `7ebe3e3a` |
| W2 | сторож стоп-крана `rules_watchdog` → реальные файлы + 26h missed-cycle | ADR-056 | `9374b27e` |
| W2 | go-live gate import-based (не compile) | ADR-057 | `3e221a4b` |
| W3 | fabricated-evidence: flag не delete + producer skip + 10% убрана | ADR-058 | `eefe2531` |
| W3 | S23 → живой MP-201 Pendle (12.73%, не mock 7%) + gate re-point → 29/29 | ADR-059 | `eefe2531` |

**Гейт готовности сейчас 29/29** — это ТЕХНИЧЕСКАЯ готовность контура, **НЕ** решение о go-live/реальных деньгах.

## W4 — что предстоит (money-path, ОСТОРОЖНО)

### W4.1 — enforcer coverage gaps (карта `agent-enforcer-coverage-gaps.md`, owner Решение-4)
`policy_enforcer.validate_positions` не проверяет часть кэпов `policy.py`. Добавить (значения из RiskConfig, не хардкод):
- `max_concentration_t2` = 20% (T2 на один протокол); `BASE_CHAIN_CAP` = 20%; `max_l2_total` = 50%; `max_single_chain` = 90%.
Только УСИЛЕНИЕ, значения RiskPolicy не менять. Замер 2026-07-23: текущий портфель проходит все новые проверки.

### W4.2 — allocator yield-trigger (карта `agent-allocator-yield-frozen-rootcause.md`, ADR-055)
**Root-cause:** ребаланс срабатывает ТОЛЬКО на нарушение (`cycle_runner.py:880` «runs ONLY when current positions
violate policy»). 40% в morpho @3.47% + 20% кэша ничего не нарушают → тюнер не зовётся → раскладка заморожена,
хотя aave $12B@4.78% / sdai $1.2B@5.50% / sfrax@6% пусты. Нужен yield-improvement триггер: пересматривать,
когда оптимум тюнера > текущей доходности за вычетом стоимости переключения (гистерезис/анти-churn). ДИЗАЙН
сначала (ADR-черновик на ревью владельцу), потом реализация.

**Рекомендованный порядок W4:** сначала **дизайн yield-trigger** (ADR-черновик, показать владельцу) → потом
реализация W4.1+W4.2 в изоляции.

## Инварианты для W4 (money-path — нарушать нельзя)

- **RiskPolicy v1.0 — единственный hard-гейт; пороги НЕ менять** (изменение → отдельный ADR).
- **Работать в изолированном workspace/worktree**, НЕ на живом дереве напрямую.
- **`spa_core/paper_trading/pre_cutover_gate.py`** — прогнать перед закрытием money-path задачи.
- **LLM запрещён** в risk/execution; детерминированно; fail-CLOSED.
- **НЕ запускать прод-цикл против живого `data/`** (track-corruption-hazard) — только sandbox.
- **Каждая правка тестов — осознанно** (#16): обоснование в теле + журнал.
- **Push — owner-gated**; sensitive-мутация (трек/деньги) — только после показа diff и явного go.

## ⚠️ Ловушка из прошлой сессии (git-push-api-drift)

Локальный `origin/main` ref ОТСТАЁТ (пуши идут через `push_to_github.py` API прямо в GitHub). Новый worktree
«fresh» может НЕ иметь последних коммитов (в W3 worktree не имел card-2 golive_checker → чуть не затёрли import-based).
**Перед worktree:** `git fetch origin main`; при правке файла, который менялся в этой серии (golive_checker и т.п.) —
сверять с origin по содержимому (GitHub API / `git show origin/main:<file>`), НЕ доверять локальному дереву слепо.

## Обязательно прочитать в начале W4-окна

1. `CLAUDE.md` + `.claude/rules/risk-engine.md` (раздел «Аллокация капитала», ADR-055).
2. `docs/decisions/ADR-055-head-of-investment-agent-layer.md` (периодичность SENSE/ACT/DERISK).
3. Карты: `agent-allocator-yield-frozen-rootcause.md`, `agent-enforcer-coverage-gaps.md`,
   `agent-head-of-investment-layer.md`.
4. `docs/POST_PAPER_TEST_PLAN.md` (Решения владельца: D→B, продлённый paper, 3 тира по доходности).
5. Этот файл.

## Owner-контекст (директивы, действуют)

Цель — **стабильная умная система, не гонка в деньги**; продлённый paper до «1000%» стабильности; оценивать
доходность по ВСЕМ 3 тирам; реальный пилот потом ~1000 USDT/стратегия; периодичность на реале — частая
(intraday) для просадки, SENSE часто / ACT редко для аллокации.
