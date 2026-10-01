# P0-4 · Public package wording — owner approval package (NOT published)

> Prepared 2026-10-01 under ADR-531 (DeFi vNext Phase 0) from the evidenced contradictions of the DeFi
> Architecture Gap Audit (ADR-530 §H, `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md`). Owner subject №2 (public
> numbers / tier wording / legal) ⇒ nothing here is published until the owner approves; delivery then goes
> only through `scripts/safe_site_push.py`. Pages verified live on https://earn-defi.com on 2026-10-01.
>
> **Rules applied to every proposal.**
> - Each one states only what the code and books do today.
> - It introduces no new yield number, return promise, fee or withdrawal term.
> - It removes solicitation-style wording rather than rephrasing it.
> - A changing number is never printed. Measured values render from `landing/src/data/track_snapshot.json` / `lib/realized_rate.js`; thresholds render from `lib/constitution.json` (`.claude/rules/site-numbers.md`). Where a needed threshold is not in `constitution.json` yet, the item says so.
> - RU text is natural Russian (no transliteration, no Latin in `data-ru` except product names).

## Current implemented state the wording must match (measured 2026-10-01)

| Package | Book | What it holds | Risk gate | Leverage / LP / loops |
|---|---|---|---|---|
| Conservative | main cycle (`cycle_runner`) | stablecoin lending, Tier 1 **and Tier 2** protocols (T2 ≈ half of the book) | RiskPolicy v1.0 + two-tier kill switch | none |
| Balanced | `hy_cycle` sleeve | stablecoin lending + staked USDe | **outside RiskPolicy**, own stop at −8 % from peak | none |
| Aggressive | `lp_cycle` sleeve | two stablecoin lending positions, high concentration | **outside RiskPolicy**, own stop at −25 % from peak | none |

