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

```change-record
id: CR-P1W2-001
task: P1 Truth & Safety Recovery — wave 2 (public financial truth), owner ARB review 2026-10-08 · role: wave-2 fork (interactive session)
component: public site — percentage formatter (landing/src/lib/site_numbers.js → lib/pct_format.js), /due-diligence protocol table, rate/total-return reconciliation lines, 86.97 % backtest claim
purpose: fmtPct2/centsHalfUp were the ADR-660 site formatter inside site_numbers.js; the /due-diligence «Protocol Whitelist» table (Content Sprint B, a3ca1d388, 2026-06-19) listed protocols, tiers and TVL as a proof-layer overview
purpose_source: a3ca1d388
defect: inline live scripts could not import site_numbers.js without bundling the 21 KB shelf, so they kept toFixed() copies; the whitelist was hand-typed and contradicted the book (no fluid_fusdc / maple — 20 % each; Morpho shown T1, registry T2; undated TVL guesses)
decision: the formatter moves to lib/pct_format.js and is RE-EXPORTED by site_numbers.js (every importer unchanged); the table is replaced by «What the book holds», generated from the shelf's exposure (← current_positions.json + ADAPTER_REGISTRY tiers)
alternative: keep a typed whitelist and correct it by hand — rejected: a typed list drifts again at the next rebalance (the same class as the 16 typed «~3,3 %»)
preserved: fmtPct2 / centsHalfUp keep their names and behaviour and stay importable from site_numbers.js; every protocol the book holds is listed with its registry tier; the 86.97 % figure stays, now qualified (backtest, run 2026-06-19, ADR-030)
changed: the eligible-universe list and TVL column are no longer printed on /due-diligence (the universe is RiskPolicy v1.0); amounts and shares of the held book are printed instead
removes: export:landing/src/lib/site_numbers.js:centsHalfUp, export:landing/src/lib/site_numbers.js:fmtPct2
consumers: every page importing fmtPct2 from site_numbers.js (unchanged by the re-export); Layout.astro now exposes the same formatter to inline scripts (window.spaFmtPct2 / spaPct / spaPctText)
owner_approval: required: wave-2 publication card (public numbers, ADR-285 subject №2) — docs/p1/W2_OWNER_CARD.md
reversible: yes (git revert of the wave-2 commit restores the table and the in-file formatter; data untouched)
rollback: git revert <wave-2 sha>; Cloudflare Pages rebuilds landing/** from origin
```

```change-record
id: CR-P1W2-002
task: P1 Truth & Safety Recovery — wave 2 v3, closing the 16 site P1s of the independent review (ARB assignment 2026-10-08) · role: wave-2 site fork (interactive session)
component: public site copy — risk-disclosure go-live paragraph, /status go-live line, /faq #08 custody answer, /packages Balanced/Aggressive caveats + Conservative «what», /readiness, /fundability, /competitive-position gate sentences, /strategies/research comparison cards, /strategies/leverage-loops «what the desk holds», CockpitRisk book description, /annual-contrast + dashboard annual line, academy/playground preset, academy/03 protocol section, academy/19 drawdown labels, tier_bands Aggressive tail, how-we-think + learn/why-20-apy tail sentence
purpose: each sentence described our system (go-live, custody, book composition, gate state, drawdown) as of the day it was typed (June–August 2026)
purpose_source: docs/p1/W2_P1_REGISTER.md (quotes + canonical sources per P1); review p1/W2_INDEPENDENT_REVIEW.md
defect: typed facts went stale or were never true — a three-month-old go-live date, no legal review, «Gnosis Safe is used» with $0 custody, solicitation wording on books refused for live, Spark listed / Fluid+Maple missing / Morpho as T1, «THIN, accruing to 30» at 107/30, «Live Strategies», «live capital» at $0, a hedged book we do not run, «~0.00% over the same year», a backtest labelled «realized», two different Aggressive tails (~50 % vs −66.30 %)
decision: every such sentence now renders from a generator — golive_label.js (goLiveLabel, trackGateSentence, remainingBlockers) + profile_view.GO_LIVE; book_exposure.js over the shelf exposure; realized_rate.js (realizedPhrase, measuredDrawdownWindow); tier_bands.json for bands and the one Aggressive tail (−66.35 %, backtest, annual_contrast.json as of 2026-06-25); wording with no evidence is qualified (backtest / illustrative) or removed
alternative: correct the literals by hand — rejected: the same literals drifted once already; spa_core/tests/test_p1_wave2_register_guards.py now fails if any of the 16 returns anywhere under landing/src
preserved: every page, section, id and data-track stays; the backtest drawdowns stay visible with dates and source; Gnosis Safe stays as the PLANNED live-phase custody (trust Q7)
changed: risk-disclosure document version 1.0 → 1.1 (effective 2026-10-08); the «Join early-access…» / «what you are buying» sentences are gone from the two caveats; the playground preset is relabelled illustrative and Morpho Steakhouse is T2 as in ADAPTER_REGISTRY
removes: none (wording only; no id, data-track, export or function removed)
consumers: readers of the listed pages; no API or data consumer
owner_approval: required: wave-2 publication card (public claims and legal text, ADR-285 subject №2) — docs/p1/W2_OWNER_CARD.md
reversible: yes (git revert of the wave-2 commit; data untouched)
rollback: git revert <wave-2 sha>; Cloudflare Pages rebuilds landing/** from origin
```

