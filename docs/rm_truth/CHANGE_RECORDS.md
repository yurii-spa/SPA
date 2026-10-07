# RM-TRUTH-01 · записи изменений (ADR-537)

Значимые удаления этого эпика. Каждая запись проверяется `scripts/check_change_evidence.py` в пушере;
достаточность рассуждения — вопрос независимого ревьюера (`docs/rm_truth/REVIEW_*.md`).

```change-record
id: CR-RMT01-001
task: RM-TRUTH-01 Wave 0 (W5 APY truth + W4 publication) · role: integrator (interactive session)
component: годовая ставка книг Balanced/Aggressive — /api/live/books (spa_core/api/routers/live.py) и снимок сайта (scripts/generate_track_snapshot.py)
purpose: _annualized_pct + _accrual_anchor_date давали владельцу годовую ставку книги в /api/live/books и /admin/portfolio-summary (фаза B надзора CIO, 2ba5e4b3d), а якорь начисления — первый день реальной записи вместо номинального start_date (533739abd); _post_fix_track отделял дни исправленной модели издержек sleeve-econ-v2 от искажённых v1 (ADR-531, c673b3df3)
purpose_source: 2ba5e4b3d
defect: линейная аннуализация за всю жизнь книги, включая 39 искажённых v1-дней, без порога зрелости — тот же расчёт жил ТРЕМЯ копиями (live.py, books_summary.py, generate_track_snapshot.py) с разными формулами; итог — инвертированная лестница у владельца (Conservative 4.15 / Balanced −4.36 / Aggressive 1.36 при 4 валидных днях), docs/rm_truth/A3_product.md §2
decision: один читатель трека рукава spa_core/paper_trading/sleeve_track.sleeve_track_view (только v2, только текущий эксперимент ADR-533, compound через spa_core/reporting/compound_apy) + порог зрелости REPORTABLE_AFTER из канона spa_core/defi_engine/package_status (ADR-580 C1/C2); ниже порога ставка null и статус «копится история»
alternative: оставить три копии и только поправить формулу в каждой — отвергнуто: ровно так три копии и разошлись (C1 «один писатель на значение»)
preserved: якорь начисления по первому дню реальной записи (теперь внутри sleeve_track_view: первый v2-день текущего эксперимента); отделение v1 от v2 и пометка pre_fix_period; _post_fix_track ПЕРЕЕХАЛ в spa_core/paper_trading/sleeve_track.py без изменения логики (сырая аудиторская v2-ставка, типизирована reportable/reportable_after); return_pct, equity, NAV книг — без изменений
changed: annualized_apy_pct книг ниже 30 валидных дней = null (было линейное число); Conservative — compound по evidenced-барам (4.90 вместо линейных 4.10, равно публичному числу); появилось типизированное поле annualized_apy_pct_rate (metric_type REALIZED_PAPER, window_days, annualisation, as_of, source, reportable)
removes: py:scripts/generate_track_snapshot.py:_post_fix_track, py:spa_core/api/routers/live.py:_accrual_anchor_date, py:spa_core/api/routers/live.py:_annualized_pct
consumers: /api/live/books → landing/src/pages/admin/portfolio-summary.astro (рендерит null как «—»); spa_core/reporting/daily_telegram_report.py блок «📚 Пакеты» (печатает «статистика текущей версии накапливается»); public track_snapshot.json paper_tracks.*.post_fix (не читается ни одной страницей — замер W4)
owner_approval: not required (применяет уже принятые владельцем ADR-531/533/548: «копится» до 30 валидных дней; публичные поля, читаемые сайтом, заморожены отдельным сторожем test_landing_read_fields_frozen)
reversible: yes (git revert коммита доставки возвращает три прежние функции; данные книг не трогались — расчёт идёт при чтении)
rollback: git revert <sha доставки RM-TRUTH-01 Wave 0>; перезапуск apiserver владельцем для KeepAlive-процесса
```

