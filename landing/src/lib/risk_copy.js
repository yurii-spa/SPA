// risk_copy.js — the plain-language risk list (PRODUCT-UX-01 §7). Words only: no scores, no figures.
// Ranked by how likely each risk is to cause a loss for these paper portfolios, most important first.
// `applies` lists which public profiles carry the risk; `detail` is the technical second layer.

export const RISKS = [
  {
    id: 'protocol',
    en: 'A lending protocol fails or is hacked', ru: 'Сбой или взлом протокола кредитования',
    plain_en: 'Money sits in smart contracts run by other teams. A bug or exploit there can lose part of it — no insurer stands behind it.',
    plain_ru: 'Деньги лежат в смарт-контрактах чужих команд. Ошибка или взлом там может стоить части средств — страховщика за этим нет.',
    detail_en: 'Only protocols above a minimum market size are used, and no single protocol may hold more than a set share of the portfolio. That limits the damage of one failure; it does not remove it.',
    detail_ru: 'Используются только протоколы не меньше минимального размера рынка, и ни один протокол не может держать больше установленной доли портфеля. Это ограничивает ущерб от одного сбоя, но не убирает его.',
    applies: ['conservative', 'balanced', 'aggressive'],
  },
  {
    id: 'depeg',
    en: 'A stablecoin loses its dollar peg', ru: 'Стейблкоин теряет привязку к доллару',
    plain_en: 'A "stable" coin can trade below $1 for days or for good. Yield does not help if the coin itself loses value.',
    plain_ru: '«Стабильная» монета может торговаться ниже $1 днями или навсегда. Доходность не спасает, если дешевеет сама монета.',
    detail_en: 'The portfolios hold USD stablecoins only. A depeg has not occurred during this track, so the measured drawdown does not show this risk.',
    detail_ru: 'Портфели держат только долларовые стейблкоины. Депега за время этого трека не было, поэтому измеренная просадка этот риск не показывает.',
    applies: ['conservative', 'balanced', 'aggressive'],
  },
  {
    id: 'leverage',
    en: 'Leverage and liquidation', ru: 'Плечо и ликвидация',
    plain_en: 'Borrowing to buy more multiplies both gains and losses. If collateral falls far enough, the position is liquidated.',
    plain_ru: 'Заём ради большей позиции умножает и доход, и убыток. Если залог падает достаточно сильно, позицию ликвидируют.',
    detail_en: 'Only Aggressive uses leverage, and only as a simulated loop. Conservative and Balanced use none. Aggressive is refused for real capital.',
    detail_ru: 'Плечо есть только в Агрессивном, и только как симулированная петля. В Консервативном и Сбалансированном плеча нет. Агрессивный для реального капитала не допускается.',
    applies: ['aggressive'],
  },
  {
    id: 'liquidity',
    en: 'You cannot exit when you want', ru: 'Выйти, когда нужно, не получается',
    plain_en: 'A lending market can be fully borrowed, a fixed-rate position may need to be sold below its value, a loop may be slow to unwind.',
    plain_ru: 'Кредитный рынок может быть полностью занят, позицию с фиксированной ставкой придётся продать ниже её стоимости, петлю — медленно разбирать.',
    detail_en: 'Conservative stays in daily-liquid lending markets; Balanced holds a fixed-rate leg to maturity; Aggressive depends on market depth.',
    detail_ru: 'Консервативный остаётся на рынках с дневной ликвидностью; Сбалансированный держит фиксированную часть до погашения; Агрессивный зависит от глубины рынка.',
    applies: ['conservative', 'balanced', 'aggressive'],
  },
  {
    id: 'maturity',
    en: 'Short history', ru: 'Короткая история',
    plain_en: 'A few months of paper results say little about a bad year — and some strategies have only days (see each strategy\'s day count).',
    plain_ru: 'Несколько месяцев бумажных результатов мало говорят о плохом годе — а у некоторых стратегий пока лишь дни (см. счётчик дней у каждой).',
    detail_en: 'Rates are published only after a minimum number of evidenced days, and every figure carries its measurement date.',
    detail_ru: 'Ставки публикуются только после минимального числа подтверждённых дней, и у каждой цифры есть дата замера.',
    applies: ['conservative', 'balanced', 'aggressive'],
  },
  {
    id: 'execution',
    en: 'Real trading costs more than paper', ru: 'Реальная торговля дороже бумажной',
    plain_en: 'These are simulations. Real gas, slippage and delays would lower the results shown.',
    plain_ru: 'Это симуляции. Реальный газ, проскальзывание и задержки снизили бы показанные результаты.',
    detail_en: 'Modelled gas and slippage of the portfolio\'s own moves are charged; real execution costs are not.',
    detail_ru: 'Расчётный газ и проскальзывание собственных ходов портфеля учитываются; реальные издержки исполнения — нет.',
    applies: ['conservative', 'balanced', 'aggressive'],
  },
  {
    id: 'concentration',
    en: 'Too much in one place', ru: 'Слишком много в одном месте',
    plain_en: 'Holding few protocols on few chains means one problem hits a large share of the money.',
    plain_ru: 'Мало протоколов и мало сетей — значит, одна проблема бьёт по большой доле денег.',
    detail_en: 'Per-protocol and per-chain caps apply to Conservative; the research portfolios hold only a handful of positions.',
    detail_ru: 'Для Консервативного действуют лимиты на протокол и на сеть; исследовательские портфели держат лишь несколько позиций.',
    applies: ['conservative', 'balanced', 'aggressive'],
  },
  {
    id: 'market',
    en: 'Yields fall', ru: 'Доходности падают',
    plain_en: 'Lending rates move with demand. When borrowing demand drops, income drops with it.',
    plain_ru: 'Ставки кредитования зависят от спроса. Падает спрос на займы — падает и доход.',
    detail_en: 'Past rates are measured, not promised; the research target is not a forecast.',
    detail_ru: 'Прошлые ставки измерены, а не обещаны; цель исследования — не прогноз.',
    applies: ['conservative', 'balanced', 'aggressive'],
  },
];

export const PROFILE_NAMES = {
  conservative: { en: 'Conservative', ru: 'Консервативный' },
  balanced: { en: 'Balanced', ru: 'Сбалансированный' },
  aggressive: { en: 'Aggressive', ru: 'Агрессивный' },
};