There are no deposits, no withdrawals and no external capital: research paper track only, product terms
only after go-live and legal review (CLAUDE.md inv. #8, `.claude/rules/site-copy.md`).

## The eight items

### 1. Conservative says «Tier 1 only» — the book is about half Tier 2
| Where | Old | Proposed EN | Proposed RU |
|---|---|---|---|
| `landing/src/pages/strategies/conservative.astro:24` (meta description) | «Tier 1 protocols only, no leverage, no looping.» | «Stablecoin lending in Tier 1 and Tier 2 protocols within per-tier RiskPolicy caps. No leverage, no looping.» | — (meta) |
| same `:40`, `:70` | «Tier 1 protocols only — …» / «Tier 1 protocols only. No leverage, no looping, no Tier 2+ allocation.» | «Tier 1 and Tier 2 lending protocols within per-tier caps. No leverage, no looping, no Tier 3.» | «Протоколы кредитования Tier 1 и Tier 2 в пределах лимитов по уровням. Без плеча, без зацикливания, без Tier 3.» |
| same `:132`, `:197` | «No Tier 2 or Tier 3 protocols.» | «No Tier 3 protocols. Tier 2 is capped per protocol and in total.» (cap values rendered from `constitution.json`) | «Без протоколов Tier 3. Tier 2 ограничен на протокол и в сумме.» |
| `landing/src/pages/index.astro:283-285` | «Tier mix T1» · «Tier 1 pools only.» | «Tier mix T1 + T2» · sentence removed | «Состав T1 + T2» · фраза убрана |
| `landing/src/data/strategy_config.json:15` | «Tier 1 protocols only. …» | same replacement as row 2 | — |
| `conservative.astro:121-131` (per-protocol APY list incl. Spark) | hard-coded «~3.5 % / ~4.8 % / ~5 %», Spark listed though not held | list of the protocols the book is *eligible* for, without per-protocol APY; «current positions and rates: /dashboard» | «Текущие позиции и ставки — на /dashboard» |

### 2. «No lock-up / T+1 / no withdrawal fee» — solicitation wording and not true
| Where | Old | Proposed EN | Proposed RU |
|---|---|---|---|
| `strategies/conservative.astro:386-389`, `strategies/balanced.astro:398-401` | «No lock-up. Standard processing T+1. Large or complex withdrawals may take up to 5 business days. No withdrawal fee.» | «There are no deposits or withdrawals: this is a research paper track and no external capital is accepted. Any terms will be set only after go-live and legal review. Note that some protocols the book can hold have their own exit delays (for example, a multi-day redemption queue).» | «Внесения и вывода средств нет: это исследовательский бумажный трек, внешний капитал не принимается. Условия появятся только после запуска и юридической проверки. Учтите: у части протоколов, которые может держать книга, есть свои задержки выхода (например, очередь на погашение в несколько дней).» |
| `landing/src/pages/fees.astro:174` | «No withdrawal fee is planned.» | «Withdrawal terms and fees are not set; they will be defined after go-live and legal review.» | «Условия и комиссии вывода не установлены; они будут определены после запуска и юридической проверки.» |
| `landing/src/data/strategy_config.json:119` (`withdrawal_terms`) | same old text | «not set — research paper track (no external capital)» | — |

### 3. Paper track tagged «L6 · live evidenced»
| Where | Old | Proposed EN | Proposed RU |
|---|---|---|---|
| `landing/src/lib/tier_bands.json:15-16` | «L6 · live evidenced» / «L6 · подтверждён вживую» | «L3 · paper track (evidenced)» | «L3 · бумажный трек (подтверждённый)» |
| `landing/src/pages/packages.astro:29` | «LIVE · evidenced · fundable» | «PAPER · evidenced track» (the word «fundable» removed: external capital is closed) | «PAPER · подтверждённый трек» |
| `tier_bands.json` `tail_en/_ru` | «… (live paper track)» | «… (paper track)» | «… (бумажный трек)» |

Basis: `docs/37_apy_realism_and_evidence_standard.md` — L6 = validated at live capital; paper = L3;
/methodology already says so.

### 4. Aggressive describes leverage the book does not use
| Where | Old | Proposed EN | Proposed RU |
|---|---|---|---|
| `strategies/aggressive.astro:43`, `:125`, `packages.astro:59` (`what_en`), `strategy_config.json:94` | «Levered PT carry loops · points / incentive farming · unhedged directional restaking» | «The Aggressive paper book holds two stablecoin lending positions with high concentration and a wider stop than Balanced. It uses no leverage, no loops and no LP. Leveraged constructions are researched only in the separate advisory Aggressive Lab and never fund this book.» | «Бумажная книга Aggressive держит две позиции кредитования стейблкоинов с высокой концентрацией и более широким стопом, чем Balanced. Плеча, петель и LP нет. Плечевые конструкции исследуются только в отдельной советующей лаборатории Aggressive Lab и эту книгу не финансируют.» |
| `strategies/aggressive.astro:176` | «Yield amplified through leverage. …» | «This book uses no leverage; its higher risk comes from concentration in fewer protocols.» | «Плеча в этой книге нет; повышенный риск — от концентрации в меньшем числе протоколов.» |

### 5. One kill-switch policy implied for all packages
| Where | Old | Proposed EN | Proposed RU |
|---|---|---|---|
| `strategies/aggressive.astro:405-409` (FAQ «Does the same risk policy apply?») | «Yes. RiskPolicy v1.0 applies to all strategies. … The same non-overridable two-tier kill switch applies: SOFT … ≥5 %, HARD … ≥10 %.» | «No. RiskPolicy v1.0 and the two-tier kill switch govern the Conservative book. Balanced and Aggressive are advisory paper books outside RiskPolicy; each has its own stop from peak (Balanced and Aggressive values rendered from code constants).» | «Нет. RiskPolicy v1.0 и двухуровневый стоп-кран действуют для книги Conservative. Balanced и Aggressive — советующие бумажные книги вне RiskPolicy; у каждой свой стоп от пика.» |

Implementation note: the stops (−8 %, −25 %) are code constants (`hy_cycle._KILL_DRAWDOWN_THRESHOLD`,
`lp_cycle.IL_KILL_THRESHOLD`) and are not yet in `constitution.json` ⇒ add them to
`scripts/build_site_constitution.py` before rendering; never print them by hand.

### 6. Three different Conservative APYs on one page
| Where | Old | Proposed |
|---|---|---|
| `index.astro:121` | «~3.5 %» literal | removed (no per-protocol literal on the home page) |
| `index.astro:186-189`, `:206` | calculator «At our realized rate» = `a*0.033` (3.3 % literal) next to «4.9 % realized» | calculator multiplies by the SAME rendered realized paper rate (`realized_rate.js`), with its measurement date |
| `index.astro:666-680` (client JS tier cards) | Conservative card shows the tier1 backtest blend (3.7 %) | card shows the realized paper rate from `paper_tracks.conservative`, labelled «paper · annualised · measured <date>»; the backtest number is not shown as the package rate |

### 7. No gross-vs-net explanation
| Where | Old | Proposed EN | Proposed RU |
|---|---|---|---|
| `index.astro:80,127,189`, `snapshot.astro:112`, `how-we-think.astro:55` | «(accrual, no costs charged)» | «(paper; modelled gas and slippage of the book's own moves charged since 2026-09-10; real execution costs not included)» | «(бумажный трек; с 10.09.2026 списываются расчётные газ и проскальзывание собственных ходов книги; реальные издержки исполнения не учтены)» |
| `tier_bands.json` `band_en/_ru` («up to N % net APY») | «net APY» | «target band, annualised, before real execution costs» (band values unchanged) | «целевой диапазон, годовых, до реальных издержек исполнения» |
| `/methodology` (new short paragraph) | — | «Gross = the protocol's supply rate as reported (DeFiLlama). Paper net = gross minus the modelled cost of the book's own moves. Neither includes taxes, real execution or fees beyond those inside the rate.» | «Брутто — ставка протокола, как её показывает DeFiLlama. Бумажное нетто — брутто минус расчётная стоимость собственных ходов книги. Ни то, ни другое не учитывает налоги, реальное исполнение и комиссии сверх тех, что уже в ставке.» |

### 8. No separate protocol-risk vs strategy-risk explanation
| Where | Old | Proposed |
|---|---|---|
| `strategies/{conservative,balanced,aggressive}.astro` section «Strategy-Specific Risks» (`:244`, `:276`, `:274`) | protocol risks listed under «strategy» | two headings: **«Protocol risks — where the money sits»** (smart contract, oracle, depeg, insolvency — existing text) and **«Strategy risks — what the book does with it»**: Conservative — «plain supply; concentration within caps; protocol exit delays»; Balanced — «plain supply plus staked USDe, a synthetic dollar whose yield depends on funding rates»; Aggressive — «plain supply concentrated in two protocols; no leverage» |

RU headings: «Риски протокола — где лежат деньги» / «Риски стратегии — что книга с ними делает».

## Also found and evidenced, NOT included (owner may add)
- `/methodology` lines ~296-309 invert the tracks: they say «Balanced — paper tracked since June 22» and «Conservative / Aggressive — not yet started». The opposite is true.
- `/risk-disclosure:63` still states a «target go-live date approximately July 21, 2026». `golive_label.js` has no owner-set date.
- FAQ, present tense: «A Gnosis Safe (multisig) is used — no transaction goes through without confirmation», although the system is paper only.
- The Balanced risk matrix says «Stablecoin depeg: Low» while the book holds 25 % staked USDe.

## Verification before publishing (after approval)
- `scripts/check_owner_gate.py` will classify these as subject №2. Ship through `scripts/safe_site_push.py` with this approval referenced.
- `scripts/site_number_provenance.py`: no new printed number (UNDECLARED must not grow).
- `scripts/site_content_audit.py` plus a manual check that the package pages agree with `track_snapshot.json` and the books.
- `data-ru` checked for Latin outside product names.
- Live check: `curl -L https://earn-defi.com/<page>/` for each touched page.
