# Owner-Gate — безопасный авто-шип сайта

> Owner-approved 2026-07-15 (ADR-OWN-2026-07-autoship). Позволяет автономному оркестратору
> САМ пушить безопасные правки сайта в live, но гарантирует, что owner-gated классы никогда
> не уезжают сами — только с одобрения владельца.

## Зачем

Сайт — **push==live** (Cloudflare Pages билдит `landing/` на каждый push в `main`). Автономный
оркестратор пушит правки прямо в `main`. Значит нужен предохранитель, который различает:
- **SAFE** (уезжает само): layout/CSS, компонент-рефакторы, не-legal копирайт, SEO, багфиксы,
  **динамические** чтения чисел (`snap.paper_apy_pct`, `{apy}`, `.toFixed`).
- **OWNER-GATED** (только карточкой владельцу): числа доходности, нейминг тиров, расшифровка «SPA»,
  legal/disclaimer, solicitation, удаление honesty-токенов (evidence L0–L6, «refused for live»).

## Три слоя защиты

1. **`scripts/check_owner_gate.py`** — детерминированный линтер (stdlib, `# LLM_FORBIDDEN`).
   Классы A–E. Структурные числа/нейминг/evidence в `tier_bands.json` и числа `track_snapshot.json`
   — через field-diff (надёжно); свободный текст — регексы по added/removed строкам. Exit 0 clean /
   2 gated / 1 error. Режимы: `--diff-mode git-range|files|worktree`.
2. **`scripts/safe_site_push.py`** — ЕДИНСТВЕННЫЙ санкционированный путь пуша сайта для оркестратора.
   Гоняет линтер → clean пушит через `push_to_github_batch.py` (ставит `SPA_SITE_PUSH_VERIFIED=1`);
   gated → создаёт карточку `needs-owner` + notify, НЕ пушит; error → fail-closed.
3. **Hard interlock** в `push_to_github.py` и `push_to_github_batch.py` — активен ТОЛЬКО при
   `SPA_AUTONOMOUS=1` (ставит только оркестратор). Любой автономный пуш в `landing/` без
   `SPA_SITE_PUSH_VERIFIED=1` → перепрогон линтера → gated/error = отказ (exit 3, fail-closed).
   LLM может «забыть» wrapper — детерминированный interlock забыть нельзя. **Attended-сессии
   (владелец/я) и детерминированный кастодиан работают БЕЗ `SPA_AUTONOMOUS` → не затронуты.**

## Кастодиан-исключение (не подделываемое)

`track_snapshot.json` легитимно авто-обновляет `deploy_site_snapshot.py`. Линтер НЕ доверяет
commit-сообщению — вместо этого регенерит снапшот из закоммиченного `data/`-канона
(`generate_track_snapshot.py`) и сравнивает (игнорируя `generated_at`). Байт-равно → exempt;
ручная правка числа не совпадёт → gated. Работает только там, где есть `data/` (pre-push на машине
владельца), не в CI — и это ок, CI не deploy-гейт.

## Owner-approval bypass

Правку owner-gated класса можно провести с трейлером `Owner-Approved: own-NN` в commit-сообщении +
карточка `own-NN` со `status: owner-done` (ставит ТОЛЬКО владелец) + `approves:` scope, покрывающий
нарушения. One-shot.

## Честный риск

In-repo гейт — **кооперативный**, не криптозащита: та же машина теоретически может его обойти. Он
механизирует мандат оркестратора и ловит честный дрейф/ошибки (реальная угроза). Более строгая опция
(branch-protect `main` + оркестратор через ветку, которую он не мёржит сам; или CF preview + ручной
промоушен) — доступное будущее ужесточение (см. ADR).

## Проверка

- Unit: `python3 -m pytest tests/test_owner_gate_check.py -q` (классы A–E, dynamic-read, bypass).
- Golden: `check_owner_gate.py --diff-mode worktree` на чистом дереве → CLEAN.
- Red-team: подмена числа тира `20%→30%` → GATED (exit 2); interlock под `SPA_AUTONOMOUS=1` → BLOCKED.