```change-record
id: CR-P1W2-003
task: P1 Wave 2 r2 — public text corrections after the owner card review (ARB 2026-10-09) · role: wave-2 r2 fork (interactive session)
component: public site copy — the 4,85 % comparison lines (/packages, /aggressive-lab, /snapshot, dashboard annual-contrast labels), «live paper» wording (TrustBand, aggressive-lab, rates-desk, structural-desk, faq, tournament, due-diligence, how-we-think, learn/why-20-apy, academy/07, strategy_config taglines, DashboardLive/SPAApp sleeve notes, blog link label), /risk-disclosure audit sentence and the «allocate only what you can afford to lose» sentence, minus-sign typography (pct_format.fmtPct2, KillGauge, leverage-loops, research, learn/is-usdt-safe, protocols meta)
purpose: the estimate 4,85 % was introduced as «фактических»/«realized»; «live paper» read as live trading; /risk-disclosure claimed «only protocols with multiple independent audits»; the modelled product told visitors how to allocate capital
purpose_source: docs/p1/W2_P1_REGISTER.md (discrepancies found 2026-10-09; owner card nimbalyst-local/tracker/owner-decision-opublikovat-volnu-2-saita-dohodnost-za-p.md); ARB assignment 2026-10-09 item 1
defect: «фактических бумажных 4,85 % (оценочный…)» contradicts itself; paper is not live; the audit claim has no per-protocol evidence for the whole book (no protocol card for fluid_fusdc; RiskPolicy does not gate lending on audits); an allocation instruction in a product that accepts no funds
decision: estimate wording only («оценочный годовой эквивалент модельного трека»); «simulated paper track on virtual capital» / «модельный (бумажный) трек»; audit sentence reduced to «an audit does not guarantee safety»; allocation sentence replaced by «the product runs on virtual capital only: no real funds are accepted»; negative percentages print U+2212
alternative: keep the audit claim — rejected: not verifiable for every protocol in the book; add new legal wording — rejected (no new promises)
preserved: every page, section, id and data-track; the 4,85 % figure itself and its label; drawdown convention (signed change «−0,04 %» in value cells, magnitude «просадка 0,04 %» in prose, both from the same shelf value)
changed: wording and the minus glyph only; risk-disclosure v1.1 change note extended
removes: two sentences (audit claim, allocation instruction) — wording, no function, id or data-track
consumers: readers of the listed pages; no API or data consumer
owner_approval: required: wave-2 publication card r2 (public claims and legal text, ADR-285 subject №2) — p1/W2_OWNER_CARD_R2.md
reversible: yes (git revert of this commit)
rollback: git revert <r2 sha>; Cloudflare Pages rebuilds landing/** from origin
```

```change-record
id: CR-P1W2-004
task: P1 Wave 2 r3 — the estimate is never «realized» in client-rendered text (ARB 2026-10-10 item 1–2) · role: wave-2 r3 fork (interactive session)
component: /snapshot client script (next-step text, idle note, re-render on language switch); the same claim on /how-we-think, /annual-contrast, /methodology, /faq, /system, /packages (meta), /pilot, /strategies/leverage-loops, /tournament; new browser check scripts/check_rendered_estimate_label.py + spa_core/tests/test_p1_wave2_client_render.py
purpose: r2 removed «realized» before 4,85 % only in static text; /snapshot's client script still printed «~4,85 % (оценочный …) реализованных» and 9 pages bound the estimate label to «realized»/«фактических»
purpose_source: nimbalyst-local/tracker/owner-decision-opublikovat-volnu-2-saita-dohodnost-za-p.md (B6, owner answer 2026-10-15); ARB 2026-10-10 items 1–2
defect: an estimate labelled «оценочный … не прогноз» was followed by «реализованных»/«realized» in the same sentence; static scans of the built HTML could not see the client-assembled text
decision: drop the «realized»-class word next to the estimate (the label already says «оценочный годовой эквивалент … не прогноз»); /snapshot rebuilds its result in the new language via the existing window.__renderLive hook (no re-tracking, no scroll)
alternative: remove the projection — rejected here: that is owner decision B6, not part of this fix
preserved: the projection block, its amount and every id/data-track; the 4,85 % figure, its label and site_numbers.json (sha256 unchanged)
changed: wording next to the estimate on 10 pages; /snapshot re-render on language switch
removes: none (wording only; no id, data-track, export or function removed)
consumers: readers of the listed pages; no API or data consumer
owner_approval: required: wave-2 publication card r3 (public claims, B6 — ADR-285 subject №2) — p1/W2_OWNER_CARD_R3.md
reversible: yes (git revert of this commit)
rollback: git revert <r3 sha>; Cloudflare Pages rebuilds landing/** from origin
```