```change-record
id: CR-UX01-001
task: PRODUCT-UX-01 publication · role: integrator (interactive session)
component: public site earn-defi.com — home (landing/src/pages/index.astro), strategies (landing/src/pages/strategies/*), risk, track-record, dashboard, header/footer, FAQ rate sentence
purpose: the home carried a yield calculator, early-access/email/pilot CTAs, live mini-charts and go-live/gate counters; the strategies index rendered its own cards client-side; analytics track ids tagged those CTAs
purpose_source: b36acda46
defect: the site explained the internal system instead of the product (4 names, Balanced missing from the home comparison, internal vocabulary, «29/29» vs «decision pending», «not raising capital» beside «join the list», risk hidden, ~17 phone screens) — audits scratchpad ux01 A/B; FAQ printed unsourced «~3.4 %» floor, «50–150 bps» and «~4.5 %»
decision: one product IA (Earn DeFi; Overview · Strategies · Performance · Risk · How it works · Research · paper dashboard), 5-block home, identical-row comparison, measured-first metric hierarchy, plain-language risk, one live-capital statement; numbers only from canonical sources (profile view built on package_card cardModels, ADR-537); FAQ sentence keeps only the canonical realized rate and the research target
alternative: restyle the existing pages in place — rejected: the defects are structural (IA, hierarchy, contradictions), not visual
preserved: every number and metric type from site_numbers/package_card/constitution; all old pages stay reachable (research hub, how-it-works); /snapshot and /pilot pages still exist; refusal token «refused for live/real capital» on every profile; legal disclaimer
changed: home/strategies/risk/track-record/dashboard layout and copy; calculator and early-access/pilot CTAs removed from primary flows; «Go-live 29/29» replaced by one statement; FAQ unsourced rates removed
removes: fn:landing/src/pages/index.astro:drawSnapshot, fn:landing/src/pages/index.astro:drawSpark, fn:landing/src/pages/index.astro:fmt, fn:landing/src/pages/index.astro:init, fn:landing/src/pages/index.astro:loadEvidence, fn:landing/src/pages/index.astro:loadGoLive, fn:landing/src/pages/index.astro:loadHealth, fn:landing/src/pages/index.astro:loadNav, fn:landing/src/pages/index.astro:loadRefusalCount, fn:landing/src/pages/index.astro:setText, fn:landing/src/pages/index.astro:upd, fn:landing/src/pages/strategies/index.astro:badge, fn:landing/src/pages/strategies/index.astro:basisTag, fn:landing/src/pages/strategies/index.astro:card, fn:landing/src/pages/strategies/index.astro:esc, fn:landing/src/pages/strategies/index.astro:isRu, fn:landing/src/pages/strategies/index.astro:load, fn:landing/src/pages/strategies/index.astro:pct, fn:landing/src/pages/strategies/index.astro:render, id:analyze, id:calc-amt, id:calc-real, id:calc-scn, id:calc-slider, id:ea-email, id:ea-form, id:ea-status, id:how, id:lab-floor, id:lab-groups, id:lab-meta-chip, id:lab-meta-text, id:lab-src, id:lab-status, id:lab-window, id:m-apy, id:m-days, id:m-dd, id:m-gates, id:m12-bar, id:m12-day, id:m4-day, id:m4-refusals, id:pkgMetaChip, id:pkgMetaText, id:sg, id:sl-asof, id:spark, id:spark-src, id:strategies, id:tierGrid, id:tr-apy, id:tr-days-target, id:tr-gates-bar, id:tr-gates-pass, id:tr-gates-total, id:tr-reset-target, id:track, track:aggressive_to_packages, track:aggressive_to_strategies_balanced, track:aggressive_to_strategies_conservative, track:analyze_wallet, track:conservative_to_pilot, track:conservative_to_strategies_balanced, track:hero_see_live_track, track:hero_snapshot, track:index_to_packages, track:index_to_strategies_btc, track:index_to_strategies_leverage_loops, track:m11_defi, track:m11_idle, track:m11_usdc, track:m12_follow_countdown, track:m4_refusals, track:tier_view_aggressive, track:tier_view_balanced, track:tier_view_conservative, track:view_strategy_lab
consumers: public visitors; analytics events for removed track ids stop; no backend reader of these page ids
owner_approval: required: owner decision 2026-10-07 «OWNER / ARB DECISION — PRODUCT-UX-01: APPROVED TO PUBLISH» (cleanup: FAQ ~3.4 % removed; no benchmark introduced)
reversible: yes (git revert of the publication commit restores every removed element; origins first appear in the mass re-add b36acda46, original decisions UNKNOWN from git)
rollback: git revert <publication sha>; Cloudflare Pages rebuilds from origin landing/**
```
