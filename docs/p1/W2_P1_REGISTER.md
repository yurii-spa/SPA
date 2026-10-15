# Реестр P1 волны 2 — 17 дефектов публичной правды (08.10.2026)

Источник находок: независимое ревью кандидата `p1/wave2-v2@489d9b515` (`scratchpad/p1/W2_INDEPENDENT_REVIEW.md`).
Ветка исправлений: `p1/wave2-v3` (на `origin/main` `bbfcc9724`). Ничего не опубликовано.

**Общая проверка для всех P1 с 1 по 16:** `spa_core/tests/test_p1_wave2_register_guards.py`.
- Положительный контроль: шаблон сторожа совпадает с исходной цитатой дефекта.
- Шаблон отсутствует во ВСЁМ `landing/src`, а не на одной странице.
- Страница проводится к генератору.
- Генераторы прогоняются настоящим `node`.

Дополнительно собранный сайт (122 страницы) просканирован на каждый шаблон: 0 попаданий. По P1-16 было одно попадание на `/protocols/weeth`, но это чужая implied yield PT, а не наш хвост.

| ID | URL · локаль | Проблема (цитата) | Канонический источник | Исправление (источник генерации) | Проверка | Остаток |
|---|---|---|---|---|---|---|
| P1-1 | `/risk-disclosure` · EN+RU | «The target go-live date is **approximately July 21, 2026**…» / «приблизительно 21 июля 2026». Условие без юридической проверки, «Last updated: June 18» | `track_snapshot.go_live_target = null`, `go_live_state = gate_passed_owner_decision_pending`; `profile_view.GO_LIVE` | Абзац рендерится из `GO_LIVE` + `goLiveLabel(snap)`: решение владельца после ручного обзора (ADR-002) **и юридической проверки**, даты нет. Документ 1.0 → **1.1**, действует с 08.10.2026, причина правки названа в строке версии | guard P1-1; сборка: 0 попаданий | ЗАКРЫТ. Правка юридического текста — предмет №2, в карточке владельца |
| P1-2 | `/status` · EN+RU | «Go-live: real capital deployment after confirmed 30-day verified track» | то же; 107/30 | Строка = `GO_LIVE` (решение владельца + юридическая проверка, «не только счёт дней») | guard P1-2 | ЗАКРЫТ |
| P1-3 | `/faq` #08 · EN+RU | «A Gnosis Safe (multisig) **is used**…» | `/trust` Q7 («planned for live phase»), proof-of-reserves ($0 real, no custody) | Ответ: сейчас бумажная книга — реального капитала, хранения средств и транзакций нет; мультисиг Gnosis Safe **запланирован** на live-этап, подписанты и порог до go-live | guard P1-3 | ЗАКРЫТ |
| P1-4 | `/packages` Balanced+Aggressive · EN+RU | «Join early-access to get in the day it clears» / «Вступи в ранний доступ…»; «That refusal is what you are buying… Want the validation report first?» | статусы карточек «RESEARCH · not live-allocated / refused for live»; инв. #8 | Оговорки переписаны без призыва и «покупки»: «вне пути к реальному капиталу… реальный капитал не принимается ни в один профиль… Исследование, не оферта» | guard P1-4 | ЗАКРЫТ. Формулировки — предмет №2, в карточке |
| P1-5 | `/packages` Conservative · EN+RU | «T1/T2 stablecoin lending — **Aave, Compound, Morpho, Spark**» | витрина `exposure` (← `current_positions.json` + тиры `ADAPTER_REGISTRY`): compound_v3 40 % T1 · fluid_fusdc 20 % T2 · maple 20 % T2 · morpho_blue_base 10 % T2 · aave_v3 5 % T1 · кэш 5 % | Новый генератор `lib/book_exposure.js` (`holdingsSentence`). Нет замера ⇒ «состав не измерен», а не список | guard P1-5 + node-тест генератора (в том числе «не измерено») | ЗАКРЫТ |
| P1-6 | `/readiness` · EN+RU + meta/og/twitter | «remaining blockers — custody, audit, legal, **and 30 evidenced track-days**» | `golive_label` (107/30, порог пройден) | `remainingBlockers(snap)` и `trackGateSentence(snap)`; meta берётся из того же | guard P1-6 + node-тест (обе ветви: пройден / открыт) | ЗАКРЫТ |
| P1-7 | `/fundability` · EN+RU + meta | «The track is THIN… accruing to 30» / «Трек ТОНКИЙ» | то же | `trackGateSentence(snap)`; meta «the track is short (see the evidenced-day count)»; подпись «ready · the track keeps accruing» | guard P1-7 | ЗАКРЫТ |
| P1-8 | `/competitive-position` · EN+RU | «The track is THIN — accruing to 30 evidenced days» | то же | `trackGateSentence(snap)` | guard P1-8 | ЗАКРЫТ |
| P1-9 | `/strategies/research` · EN (RU без `data-ru`) | «Compare with **Live Strategies**»; «~6.00% · T1 only», «6.00–14.00%», «14.00–28.00%» | `tier_bands.json` (цели до 6/12/20 %); витрина (4,90 %, T2 50 %) | Карточки: имена, цели и уровень доказательности из `tier_bands.json`; у Консервативного `realizedPhrase` + `tierSummary`; заголовок «Compare with the paper profiles»; все строки с `data-ru` | guard P1-9 | ЗАКРЫТ |
| P1-10 | `/strategies/leverage-loops` · EN+RU | «The desk's **live capital** is conservative stablecoin lending» | `live_capital_usd = 0` | «The desk has no real capital (paper stage). Its paper book is unlevered conservative stablecoin lending — research target up to 6.00%, {ставка} annualised realized on paper» | guard P1-10 | ЗАКРЫТ |
| P1-11 | `/cockpit/risk` (`CockpitRisk.jsx`) · EN+RU | «stablecoin lending + **delta-hedged carry** (β≈0)», «net delta targets ±0.50% (a market-neutral book)», «On a hedged-carry book a funding flip…» | книга = кредитование стейблкоинов без плеча + кэш (витрина `exposure`; хеджа и перпа нет) | Описание книги исправлено; сценарий funding flip: «к текущей книге неприменимо»; дельта «≈0 по построению (не живой замер)» | guard P1-11; сканирование JS-бандлов: 0 | ЗАКРЫТ |
| P1-12 | `/annual-contrast` + dashboard (`acBottom`) · EN+RU | «The desk's steady book over the same year: max-drawdown **~0.00%**» | витрина: макс. просадка −0,04 %, 107 дней с 22.06 (не год); 15 %-сторона — бэктест | Новый `realized_rate.measuredDrawdownWindow()`: «paper book since 2026-06-22, 107 evidenced days (not a full year): max drawdown −0.04% — a measurement, not a backtest»; 15 %-сторона подписана как бэктест; «We will run either» → «research, not an offer» | guard P1-12 | ЗАКРЫТ |
| P1-13 | `/academy/playground` (`PortfolioBuilder.jsx`) · RU/EN | «Реальная книга (~4,50 % T1)»: Spark 20 %, Morpho Steakhouse как T1; «живая книга сидит на ~4,50 %» | `ADAPTER_REGISTRY`: morpho_steakhouse = **T2**; витрина | Пресет переименован: «Пример: книга в основном из T1 (иллюстрация)»; Morpho Steakhouse → T2; урок отсылает к реальному составу и ставке на /due-diligence | guard P1-13 | ЗАКРЫТ |
| P1-14 | `/academy/03-lending-aave-compound` · RU | «Ядро деска — Aave/Compound/Morpho/Spark, ~4,50 % supply APY, Tier 1» | витрина `exposure`, `realized_rate` | Раздел — «учебная выборка, а не состав книги» с тирами из реестра; состав книги (`holdingsSentence`) и ставка (`realizedPhrase`) из витрины | guard P1-14 | ЗАКРЫТ |
| P1-15 | `/academy/19-aggressive-lab-annual-contrast` · RU | «**realized** drawdown −66,30 %», «**реальная** просадка eth_directional», «Глубины… — реальные» | `data/aggressive_lab/annual_contrast.json` (as_of 2026-06-25), `realized_drawdowns.source = realized_backtest_series`: эпизод 2025-08-24 → 2026-06-06, **−66,3466 %** | Подписи «в бэктесте на исторических ценах», значение −66,35 % (половина вверх), источник и дата названы; гладкая «~4,50 %» кривая помечена иллюстрацией, рядом наш замер | guard P1-15 | ЗАКРЫТ |
| P1-16 | `/learn/why-20-apy-means-tail-risk`, `/how-we-think`, `/packages`, `/strategies/aggressive` (`tier_bands`) · EN+RU | «lost **~50.00%** through the 2024 ETH crash» и «up to ~50.00% drawdown» против «−66.30 %» в уроке 19 | тот же файл: eth_directional — −42,07 % (2024-06-06 → 09-06), −63,03 % (2024-12 → 2025-04), **−66,35 %** (2025-08-24 → 2026-06-06, не восстановилась). «~50 %» данными не подтверждается | Один хвост везде: `tier_bands.json` «−66,35 % в БЭКТЕСТЕ… источник annual_contrast.json на 2026-06-25»; тексты: «в бэктесте… упала на 42,07 % в распродаже ETH середины 2024 и на 66,35 % с августа 2025 по июнь 2026» | guard P1-16 + `test_aggressive_tail_is_one_backtest_number_everywhere` | ЗАКРЫТ. Хвост — публичное число, в карточке |
| P1-17 | `/track-record`, `/due-diligence` (строка сверки ставки) | «^(365/107)… over the same 107 days»: 107 баров ≠ 108 календарных суток | `generate_track_snapshot.py` / `build_site_numbers.py` (`annualisation`) | **Не в этом изменении.** Методика принадлежит генератору витрины (другая ветвь работы). Страницы уже читают ставку только через `landing/src/lib/realized_rate.js` (`rateWindow`, `rateReconciliation`, `totalReturnSinceStart`, `realizedPhrase`, `publishedRateFigure`), поэтому новая методика переключается в одном месте | — | **ОТКРЫТ (зависит от генератора)** |

## P2/P3, исправленные попутно (безопасно)

- **methodology:** «4.90% real» → «realized on paper»; в условия go-live добавлена юридическая проверка (P2-5, P2-7).
- **how-we-think:** «Our live conservative paper track» → «Our conservative paper track» (часть P2-2).
- **academy/playground:** «устойчивая ~4,50 % остаётся плоской» → «иллюстративная устойчивая кредитная книга».

## Не сделано (P2/P3, остаются)

- Порог «Early warning · 2.00%» на дашборде: его нет в `constitution.json` (P2-1).
- Число адаптеров «35» вписано в `/methodology` руками, в реестре 36 (P2-6).
- «~3.40%» по токенизированным казначейским бумагам без даты и источника; сравнение «15.00% vs 4.90%» без метки рода (P2-2, P2-3).
- `/snapshot` проецирует бумажную ставку на деньги посетителя (P2-4).
- Остатки бренда «SPA»: это нейминг, предмет №2.
- Страницы BTC-движка генерирует отдельный репозиторий earn-defi.
- Клиентские проценты из API в части островов идут в обход форматтера.
