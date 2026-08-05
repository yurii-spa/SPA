---
trackerStatus:
  type: inbox
title: "py: числа скриншота → approved:False (не DN); та же позиция с is_delta_neutral=…"
status: done
source: telegram
created: 2026-08-05
---

## Задание (из Telegram)

py: числа скриншота → approved:False (не DN); та же позиция с is_delta_neutral=True и TVL≥порог → поведение по ADR.
 • IL-модель: границы (цена в центре диапазона → IL≈0; у края → IL растёт квадратично).
 • Range-exit: out-of-range → одна нога 100%, fee=0.
 • Если делаем s78 — unit-тест по конвенции Задачи 1.

Инварианты

 • policy_lp остаётся fail-closed, детерминированным, LLM-forbidden; approved=False не оверрайдится.
 • Атомарные записи (tmp+os.replace) для любых новых data/-артефактов.
 • Никаких PAT/секретов; stdlib-only; read-only домен не импортирует execution/.
 • USDG вводится в whitelist только с подтверждёнными данными TVL/глубины пула (иначе fail-closed сохраняется — это фича, не баг).

Acceptance criteria

 • docs/research/RS-volatile-clmm.md + docs/adr/ADR-027-volatile-clmm-t3spec.md (решение: вводим/не вводим, в какой форме, лимиты).
 • Гейт: прогон числами скриншота даёт задокументированный вердикт; тесты зелёные offline.
 • Классификатор/risk-map обновлены (если Owner одобрил ввод).
 • Ноль регрессий (методология stash-diff).
 • Чёткая запись в CODE_AUDIT_BACKLOG.md.

Файлы

 • Новые: docs/research/RS-volatile-clmm.md, docs/adr/ADR-027-*.md, spa_core/tests/test_policy_lp_directional.py, (опц.) spa_core/strategies/s78_dn_volatile_clmm.py + тест.
 • Менять: spa_core/risk/policy_lp.py, spa_core/risk/protocol_risk_map.py, spa_core/agents/yield_classifier_agent.py, CODE_AUDIT_BACKLOG.md.
 • Переиспользовать: IL-модель из spa_core/strategies/s21_cashflow_research.py; хедж-паттерн из S8/s71_delta_neutral.py.

Риски / решения для Owner (блокеры)

 1. Вводим ли класс вообще? Он конфликтует с мандатом «сохранение стейбл-капитала» из-за направленного ETH-риска. Форма (a) delta-neutral снимает конфликт, но добавляет перп-хедж (funding, ликвидация, execution-сложность).
 2. T3 cap 15% — этот класс делит лимит с Pendle/Ethena/поинтами; не раздуть T3.
 3. USDG — новый стейбл вне whitelist; нужен отдельный due-diligence (эмитент Paxos/Global Dollar, TVL, аудиты).
 4. Часть D (стратегия) — делать только после ADR-решения; без него — стоп на research + гейте.

Обе задачи независимы: AUD-18 можно брать сразу (чистые тесты, без решений), AUD-19 упирается в твоё решение по пункту «вводим ли класс и в какой форме».

Хочешь — запишу обе карточки в CODE_AUDIT_BACKLOG.md и сразу возьму AUD-18 (тесты) в работу? Или пойдём читать/уточнять модель под AUD-19 сначала?

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Разобрано циклом #121 (2026-08-05)

Одно твоё сообщение бот разбил на три карточки — это три части ОДНОГО задания
(AUD-18 + AUD-19). Разобраны вместе, чтобы не плодить дубли.

- **AUD-18 (тесты на пять стратегий) — СДЕЛАНО:** `agent-aud18-strategy-unit-tests.md`.
  Пять файлов в `spa_core/tests/`. По дороге замерено, что покрытие было не таким,
  как в задании: тесты у этих стратегий есть (в `tests/`), но расчёт доходности
  `compute_weighted_apy` у s76 и s73 **не исполнялся ни разу** — именно он и течёт
  в турнир. Подробности и таблица замера — в карточке.
- **AUD-19 (волатильный CLMM ETH/стейбл) — НЕ БЕРУ САМ, ждёт тебя:**
  `own-aud19-volatile-clmm-vvodim-li-klass.md`. Он меняет правила допуска
  (`spa_core/risk/policy_lp.py`), а это можно только с твоего решения — ты и сам
  написал, что задача упирается в него. Там же три варианта и рекомендация.
- Найденный по дороге дефект (s76 угадывает единицу измерения доходности по величине
  числа) молча не чинится — карточка `agent-s76-apy-unit-guess.md`.
