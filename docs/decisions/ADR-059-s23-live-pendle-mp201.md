# ADR-059 — S23 reads the LIVE MP-201 Pendle feed; go-live gate criterion re-pointed

- **Статус:** Accepted (owner Variant A, 2026-07-23)
- **Контекст-источник:** карта `owner-decision-strategiya-s23-nikogda-ne-vidit-zhivoi-p.md`.
- **Домен:** research strategy (advisory/paper, капитал не двигает) + go-live gate criterion.

## Контекст

Стратегия S23 «Pendle PT Fixed Rate» заявляла живой Pendle, но импортировала РЕТИРОВАННЫЙ MP-354
`pendle_pt_adapter` внутри `except: pass` → ImportError глотался → S23 НАВСЕГДА на mock 7%. Живой
read-only заменитель — MP-201 `spa_core/adapters/pendle_pt.py` (в рабочем реестре, зелёные тесты),
но с ДРУГИМ API (модуль-функция `get_pendle_apy()`, не canonical adapter-объект).

## Решение (Variant A)

1. `S23._load_adapters` импортирует `pendle_pt.get_pendle_apy` (MP-201), НЕ ретированный модуль.
2. `S23.get_pt_apy` — склейка: `get_pendle_apy(MOCK_PT_APY)` → dict `{apy%, source, is_available}`.
   Живо ТОЛЬКО при `source=="pendle_api"` + `is_available` + apy>0 (fallback-dict НЕ выдаётся за live —
   S23 честно ставит `pendle_pt_live=False` и использует свой mock). Живой замер 2026-07-23: **12.73%**.
3. **Gate re-point:** критерий готовности `pendle_pt_adapter` перецелен с мёртвого
   `pendle_pt_adapter.py` на живой `pendle_pt.py` (import-based, ADR-057). Критерий зеленеет →
   гейт **28/29 → 29/29** (техническая готовность, НЕ решение о go-live/реальных деньгах).

## Последствия

- (+) S23 оценивается по РЕАЛЬНОМУ Pendle-APY (созвучно owner-директиве «оценивать стратегии по
  реальной доходности»); турнир получает честное число вместо mock 7% (когда турнир станет доверяемым —
  ADR-нет, карта `agent-tournament-trustworthy-real-apy`).
- (−) Место S23 в турнире сдвинется (7% → живые 8–13%) — это ожидаемо и честно.
- **29/29 ≠ разрешение на капитал.** Owner-Решение-1: сначала стабильность + продлённый paper.
- Тесты: `test_s23_pendle_live.py` (6, live/fallback/unavailable/no-fn/raise/no-retired-import);
  `test_golive_checker.py` обновлён (criterion зелёный на MP-201, guard от отката к compile/dead).

## Связанные

ADR-057 (import-based gate), карта `agent-guard-no-silent-mock-in-tournament`,
`agent-tournament-trustworthy-real-apy`, memory `pendle-pt-adapters` / `owner-directive-head-of-investment-layer`.
